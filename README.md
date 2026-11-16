# China FX & Rates Monitor

A static, auto-refreshing dashboard that asks: **is the renminbi under depreciation pressure, and how do interest-rate and inflation gaps with the United States shape its nominal and real value?**

## Indicators

| # | Indicator | Frequency | Source |
|---|---|---|---|
| 1 | USD/CNY spot (CNY per USD) | Daily | Federal Reserve Board, H.10 |
| 2 | RMB real & nominal effective exchange rate (2020 = 100) | Monthly | BIS |
| 3 | Policy rates: PBoC 1-year LPR vs Fed funds target | Monthly | BIS |
| 4 | 10-year government bond yields, China vs US | Monthly (daily spot in header) | OECD; ChinaBond and US Treasury for daily |
| 5 | CPI inflation y/y, China vs US | Monthly | OECD (NBS / BLS underlying) |
| 6 | Real GDP growth y/y | Quarterly | National Bureau of Statistics of China |
| 7 | Official manufacturing PMI | Monthly | National Bureau of Statistics of China / CFLP |
| 8 | Labour productivity growth (GDP per person employed) | Annual | World Bank WDI |
| – | Derived: UIP-implied vs realised USD/CNY change | Monthly | computed from 1 and 4 |

## How the refresh works

`scripts/fetch_data.py` (standard library only) downloads every series, writes `data/series.json`, and appends to `logs/refresh_log.txt`.
`.github/workflows/refresh.yml` runs it daily and on demand, commits the result, and GitHub Pages serves the static site from `main`.

* `meta.last_successful_refresh_utc` = last time **all** sources were fetched without error (shown in the page header).
* Each series' `latest_obs` = date of its newest data point (shown under each chart). The two are shown separately on purpose.
* If a source fails, its previous data are kept and flagged on the page; the workflow run is marked failed.
* NBS's data portal blocks automated access, so PMI and GDP are parsed from the NBS English press-release pages (cached in `data/nbs_cache.json`).

## Run locally

```bash
python3 scripts/fetch_data.py
python3 -m http.server 8000   # then open http://localhost:8000
```

See `docs/VERIFICATION.md` for source checks and `docs/PROMPT.md` for the prompt used to build it.
