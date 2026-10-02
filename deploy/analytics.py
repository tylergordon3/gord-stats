#!/usr/bin/env python3
"""
Who reads gordstats.com: a plain-text report from Cloudflare.

    pi analytics            # the last 14 days, from the PC
    pi analytics 30
    python3 deploy/analytics.py 14      # on the Pi, with the secrets loaded

Runs on the Pi, which holds CLOUDFLARE_ANALYTICS_TOKEN (read-only: Account
Analytics, Zone Analytics, Workers KV) and CLOUDFLARE_ACCOUNT_ID in
~/secrets/gord-stats.env. Standard library only, so it needs no venv.

What it reports, and the traps it steps around (2026-10-02, the first look):
  * Readers a day from the footer counter (KV `day:<ET date>`): each address
    once per Eastern day, bot user agents left out - the most honest count.
    Cloudflare's own "visits" count our headless test runs as readers.
  * Page views from Web Analytics, with **bursts left out**: an hour with far
    more views than any reader produces is one of our own audits loading every
    page (550 on 2026-09-28 at 7 PM, 1,010 on 2026-10-02 at 1 PM). The page,
    device and speed breakdowns are asked for the quiet hours only.
  * Speed: Cloudflare gives the quantiles in **microseconds**; shown here in
    seconds and milliseconds. iOS Safari reports no LCP/CLS/INP, so the
    phone figures are mostly Android.
  * Counts are sampled at this volume (they come in tens).
"""
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
API = "https://api.cloudflare.com/client/v4"
VISITS_NS = "334f93448a734bb8bc6dd47c49cd81cd"      # wrangler.toml's VISITS binding
BURST_FLOOR = 200            # views in one hour that no reader has come near


def section(path: str) -> str:
    """A page's place on the site: every team page or preview is one row."""
    path = re.sub(r"\.html$", "", path or "/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "Home"
    if parts[0] in ("cfb", "nfl", "fantasy", "cbb") and len(parts) > 1:
        if parts[1] in ("teams", "game", "recap"):
            return f"/{parts[0]}/{parts[1]}/*"
        return f"/{parts[0]}/{parts[1]}/"
    return f"/{parts[0]}/"


def bursts(hourly: dict) -> set:
    """Hours (UTC 'YYYY-MM-DDTHH') with far more views than readers make."""
    counts = [v for v in hourly.values() if v > 0]
    if not counts:
        return set()
    cut = max(BURST_FLOOR, 10 * statistics.median(counts))
    return {h for h, v in hourly.items() if v >= cut}


def quiet_windows(start: datetime, end: datetime, loud: set) -> list:
    """[start, end) split around the loud hours."""
    out, cur, t = [], start, start.replace(minute=0, second=0, microsecond=0)
    while t < end:
        if t.strftime("%Y-%m-%dT%H") in loud:
            if cur < t:
                out.append((cur, t))
            cur = t + timedelta(hours=1)
        t += timedelta(hours=1)
    if cur < end:
        out.append((cur, end))
    return out


def secs(us) -> str:
    return "-" if us is None or us < 0 else f"{us / 1e6:.2f}s"


def ms(us) -> str:
    return "-" if us is None or us < 0 else f"{us / 1e3:.0f}ms"


class Cloudflare:
    def __init__(self, token: str, account: str):
        self.h = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        self.account = account

    def _open(self, url, body=None):
        req = urllib.request.Request(url, data=body, headers=self.h)
        return urllib.request.urlopen(req, timeout=60).read()

    def gql(self, query: str, **variables):
        body = json.dumps({"query": query, "variables": {"a": self.account, **variables}}).encode()
        out = json.loads(self._open(API + "/graphql", body))
        if out.get("errors"):
            raise RuntimeError(out["errors"][0].get("message"))
        return out["data"]

    def rum(self, dataset: str, fields: str, start: datetime, end: datetime, limit=500):
        q = ("query($a:String!,$s:Time!,$e:Time!){viewer{accounts(filter:{accountTag:$a}){"
             f"{dataset}(limit:{limit},filter:{{datetime_geq:$s,datetime_lt:$e}}){{{fields}}}}}}}}}")
        return self.gql(q, s=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        e=end.strftime("%Y-%m-%dT%H:%M:%SZ"))["viewer"]["accounts"][0][dataset]

    def kv(self, key: str):
        try:
            return self._open(f"{API}/accounts/{self.account}/storage/kv/namespaces/"
                              f"{VISITS_NS}/values/{key}").decode()
        except urllib.error.HTTPError:
            return None


def report(cf: Cloudflare, days: int) -> str:
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    lines = [f"gordstats.com, last {days} days (to {end.astimezone(ET):%a %b %-d %-I:%M %p} ET)", ""]

    # Readers, from the footer counter.
    today = end.astimezone(ET).date()
    daily = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        v = cf.kv(f"day:{d}")
        daily.append((d, int(v) if v and v.isdigit() else 0))
    total = cf.kv("total")
    lines.append("Readers a day (footer counter: each address once a day, bots left out)")
    lines.append("  " + "  ".join(f"{d:%m-%d} {n}" for d, n in daily[-14:]))
    counted = [n for _, n in daily if n]
    if counted:
        lines.append(f"  median {statistics.median(counted):.0f} a day; {total or '?'} since the counter began")
    lines.append("")

    # Views by hour, to find our own test runs.
    hourly = defaultdict(int)
    for r in cf.rum("rumPageloadEventsAdaptiveGroups", "count dimensions{datetimeHour}", start, end, 2000):
        hourly[r["dimensions"]["datetimeHour"][:13]] += r["count"]
    loud = bursts(hourly)
    views = sum(hourly.values())
    quiet = views - sum(hourly[h] for h in loud)
    lines.append(f"Page views (Cloudflare Web Analytics, sampled): {views}")
    for h in sorted(loud):
        t = datetime.fromisoformat(h + ":00+00:00").astimezone(ET)
        lines.append(f"  left out: {hourly[h]} views {t:%a %b %-d, %-I %p} ET - a burst, our own test runs")
    lines.append(f"  without them: {quiet}")
    lines.append("")

    windows = quiet_windows(start, end, loud)

    def gather(dataset, fields, limit=500):
        rows = []
        for s, e in windows:
            rows += cf.rum(dataset, fields, s, e, limit)
        return rows

    # Pages and devices, quiet hours only.
    pages, phone = defaultdict(lambda: [0, 0]), defaultdict(int)
    for r in gather("rumPageloadEventsAdaptiveGroups",
                    "count sum{visits} dimensions{requestPath deviceType}"):
        s = section(r["dimensions"]["requestPath"])
        pages[s][0] += r["count"]
        pages[s][1] += r["sum"]["visits"]
        if r["dimensions"]["deviceType"] == "mobile":
            phone[s] += r["count"]
    dev = defaultdict(lambda: [0, 0])
    for r in gather("rumPageloadEventsAdaptiveGroups",
                    "count sum{visits} dimensions{deviceType userAgentOS}"):
        k = f'{r["dimensions"]["deviceType"]} {r["dimensions"]["userAgentOS"]}'
        dev[k][0] += r["count"]
        dev[k][1] += r["sum"]["visits"]
    lines.append("Devices (views / visits; many views in few visits is one person - the owner's desktop)")
    for k, (c, v) in sorted(dev.items(), key=lambda x: -x[1][0])[:8]:
        lines.append(f"  {k:28} {c:6} / {v}")
    lines.append("")
    lines.append("Most read (views, share on phones)")
    shown = sum(c for c, _ in pages.values()) or 1
    for s, (c, _v) in sorted(pages.items(), key=lambda x: -x[1][0])[:25]:
        lines.append(f"  {s:26} {c:5}  {c / shown:4.0%}   phones {phone[s] / c:4.0%}")
    lines.append("")

    refs = defaultdict(int)
    for r in gather("rumPageloadEventsAdaptiveGroups", "count dimensions{refererHost}"):
        host = r["dimensions"]["refererHost"] or "(direct, or a link in a text)"
        if "gordstats.com" not in host:
            refs[host] += r["count"]
    lines.append("Arrived from (outside the site)")
    for h, c in sorted(refs.items(), key=lambda x: -x[1])[:10]:
        lines.append(f"  {h:34} {c}")
    lines.append("")

    # Speed, by page, where there is enough of it to mean something.
    vit = defaultdict(lambda: {"n": 0, "lcp": [], "cls": [], "inp": []})
    for r in gather("rumWebVitalsEventsAdaptiveGroups",
                    "count dimensions{requestPath deviceType} quantiles{largestContentfulPaintP75 "
                    "cumulativeLayoutShiftP75 interactionToNextPaintP75}", 200):
        k = (section(r["dimensions"]["requestPath"]), r["dimensions"]["deviceType"])
        q = r["quantiles"]
        vit[k]["n"] += r["count"]
        vit[k]["lcp"].append((r["count"], q["largestContentfulPaintP75"]))
        vit[k]["cls"].append((r["count"], q["cumulativeLayoutShiftP75"]))
        vit[k]["inp"].append((r["count"], q["interactionToNextPaintP75"]))

    def wmean(pairs):
        """The p75s of the quiet windows and OS splits, weighted by samples -
        an approximation (quantiles don't average), but the worst window alone
        let one thin evening speak for the fortnight."""
        vals = [(n, v) for n, v in pairs if v is not None and v >= 0]
        return sum(n * v for n, v in vals) / sum(n for n, _ in vals) if vals else None

    lines.append("Speed, p75 (LCP = main content shown; CLS = layout jumping, under 0.1 is good;")
    lines.append("INP = response to a tap). Pages with 10+ samples; iPhones report none of these.")
    for (s, d), v in sorted(vit.items(), key=lambda x: -x[1]["n"]):
        if v["n"] < 10:
            continue
        cls = wmean(v["cls"])
        flag = "  <- jumps" if cls is not None and cls >= 0.1 else ""
        lines.append(f"  {s:26} {d:8} n={v['n']:4}  LCP {secs(wmean(v['lcp'])):>6}  "
                     f"CLS {'-' if cls is None else f'{cls:.2f}':>5}  INP {ms(wmean(v['inp'])):>6}{flag}")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    days = int(argv[0]) if argv else 14
    token = os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN")
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account:
        print("analytics: CLOUDFLARE_ANALYTICS_TOKEN and CLOUDFLARE_ACCOUNT_ID must be set "
              "(they live in the Pi's ~/secrets/gord-stats.env)", file=sys.stderr)
        return 2
    print(report(Cloudflare(token, account), days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
