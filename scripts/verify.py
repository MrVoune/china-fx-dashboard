#!/usr/bin/env python3
"""Check at least one observation of every series against an independent path to its original source.

Run after fetch_data.py:  python3 scripts/verify.py
Writes docs/verification_output.txt and exits 1 if any check fails.
"""
import csv, io, json, re, sys, html, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import get, page_text, DATA, ROOT  # noqa: E402

S = json.loads((DATA / "series.json").read_text())["series"]
CACHE = json.loads((DATA / "nbs_cache.json").read_text())
rows_out, fails = [], 0


def last(sid):
    return S[sid]["points"][-1]


def check(name, sid, obs, ours, theirs, tol, source, how):
    global fails
    ok = abs(ours - theirs) <= tol
    fails += (not ok)
    rows_out.append(f"{'PASS' if ok else 'FAIL'} | {name:<28} | obs {obs:<10} | dashboard {ours:>10.4f} | source {theirs:>10.4f} | tol {tol} | {source} | {how}")


# 1 USD/CNY vs the Fed's own "current release" page (independent of the history file we parse)
t = page_text(get("https://www.federalreserve.gov/releases/h10/current/"))
m = re.search(r"CHINA, P\.R\. YUAN ((?:[\d.]+|ND) ){4,5}", t)
vals = [x for x in m.group(0).split()[3:] if x != "ND"] if m else []
d, v = last("usdcny")
check("USD/CNY (latest day)", "usdcny", d, v, float(vals[-1]), 0.00005,
      "Fed H.10 current release page", "last number in China row of the weekly table")

# 2 BIS series: fresh single-observation request
for sid, key, flow in (("reer", "M.R.B.CN", "WS_EER"), ("neer", "M.N.B.CN", "WS_EER"),
                       ("policy_cn", "M.CN", "WS_CBPOL"), ("policy_us", "M.US", "WS_CBPOL")):
    url = f"https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/1.0/{key}?lastNObservations=1&format=csv"
    r = list(csv.DictReader(io.StringIO(get(url))))[-1]
    d, v = last(sid)
    check(f"BIS {sid}", sid, d, v, float(r["OBS_VALUE"]), 0.0001,
          f"BIS {flow} (period {r['TIME_PERIOD']})", "fresh lastNObservations=1 request")
    assert r["TIME_PERIOD"] == d, f"{sid}: period mismatch {r['TIME_PERIOD']} vs {d}"

# 3 US 10Y: OECD monthly average vs mean of US Treasury daily par yields (primary source)
d, v = last("y10_us")
yr, mo = int(d[:4]), int(d[5:])
url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
       f"{yr}/all?type=daily_treasury_yield_curve&field_tdr_date_value={yr}&page&_format=csv")
daily = [float(r["10 Yr"]) for r in csv.DictReader(io.StringIO(get(url)))
         if dt.datetime.strptime(r["Date"], "%m/%d/%Y").month == mo and r["10 Yr"]]
check("US 10Y (monthly mean)", "y10_us", d, v, sum(daily) / len(daily), 0.06,
      "US Treasury daily par yield curve", f"mean of {len(daily)} daily obs (OECD uses monthly avg)")

# 4 China 10Y: ChinaBond curve today vs last OECD monthly average (sanity only: different dates)
import json as _j
cb = _j.loads(get("https://yield.chinabond.com.cn/cbweb-czb-web/czb/czbChartSearch?locale=en_US"))
gov = next(c for c in cb if "国债" in c["ycDefName"])
y10 = next(p[1] for p in gov["seriesData"] if abs(p[0] - 10.0) < 1e-9)
d, v = last("y10_cn")
check("China 10Y (sanity)", "y10_cn", d, v, float(y10), 0.20,
      f"ChinaBond curve {gov['worktime']}", "different date (daily vs monthly avg): level sanity check only")

# 5 China CPI vs NBS release page
d, v = last("cpi_cn")
y, mm = int(d[:4]), int(d[5:])
names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
idx = ""
for p in range(0, 6):
    idx += get("https://www.stats.gov.cn/english/PressRelease/" + ("index.html" if p == 0 else f"index_{p}.html"))
mm_url = re.search(r'href="\./(\d{6}/[^"]+)"[^>]*>[^<]*Consumer Price Index in ' + names[mm - 1] + f" {y}", idx)
if mm_url:
    txt = page_text(get("https://www.stats.gov.cn/english/PressRelease/" + mm_url.group(1)))
    g = re.search(r"Consumer Price Index \(CPI\) (?:increased|decreased|rose|fell) by ([\d.]+)% year on year", txt)
    val = float(g.group(1)) * (-1 if re.search(r"CPI\) decreased", txt) else 1)
    check("China CPI y/y", "cpi_cn", d, v, val, 0.05, "NBS press release", "OECD value vs NBS release text")
else:
    rows_out.append(f"SKIP | China CPI y/y | NBS release for {d} not found in first 6 index pages")

# 6 US CPI y/y from BLS (index levels, NSA, all items)
d, v = last("cpi_us")
y, mm = int(d[:4]), int(d[5:])
j = json.loads(get(f"https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0?startyear={y-1}&endyear={y}"))
lv = {(r["year"], r["period"]): float(r["value"]) for r in j["Results"]["series"][0]["data"] if r["value"] not in ("-", "")}
cur, prev = lv[(str(y), f"M{mm:02d}")], lv[(str(y - 1), f"M{mm:02d}")]
check("US CPI y/y", "cpi_us", d, v, (cur / prev - 1) * 100, 0.06, "US BLS CPI-U (CUUR0000SA0)", f"index {cur} vs {prev} a year earlier")

# 7 NBS-derived series: re-read the exact release page and confirm the number is in the text
for sid in ("pmi", "gdp"):
    d, v = last(sid)
    rec = next(r for r in CACHE.values() if r["kind"] == sid and r["date"] == d)
    txt = page_text(get(rec["url"]))
    found = re.search(rf"(?<![\d.]){v:.1f}(?![\d])", txt) is not None
    fails += (not found)
    rows_out.append(f"{'PASS' if found else 'FAIL'} | NBS {sid.upper():<24} | obs {d:<10} | dashboard {v:>10.1f} | value found in {rec['url']}")

# 8 World Bank productivity: independent single-country request, recompute growth
for sid, iso in (("prod_cn", "CHN"), ("prod_us", "USA")):
    j = json.loads(get(f"https://api.worldbank.org/v2/country/{iso}/indicator/SL.GDP.PCAP.EM.KD?format=json&per_page=100&mrv=3"))
    pts = sorted((int(r["date"]), r["value"]) for r in j[1] if r["value"] is not None)
    g = (pts[-1][1] / pts[-2][1] - 1) * 100
    d, v = last(sid)
    assert int(d) == pts[-1][0]
    check(f"World Bank {sid}", sid, d, v, g, 0.001, "World Bank WDI API", "growth recomputed from two levels")

out = "\n".join(rows_out) + f"\n\n{'ALL CHECKS PASSED' if not fails else str(fails) + ' CHECK(S) FAILED'} at {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
print(out)
(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs" / "verification_output.txt").write_text(out)
sys.exit(1 if fails else 0)
