#!/usr/bin/env python3
"""
Secondhand bike image scraper.

Pulls bike images from cycling classifieds and forums, filters to images at
least MIN_WIDTH wide, deduplicates by URL + perceptual hash, and saves them
numbered (0001.jpg, 0002.jpg, ...) into an output folder.

Each invocation grabs up to --batch-size new images (default 200). State is
persisted in <output>/.state.json so running the script five times in a row
fills the folder to 1000.

Usage:
    pip install -r requirements-scraper.txt
    python scrape_bikes.py                              # one batch of 200
    python scrape_bikes.py --output ./bike_images       # custom folder
    python scrape_bikes.py --source pinkbike            # restrict to one source
    python scrape_bikes.py --min-width 2000             # stricter resolution

To collect 1000 in one shot:
    for i in 1 2 3 4 5; do python scrape_bikes.py; done
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin

import imagehash
import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

# ----- Config -----

DEFAULT_MIN_WIDTH = 1500
DEFAULT_BATCH_SIZE = 200
PHASH_DISTANCE = 4

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTML_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
IMAGE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
}
REDDIT_HEADERS = {
    "User-Agent": "bike-image-scraper/1.0 (personal dataset collection)",
    "Accept": "application/json",
}

REQUEST_DELAY = 1.2

session = requests.Session()
session.headers.update(HTML_HEADERS)

log = logging.getLogger("scrape_bikes")


# ----- State -----

@dataclass
class State:
    seen_urls: set = field(default_factory=set)
    phashes: list = field(default_factory=list)
    next_index: int = 1

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls(
            seen_urls=set(raw.get("seen_urls", [])),
            phashes=list(raw.get("phashes", [])),
            next_index=int(raw.get("next_index", 1)),
        )

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "seen_urls": sorted(self.seen_urls),
            "phashes": self.phashes,
            "next_index": self.next_index,
        }))
        tmp.replace(path)

    def is_near_duplicate(self, phash_hex: str) -> bool:
        new_int = int(phash_hex, 16)
        for existing in self.phashes:
            if bin(new_int ^ int(existing, 16)).count("1") <= PHASH_DISTANCE:
                return True
        return False


# ----- Image handling -----

def guess_extension(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ".jpg"


def download_image(url: str, min_width: int) -> tuple[bytes, Image.Image] | None:
    try:
        resp = session.get(url, headers=IMAGE_HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.debug("download failed %s: %s", url, e)
        return None
    data = resp.content
    if len(data) < 20_000:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        log.debug("not a usable image %s: %s", url, e)
        return None
    if img.width < min_width:
        log.debug("too narrow (%d < %d): %s", img.width, min_width, url)
        return None
    return data, img


# ----- Sources -----

class Source:
    name: str = ""
    BLOCK_LIMIT = 2
    FAIL_LIMIT = 4

    def __init__(self) -> None:
        self.fails = 0
        self.blocks = 0
        self.dropped = False

    def candidate_urls(self) -> Iterator[str]:
        raise NotImplementedError

    def _fetch(self, url: str, *, headers: dict | None = None, timeout: int = 30):
        if self.dropped:
            return None
        try:
            resp = session.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            self.fails += 1
            log.warning("%s: request failed (%s) [%d/%d]",
                        self.name, e, self.fails, self.FAIL_LIMIT)
            if self.fails >= self.FAIL_LIMIT:
                log.error("%s: too many failures, dropping source for this run", self.name)
                self.dropped = True
            return None
        if resp.status_code in (401, 403, 429):
            self.blocks += 1
            log.warning("%s: HTTP %d on %s [%d/%d]",
                        self.name, resp.status_code, url, self.blocks, self.BLOCK_LIMIT)
            if self.blocks >= self.BLOCK_LIMIT:
                log.error("%s: appears blocked (HTTP %d), dropping source for this run",
                          self.name, resp.status_code)
                self.dropped = True
            return None
        if not resp.ok:
            log.debug("%s: HTTP %d on %s", self.name, resp.status_code, url)
            return None
        self.fails = 0
        self.blocks = 0
        return resp


class Pinkbike(Source):
    name = "pinkbike"
    LIST_URL = "https://www.pinkbike.com/buysell/list/"

    def candidate_urls(self) -> Iterator[str]:
        for page in range(1, 200):
            if self.dropped:
                return
            list_url = f"{self.LIST_URL}?page={page}"
            resp = self._fetch(list_url)
            if resp is None:
                if self.dropped:
                    return
                time.sleep(REQUEST_DELAY * 2)
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            detail_urls: set[str] = set()
            for a in soup.find_all("a", href=True):
                m = re.search(r"/buysell/(\d+)/?$", a["href"])
                if m:
                    detail_urls.add(urljoin(list_url, m.group(0)))
            if not detail_urls:
                log.info("pinkbike: no more listings at page %d", page)
                return
            log.info("pinkbike page %d: %d listings", page, len(detail_urls))
            for detail in detail_urls:
                if self.dropped:
                    return
                yield from self._listing_images(detail)
                time.sleep(REQUEST_DELAY)
            time.sleep(REQUEST_DELAY)

    def _listing_images(self, url: str) -> Iterator[str]:
        resp = self._fetch(url)
        if resp is None:
            return
        urls: set[str] = set()
        soup = BeautifulSoup(resp.text, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                continue
            if src.startswith("//"):
                src = "https:" + src
            if "pinkbike.org" in src and re.search(r"\.(jpe?g|png)(\?|$)", src, re.I):
                urls.add(src)
        for m in re.finditer(
            r"https?://ep\d+\.pinkbike\.org/[^\"'\s>]+?\.(?:jpe?g|png)",
            resp.text,
            re.I,
        ):
            urls.add(m.group(0))
        for u in urls:
            yield self._upgrade(u)

    @staticmethod
    def _upgrade(u: str) -> str:
        u = re.sub(r"/v\d+x\d+/", "/", u)
        u = re.sub(r"/s\d+/", "/", u)
        return u


class Reddit(Source):
    name = "reddit"
    SUBS = [
        "whichbike", "BikeMechanics", "bicycling", "MTB", "Velo",
        "gravelcycling", "cycling", "BikePorn", "xbiking", "BikeWrench",
    ]

    def candidate_urls(self) -> Iterator[str]:
        for sub in self.SUBS:
            for sort in ("new", "top"):
                yield from self._scan(sub, sort)

    def _scan(self, sub: str, sort: str) -> Iterator[str]:
        after = None
        for _ in range(25):
            if self.dropped:
                return
            url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit=100&t=all"
            if after:
                url += f"&after={after}"
            resp = self._fetch(url, headers=REDDIT_HEADERS)
            if resp is None:
                if self.dropped:
                    return
                time.sleep(REQUEST_DELAY * 5)
                return
            try:
                data = resp.json()
            except ValueError as e:
                log.warning("reddit r/%s/%s: bad JSON: %s", sub, sort, e)
                return
            children = data.get("data", {}).get("children", [])
            if not children:
                return
            log.info("reddit r/%s/%s: %d posts", sub, sort, len(children))
            for c in children:
                yield from self._post_images(c.get("data") or {})
            after = data.get("data", {}).get("after")
            if not after:
                return
            time.sleep(REQUEST_DELAY)

    def _post_images(self, p: dict) -> Iterator[str]:
        url = p.get("url_overridden_by_dest") or p.get("url") or ""
        if "i.redd.it/" in url:
            yield url
            return
        if p.get("is_gallery"):
            media = p.get("media_metadata") or {}
            for m in media.values():
                if not isinstance(m, dict):
                    continue
                s = m.get("s") or {}
                u = s.get("u") or ""
                if u:
                    yield u.replace("&amp;", "&")
            return
        for image in (p.get("preview") or {}).get("images", []) or []:
            src = (image or {}).get("source") or {}
            u = src.get("url") or ""
            if u:
                yield u.replace("&amp;", "&")
        if url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
            yield url


class Ebay(Source):
    name = "ebay"
    QUERIES = [
        "used road bike", "used mountain bike", "used gravel bike",
        "used hybrid bike", "secondhand bicycle", "used carbon bike",
        "used cyclocross bike", "used touring bike", "used commuter bike",
    ]

    def candidate_urls(self) -> Iterator[str]:
        for q in self.QUERIES:
            if self.dropped:
                return
            for page in range(1, 25):
                if self.dropped:
                    return
                url = (
                    "https://www.ebay.com/sch/i.html?"
                    f"_nkw={q.replace(' ', '+')}&LH_ItemCondition=3000&_pgn={page}"
                )
                resp = self._fetch(url)
                if resp is None:
                    if self.dropped:
                        return
                    break
                soup = BeautifulSoup(resp.text, "html.parser")
                listing_urls: set[str] = set()
                for a in soup.find_all("a", href=True):
                    if "/itm/" in a["href"]:
                        listing_urls.add(a["href"].split("?")[0])
                if not listing_urls:
                    break
                log.info("ebay '%s' p%d: %d listings", q, page, len(listing_urls))
                for lurl in listing_urls:
                    if self.dropped:
                        return
                    yield from self._listing_images(lurl)
                    time.sleep(REQUEST_DELAY)
                time.sleep(REQUEST_DELAY)

    def _listing_images(self, url: str) -> Iterator[str]:
        resp = self._fetch(url)
        if resp is None:
            return
        seen: set[str] = set()
        for m in re.finditer(
            r"https://i\.ebayimg\.com/images/g/[A-Za-z0-9~\-_]+/s-l\d+\.(?:jpg|jpeg|webp|png)",
            resp.text,
            re.I,
        ):
            full = re.sub(r"s-l\d+", "s-l1600", m.group(0))
            if full not in seen:
                seen.add(full)
                yield full


class BikeExchange(Source):
    name = "bikeexchange"
    BASES = [
        "https://www.bikeexchange.com.au",
        "https://www.bikeexchange.co.nz",
        "https://www.bikeexchange.com",
    ]
    LISTING_PATHS = ["/buy/used", "/used-bikes", "/used"]

    def candidate_urls(self) -> Iterator[str]:
        for base in self.BASES:
            if self.dropped:
                return
            for path in self.LISTING_PATHS:
                if self.dropped:
                    return
                for page in range(1, 40):
                    if self.dropped:
                        return
                    url = f"{base}{path}?page={page}"
                    resp = self._fetch(url)
                    if resp is None:
                        if self.dropped:
                            return
                        break
                    soup = BeautifulSoup(resp.text, "html.parser")
                    detail_urls: set[str] = set()
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if any(seg in href for seg in ("/item/", "/listing/", "/bike/")):
                            detail_urls.add(urljoin(url, href.split("?")[0]))
                    if not detail_urls:
                        break
                    log.info("bikeexchange %s p%d: %d listings", path, page, len(detail_urls))
                    for d in detail_urls:
                        if self.dropped:
                            return
                        yield from self._listing_images(d)
                        time.sleep(REQUEST_DELAY)
                    time.sleep(REQUEST_DELAY)

    def _listing_images(self, url: str) -> Iterator[str]:
        resp = self._fetch(url)
        if resp is None:
            return
        soup = BeautifulSoup(resp.text, "html.parser")
        for og in soup.find_all("meta", property="og:image"):
            c = og.get("content")
            if c:
                yield c
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-srcset") or ""
            if not src:
                continue
            first = src.split(",")[0].strip().split(" ")[0]
            if first.startswith("http") and re.search(r"\.(jpe?g|png|webp)(\?|$)", first, re.I):
                yield first


class BikeRegister(Source):
    name = "bikeregister"
    LIST_URL = "https://www.bikeregister.com/stolen-bikes"

    def candidate_urls(self) -> Iterator[str]:
        for page in range(1, 400):
            if self.dropped:
                return
            url = f"{self.LIST_URL}?page={page}"
            resp = self._fetch(url)
            if resp is None:
                if self.dropped:
                    return
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            inline_images: set[str] = set()
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if not src:
                    continue
                full = src if src.startswith("http") else urljoin(url, src)
                if re.search(r"\.(jpe?g|png|webp)(\?|$)", full, re.I) and \
                   "logo" not in full.lower() and "icon" not in full.lower():
                    inline_images.add(full)
            detail_urls: set[str] = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if re.search(r"/stolen-bikes?/[^/?#]+$", href):
                    detail_urls.add(urljoin(url, href.split("?")[0]))
            if not inline_images and not detail_urls:
                log.info("bikeregister: no more listings at page %d", page)
                return
            log.info("bikeregister p%d: %d inline images, %d detail pages",
                     page, len(inline_images), len(detail_urls))
            for u in inline_images:
                yield u
            for detail in detail_urls:
                if self.dropped:
                    return
                yield from self._listing_images(detail)
                time.sleep(REQUEST_DELAY)
            time.sleep(REQUEST_DELAY)

    def _listing_images(self, url: str) -> Iterator[str]:
        resp = self._fetch(url)
        if resp is None:
            return
        soup = BeautifulSoup(resp.text, "html.parser")
        for og in soup.find_all("meta", property="og:image"):
            c = og.get("content")
            if c:
                yield c
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                continue
            full = src if src.startswith("http") else urljoin(url, src)
            if re.search(r"\.(jpe?g|png|webp)(\?|$)", full, re.I) and \
               "logo" not in full.lower() and "icon" not in full.lower():
                yield full


SOURCES = {s.name: s for s in [Pinkbike(), Reddit(), Ebay(), BikeExchange(), BikeRegister()]}


# ----- Main -----

def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", type=Path, default=Path("./bike_images"))
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                    help="Stop after this many NEW images this run (default: 200).")
    ap.add_argument("--target", type=int, default=1000,
                    help="Overall total across runs; stop early if reached (default: 1000).")
    ap.add_argument("--min-width", type=int, default=DEFAULT_MIN_WIDTH,
                    help=f"Minimum image width in pixels (default: {DEFAULT_MIN_WIDTH}).")
    ap.add_argument("--source", action="append", choices=list(SOURCES),
                    help="Restrict to one or more sources (repeatable). Default: all.")
    ap.add_argument("--log", default="INFO", help="DEBUG, INFO, WARNING, ERROR.")
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    args.output.mkdir(parents=True, exist_ok=True)
    state_path = args.output / ".state.json"
    index_path = args.output / "index.csv"
    state = State.load(state_path)

    chosen = args.source or list(SOURCES.keys())
    random.shuffle(chosen)
    iterators: list[tuple[str, Iterator[str]]] = [
        (name, SOURCES[name].candidate_urls()) for name in chosen
    ]

    kept_this_run = 0
    total = state.next_index - 1
    log.info("starting; have %d so far, target %d, this run cap %d, sources=%s, min_width=%d",
             total, args.target, args.batch_size, ",".join(chosen), args.min_width)

    if not index_path.exists():
        with index_path.open("w", newline="") as f:
            csv.writer(f).writerow(["index", "filename", "source", "source_url", "width", "height", "phash"])

    try:
        while iterators and kept_this_run < args.batch_size and total < args.target:
            still_active: list[tuple[str, Iterator[str]]] = []
            for sname, it in iterators:
                if kept_this_run >= args.batch_size or total >= args.target:
                    break
                try:
                    url = next(it)
                except StopIteration:
                    log.info("source %s exhausted", sname)
                    continue
                except Exception as e:
                    log.warning("source %s raised %s; dropping", sname, e)
                    continue
                still_active.append((sname, it))

                if url in state.seen_urls:
                    continue
                state.seen_urls.add(url)

                result = download_image(url, args.min_width)
                if result is None:
                    continue
                data, img = result

                try:
                    phash_hex = str(imagehash.phash(img))
                except Exception as e:
                    log.debug("phash failed for %s: %s", url, e)
                    continue
                if state.is_near_duplicate(phash_hex):
                    log.debug("near-duplicate skip: %s", url)
                    continue

                idx = state.next_index
                ext = guess_extension(data)
                filename = f"{idx:04d}{ext}"
                (args.output / filename).write_bytes(data)

                state.phashes.append(phash_hex)
                state.next_index += 1
                kept_this_run += 1
                total += 1

                with index_path.open("a", newline="") as f:
                    csv.writer(f).writerow([idx, filename, sname, url, img.width, img.height, phash_hex])

                log.info("saved %s  (w=%d h=%d  src=%s  run=%d/%d  total=%d/%d)",
                         filename, img.width, img.height, sname,
                         kept_this_run, args.batch_size, total, args.target)
                state.save(state_path)
            iterators = still_active
    except KeyboardInterrupt:
        log.warning("interrupted; saving state")
    finally:
        state.save(state_path)

    dropped = [name for name in chosen if SOURCES[name].dropped]
    if dropped:
        print(f"Sources dropped this run (blocked / too many failures): {', '.join(dropped)}")
    print(f"Done. Saved {kept_this_run} new images this run. Total in folder: {total}/{args.target}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
