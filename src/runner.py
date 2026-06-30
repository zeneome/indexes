import argparse
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd

from config import INDEX_CONFIGS
from scraper import scrape_symbols
from enricher import enrich_symbols, validate_results
from logger import logger

# data lives in the repo root next to src, regardless of the current working directory
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# full field list matching the enricher output format
CSV_COLUMNS = [
    "symbol", "company", "sector", "industry",
    "market_cap", "enterprise_value", "trailing_pe", "forward_pe",
    "peg_ratio", "price_to_book", "price_to_sales", "ev_to_revenue", "ev_to_ebitda",
    "dividend_yield", "dividend_rate", "payout_ratio",
    "five_year_avg_dividend_yield", "ex_dividend_date",
    "revenue", "revenue_growth", "gross_margins", "operating_margins",
    "profit_margins", "ebitda", "return_on_equity", "return_on_assets",
    "debt_to_equity", "total_cash", "total_debt", "free_cashflow", "operating_cashflow",
    "current_ratio", "earnings_growth",
    "current_price", "previous_close", "fifty_two_week_high",
    "fifty_two_week_low", "fifty_day_average", "two_hundred_day_average",
    "beta", "average_volume", "shares_outstanding", "float_shares",
    "data_quality",
]


def write_outputs(rows, base_path):
    # writes enriched rows to csv and parquet
    os.makedirs(os.path.dirname(base_path), exist_ok=True)

    csv_path = f"{base_path}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    parquet_path = f"{base_path}.parquet"
    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    # yfinance sometimes returns "Infinity" as a string, which breaks pyarrow double conversion
    df = df.replace({"Infinity": float("inf"), "-Infinity": float("-inf")})
    df.to_parquet(parquet_path, engine="pyarrow", index=False)


def write_diff(name, region, new_symbols, data_dir):
    # compares old vs new symbol lists and appends changes to the tracking file
    csv_path = os.path.join(data_dir, region, f"{name}.csv")
    old_symbols = set()

    if not os.path.exists(csv_path):
        return

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            old_symbols.add(row["symbol"])

    new_set = set(new_symbols)
    added = sorted(new_set - old_symbols)
    removed = sorted(old_symbols - new_set)

    if not added and not removed:
        return

    entry = {
        "date": date.today().strftime("%Y%m%d"),
        "added": added,
        "removed": removed,
        "count_before": len(old_symbols),
        "count_after": len(new_set),
    }

    changes_path = os.path.join(data_dir, region, f"{name}_changes.json")
    changes = []
    if os.path.exists(changes_path):
        with open(changes_path, "r", encoding="utf-8") as f:
            changes = json.load(f)

    changes.append(entry)

    os.makedirs(os.path.dirname(changes_path), exist_ok=True)
    with open(changes_path, "w", encoding="utf-8") as f:
        json.dump(changes, f, indent=2, ensure_ascii=False)

def write_manifest(results):
    # writes data/manifest.json summarising every index and providing an llm-friendly schema definition
    manifest_path = os.path.join(DATA_DIR, "manifest.json")
    
    # load existing manifest so we can update in place instead of wiping out unrelated indices
    manifest = {"indices": []}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except json.JSONDecodeError:
            pass

    # dict mapping index name to its properties for easy updating
    indices_map = {item["name"]: item for item in manifest.get("indices", [])}

    for name, region, count, enriched, quality, csv_path, parquet_path in results:
        indices_map[name] = {
            "name": name,
            "region": region,
            "updated": date.today().strftime("%Y%m%d"),
            "count": count,
            "enriched": enriched,
            "data_quality": quality,
        }

    # sort alphabetically by name for predictable output
    sorted_indices = [indices_map[k] for k in sorted(indices_map.keys())]

    manifest = {
        "indices": sorted_indices,
    }
    
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def process_index(config, scrape_only=False, cache_dir=None, max_workers=5):
    # scrapes symbols, tracks diff, enriches via yfinance, validates, writes csv + parquet
    name = config["name"]
    region = config["region"]
    base_path = os.path.join(DATA_DIR, region, name)

    symbols = scrape_symbols(config)
    if not symbols:
        raise ValueError(f"[{name}] scrape returned no symbols")

    # record symbol changes before overwriting the old csv
    write_diff(name, region, symbols, DATA_DIR)

    # build bare rows when enrichment is skipped, otherwise fetch metadata
    if scrape_only:
        rows = [
            {col: ("" if col in ("company", "sector", "industry") else None) for col in CSV_COLUMNS}
            | {"symbol": s}
            for s in symbols
        ]
        enriched = 0
        quality = 0.0
    else:
        rows = enrich_symbols(symbols, max_workers=max_workers, cache_dir=cache_dir)
        validation = validate_results(rows)
        enriched = validation["enriched"]
        quality = validation["quality"]



    write_outputs(rows, base_path)
    csv_path = os.path.relpath(f"{base_path}.csv", os.path.dirname(DATA_DIR))
    parquet_path = os.path.relpath(f"{base_path}.parquet", os.path.dirname(DATA_DIR))

    logger.log(index=name, enriched=enriched, total=len(rows), data_quality=round(quality, 2))
    return name, region, len(rows), enriched, quality, csv_path, parquet_path


def get_configs(names=None):
    # returns filtered configs if names provided, otherwise all
    if not names:
        return INDEX_CONFIGS
    name_set = set(names)
    return [c for c in INDEX_CONFIGS if c["name"] in name_set]


def main():
    # parse cli arguments for the index list and the optional modes
    parser = argparse.ArgumentParser(description="indexes: fetch and update index components")
    parser.add_argument("indices", nargs="*", help="index names to process [default: all]")
    parser.add_argument("--list", action="store_true", help="list available index names")
    parser.add_argument("--scrape-only", action="store_true", help="skip yfinance enrichment")
    parser.add_argument("--no-cache", action="store_true", help="skip enrichment caching")
    parser.add_argument("--workers", type=int, default=5, help="max workers for enrichment [default: 5]")
    args = parser.parse_args()

    # list mode prints the known indices and exits
    if args.list:
        for config in INDEX_CONFIGS:
            logger.log(action="list", index=config['name'], region=config['region'])
        return

    # resolve which configs to run, exiting non-zero when nothing matches
    configs = get_configs(args.indices if args.indices else None)
    if not configs:
        sys.exit(1)

    cache_dir = None if args.no_cache else os.path.join(DATA_DIR, ".cache")

    # run each index sequentially to avoid massive yfinance api rate limiting [429s]
    manifest_entries = []
    failed = 0

    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {
            executor.submit(process_index, c, args.scrape_only, cache_dir, args.workers): c
            for c in configs
        }
        for future in as_completed(futures):
            config = futures[future]
            name = config["name"]
            try:
                entry = future.result()
                manifest_entries.append(entry)
            except Exception:
                failed += 1

    write_manifest(manifest_entries)


    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
