#!/usr/bin/env python3
"""Fetch all dashboard series from primary / international-organisation sources.

Standard library only. Writes:
  data/series.json      - every series + metadata (what the page reads)
  data/nbs_cache.json   - parsed NBS release pages (so we only crawl new ones)
  logs/refresh_log.txt  - append-only run log (evidence of refreshes)

Design rules
  * A source that fails keeps its previous data and is flagged; the run is only
    a "successful refresh" if every source succeeded.
  * `last_successful_refresh_utc` (when the job last worked) is stored separately
    from each series' `latest_obs` (the date of the newest data point).
"""
import csv, io, json, re, sys, time, html, subprocess, datetime as dt
import urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LOGS = ROOT / "logs"
DATA.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)
START_YEAR = 2015
UA = "Mozilla/5.0 (compatible; china-fx-dashboard/1.0)"
NOW = dt.datetime.now(dt.timezone.utc)

log_lines = []


def log(msg):
    line = f"{NOW.strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line)
    log_lines.append(line)


def get(url, tries=3, timeout=60):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:  # noqa
            last = e
            if "CERTIFICATE_VERIFY_FAILED" in str(e):  # e.g. python.org build without CA bundle
                try:
                    return subprocess.run(
                        ["curl", "-sSL", "--http1.1", "-m", str(timeout), "-A", UA, url],
                        check=True, capture_output=True).stdout.decode("utf-8", errors="ignore")
                except Exception as e2:  # noqa
                    last = e2
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def pts_sorted(points):
    return sorted(points, key=lambda p: p[0])


MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
MONTH_FULL = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"])}

# --------------------------------------------------------------------------- Fed H.10
def fetch_fed():
    url = "https://www.federalreserve.gov/releases/h10/hist/dat00_ch.htm"
    h = get(url, timeout=120)
    pts = []
    for d, v in re.findall(r"<th[^>]*>\s*(\d{1,2}-[A-Z]{3}-\d{2})\s*</th>\s*<td[^>]*>\s*([\d.]+)\s*</td>", h):
        dd, mon, yy = d.split("-")
        year = 2000 + int(yy)
        if year < START_YEAR:
            continue
        pts.append([f"{year}-{MONTHS[mon.capitalize()]:02d}-{int(dd):02d}", float(v)])
    if not pts:
        raise RuntimeError("Fed H.10: no data parsed")
    return {"usdcny": pts_sorted(pts)}, url


# --------------------------------------------------------------------------- BIS
def bis_csv(flow, key, start=f"{START_YEAR}-01"):
    url = (f"https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/1.0/{key}"
           f"?startPeriod={start}&format=csv")
    rows = list(csv.DictReader(io.StringIO(get(url))))
    return rows, url


def fetch_bis():
    out = {}
    rows, u1 = bis_csv("WS_EER", "M.R.B.CN")
    out["reer"] = pts_sorted([[r["TIME_PERIOD"], float(r["OBS_VALUE"])] for r in rows if r["OBS_VALUE"]])
    rows, _ = bis_csv("WS_EER", "M.N.B.CN")
    out["neer"] = pts_sorted([[r["TIME_PERIOD"], float(r["OBS_VALUE"])] for r in rows if r["OBS_VALUE"]])
    rows, u2 = bis_csv("WS_CBPOL", "M.CN+US")
    cn, us = [], []
    for r in rows:
        if not r["OBS_VALUE"]:
            continue
        (cn if r["REF_AREA"] == "CN" else us).append([r["TIME_PERIOD"], float(r["OBS_VALUE"])])
    out["policy_cn"], out["policy_us"] = pts_sorted(cn), pts_sorted(us)
    if not all(out.values()):
        raise RuntimeError("BIS: empty series")
    return out, u1 + " | " + u2


# --------------------------------------------------------------------------- OECD
def oecd_csv(flow, key, start=f"{START_YEAR}-01"):
    url = (f"https://sdmx.oecd.org/public/rest/data/{flow}/{key}"
           f"?startPeriod={start}&format=csvfilewithlabels")
    return list(csv.DictReader(io.StringIO(get(url)))), url


def fetch_oecd():
    out = {}
    rows, u1 = oecd_csv("OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0", "CHN+USA.M.IRLT.PA.....")
    y = {"CHN": [], "USA": []}
    for r in rows:
        if r["OBS_VALUE"] and r["REF_AREA"] in y:
            y[r["REF_AREA"]].append([r["TIME_PERIOD"], float(r["OBS_VALUE"])])
    out["y10_cn"], out["y10_us"] = pts_sorted(y["CHN"]), pts_sorted(y["USA"])
    rows, u2 = oecd_csv("OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0", "CHN+USA.M.N.CPI.PA._T.N.GY")
    c = {"CHN": [], "USA": []}
    for r in rows:
        if r["OBS_VALUE"] and r["REF_AREA"] in c:
            c[r["REF_AREA"]].append([r["TIME_PERIOD"], float(r["OBS_VALUE"])])
    out["cpi_cn"], out["cpi_us"] = pts_sorted(c["CHN"]), pts_sorted(c["USA"])
    if not all(out.values()):
        raise RuntimeError("OECD: empty series")
    return out, u1 + " | " + u2


# --------------------------------------------------------------------------- World Bank
def fetch_worldbank():
    ind = "SL.GDP.PCAP.EM.KD"
    url = (f"https://api.worldbank.org/v2/country/CHN;USA/indicator/{ind}"
           f"?format=json&per_page=500&date=2005:{NOW.year}")
    j = json.loads(get(url))
    lv = {"CHN": {}, "USA": {}}
    for r in j[1]:
        if r["value"] is not None:
            lv[r["countryiso3code"]][int(r["date"])] = r["value"]
    out = {}
    for c, key in (("CHN", "prod_cn"), ("USA", "prod_us")):
        growth = []
        for y in sorted(lv[c]):
            if y - 1 in lv[c] and y >= 2011:
                growth.append([str(y), round((lv[c][y] / lv[c][y - 1] - 1) * 100, 3)])
        out[key] = growth
        out[key + "_level"] = [[str(y), lv[c][y]] for y in sorted(lv[c]) if y >= 2010]
    if not out["prod_cn"]:
        raise RuntimeError("World Bank: empty")
    return out, url


# --------------------------------------------------------------------------- NBS (English release pages)
NBS_BASE = "https://www.stats.gov.cn/english/PressRelease/"
NBS_TITLE = re.compile(
    r"(Purchasing Managers.{1,3}Index for (\w+) (\d{4}))"
    r"|(Preliminary Accounting Results of GDP for ([^<]*?))\s*$", re.I)


def page_text(h):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def parse_nbs_page(url, title):
    txt = page_text(get(url))
    m = re.search(r"Purchasing Managers.{1,3}Index for (\w+) (\d{4})", title, re.I)
    if m and m.group(1) in MONTH_FULL:
        v = re.search(r"PMI\) of China.s manufacturing industry[^%]{0,60}?([\d.]+)\s?(?:%|percent)", txt)
        if not v:
            raise RuntimeError(f"PMI value not found: {url}")
        return {"kind": "pmi", "date": f"{m.group(2)}-{MONTH_FULL[m.group(1)]:02d}",
                "value": float(v.group(1)), "url": url}
    if re.search(r"Preliminary Accounting Results of GDP", title, re.I):
        qm = re.search(r"(First|Second|Third|Fourth) Quarter(?: of)? (\d{4})", title, re.I)
        hm = re.search(r"First Half(?: of)? (\d{4})", title, re.I)
        ym = re.search(r"(\d{4})", title)
        if qm:
            q, year = {"first": 1, "second": 2, "third": 3, "fourth": 4}[qm.group(1).lower()], int(qm.group(2))
        elif hm:  # mid-year release: table columns are Q2 and H1; first growth number is Q2
            q, year = 2, int(hm.group(1))
        elif "three quarters" in title.lower():
            q, year = 3, int(ym.group(1))
        else:  # annual release: first growth number is Q4
            q, year = 4, int(ym.group(1))
        g = re.search(r"\bGDP\s+([\d,]+)\s+([\d,]+)\s+(-?[\d.]+)\s+(-?[\d.]+)", txt)
        if g:
            yoy = float(g.group(3))
        else:
            g2 = re.search(r"\bGDP\s+([\d,]+)\s+(-?[\d.]+)\s", txt)
            if not g2:
                raise RuntimeError(f"GDP row not found: {url}")
            yoy = float(g2.group(2))
        return {"kind": "gdp", "date": f"{year}-Q{q}", "value": yoy, "url": url}
    return None


def fetch_nbs(max_pages=90, stop_year=2021):
    cache_path = DATA / "nbs_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    warm = bool(cache)
    new_hits, pages_done = 0, 0
    for p in range(max_pages):
        idx = NBS_BASE + ("index.html" if p == 0 else f"index_{p}.html")
        try:
            h = get(idx)
        except RuntimeError:
            break
        pages_done += 1
        items = re.findall(r'<a[^>]*href="(\./(\d{6})/[^"]+)"[^>]*>(.*?)</a>', h, re.S)
        if not items:
            break
        page_new = 0
        for href, ym, inner in items:
            title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", inner))).strip()
            title = re.sub(r"^\d+\.\s*", "", title)
            if not re.search(r"Purchasing Managers|Preliminary Accounting Results of GDP", title, re.I):
                continue
            url = NBS_BASE + href[2:]
            if url in cache:
                continue
            try:
                rec = parse_nbs_page(url, title)
            except RuntimeError as e:
                log(f"WARN NBS page skipped: {e}")
                continue
            if rec:
                cache[url] = rec
                page_new += 1
                new_hits += 1
        # warm cache: stop once a page (after the first two) brings nothing new
        if warm and p >= 2 and page_new == 0:
            break
        if int(items[-1][1][:4]) < stop_year:
            break
    cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    pmi = {r["date"]: r["value"] for r in cache.values() if r["kind"] == "pmi"}
    gdp = {r["date"]: r["value"] for r in cache.values() if r["kind"] == "gdp"}
    if not pmi or not gdp:
        raise RuntimeError("NBS: no PMI/GDP parsed")
    log(f"NBS crawl: {pages_done} index pages, {new_hits} new release pages, "
        f"{len(pmi)} PMI obs, {len(gdp)} GDP obs")
    return {"pmi": pts_sorted([[k, v] for k, v in pmi.items()]),
            "gdp": pts_sorted([[k, v] for k, v in gdp.items()])}, NBS_BASE


# --------------------------------------------------------------------------- latest daily 10Y (spot cards + verification)
def fetch_daily_10y():
    spot = {}
    yr = NOW.year
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
           f"daily-treasury-rates.csv/{yr}/all?type=daily_treasury_yield_curve"
           f"&field_tdr_date_value={yr}&page&_format=csv")
    rows = list(csv.DictReader(io.StringIO(get(url))))
    r = rows[0]
    d = dt.datetime.strptime(r["Date"], "%m/%d/%Y").date().isoformat()
    spot["us10y_daily"] = {"date": d, "value": float(r["10 Yr"]), "source": url}
    try:
        cb = "https://yield.chinabond.com.cn/cbweb-czb-web/czb/czbChartSearch?locale=en_US"
        j = json.loads(get(cb))
        gov = next(c for c in j if "国债" in c["ycDefName"])
        y10 = next(p[1] for p in gov["seriesData"] if abs(p[0] - 10.0) < 1e-9)
        spot["cn10y_daily"] = {"date": gov["worktime"], "value": float(y10), "source": cb}
    except Exception as e:  # noqa - optional
        log(f"WARN ChinaBond daily 10Y unavailable: {e}")
    return spot


# --------------------------------------------------------------------------- derived
def month_key(d):
    return d[:7]


def derive(S):
    """UIP check: implied vs realised 12-month change in USD/CNY (CNY per USD)."""
    # monthly mean of daily USD/CNY
    acc = {}
    for d, v in S["usdcny"]["points"]:
        acc.setdefault(month_key(d), []).append(v)
    mm = {k: sum(v) / len(v) for k, v in acc.items()}
    ycn = dict(S["y10_cn"]["points"])
    yus = dict(S["y10_us"]["points"])
    months = sorted(mm)
    implied, realised = [], []
    for m in months:
        if m in ycn and m in yus:
            implied.append([m, round(((1 + ycn[m] / 100) / (1 + yus[m] / 100) - 1) * 100, 3)])
        y, mo = int(m[:4]), int(m[5:])
        fut = f"{y + 1}-{mo:02d}"
        if fut in mm:
            realised.append([m, round((mm[fut] / mm[m] - 1) * 100, 3)])
    spread = [[m, round(ycn[m] - yus[m], 3)] for m in sorted(ycn) if m in yus]
    cpi_gap = []
    cc, cu = dict(S["cpi_cn"]["points"]), dict(S["cpi_us"]["points"])
    for m in sorted(cc):
        if m in cu:
            cpi_gap.append([m, round(cc[m] - cu[m], 3)])
    return {"uip_implied": implied, "realised_12m": realised, "spread_10y": spread,
            "cpi_gap": cpi_gap, "usdcny_monthly": [[m, round(mm[m], 4)] for m in months]}


# --------------------------------------------------------------------------- metadata
META = {
    "usdcny": dict(title="USD/CNY spot exchange rate", units="CNY per 1 USD (up = RMB weaker)",
                   frequency="Daily (business days)", source="Federal Reserve Board, H.10 release (China)",
                   transform="None. Quoted as yuan per US dollar (direct quote from a US perspective)."),
    "reer": dict(title="RMB real effective exchange rate (broad)", units="Index, 2020 = 100 (up = RMB stronger)",
                 frequency="Monthly", source="Bank for International Settlements, Effective exchange rate indices (64 economies)",
                 transform="None. CPI-based real index; trade-weighted vs 63 partners."),
    "neer": dict(title="RMB nominal effective exchange rate (broad)", units="Index, 2020 = 100 (up = RMB stronger)",
                 frequency="Monthly", source="Bank for International Settlements, Effective exchange rate indices (64 economies)",
                 transform="None."),
    "policy_cn": dict(title="China policy rate", units="Percent per annum",
                      frequency="Monthly, end of period", source="BIS central bank policy rates (People's Bank of China)",
                      transform="BIS series = 1-year Loan Prime Rate since Aug 2019 (official 1-year lending rate before)."),
    "policy_us": dict(title="US policy rate", units="Percent per annum",
                      frequency="Monthly, end of period", source="BIS central bank policy rates (Federal Reserve)",
                      transform="Federal funds target (upper bound)."),
    "y10_cn": dict(title="China 10-year government bond yield", units="Percent per annum",
                   frequency="Monthly average", source="OECD, Financial market (long-term interest rates)",
                   transform="None."),
    "y10_us": dict(title="US 10-year government bond yield", units="Percent per annum",
                   frequency="Monthly average", source="OECD, Financial market (long-term interest rates)",
                   transform="None."),
    "cpi_cn": dict(title="China CPI inflation", units="% change, year on year",
                   frequency="Monthly", source="OECD Consumer prices (national source: NBS China)",
                   transform="Year-on-year growth rate as published."),
    "cpi_us": dict(title="US CPI inflation", units="% change, year on year",
                   frequency="Monthly", source="OECD Consumer prices (national source: US BLS)",
                   transform="Year-on-year growth rate as published."),
    "gdp": dict(title="China real GDP growth", units="% change, year on year",
                frequency="Quarterly", source="National Bureau of Statistics of China, Preliminary accounting results of GDP",
                transform="Year-on-year growth for the quarter, as published by NBS."),
    "pmi": dict(title="China official manufacturing PMI", units="Diffusion index (50 = no change)",
                frequency="Monthly", source="National Bureau of Statistics of China / CFLP",
                transform="None."),
    "prod_cn": dict(title="China labour productivity growth", units="% change, year on year",
                    frequency="Annual", source="World Bank WDI (SL.GDP.PCAP.EM.KD, ILO modelled estimates)",
                    transform="Growth of GDP per person employed (constant 2021 PPP$), computed from levels."),
    "prod_us": dict(title="US labour productivity growth", units="% change, year on year",
                    frequency="Annual", source="World Bank WDI (SL.GDP.PCAP.EM.KD, ILO modelled estimates)",
                    transform="Growth of GDP per person employed (constant 2021 PPP$), computed from levels."),
}

GROUPS = {  # source group -> (fetch fn, series ids)
    "Federal Reserve H.10": (fetch_fed, ["usdcny"]),
    "BIS": (fetch_bis, ["reer", "neer", "policy_cn", "policy_us"]),
    "OECD": (fetch_oecd, ["y10_cn", "y10_us", "cpi_cn", "cpi_us"]),
    "World Bank": (fetch_worldbank, ["prod_cn", "prod_us", "prod_cn_level", "prod_us_level"]),
    "NBS China": (fetch_nbs, ["gdp", "pmi"]),
}


def main():
    prev_path = DATA / "series.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {"series": {}, "meta": {}}
    S = dict(prev.get("series", {}))
    status = {}
    for name, (fn, ids) in GROUPS.items():
        try:
            out, src_url = fn()
            fetched = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
            for sid, pts in out.items():
                m = dict(META.get(sid, {"title": sid, "units": "", "frequency": "Annual",
                                        "source": "World Bank WDI", "transform": "Level"}))
                m.update(points=pts, latest_obs=pts[-1][0], fetched_at=fetched, source_url=src_url)
                S[sid] = m
            status[name] = {"ok": True, "at": fetched}
            log(f"OK   {name}: " + ", ".join(f"{k}={len(v)}pts latest={v[-1][0]}" for k, v in out.items()))
        except Exception as e:  # noqa
            status[name] = {"ok": False, "error": str(e)[:300],
                            "at": prev.get("meta", {}).get("sources", {}).get(name, {}).get("at")}
            log(f"FAIL {name}: {e}")
    spot = {}
    try:
        spot = fetch_daily_10y()
        log("OK   daily 10Y: " + ", ".join(f"{k}={v['value']} ({v['date']})" for k, v in spot.items()))
    except Exception as e:  # noqa
        log(f"WARN daily 10Y spot failed: {e}")
        spot = prev.get("meta", {}).get("spot", {})

    needed = ["usdcny", "y10_cn", "y10_us", "cpi_cn", "cpi_us"]
    if all(k in S for k in needed):
        for sid, pts in derive(S).items():
            S[sid] = {"title": sid, "points": pts, "latest_obs": pts[-1][0] if pts else None,
                      "derived": True}
        S["uip_implied"].update(
            title="UIP-implied change in USD/CNY (from 10Y yield gap)",
            units="Percent, annual", frequency="Monthly",
            source="Derived from OECD 10Y yields",
            transform="(1+y_CN)/(1+y_US) - 1. Negative = CNY expected to strengthen.")
        S["realised_12m"].update(
            title="Realised change in USD/CNY over the following 12 months",
            units="Percent", frequency="Monthly",
            source="Derived from Fed H.10 (monthly mean of daily rates)",
            transform="Mean USD/CNY in month t+12 vs month t. Positive = RMB weakened.")

    all_ok = all(s["ok"] for s in status.values())
    meta = prev.get("meta", {})
    meta["last_attempt_utc"] = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    if all_ok:
        meta["last_successful_refresh_utc"] = meta["last_attempt_utc"]
    meta["sources"] = status
    meta["spot"] = spot
    meta["all_sources_ok"] = all_ok
    prev_path.write_text(json.dumps({"meta": meta, "series": S}, separators=(",", ":")))
    with open(LOGS / "refresh_log.txt", "a") as f:
        f.write("\n".join(log_lines) + f"\n{NOW.strftime('%Y-%m-%dT%H:%M:%SZ')} RESULT all_sources_ok={all_ok}\n---\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
