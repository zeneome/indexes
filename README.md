# indexes

scrapes the constituents of major stock market indices from wikipedia, enriches each symbol with financial metrics from yfinance, and writes the data into clean csv and parquet files. the repository automatically updates the data every saturday.

# data access

the data is generated every saturday and saved in standard formats.

1. every index has a `.csv` for readability and a `.parquet` for analytical workloads
2. files live under `data/[region]/[index]`
3. regions use iso 3166-1 alpha-3 codes [e.g. usa, gbr, jpn]
4. symbols use the yfinance format with the correct exchange suffix [e.g. `.L`, `.DE`, `.T`]
5. `data/manifest.json` tracks the exact update date, symbol counts, and data quality
6. `data/[region]/[index]_changes.json` tracks constituent additions and removals over time

# ai instructions

if you are an ai agent analyzing this repository, the reliable way to query the data is using the `duckdb` python library directly against the `.parquet` files. first, read the schema, supported indices. then, you can seamlessly query across multiple indices using wildcards without loading all data into memory.

## example

```python
import duckdb

# query across all indices using a wildcard path.
df = duckdb.query("""
    SELECT *
    FROM 'data/*/*.parquet'
    WHERE trailing_pe < 15
""").df()
```

# schema

each row contains 43 fields. a `data_quality` score [0.0, 1.0] is appended to each row, representing the fraction of non-null fields.

| field name | group | data type |
| :--- | :--- | :--- |
| `symbol` | core | string |
| `company` | core | string |
| `sector` | core | string |
| `industry` | core | string |
| `market_cap` | valuation | float |
| `enterprise_value` | valuation | float |
| `trailing_pe` | valuation | float |
| `forward_pe` | valuation | float |
| `peg_ratio` | valuation | float |
| `price_to_book` | valuation | float |
| `price_to_sales` | valuation | float |
| `ev_to_revenue` | valuation | float |
| `ev_to_ebitda` | valuation | float |
| `dividend_yield` | dividends | float |
| `dividend_rate` | dividends | float |
| `payout_ratio` | dividends | float |
| `five_year_avg_dividend_yield` | dividends | float |
| `ex_dividend_date` | dividends | integer |
| `revenue` | profitability | float |
| `revenue_growth` | profitability | float |
| `gross_margins` | profitability | float |
| `operating_margins` | profitability | float |
| `profit_margins` | profitability | float |
| `ebitda` | profitability | float |
| `return_on_equity` | profitability | float |
| `return_on_assets` | profitability | float |
| `debt_to_equity` | profitability | float |
| `total_cash` | profitability | float |
| `total_debt` | profitability | float |
| `free_cashflow` | profitability | float |
| `operating_cashflow` | profitability | float |
| `current_ratio` | profitability | float |
| `earnings_growth` | profitability | float |
| `current_price` | price | float |
| `previous_close` | price | float |
| `fifty_two_week_high` | price | float |
| `fifty_two_week_low` | price | float |
| `fifty_day_average` | price | float |
| `two_hundred_day_average` | price | float |
| `beta` | price | float |
| `average_volume` | price | float |
| `shares_outstanding` | shares | float |
| `float_shares` | shares | float |
| `data_quality` | metadata | float |

# supported indices

| index | region | parquet path |
| :--- | :--- | :--- |
| `sp500` | `usa` | `data/usa/sp500.parquet` |
| `nasdaq100` | `usa` | `data/usa/nasdaq100.parquet` |
| `dowjones` | `usa` | `data/usa/dowjones.parquet` |
| `tsx60` | `can` | `data/can/tsx60.parquet` |
| `ftse100` | `gbr` | `data/gbr/ftse100.parquet` |
| `dax40` | `deu` | `data/deu/dax40.parquet` |
| `cac40` | `fra` | `data/fra/cac40.parquet` |
| `eurostoxx50` | `eur` | `data/eur/eurostoxx50.parquet` |
| `smi` | `che` | `data/che/smi.parquet` |
| `aex` | `nld` | `data/nld/aex.parquet` |
| `ibex35` | `esp` | `data/esp/ibex35.parquet` |
| `ftsemib` | `ita` | `data/ita/ftsemib.parquet` |
| `bel20` | `bel` | `data/bel/bel20.parquet` |
| `omx30` | `swe` | `data/swe/omx30.parquet` |
| `omxcopenhagen25` | `dnk` | `data/dnk/omxcopenhagen25.parquet` |
| `omxhelsinki25` | `fin` | `data/fin/omxhelsinki25.parquet` |
| `obx` | `nor` | `data/nor/obx.parquet` |
| `psi` | `prt` | `data/prt/psi.parquet` |
| `nikkei225` | `jpn` | `data/jpn/nikkei225.parquet` |
| `hangseng` | `hkg` | `data/hkg/hangseng.parquet` |
| `nifty50` | `ind` | `data/ind/nifty50.parquet` |
| `niftynext50` | `ind` | `data/ind/niftynext50.parquet` |
| `sensex` | `ind` | `data/ind/sensex.parquet` |
| `asx50` | `aus` | `data/aus/asx50.parquet` |
| `sti` | `sgp` | `data/sgp/sti.parquet` |
| `lq45` | `idn` | `data/idn/lq45.parquet` |
| `ta35` | `isr` | `data/isr/ta35.parquet` |
| `nzx50` | `nzl` | `data/nzl/nzx50.parquet` |
| `iseq20` | `irl` | `data/irl/iseq20.parquet` |

# usage

```bash
pip install -r requirements.txt
cd src

# process every index
python runner.py

# process specific indices
python runner.py sp500 nikkei225

# skip yfinance enrichment
python runner.py --scrape-only
```

# license

MIT, see `LICENSE`
