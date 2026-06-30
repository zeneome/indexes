import re
from io import StringIO

import pandas as pd
import requests

USER_AGENT = "Mozilla/5.0 [compatible; indexes-bot/1.0]"

# wikipedia mediawiki api endpoint used for non-table sources [e.g. nikkei 225]
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


def fetch_table(config):
    # fetches the correct wikipedia table for a given index config
    name = config["name"]

    # download the page with a browser-like user agent and a hard timeout
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(config["url"], headers=headers, timeout=30)
    resp.raise_for_status()
    html = StringIO(resp.text)

    # three ways to locate the table, tried in order of reliability
    table_id = config.get("table_id")
    table_match = config.get("table_match")
    table_index = config["table_index"]

    # first choice: match the table by its html id attribute
    if table_id:
        try:
            html.seek(0)
            tables = pd.read_html(html, attrs={"id": table_id})
            if tables:
                return tables[0]
        except ValueError:
            pass

    # second choice: match the table by a string in one of its cells
    if table_match:
        try:
            html.seek(0)
            tables = pd.read_html(html, match=table_match)
            if tables:
                return tables[0]
        except ValueError:
            pass

    # last resort: pick the table by its position on the page
    html.seek(0)
    tables = pd.read_html(html)
    if table_index >= len(tables):
        raise ValueError(f"[{name}] table index {table_index} out of range, {len(tables)} tables found")
    return tables[table_index]


def normalize_symbol(raw_symbol, config):
    # converts raw wikipedia symbol to yfinance-compatible ticker
    symbol = str(raw_symbol).strip()
    ticker_format = config.get("ticker_format", "")

    # hang seng format: "SEHK: 5" -> "0005.HK"
    if ticker_format == "sehk":
        digits = "".join(c for c in symbol if c.isdigit())
        return digits.zfill(4) + config["ticker_suffix"]

    # remove exchange prefixes like "Euronext Brussels: ABI.BR" or "IDX: ACES"
    if ":" in symbol:
        symbol = symbol.split(":")[-1].strip()

    # replace class share spaces with dashes: "NOVO B" -> "NOVO-B"
    if " " in symbol:
        symbol = symbol.replace(" ", "-")

    # apply known corrections before adding suffix
    overrides = config.get("ticker_overrides", {})
    if symbol in overrides:
        symbol = overrides[symbol]

    # yahoo finance exchange suffixes already present on some scraped tickers
    known_suffixes = {
        "sw", "to", "ax", "mc", "as", "st", "si", "br", "mi", "ls", "sa",
        "de", "pa", "l", "t", "bo", "ns", "hk", "he",
        "ol", "vi", "jk", "co", "ta", "ps", "nz", "ir",
    }

    # append default suffix only if symbol doesn't already have one
    has_suffix = any(symbol.lower().endswith("." + s) for s in known_suffixes)
    if not has_suffix:
        suffix = config.get("ticker_suffix", "")
        if suffix and not symbol.lower().endswith(suffix.lower()):
            symbol = symbol + suffix

    # convert class share dots to dashes if not part of exchange suffix
    parts = symbol.split(".")
    if len(parts) > 1:
        # separate the exchange suffix so only the base ticker is rewritten
        if parts[-1].lower() in known_suffixes:
            base_parts = parts[:-1]
            ext_suffix = "." + parts[-1]
        else:
            base_parts = parts
            ext_suffix = ""

        # join class shares with a dash, e.g. brk.b becomes brk-b
        if len(base_parts) > 1:
            symbol = "-".join(base_parts) + ext_suffix

    return symbol


def scrape_nikkei(config):
    # fetches nikkei 225 codes via the wikipedia wikitext api and converts to yfinance tickers
    # the nikkei 225 page lists components as {{tyo2|XXXX}} and {{TYO|XXXX}} wikitext templates
    name = config["name"]
    params = {
        "action": "parse",
        "page": "Nikkei_225",
        "prop": "wikitext",
        "section": "5",
        "format": "json",
    }
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(WIKIPEDIA_API, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    wikitext = resp.json()["parse"]["wikitext"]["*"]

    # match both {{tyo2|XXXX}} and {{TYO|XXXX}} template forms
    codes = re.findall(r"\{\{(?:tyo2|TYO)\|(\w+)\}\}", wikitext)
    if not codes:
        raise ValueError(f"[{name}] no tyo2/TYO codes found in wikitext")

    suffix = config.get("ticker_suffix", ".T")
    return [code + suffix for code in codes]


def scrape_symbols(config):
    # returns list of yfinance-compatible ticker strings for the given index
    # raises on scrape failure so the caller can distinguish a real error from an empty index
    name = config["name"]
    ticker_format = config.get("ticker_format", "")

    if ticker_format == "nikkei":
        symbols = scrape_nikkei(config)
    else:
        df = fetch_table(config)

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(-1)

        symbol_col = config["symbol_col"]
        if symbol_col not in df.columns:
            raise ValueError(f"[{name}] column '{symbol_col}' not found; available: {list(df.columns)}")

        symbols = []
        for raw in df[symbol_col].dropna():
            symbol = normalize_symbol(raw, config)
            if symbol:
                symbols.append(symbol)

    expected = config.get("expected_count")
    if expected and len(symbols) < expected * 0.8:
        raise ValueError(
            f"[{name}] expected ~{expected} symbols but got {len(symbols)}, wikipedia table may have changed"
        )

    return symbols
