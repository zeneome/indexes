import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import yfinance as yf

# silence yfinance's own log output so automated runs stay quiet
logging.getLogger("yfinance").disabled = True

RETRY_ATTEMPTS = 4
RETRY_BACKOFF = 3
REQUEST_DELAY = 1.0
DEFAULT_CACHE_DIR = "data/.cache"

# maps output field name -> yfinance info key for all extractable fields
ENRICH_FIELDS = [
    ("sector", "sector"),
    ("industry", "industry"),
    ("market_cap", "marketCap"),
    ("enterprise_value", "enterpriseValue"),
    ("trailing_pe", "trailingPE"),
    ("forward_pe", "forwardPE"),
    ("peg_ratio", "pegRatio"),
    ("price_to_book", "priceToBook"),
    ("price_to_sales", "priceToSalesTrailing12Months"),
    ("ev_to_revenue", "enterpriseToRevenue"),
    ("ev_to_ebitda", "enterpriseToEbitda"),
    ("dividend_yield", "dividendYield"),
    ("dividend_rate", "dividendRate"),
    ("payout_ratio", "payoutRatio"),
    ("five_year_avg_dividend_yield", "fiveYearAvgDividendYield"),
    ("ex_dividend_date", "exDividendDate"),
    ("revenue", "totalRevenue"),
    ("revenue_growth", "revenueGrowth"),
    ("gross_margins", "grossMargins"),
    ("operating_margins", "operatingMargins"),
    ("profit_margins", "profitMargins"),
    ("ebitda", "ebitda"),
    ("return_on_equity", "returnOnEquity"),
    ("return_on_assets", "returnOnAssets"),
    ("debt_to_equity", "debtToEquity"),
    ("total_cash", "totalCash"),
    ("total_debt", "totalDebt"),
    ("free_cashflow", "freeCashflow"),
    ("operating_cashflow", "operatingCashflow"),
    ("current_ratio", "currentRatio"),
    ("earnings_growth", "earningsGrowth"),
    ("current_price", "currentPrice"),
    ("previous_close", "previousClose"),
    ("fifty_two_week_high", "fiftyTwoWeekHigh"),
    ("fifty_two_week_low", "fiftyTwoWeekLow"),
    ("fifty_day_average", "fiftyDayAverage"),
    ("two_hundred_day_average", "twoHundredDayAverage"),
    ("beta", "beta"),
    ("average_volume", "averageVolume"),
    ("shares_outstanding", "sharesOutstanding"),
    ("float_shares", "floatShares"),
]

# all field names used for validation [company + every ENRICH_FIELDS entry]
_ALL_FIELD_NAMES = ["company"] + [name for name, _ in ENRICH_FIELDS]


def fetch_info(symbol):
    # returns a dict of enriched fields for a single ticker
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            info = yf.Ticker(symbol).info or {}

            # yfinance returns sparse dicts [e.g. {"trailingPegRatio": None}] on 404 or 429
            if len(info) < 5:
                raise ValueError(f"incomplete info for {symbol}")

            # company uses longName with shortName as fallback
            row = {"company": info.get("longName") or info.get("shortName", "")}

            # extract every mapped field via the shared lookup list
            for output_name, yf_key in ENRICH_FIELDS:
                row[output_name] = info.get(yf_key)

            return row
        except Exception:
            # back off exponentially between attempts
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF ** attempt)

    # give up after exhausting retries and return empty row
    row = {"company": ""}
    for output_name, _ in ENRICH_FIELDS:
        row[output_name] = None
    return row


def validate_row(row):
    # returns a float [0.0-1.0] representing fraction of non-None, non-empty fields
    filled = 0
    for name in _ALL_FIELD_NAMES:
        value = row.get(name)
        if value is not None and value != "":
            filled += 1
    return filled / len(_ALL_FIELD_NAMES)


def validate_results(results):
    # returns aggregate quality stats across all enriched rows
    total = len(results)
    qualities = [r.get("data_quality", 0.0) for r in results]
    enriched = sum(1 for q in qualities if q > 0.0)
    avg_quality = sum(qualities) / total if total > 0 else 0.0
    failed_symbols = [r["symbol"] for r in results if not r.get("company")]
    return {
        "total": total,
        "enriched": enriched,
        "quality": avg_quality,
        "failed_symbols": failed_symbols,
    }


def _load_cache(cache_path):
    # reads the json cache file from disk, returns empty dict on any failure
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache_path, cache_data):
    # atomic write [write to .tmp then rename] to avoid corruption
    cache_dir = os.path.dirname(cache_path)
    os.makedirs(cache_dir, exist_ok=True)
    tmp_path = cache_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(cache_data, f)
    os.replace(tmp_path, cache_path)


def _cache_entry_valid(entry, cache_ttl_days):
    # checks whether a cached entry is still within the ttl window
    fetched_at = entry.get("fetched_at")
    if not fetched_at:
        return False
    try:
        fetched_date = datetime.strptime(fetched_at, "%Y%m%d")
        return datetime.utcnow() - fetched_date < timedelta(days=cache_ttl_days)
    except ValueError:
        return False


def enrich_symbols(symbols, max_workers=5, cache_dir=DEFAULT_CACHE_DIR, cache_ttl_days=7):
    # fetches metadata for each ticker concurrently with optional disk caching
    use_cache = cache_dir is not None
    cache_path = os.path.join(cache_dir, "enrichment_cache.json") if use_cache else None
    cache_data = _load_cache(cache_path) if use_cache else {}

    # separate symbols into cached hits and symbols that need fetching
    results = [None] * len(symbols)
    to_fetch = []
    for i, symbol in enumerate(symbols):
        if use_cache and symbol in cache_data and _cache_entry_valid(cache_data[symbol], cache_ttl_days):
            row = dict(cache_data[symbol])
            row.pop("fetched_at", None)
            row["symbol"] = symbol
            row["data_quality"] = validate_row(row)
            results[i] = row
        else:
            to_fetch.append((i, symbol))

    def fetch_with_delay(index_and_symbol):
        index, symbol = index_and_symbol
        data = fetch_info(symbol)
        # per-worker delay keeps the aggregate request rate polite
        time.sleep(REQUEST_DELAY)
        return index, data

    # fetch any symbols not satisfied by the cache
    if to_fetch:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_with_delay, pair): pair for pair in to_fetch}
            for future in as_completed(futures):
                index, data = future.result()
                symbol = symbols[index]
                row = {"symbol": symbol}
                row.update(data)
                row["data_quality"] = validate_row(row)
                results[index] = row

                # update cache with fresh data
                if use_cache:
                    cache_entry = dict(data)
                    cache_entry["fetched_at"] = datetime.utcnow().strftime("%Y%m%d")
                    cache_data[symbol] = cache_entry

    # persist updated cache to disk
    if use_cache and to_fetch:
        _save_cache(cache_path, cache_data)

    return results
