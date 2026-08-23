# TCG Price Tracker

Tracks TCGPlayer market prices for any cards you list — runs entirely on GitHub's
free infrastructure. Data comes from [tcgcsv.com](https://tcgcsv.com), a public
mirror of TCGPlayer's official API (no scraping, no API key needed).

## How to add a card

Edit [`watchlist.json`](watchlist.json):

```json
{
  "game": "one-piece",          // one-piece, pokemon, mtg, yugioh, lorcana, digimon, gundam...
  "set":  "Romance Dawn",       // partial set name is fine
  "name": "MonkeyDLuffy",       // partial card name, no spaces needed
  "number": "003"               // card number to disambiguate
}
```

Commit the change. The next scheduled run resolves it automatically and starts
recording prices.

## Schedule

Prices are checked twice daily (~7am / ~7pm Pacific) by GitHub Actions.
You can also trigger a run manually: **Actions → Track prices → Run workflow**.

> Note: tcgcsv refreshes TCGPlayer data about once per day, so the two daily
> snapshots often match. The tracker skips true duplicates automatically.

## Files

| Path | What it is |
|---|---|
| `watchlist.json` | **Your editable list of cards to track** |
| `report.md` | Auto-generated: latest prices + trend arrows |
| `data/prices.csv` | Full price history (one row per card per snapshot) |
| `product_map.json` | Cache mapping watchlist entries → TCGPlayer product IDs |

## Local use

```bash
python tracker.py
```
