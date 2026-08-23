#!/usr/bin/env python3
"""TCGPlayer price tracker.

Reads watchlist.json, resolves each entry to a TCGPlayer productId via the
public tcgcsv.com mirror of TCGPlayer's official API, appends current prices
to data/prices.csv (skipping duplicate snapshots), and regenerates report.md.
"""
import csv
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
DATA = ROOT / "data"
PRICES_CSV = DATA / "prices.csv"
MAP_FILE = ROOT / "product_map.json"
WATCHLIST = ROOT / "watchlist.json"
REPORT = ROOT / "report.md"
BASE = "https://tcgcsv.com/tcgplayer"
UA = "tcg-price-tracker/1.0 (personal price monitoring)"
FIELDS = ["timestamp_utc", "game", "set", "name", "number",
          "product_id", "sub_type", "low", "mid", "market", "high", "direct_low"]


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["results"]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_json(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")


def get_categories():
    cache = ROOT / ".categories_cache.json"
    if cache.exists():
        return {c["name"].lower(): c["categoryId"] for c in load_json(cache, [])}
    cats = http_json(f"{BASE}/categories")
    save_json(cache, cats)
    return {c["name"].lower(): c["categoryId"] for c in cats}


def resolve_category(game, cat_map):
    aliases = {
        "one-piece": "one piece card game", "pokemon": "pokemon",
        "mtg": "magic", "magic": "magic", "yugioh": "yugioh",
        "lorcana": "lorcana", "digimon": "digimon card game",
        "dragon-ball-super": "dragon ball super ccg",
        "star-wars-unlimited": "star wars unlimited", "gundam": "gundam card game",
    }
    key = aliases.get(game.lower(), game.lower())
    for name, cid in cat_map.items():
        if key in name:
            return cid
    sys.exit(f"ERROR: no TCGPlayer category matches game '{game}'")


def find_group(cat_id, set_name, groups_cache):
    for g in groups_cache.setdefault(cat_id, http_json(f"{BASE}/{cat_id}/groups")):
        if norm(set_name) in norm(g["name"]):
            return g
    return None


def resolve(entry, cat_map, groups_cache):
    """entry -> dict(productId, groupId, ...) using product_map.json cache."""
    pmap = load_json(MAP_FILE, {})
    key = f"{norm(entry['game'])}|{norm(entry['set'])}|{norm(entry['name'])}|{norm(str(entry['number']))}"
    if key in pmap:
        return pmap[key]

    cat_id = resolve_category(entry["game"], cat_map)
    group = find_group(cat_id, entry["set"], groups_cache)
    if not group:
        print(f"  !! set '{entry['set']}' not found, skipping")
        return None
    products = http_json(f"{BASE}/{cat_id}/{group['groupId']}/products")

    want_name, want_num = norm(entry["name"]), norm(str(entry["number"]))
    hits = []
    for p in products:
        cn = norm(p["cleanName"])
        if want_name in cn:
            num = re.search(r"(\d+[a-z]*)\s*$", p.get("cleanName", "").strip().lower())
            if num and want_num and num.group(1).startswith(want_num):
                hits.append(p)
    if len(hits) != 1:
        print(f"  !! '{entry['name']}' #{entry['number']}: {len(hits)} matches, skipping "
              f"({[h['cleanName'] for h in hits][:3]})")
        return None

    hit = {"productId": hits[0]["productId"], "groupId": group["groupId"],
           "categoryId": cat_id, "cleanName": hits[0]["cleanName"]}
    pmap[key] = hit
    save_json(MAP_FILE, pmap)
    return hit


def fetch_prices(groups_used):
    prices = {}
    for cat, gid in groups_used:
        for pr in http_json(f"{BASE}/{cat}/{gid}/prices"):
            prices[pr["productId"]] = pr
    return prices


def main():
    watchlist = load_json(WATCHLIST, {}).get("cards", [])
    if not watchlist:
        sys.exit("watchlist.json has no cards")
    cat_map = get_categories()
    groups_cache, resolved, used_groups = {}, [], set()

    print(f"Resolving {len(watchlist)} watchlist entries...")
    for entry in watchlist:
        r = resolve(entry, cat_map, groups_cache)
        if r:
            r.update({k: entry.get(k, "") for k in ("game", "set", "name", "number")})
            used_groups.add((r["categoryId"], r["groupId"]))
            resolved.append(r)
            print(f"  ok -> {r['cleanName']} (id {r['productId']})")
    if not resolved:
        sys.exit("nothing resolved; fix watchlist entries above")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    price_data = fetch_prices(used_groups)

    # previous snapshot per product for dedupe + trend
    last_row = {}
    if PRICES_CSV.exists():
        with open(PRICES_CSV) as f:
            for row in csv.DictReader(f):
                last_row[row["product_id"]] = row

    new_rows, changed = [], 0
    for r in resolved:
        p = price_data.get(r["productId"], {})
        vals = [p.get(k) for k in ("lowPrice", "midPrice", "marketPrice", "highPrice", "directLowPrice")]
        prev = last_row.get(str(r["productId"]))
        same_day = prev and prev["timestamp_utc"][:10] == now[:10]
        unchanged = prev and [prev[k] for k in ("low", "mid", "market", "high", "direct_low")] == \
            [str(v) if v is not None else "" for v in vals]
        if same_day and unchanged:
            continue
        row = {"timestamp_utc": now, "game": r["game"], "set": r["set"],
               "name": r["cleanName"], "number": r["number"],
               "product_id": r["productId"], "sub_type": p.get("subTypeName", "")}
        row.update(dict(zip(("low", "mid", "market", "high", "direct_low"),
                            (v if v is not None else "" for v in vals))))
        new_rows.append(row)
        if not unchanged and prev:
            changed += 1

    DATA.mkdir(exist_ok=True)
    write_header = not PRICES_CSV.exists()
    with open(PRICES_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            w.writeheader()
        w.writerows(new_rows)
    print(f"Appended {len(new_rows)} rows ({changed} price changes); "
          f"skipped duplicates.")

    # ---- report ----
    lines = ["# Price Report", "",
             f"_Last run: {now} UTC · source: TCGPlayer via tcgcsv.com_", "",
             "| Card | Market | Prev | Change | Since start | Low–High |",
             "|---|---|---|---|---|---|"]
    for r in resolved:
        pid, cur = str(r["productId"]), last_row.get(str(r["productId"]))
        mkt = next((x["market"] for x in new_rows if str(x["product_id"]) == pid),
                   cur["market"] if cur else "")
        arrow, pct = "", ""
        if cur and cur["market"] and mkt:
            try:
                d = float(mkt) - float(cur["market"])
                pct = f"{d / float(cur['market']) * 100:+.1f}%"
                arrow = "🔺" if d > 0 else ("🔻" if d < 0 else "➖")
            except ValueError:
                pass
        first_mkt = ""
        for row in csv.DictReader(open(PRICES_CSV)):
            if row["product_id"] == pid and row["market"]:
                first_mkt = row["market"]
        rng = ""
        nr = next((x for x in new_rows if str(x["product_id"]) == pid), None)
        if nr and nr["low"] and nr["high"]:
            rng = f"${float(nr['low']):.2f} – ${float(nr['high']):.2f}"
        lines.append(f"| [{r['cleanName']}](https://www.tcgplayer.com/product/{pid}) "
                     f"`{r['number']}` | ${mkt} | {cur['market'] if cur else '—'} "
                     f"{arrow}{pct} | ${first_mkt} | {rng} |")
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"Report written: {REPORT}")


if __name__ == "__main__":
    main()
