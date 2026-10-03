"""
NFL rankings (docs/nfl/power/): all 32 teams, the twin of /cfb/power/.

GordStats - this site's own rating, the number /nfl/ predicts every game
with (nfl.predict) - leads and sets the order. Beside it ESPN's Football
Power Index (nfl.fpi) with its rank and its split into what the offense,
defense and special teams each add, the schedule ranks, and under Odds
ESPN's season simulations: projected record, playoffs, division, reaching
the Super Bowl and winning it. Each team links to its page (nfl.site.teams)
and carries a star (gordstats.favorites, keys `nfl:<ESPN id>`), which the
watch guide reads to put a reader's teams first.

Move columns come from the snapshot archive (gordstats.rankmoves,
data/nfl/power_history/<season>/, a 3 KB CSV at most twice a day) with the
NFL's weeks as its calendar: "Before Wk N" opens the bar, and every finished
week is its own window. A season whose archive starts mid-way is seeded once
with the GordStats table as it stood before each week kicked off - the same
fit on the games before then - so Move works from the first build; FPI has
no such history and its Move fills in as builds accumulate.

The table, its tabs, sorting and Move script are the college page's own
(cfb.site.power), imported rather than copied, so the two rankings pages
cannot drift apart; the table keeps its `cfb-power` class for that reason.

    python -m nfl.site.power
    python -m nfl.site.power --refresh      # refetch FPI first
"""
import argparse
import json
from datetime import datetime, timedelta
from html import escape

import pandas as pd

from cfb.site.power import (_CSS, _JS, ALL, _chg, _pct, _plain, _switcher, _td, _th,
                             _window_picker)
from gordstats import favorites, how, logos, rankmoves, share_card
from gordstats.frontmatter import add_front_matter
from nfl import fpi, predict
from nfl.config import DATA_DIR, SEASON, TZ, WEB_DIR
from nfl.site import teams as teams_page

HISTORY_DIR = DATA_DIR / "power_history" / str(SEASON)
OUT = WEB_DIR / "power" / "index.html"

# The figures each snapshot archives beyond the rank (ESPN's FPI rank, as on
# the college page), and how a change in each reads: "num" is now minus then
# to `dec` places, "rank" places climbed. Every sortable column names one, and
# Move shows whichever the table is sorted by.
TRACKED = {
    "rank": ("rank", 0), "fpi": ("num", 1), "numwins": ("num", 0),
    "gs": ("num", 1), "gs_rank": ("rank", 0),
    "off": ("num", 1), "def": ("num", 1), "st": ("num", 1),
    "projectedw": ("num", 1), "probmakeplayoffs": ("num", 1), "probwindiv": ("num", 1),
    "probmaketitlegame": ("num", 1), "probwintitle": ("num", 1),
    "avgsosrank": ("rank", 0), "sosremainingrank": ("rank", 0),
    "accomplishmentrank": ("rank", 0),
}

# FPI's components, renamed for the table.
_SPLIT = {"off": "epaoffense", "def": "epadefense", "st": "epaspecialteams"}


# --------------------------------------------------------------------------- #
# The calendar
# --------------------------------------------------------------------------- #

def week_number(week: int, seasontype: int) -> int:
    """One number per week for the archive: the playoff rounds follow the
    regular season (Wild Card 19 ... the Super Bowl 22 from 2026, 23 before
    it), as /nfl/ keys them."""
    return int(week) + (18 if int(seasontype) == 3 else 0)


def week_label(number: int) -> str:
    """A week's button: "Wk 5", or the playoff round."""
    number = int(number)
    if number > 18:
        return teams_page.ROUNDS.get(number - 18, f"Wk {number}")
    return f"Wk {number}"


def week_spans(frame: pd.DataFrame) -> list:
    """(week, first kickoff, last game over) per week, in the machine's local
    clock - the one the snapshots are named in, Eastern on the Pi. A game is
    over four hours after kickoff. Unpaired playoff games (TBD) still date
    their round.

    The zone, not today's offset: datetime.now().astimezone() is a fixed
    offset (EDT, -4, in October), which put every January playoff window an
    hour off the snapshots' EST names."""
    if frame.empty:
        return []
    local = frame["date"].dt.tz_convert(TZ).dt.tz_localize(None)
    number = [week_number(w, s) for w, s in zip(frame["week"], frame["seasontype"])]
    spans = local.groupby(pd.Series(number, index=frame.index)).agg(["min", "max"])
    return [(int(w), r["min"].to_pydatetime(), (r["max"] + pd.Timedelta(hours=4)).to_pydatetime())
            for w, r in spans.iterrows()]


# --------------------------------------------------------------------------- #
# The archive
# --------------------------------------------------------------------------- #

def _snapshot(teams: list, now=None) -> None:
    frame = pd.DataFrame({**{f: [t.get(f) for t in teams] for f in TRACKED if f != "rank"},
                          "abbr": [t["abbr"] for t in teams]},
                         index=[t["id"] for t in teams])
    num = frame.columns.drop("abbr")
    frame[num] = frame[num].astype(float).round(3)
    rankmoves.snapshot(HISTORY_DIR, pd.Series([t.get("rank") for t in teams],
                                              index=[t["id"] for t in teams], dtype="Int64"),
                       now=now, extra=frame)


def seed_history(spans: list, now: datetime = None) -> int:
    """Seed an empty archive with the GordStats table as it stood at the
    end of each finished week (just before the next one kicked off) and
    before Week 1: the same fit, on the games played by then. Returns the
    number of snapshots written.

    Only for an archive with nothing in it - the season the page launches
    mid-way through - and only for moments old enough to be a baseline, so
    this build's own snapshot still goes in after them."""
    now = now or datetime.now()
    if any(HISTORY_DIR.glob("*.csv")):
        return 0
    latest = now - timedelta(hours=rankmoves.GAP_HOURS)
    stamps = []
    spans = sorted(spans)
    if spans and spans[0][1] - timedelta(hours=1) <= latest:
        stamps.append(spans[0][1] - timedelta(hours=1))
    for i, (_week, _kick, end) in enumerate(spans):
        stamp = end + timedelta(hours=1)
        if i + 1 < len(spans):
            stamp = min(stamp, spans[i + 1][1] - timedelta(minutes=1))
        if stamp <= latest:
            stamps.append(stamp)
    for stamp in stamps:
        # In the zone (week_spans), so a stamp past November's clock change
        # is read at its own offset; the repeated 1 AM hour reads as EDT.
        asof = (pd.Timestamp(stamp).tz_localize(TZ, ambiguous=True,
                                                 nonexistent="shift_forward")
                .tz_convert("UTC"))
        frame, model, names = predict.season(asof=asof)
        table = teams_page.standings(frame, model, names, asof=asof)
        _snapshot([{"id": str(r["team"]), "abbr": r["abbr"], "rank": None,
                    "gs": float(r["rating"]), "gs_rank": int(r["rank"]),
                    "numwins": float(r["wins"])} for _, r in table.iterrows()], now=stamp)
    return len(stamps)


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

def rows(frame: pd.DataFrame, model, names: dict, espn: dict) -> list:
    """One dict per team, in GordStats order: our rating, rank and record,
    and every FPI figure (None throughout when ESPN has nothing)."""
    table = teams_page.standings(frame, model, names)
    blank = {f: None for fields in fpi.FIELDS.values() for f in fields} | {"rank": None}
    out = []
    for _, r in table.iterrows():
        e = espn.get(str(r["team"])) or {}
        t = {**blank, **{k: v for k, v in e.items() if k in blank}}
        nick = str(r["name"])
        full = e.get("full") or nick
        t.update({
            "id": str(r["team"]), "abbr": r["abbr"], "nick": nick, "full": full,
            # "Kansas City " rides before "Chiefs" and is the first thing to
            # go as the window narrows (.pwr-masc), as the mascot does on the
            # college page.
            "city": full[:-len(nick)] if full.endswith(" " + nick) else "",
            "gs": float(r["rating"]), "gs_rank": int(r["rank"]),
            "w": int(r["wins"]), "l": int(r["losses"]), "t": int(r["ties"]),
            "numwins": float(r["wins"]),
        })
        for key, field in _SPLIT.items():
            t[key] = e.get(field)
        out.append(t)
    return out


def _deltas(bases: dict, teams: list) -> dict:
    """{window: {field: [change per team, in table order]}} - cfb.site.power's
    answer on this page's tracked figures, handed to the script as JSON."""
    out = {}
    for win, b in bases.items():
        frame, cols = b["frame"], {}
        for field, (kind, dec) in TRACKED.items():
            if field not in frame.columns:
                continue
            base, vals = frame[field], []
            for t in teams:
                now, then = t.get(field), base.get(t["id"])
                if now is None or then is None or pd.isna(then):
                    vals.append(None)
                    continue
                delta = (float(then) - now) if kind == "rank" else (now - float(then))
                vals.append(int(round(delta)) if dec == 0 else round(delta, dec))
            if any(v is not None for v in vals):
                cols[field] = vals
        out[win] = cols
    return out


def _change(v, field) -> tuple:
    kind, dec = TRACKED[field]
    if v is None:
        return None, ""
    return v, (rankmoves.cell(v) if kind == "rank" else rankmoves.signed(v, dec))


def _team(t, record: bool) -> str:
    rec = (f"<span class='pwr-rec'>{teams_page.record_text(t['w'], t['l'], t['t'])}</span>"
           if record else "")
    city = f"<span class='pwr-masc'>{escape(t['city'])}</span>" if t["city"] else ""
    return (logos.img("nfl", t["abbr"], 22)
            + f"<a href='{teams_page.url(t['nick'])}'>{city}{escape(t['nick'])}</a>"
            + rec + favorites.star("nfl", t["id"], t["full"]))


def _rated(value, rank, chg_field, chg) -> tuple:
    """A rating cell: rank beside rating, and the rating's own change."""
    if value is None:
        return None, ""
    rk = f"<span class='gs-rk'>{rank}</span>" if rank else ""
    return value, (f"{rk}{value:+.1f}<span class='pwr-chg' data-chg='{chg_field}'>{chg}</span>")


def _signed(v) -> tuple:
    """A points figure: +6.6, -0.5, and a plain 0.0 rather than "-0.0"."""
    if v is None:
        return None, ""
    return v, ("0.0" if round(v, 1) == 0 else f"{v:+.1f}")




def body() -> str:
    frame, model, names = predict.season()
    espn = fpi.by_id()
    teams = rows(frame, model, names, espn)
    order = {t["id"]: i for i, t in enumerate(teams)}
    _CARD["rows"] = [(str(t["gs_rank"]), t["nick"],
                      " · ".join(x for x in (
                          teams_page.record_text(t["w"], t["l"], t["t"]),
                          f"FPI {t['rank']}" if t.get("rank") else "") if x))
                     for t in teams[:5]]

    spans = week_spans(frame)
    try:
        seeded = seed_history(spans)
    except Exception as exc:                            # noqa: BLE001 - Move can wait a build
        print(f"  ! NFL rankings: history seed failed ({exc})")
        seeded = 0
    if seeded:
        print(f"  seeded the NFL rankings archive with {seeded} past tables")
    bases = rankmoves.baselines(HISTORY_DIR, weeks=spans, week_label=week_label)
    show_move = bool(bases)
    first_win = next(iter(bases)) if bases else None
    first_at = bases[first_win]["at"] if bases else None
    deltas = _deltas(bases, teams)

    def live(field) -> bool:
        return any(t.get(field) is not None for t in teams)

    opening = deltas.get(first_win, {}) if first_win else {}
    for i, t in enumerate(teams):
        for field in ("fpi", "gs"):
            vals = opening.get(field)
            t[f"{field}_chg"] = _chg(vals[i] if vals else None, TRACKED[field][1])

    show_rec = any(t["w"] or t["l"] or t["t"] for t in teams)
    show_rem_sos = live("sosremainingrank") and any(
        t["sosremainingrank"] != t["avgsosrank"] for t in teams)

    def col(views, label, tip, direction, cell, field=None):
        return views, label, tip, direction, cell, field

    def move(t):
        vals = deltas[first_win].get("gs_rank") if first_win else None
        return _change(vals[order[t["id"]]] if vals else None, "gs_rank")

    cols = [col(ALL, "Team", None, None, lambda t: (t["gs_rank"], _team(t, show_rec)))]
    if show_move:
        cols.append(col(ALL, "Move", f"Places climbed since {first_at:%b %-d}", None, move))
    cols.append(col(("rating",), "GordStats", "This site's own rating - points better than an "
                    "average team on a neutral field, the number the predictions run on - "
                    "with its rank", "desc",
                    lambda t: _rated(t["gs"], t["gs_rank"], "gs", t["gs_chg"]), "gs_rank"))
    if live("fpi"):
        cols += [
            col(("rating",), "FPI", "ESPN's Football Power Index: expected point margin "
                "against an average team on a neutral field, with its rank", "desc",
                lambda t: _rated(t["fpi"], t["rank"], "fpi", t["fpi_chg"]), "rank"),
            col(("rating",), "Off", "FPI's offense: the points it adds to that margin",
                "desc", lambda t: _signed(t["off"]), "off"),
            col(("rating",), "Def", "FPI's defense: the points it adds to that margin",
                "desc", lambda t: _signed(t["def"]), "def"),
            col(("rating",), "ST", "FPI's special teams: the points they add to that margin",
                "desc", lambda t: _signed(t["st"]), "st"),
        ]
    if live("avgsosrank"):
        cols.append(col(("rating",), "SOS", "ESPN's strength-of-schedule rank for the games "
                        "played, hardest first", "asc",
                        lambda t: _plain(t["avgsosrank"]), "avgsosrank"))
    if show_rem_sos:
        cols.append(col(("rating",), "Rem SOS", "Strength-of-schedule rank for the games "
                        "still to play", "asc",
                        lambda t: _plain(t["sosremainingrank"]), "sosremainingrank"))
    if live("accomplishmentrank"):
        cols.append(col(("rating",), "SOR", "Strength-of-record rank: how hard this record "
                        "would be for an average contender to match", "asc",
                        lambda t: _plain(t["accomplishmentrank"]), "accomplishmentrank"))
    if live("projectedw"):
        cols += [
            col(("odds",), "Proj W-L", "ESPN's simulation of the full schedule", "desc",
                lambda t: (t["projectedw"], f"{t['projectedw']:.1f}-{t['projectedl']:.1f}")
                if t["projectedw"] is not None and t["projectedl"] is not None else (None, ""),
                "projectedw"),
            col(("odds",), "Playoff%", "Chance of making the playoffs", "desc",
                lambda t: _pct(t["probmakeplayoffs"]), "probmakeplayoffs"),
            col(("odds",), "Div%", "Chance of winning the division", "desc",
                lambda t: _pct(t["probwindiv"]), "probwindiv"),
            col(("odds",), "Conf%", "Chance of winning the AFC or NFC - reaching the Super Bowl",
                "desc", lambda t: _pct(t["probmaketitlegame"]), "probmaketitlegame"),
            col(("odds",), "SB%", "Chance of winning the Super Bowl", "desc",
                lambda t: _pct(t["probwintitle"]), "probwintitle"),
        ]
    has_odds = any("odds" in c[0] and c[0] != ALL for c in cols)

    kinds = {"rank": {"k": "rank", "d": 0, "label": "FPI", "tip": "FPI places climbed"}}
    for _views, label, _tip, _dir, _cell, field in cols:
        if field and field != "rank" and field in TRACKED:
            kind, dec = TRACKED[field]
            tip = f"{label} places climbed" if kind == "rank" else f"{label} change"
            if field == "gs_rank":
                tip = "GordStats places climbed"
            kinds[field] = {"k": kind, "d": dec, "label": label, "tip": tip}

    body_rows = []
    for t in teams:
        cells = []
        for views, label, _tip, direction, cell, _field in cols:
            value, text = cell(t)
            cells.append(_td(views, value, text, team=(label == "Team"),
                             sortable=direction is not None,
                             extra=(" mv-cell" if label == "Move"
                                    else " sorted-col" if label == "GordStats" else "")))
        body_rows.append(f"<tr{favorites.row_attr('nfl', t['id'])}>" + "".join(cells) + "</tr>")
    head = "".join(
        _th(views, label, tip, direction, first=(label == "GordStats"), team=(label == "Team"),
            field=field, extra=(" mv-th" if label == "Move" else ""))
        for views, label, tip, direction, _cell, field in cols)

    # How the ratings are made is an explainer of its own (gordstats.how),
    # opened from the chip; each column is defined in its header's tooltip.
    move_note = ("<p class='power-note'><strong>Move</strong> is the sorted column's change "
                 "since the <strong>Since</strong> menu's pick.</p>" if show_move else "")
    intro = (how.section_note("nfl-rankings") + move_note
             + "<p class='power-note'><a href='/nfl/playoff/'>Playoff odds</a>: who makes the "
             "field, on our model beside ESPN's.</p>")

    _snapshot(teams)
    blob = json.dumps({"deltas": deltas, "kinds": kinds, "chg": {"fpi": 1, "gs": 1},
                       "when": {win: f"{b['at']:%b %-d}" for win, b in bases.items()}},
                      separators=(",", ":"))
    return (_CSS + favorites.table_css("table.cfb-power") + intro
            # One row on a phone: the CFB page's Since menu, not a row of buttons.
            + "<div class='pin-bar pwr-pin'>" + (_switcher() if has_odds else "")
            + _window_picker(bases) + favorites.controls() + "</div>"
            + "<div class='power-wrap'>"
            + f"<table class='cfb-power view-rating'><thead><tr>{head}</tr></thead>"
            + f"<tbody>{''.join(body_rows)}</tbody></table></div>"
            + "<script type='application/json' id='pwr-deltas'>" + blob + "</script>"
            + _JS + how.JS_TAG)


_CARD: dict = {}


def card() -> dict | None:
    """The link-preview card: our top five, with each team's record and FPI rank."""
    rows_ = _CARD.get("rows")
    if not rows_:
        return None
    return share_card.ranked("nfl-rankings", f"NFL · {SEASON}", "GordStats NFL Rankings",
                             "The model's ranking, beside ESPN's FPI", rows_,
                             alt="GordStats NFL rankings: "
                             + ", ".join(f"{r[0]}. {r[1]}" for r in rows_))


def generate():
    html = body()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        html, "NFL Rankings", f"{SEASON} season", image=card(),
        description=f"All 32 NFL teams ranked by the GordStats model for {SEASON}, beside "
                    "ESPN's FPI, with playoff and Super Bowl odds."), encoding="utf-8")
    print(f"Wrote NFL Rankings -> {OUT}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build the NFL rankings page.")
    p.add_argument("--refresh", action="store_true")
    if p.parse_args().refresh:
        fpi.fetch(refresh=True)
    generate()
