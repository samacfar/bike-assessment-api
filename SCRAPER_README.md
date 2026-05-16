# Bike image scraper

Pulls secondhand bike photos from cycling classifieds and forums, filters to
images **≥ 1500 px wide**, deduplicates by URL **and** perceptual hash, and
saves them numbered `0001.jpg`, `0002.jpg`, ... into a folder.

Sources:
- **Bike Index** — public API; biased toward NZ/AU via location filters, with a
  global fallback. All owner-uploaded photos.
- **Reddit** — cycling subs, including some AU/NZ-specific ones.
- **Pinkbike Buy/Sell** — often Cloudflare-blocks scrapers; auto-drops if so.
- **eBay** — used filter (LH_ItemCondition=3000).
- **BikeExchange** — AU/NZ marketplace; best-effort, varies by region.
- **BikeRegister** — UK stolen-bike registry; all owner-uploaded.
- **LFGSS** — London Fixed-Gear forum "For Sale" microcosm. UK-only.
- **Retrobike** — UK vintage MTB forum "For Sale". UK-only.

## Setup

```bash
pip install -r requirements-scraper.txt
```

## Run

Each invocation grabs **up to 200 new images** ("a lump"), then stops. State
is persisted in `<output>/.state.json`, so just run it again to keep going.

```bash
# one lump of 200
python scrape_bikes.py

# the full 1000 (five lumps back-to-back)
for i in 1 2 3 4 5; do python scrape_bikes.py; done
```

A few useful flags:

```bash
python scrape_bikes.py --output ./bike_images     # folder (default ./bike_images)
python scrape_bikes.py --min-width 2000           # raise the resolution floor
python scrape_bikes.py --source pinkbike          # restrict to one source
python scrape_bikes.py --source pinkbike --source reddit
python scrape_bikes.py --log DEBUG                # verbose
```

## What you get

```
bike_images/
  0001.jpg
  0002.jpg
  ...
  index.csv        # index, filename, source, source URL, width, height, pHash
  .state.json      # seen URLs + pHashes + next index (for resume)
```

`index.csv` is the audit trail — if you later want to know where image 0427
came from, it's there.

## Notes

- Pinkbike, Reddit, and eBay don't require credentials. BikeExchange varies by
  region and may return little; it's a bonus source.
- The script is polite (~1.2 s between requests per source) but you can hit
  rate limits, especially on Reddit. If you do, the relevant source logs a
  warning and the script moves on.
- Deduplication uses pHash with Hamming distance ≤ 4. The same bike posted in
  two places, or two near-identical shots, will be caught.
- If the filter ratio is rough (lots of candidates rejected for width) consider
  lowering `REQUEST_DELAY` in the script — but be a good citizen.
