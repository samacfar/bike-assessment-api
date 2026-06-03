# Changelog — bike-assessment-api

## 2026-06-03

### Completed
- Added `scrape_bikes.py`: multi-source bike image scraper. Width filter (≥1500px), URL + perceptual-hash dedup (Hamming ≤4), numbered output (`0001.jpg`…), `index.csv` audit trail, resumable state via `.state.json`, `--batch-size` default 200.
- Added `requirements-scraper.txt` (requests, beautifulsoup4, Pillow, ImageHash).
- Added `SCRAPER_README.md` with setup and usage.
- Implemented sources: Pinkbike, Reddit (10 cycling subs), eBay (used filter), BikeExchange, BikeRegister, Bike Index (public API, AU/NZ city location filters + global fallback), LFGSS (microcosm 548), Retrobike (XenForo for-sale).
- Added per-source block detection: 2 consecutive 401/403/429 or 4 general failures → source dropped from rotation; dropped sources surfaced in final summary.
- Extended Reddit subs with `cycling_aus`, `bicycling_aus`, `MTB_Australia`, `CyclingNZ`, `newzealand_cycling`.
- Commits on `claude/bike-image-scraper-Ky7Gs`: initial scraper, auto-drop blocked sources, BikeRegister, Bike Index + LFGSS + Retrobike + AU/NZ Reddit subs.

### Attempted, not finished
- Live verification of source selectors / URL patterns — container egress proxy returns 403 for every external host, so all scraping logic is from prior knowledge rather than tested against real pages.
- TradeMe NZ source — discussed, not implemented; offered to user pending feedback from first run.

### Blocked
- Cannot validate sources from this container: outbound HTTPS to all tested sites (pinkbike, reddit, ebay, bikeexchange, bikeindex, mtbr, lfgss, bikeforums, retrobike, craigslist, gumtree, 2dehands) returns `403, 21 bytes` from the egress proxy. Scraper must be run from user's local machine.
- User reported Pinkbike returning 403 on their machine too (Cloudflare bot protection on their IP). Auto-drop logic added; Pinkbike likely unusable from their location.

### Next
- User runs latest scraper locally; reports which sources actually deliver images and which auto-drop.
- Adjust CSS selectors / URL patterns for any source that connects but yields 0 candidates (most likely candidates for tuning: Pinkbike list cards, BikeExchange detail-page links, Retrobike thread image selectors).
- Add TradeMe NZ if AU/NZ volume is insufficient.
- Consider Playwright-based sources (Craigslist, Gumtree, 2dehands) only if HTTP-only sources fall short of 1000.
