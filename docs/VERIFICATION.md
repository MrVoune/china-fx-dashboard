# Evidence of verification

## 1. Successful automated refresh

* Workflow: https://github.com/MrVoune/china-fx-dashboard/actions/runs/43980411697 (trigger: `workflow_dispatch`, runner: GitHub-hosted `ubuntu-latest`).
* All steps succeeded: *Fetch data*, *Verify against original sources*, *Commit refreshed data and log*. The scheduled trigger is `30 2 * * *` (daily, 02:30 UTC).
* The run appended to [`logs/refresh_log.txt`](../logs/refresh_log.txt) and committed `data/series.json`; the page header shows this timestamp as **Last successful refresh**, separate from each chart's **Latest obs.**
* Source behaviour confirmed on the cloud runner: Fed H.10, BIS, OECD, World Bank, US Treasury, ChinaBond and the NBS English release pages were all reachable (NBS data portal `data.stats.gov.cn` is blocked, hence the parsed release pages).
* The refresh produced no new data points for sources that had not published since the earlier local run, which is expected: a successful refresh need not change values.

## 2. Data checks against original sources

`scripts/verify.py` runs after every refresh (output: [`verification_output.txt`](verification_output.txt)). Latest run, 2026-11-16 23:34 UTC, all 12 checks passed:

| Series | Observation | Dashboard | Original source | Check path |
|---|---|---|---|---|
| USD/CNY | 13 Nov 2026 | 6.6710 | 6.6710 | Fed H.10 current-release weekly table (not the history file used for the chart) |
| BIS REER | Sep 2026 | 91.91 | 91.91 | Fresh BIS request, last observation |
| BIS NEER | Sep 2026 | 113.42 | 113.42 | same |
| China policy rate (1y LPR) | Oct 2026 | 3.00 | 3.00 | same |
| US policy rate | Oct 2026 | 3.875 | 3.875 | same |
| US 10Y yield | Oct 2026 | 5.130 | 5.131 | Mean of 21 US Treasury daily par yields (OECD reports a monthly average) |
| China 10Y yield | Sep 2026 | 1.68 | 1.6285 | ChinaBond curve for 16 Nov: **level sanity check only** (different date; ChinaBond has no free history) |
| China CPI y/y | Oct 2026 | 0.7 | 0.7 | NBS press release "Consumer Price Index in October 2026" |
| US CPI y/y | Sep 2026 | 3.7377 | 3.7377 | BLS CPI-U index levels, 336.94 vs 324.80 a year earlier |
| China PMI | Oct 2026 | 49.3 | 49.3 | Value located in the NBS release page it was parsed from |
| China GDP y/y | Q3 2026 | 4.5 | 4.5 | same (NBS "Preliminary Accounting Results of GDP for the Third Quarter of 2026") |
| Productivity growth CN / US | 2025 | 5.001 / 1.958 | 5.001 / 1.958 | World Bank single-country request, growth recomputed from two levels |

The derived UIP chart contains no external data; it is computed from the USD/CNY and 10-year-yield series above.

## 3. Known limitations

* China 10Y: monthly series is OECD; the ChinaBond cross-check is approximate.
* PMI and GDP history begins mid-2024 because that is as far back as the NBS English release index goes.
* Productivity data are annual and lag (latest 2025), using World Bank/ILO modelled estimates.
* If a source fails, the page keeps that source's previous data, shows a warning and marks the run as failed.
