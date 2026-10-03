"""
Team dashboard (docs/cfb/roster/): one fantasy roster's week on one screen.

The matchups page sets two rosters against each other; this one is for the
manager alone with his lineup on a Thursday. Per team, for the week being
played:

  * Start / sit  the best lineup by this site's weekly projection (cfb.weekly)
                 and the slot each starter belongs in: early kickoffs in the
                 position slots, the latest in the flex, so a late scratch
                 leaves a hole any back or receiver on the bench can fill
                 (cfb.lineup). Each starter names the bench player who could
                 still cover for him.
  * The game     opponent and kickoff, what that defence gives up to the
                 player's position (cfb.defense - the matchup-strength page's
                 number, with its rank), and the forecast.
  * Usage        his share of the carries and targets lately (cfb.usage).
  * Waiver adds  free agents projected to outscore somebody this roster would
                 otherwise start, with the same matchup and weather columns.

All ten teams are on the page; the menu picks one and the browser remembers
which is yours - the usage page's "My team" filter reads the same choice.

    python -m cfb.site.roster
"""
import json
from datetime import datetime
from html import escape

import pandas as pd

from cfb import (cfbd, defense, gameinfo, in_season, lineup, ownership, predict,
                 schools as schools_mod, usage as usage_mod, waivers, weekly, yahoo)
from cfb.config import LEAGUE_TZ, MY_TEAM, SEASON, WEB_DIR
from cfb.site import write_page
from cfb.site.matchups import (_school_logo, game_cell, game_for, order_roster,
                                slot_order)
from cfb.site.schedule import _merge_weather, _wx_icon
from cfb.site.strength import _heat
from cfb.site.usage import RECENT_WEEKS
from gordstats import lineup as shared_lineup, matchup_page as ui, roster_page as page
from gordstats.jsonio import script_json

OUTPUT = WEB_DIR / "roster" / "index.html"
ADDS_SHOWN = 8
MIN_GAIN = 0.5                  # an add worth less than this is a coin flip, not advice
BAD_WEATHER = 2.0               # gameinfo.weather_severity's own "bad weather" cut

# --------------------------------------------------------------------------- #
# The week's shared data
# --------------------------------------------------------------------------- #

class Week:
    """Everything every team's view reads, worked out once."""

    def __init__(self):
        self.lg = yahoo.league()
        weeks = yahoo.archived_weeks()
        datas = {w: yahoo.week_matchups(w) for w in weeks}
        live = [w for w in weeks if not yahoo.week_final(datas[w])]
        self.week = max(live) if live else weeks[-1]
        self.data = datas[self.week]
        self.final = yahoo.week_final(self.data)
        self.frame, _model, _names = predict.season()
        self.board = in_season.board(frame=self.frame)
        statuses = {p["yahoo_id"]: p["status"] for roster in self.data["rosters"].values()
                    for p in roster if p.get("status")}
        self.wk = weekly.week_projections(self.data["week_start"], self.data["week_end"],
                                          board=self.board, league=self.lg, frame=self.frame,
                                          injuries=statuses)
        self.by_team = weekly.team_games(weekly.games_between(
            self.frame, self.data["week_start"], self.data["week_end"]))
        self.to_school = schools_mod.yahoo_school()
        self.espn = schools_mod.espn_ids()
        self.yproj = self.data.get("yahoo_proj") or {}
        self.season_proj = (self.board.drop_duplicates("yahoo_id").set_index("yahoo_id")["proj"]
                            .to_dict())

        # What each defence gives up by position, and where that ranks: 1 is the
        # stingiest, the last place gives up the most.
        grid = defense.table()
        self.ratings = {str(k): row for k, row in grid.iterrows()} if not grid.empty else {}
        self.ranks = ({pos: grid[pos].rank(ascending=True, method="min")
                       for pos in defense.POSITIONS} if not grid.empty else {})
        self.n_def = len(grid)

        info, cfbd_wx = gameinfo.load(), cfbd.weather()
        self.weather = {}
        for gid in {g["game_id"] for games in self.by_team.values() for g in games}:
            wx = _merge_weather((info.get(gid) or {}).get("weather"), cfbd_wx.get(str(gid)))
            if wx:
                self.weather[gid] = wx

        # Recent usage by yahoo id, for rostered players and listed free agents.
        self.usage = {}
        box = usage_mod.load()
        if not box.empty:
            shares = ownership.attach(usage_mod.shares(box, weeks=RECENT_WEEKS), self.week)
            for _, r in shares[shares["yahoo_id"] != ""].iterrows():
                self.usage[str(r["yahoo_id"])] = r

    def game(self, p: dict):
        return game_for(p, self.wk, self.by_team, self.to_school, self.espn)

    def proj(self, pid: str):
        if pid in self.wk.index and pd.notna(self.wk.loc[pid, "proj_week"]):
            return float(self.wk.loc[pid, "proj_week"])
        return None


# --------------------------------------------------------------------------- #
# Cells
# --------------------------------------------------------------------------- #

def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _when(ts) -> str:
    if ts is None or pd.isna(ts):
        return "bye"
    local = pd.Timestamp(ts).tz_convert(LEAGUE_TZ)
    return f"{local:%a %-I:%M}{local:%p}".replace("AM", "a").replace("PM", "p")


def opp_cell(wkd: Week, g, pos: str) -> str:
    """What this week's opponent allows to the position: the matchup-strength
    rating (1.00 = par, higher is softer) over its rank among FBS defences."""
    if g is None or not isinstance(g.get("opp"), str):
        return "<td>&mdash;</td>"
    if pos == "DEF":
        # A defence's matchup is the offence across from it.
        pts = g.get("pred_against")
        if pts is None or pd.isna(pts):
            return "<td>&mdash;</td>"
        return (f"<td title='Points this site's model expects the opposing offense to score'>"
                f"{float(pts):.0f}<span class='rd-rk'>opp proj pts</span></td>")
    opp_id = g.get("opp_id")
    row = wkd.ratings.get(str(opp_id))
    value = None if row is None else row.get(pos)
    if value is None or pd.isna(value):
        return "<td title='No rating: an FCS defense, or no games yet'>&mdash;</td>"
    rank = int(wkd.ranks[pos].get(str(opp_id)))
    return (f"<td style='{_heat(value)}' title='Fantasy points allowed to {pos}s against "
            f"expectation; 1.00 is par. Rank 1 is the toughest defense; the higher the number the more it gives up.'>{value:.2f}"
            f"<span class='rd-rk'>{_ordinal(rank)} of {wkd.n_def}</span></td>")


def weather_cell(wkd: Week, g) -> str:
    if g is None or not isinstance(g.get("opp"), str):
        return "<td>&mdash;</td>"
    wx = wkd.weather.get(str(g.get("game_id")))
    if not wx:
        return "<td class='rd-wx' title='No forecast yet - they appear about ten days out'>&mdash;</td>"
    if wx.get("indoors"):
        return "<td class='rd-wx'>&#127967;&#65039; Indoors</td>"
    main = []
    if wx.get("temp") is not None:
        main.append(f"{wx['temp']:.0f}&deg;")
    text = gameinfo.weather_text(wx) or wx.get("text") or ""
    if text:
        main.append(escape(text))
    sub = []
    if wx.get("precip") is not None and wx["precip"] > 0:
        sub.append(f"rain {wx['precip']:.0f}%")
    if wx.get("wind") is not None and wx["wind"] >= 10:
        sub.append(f"wind {wx['wind']:.0f} mph")
    # The gust is what flags a game as windy, so it shows whenever it is the reason.
    if wx.get("gust") is not None and wx["gust"] >= (25 if wx.get("wind") is not None
                                                     and wx["wind"] >= 10 else 10):
        sub.append(f"gusts {wx['gust']:.0f} mph")
    bad = gameinfo.weather_severity(wx) >= BAD_WEATHER
    return (f"<td class='rd-wx{' bad' if bad else ''}'>{_wx_icon(wx.get('cond'))} "
            + " ".join(main)
            + (f"<span class='sub'>{' &middot; '.join(sub)}</span>" if sub else "") + "</td>")


def usage_cells(wkd: Week, pid: str, pos: str) -> str:
    r = wkd.usage.get(pid)
    if r is None or pos == "DEF":
        return "<td>&mdash;</td><td>&mdash;</td>"

    def pct(v):
        # Nothing is a dash, not "0%": a receiver's carry share is not a finding.
        return "&mdash;" if v is None or pd.isna(v) or float(v) < 0.005 else f"{float(v):.0%}"
    return f"<td>{pct(r['car_share'])}</td><td>{pct(r['tgt_share'])}</td>"


def player_cell(wkd: Week, p: dict, extra: str = "") -> str:
    inj = (f"<span class='rd-inj' title='{escape(p.get('injury_note') or p.get('status_full') or '', quote=True)}'>"
           f"{escape(p['status'])}</span>" if p.get("status") else "")
    return (f"<td class='rd-p'>{_school_logo(p.get('team_full') or '', wkd.to_school, wkd.espn).replace('mu-logo', 'rd-logo')}"
            f"<span class='nm'>{escape(p['player'])}</span>"
            f"<span class='rd-lbl'>{escape(str(p['pos']))} &middot; {escape(str(p['team']))}</span>"
            f"{inj}{extra}</td>")


def _wx_short(wkd: Week, g) -> str:
    """The forecast in a few characters, for a phone card."""
    if g is None or not isinstance(g.get("opp"), str):
        return ""
    wx = wkd.weather.get(str(g.get("game_id")))
    if not wx:
        return ""
    if wx.get("indoors"):
        return "&#127967;&#65039; indoors"
    text = gameinfo.weather_text(wx) or wx.get("text") or ""
    temp = f"{wx['temp']:.0f}&deg; " if wx.get("temp") is not None else ""
    out = f"{_wx_icon(wx.get('cond'))} {temp}{escape(text)}"
    if gameinfo.weather_severity(wx) >= BAD_WEATHER:
        out = f"<b class='rd-key-w'>{out}</b>"
    return out


def card_info(wkd: Week, p: dict, g, proj) -> dict:
    """The fields gordstats.roster_page.player_card draws, for one player."""
    pos = p["pos"]
    info = {"name": p["player"], "pos": pos, "team": str(p.get("team") or ""),
            "logo": _school_logo(p.get("team_full") or "", wkd.to_school, wkd.espn)
            .replace("mu-logo", "rd-logo"),
            "game": game_cell(g), "proj": proj, "inj": p.get("status") or ""}
    playing = g is not None and isinstance(g.get("opp"), str)
    if playing:
        where = "vs" if g.get("home") else "@"
        info["opp_label"] = f"{where} {g.get('opp_abbr') or g['opp']}"
        if pos == "DEF":
            pts = g.get("pred_against")
            if pts is not None and not pd.isna(pts):
                info["opp_note"] = f"opp {float(pts):.0f} pts"
        else:
            row = wkd.ratings.get(str(g.get("opp_id")))
            value = None if row is None else row.get(pos)
            if value is not None and not pd.isna(value):
                info["opp_value"] = float(value)
                info["opp_rank"] = int(wkd.ranks[pos].get(str(g.get("opp_id"))))
    bits = [_wx_short(wkd, g)] if playing else []
    use = wkd.usage.get(p["yahoo_id"])
    if use is not None and pos != "DEF":
        for label, col in (("car", "car_share"), ("tgt", "tgt_share")):
            v = use[col]
            if v is not None and not pd.isna(v) and float(v) >= 0.005:
                bits.append(f"{label} {float(v):.0%}")
    bits = [b for b in bits if b]
    if bits:
        info["extra"] = f"<div class='rd-c-sub'>{' &middot; '.join(bits)}</div>"
    return info


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def _name(p: dict, wkd: Week, with_proj: bool = True) -> str:
    v = wkd.proj(p["yahoo_id"])
    return (f"<b>{escape(p['player'])}</b>"
            + (f" ({v:.1f})" if with_proj and v is not None else ""))


def _change(p: dict, got: dict) -> str:
    return shared_lineup.change(p["slot"], got["slot"][p["yahoo_id"]], lineup.BENCH)


def moves_box(wkd: Week, roster: list, got: dict, proj: dict, kick: dict, gain: float) -> str:
    """This roster's changes, handed to the shared box."""
    changes = []
    for p in roster:
        kind = _change(p, got)
        if kind:
            pid = p["yahoo_id"]
            changes.append({"kind": kind, "name": p["player"], "proj": wkd.proj(pid),
                            "now": p["slot"], "new": got["slot"][pid],
                            "when": _when(kick.get(pid)), "sort": str(kick.get(pid))})
    # A starter with an injury tag and nobody who could still replace him.
    by_id = {p["yahoo_id"]: p for p in roster}
    warns = []
    for pid in got["start"]:
        p = by_id[pid]
        if p.get("status") and pid in got["cover"] and not got["cover"][pid]:
            warns.append(f"{_name(p, wkd, False)} is <b>{escape(p['status'])}</b> and kicks off "
                         f"{_when(kick.get(pid))} with no eligible bench player left to play "
                         "after him &mdash; decide before the earlier games lock.")
    return page.moves_box(changes, warns, gain, lineup.FLEX)


def p_unlocked(pid: str, wkd: Week) -> bool:
    return not (pid in wkd.wk.index and wkd.wk.loc[pid, "state"] in ("in", "post"))


def lineup_table(wkd: Week, roster: list, got: dict, now_total: float,
                 best_total: float) -> str:
    """The lineup to set, each row coloured by what it takes to get there:
    green comes off the bench, red goes to it, blue changes starting slot for
    the kickoff order."""
    by_id = {p["yahoo_id"]: p for p in roster}
    rows, cards, benched = [], [], False
    slot_rank = {}
    for i, slot in enumerate(slot_order(wkd.lg)):
        slot_rank.setdefault(slot, i)
    # The lineup to set, in lineup order; `cards` keeps the roster as it is now
    # for the phone view's Current side.
    current = {p["yahoo_id"]: i for i, p in enumerate(order_roster(roster, wkd.lg))}
    for p in sorted(roster, key=lambda p: (slot_rank.get(got["slot"][p["yahoo_id"]], 99),
                                           -(wkd.proj(p["yahoo_id"]) or 0.0))):
        pid = p["yahoo_id"]
        new = got["slot"][pid]
        bench = new in lineup.BENCH
        kind = _change(p, got)
        g = wkd.game(p)
        state = (g.get("state") if g is not None else None) or "pre"
        tag = "<span class='rd-tag lock'>locked</span>" if state in ("in", "post") else ""
        move_td = page.move_cell(kind, p["slot"])
        cover = got["cover"].get(pid)
        if new in lineup.BENCH or cover is None:
            cover_td = "<td class='rd-cov none'>&mdash;</td>"
        elif cover:
            c = by_id[cover[0]]
            cover_td = (f"<td class='rd-cov'>{escape(c['player'])} "
                        f"<span class='rd-lbl'>{ui.fmt(wkd.proj(cover[0]))} &middot; "
                        f"{_when(wkd.game(c).get('kickoff') if wkd.game(c) is not None else None)}"
                        "</span></td>")
        else:
            cover_td = (f"<td class='rd-cov {'warn' if p.get('status') else 'none'}'>"
                        "nobody later</td>")
        pts = p.get("points")
        pts_td = (f"<td>{ui.fmt(pts)}</td>" if state in ("in", "post") and pts is not None
                  else "<td>&mdash;</td>")
        split = " rd-split" if bench and not benched else ""
        benched = benched or bench
        cards.append({**card_info(wkd, p, g, wkd.proj(pid)), "slot": p["slot"], "new": new,
                      "kind": kind, "locked": state in ("in", "post"), "order": current[pid]})
        rows.append(
            f"<tr class='{'rd-bn' if bench else 'rd-st'}{split}{' rd-' + kind if kind else ''}'>"
            f"<td class='rd-slot'>{escape(new)}</td>" + move_td
            + player_cell(wkd, p, tag)
            + f"<td class='rd-g'>{game_cell(g)}</td>"
            + opp_cell(wkd, g, p["pos"]) + weather_cell(wkd, g)
            + f"<td><b>{ui.fmt(wkd.proj(pid))}</b></td><td>{ui.fmt(wkd.yproj.get(pid))}</td>"
            + pts_td + usage_cells(wkd, pid, p["pos"]) + cover_td + "</tr>")
    head = ("<tr><th title='Where he belongs this week'>Slot</th>"
            "<th title='What it takes to get him there'>Change</th><th>Player</th><th>Game</th>"
            "<th title='What the opposing defense allows to this position, against "
            "expectation. 1.00 is par; rank 1 is the toughest, the highest number gives up the most.'>Opp vs pos</th>"
            "<th>Weather</th><th title='This site&#39;s projection for the week'>GS proj</th>"
            "<th>Yahoo</th><th>Pts</th>"
            f"<th title='Share of his team&#39;s carries, last {RECENT_WEEKS} played weeks'>Car%</th>"
            f"<th title='Share of his team&#39;s targets, last {RECENT_WEEKS} played weeks'>Tgt%</th>"
            "<th title='Once the changes are made: the best bench player who could still take "
            "this slot - eligible for it and not kicking off any earlier'>Late-swap cover</th></tr>")
    cards.sort(key=lambda c: c["order"])
    return (page.legend()
            + f"<div class='rd-desk rd-scroll'><table class='rd'><thead>{head}</thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
            + page.phone_lineup(cards, slot_rank, lineup.BENCH, now_total, best_total))


def adds_section(wkd: Week, roster: list, got: dict, free: pd.DataFrame) -> str:
    """Free agents who project past someone this roster would start.

    Each is set against the weakest unlocked starter in a slot he could take -
    his own position's, or the flex for a back, receiver or tight end - so the
    gain is what the lineup total would actually move by this week."""
    by_id = {p["yahoo_id"]: p for p in roster}
    starters = [by_id[i] for i in got["start"] if p_unlocked(i, wkd)]
    rows = []
    for _, f in free.iterrows():
        pid, pos = str(f["yahoo_id"]), str(f["pos"]).split(",")[0]
        value = wkd.proj(pid)
        if value is None or value <= 0 or not p_unlocked(pid, wkd):
            continue
        rivals = [s for s in starters
                  if s["pos"] == pos or (got["slot"][s["yahoo_id"]] == lineup.FLEX
                                         and pos in lineup.FLEX_POSITIONS)]
        if not rivals:
            continue
        worst = min(rivals, key=lambda s: wkd.proj(s["yahoo_id"]) or 0.0)
        gain = value - (wkd.proj(worst["yahoo_id"]) or 0.0)
        if gain >= MIN_GAIN:
            rows.append((gain, f, pos, value, worst))
    if not rows:
        return ("<p class='rd-note'>Nobody in the free-agent pool projects to outscore a "
                "starter on this roster this week.</p>")
    rows.sort(key=lambda r: -r[0])
    body, cards = [], []
    for gain, f, pos, value, worst in rows[:ADDS_SHOWN]:
        pid = str(f["yahoo_id"])
        p = {"yahoo_id": pid, "player": f["player"], "pos": pos, "team": f["team"],
             "team_full": f.get("team_full")}
        g = wkd.game(p)
        ros = wkd.season_proj.get(pid)
        card = card_info(wkd, p, g, value)
        card["extra"] = (card.get("extra") or "") + (
            # A class, not an inline colour: the dark theme's green (rd-gain)
            # could not reach a style attribute, and #15803d was 3.2:1 there.
            f"<div class='rd-c-do rd-gain'>+{gain:.1f} over "
            f"{escape(worst['player'])} ({ui.fmt(wkd.proj(worst['yahoo_id']))})</div>")
        cards.append({**card, "slot": pos, "new": pos, "kind": ""})
        body.append(
            "<tr>" + player_cell(wkd, p) + f"<td class='rd-g'>{game_cell(g)}</td>"
            + opp_cell(wkd, g, pos) + weather_cell(wkd, g)
            + f"<td><b>{value:.1f}</b></td>"
            f"<td class='rd-cov'>{escape(worst['player'])} "
            f"<span class='rd-lbl'>{ui.fmt(wkd.proj(worst['yahoo_id']))}</span></td>"
            f"<td class='rd-gain'>+{gain:.1f}</td>"
            + usage_cells(wkd, pid, pos)
            + f"<td>{'&mdash;' if ros is None or pd.isna(ros) else f'{ros:.0f}'}</td></tr>")
    head = ("<tr><th>Add</th><th>Game</th><th>Opp vs pos</th><th>Weather</th><th>GS proj</th>"
            "<th>Would start over</th><th>Gain</th><th>Car%</th><th>Tgt%</th>"
            "<th title='Season projection from the draft board - whether he is worth "
            "keeping past Saturday'>Season</th></tr>")
    # The roster spot has to come from somewhere: the weakest things held.
    droppable = [p for p in roster if got["slot"][p["yahoo_id"]] in lineup.BENCH
                 and p["pos"] != "DEF"]
    # Ruled out first (not merely tagged: a Q plays), then the weakest season.
    droppable.sort(key=lambda p: (not waivers.ruled_out(p.get("status")),
                                  wkd.season_proj.get(p["yahoo_id"]) or 0.0))
    drop = ", ".join(
        f"{escape(p['player'])} ({escape(p['pos'])}"
        + (f", {escape(p['status'])}" if p.get("status") else "")
        + f", season {wkd.season_proj.get(p['yahoo_id']) or 0:.0f})" for p in droppable[:3])
    return (f"<div class='rd-desk rd-scroll'><table class='rd'><thead>{head}</thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>" + page.phone_adds(cards)
            + (f"<p class='rd-note'><b>To make room:</b> the bench's weakest holds by season "
               f"projection, injured first &mdash; {drop}.</p>" if drop else ""))


def team_view(wkd: Week, team: dict, free: pd.DataFrame) -> str:
    key = team["team_key"]
    roster = wkd.data["rosters"].get(key) or []
    ids = [p["yahoo_id"] for p in roster]
    proj = {i: wkd.proj(i) for i in ids}
    kick, locked = {}, set()
    for p in roster:
        g = wkd.game(p)
        if g is not None and isinstance(g.get("opp"), str):
            kick[p["yahoo_id"]] = g.get("kickoff")
            if (g.get("state") or "pre") in ("in", "post"):
                locked.add(p["yahoo_id"])
    got = lineup.plan(roster, wkd.lg["roster"], proj, kick, locked)
    now_total = lineup.total(roster, {p["yahoo_id"]: p["slot"] for p in roster}, proj)
    best_total = lineup.total(roster, got["slot"], proj)
    gain = best_total - now_total

    foe = next((t for m in wkd.data["matchups"] if any(x["team_key"] == key for x in m["teams"])
                for t in m["teams"] if t["team_key"] != key), None)
    record = f"{int(team.get('wins') or 0)}-{int(team.get('losses') or 0)}"
    if team.get("ties"):
        record += f"-{int(team['ties'])}"
    logo = (f"<img class='rd-tlogo' src='{escape(team['logo'], quote=True)}' alt=''>"
            if team.get("logo") else "")
    head = (
        f"<div class='rd-head'>{logo}<div><div class='rd-nm'>{escape(team['name'])}</div>"
        f"<div class='rd-sub'>{record} &middot; week {wkd.week}"
        + (f" vs <b>{escape(foe['name'])}</b>" if foe else "")
        + " &middot; <a href='/cfb/matchups/'>matchup</a> &middot; "
        f"<a href='/cfb/usage/#own={escape(key, quote=True)}'>usage</a></div></div>"
        "<div class='rd-tiles'>"
        f"<div class='rd-tile'><b>{now_total:.1f}</b><span>As set</span></div>"
        f"<div class='rd-tile{' up' if gain >= MIN_GAIN else ''}'><b>{best_total:.1f}</b>"
        "<span>Best lineup</span></div>"
        + (f"<div class='rd-tile'><b>{foe['projected']:.1f}</b><span>Opp (Yahoo)</span></div>"
           if foe and foe.get("projected") else "")
        + "</div></div>")
    return (f"<div class='rd-view' data-key='{escape(key, quote=True)}' style='display:none'>"
            + head + "<h2>Start / sit</h2>"
            + moves_box(wkd, roster, got, proj, kick, gain)
            + lineup_table(wkd, roster, got, now_total, best_total)
            + "<h2>Waiver adds</h2>"
            "<p class='rd-note'>Free agents projected to outscore someone this roster would "
            "otherwise start this week, biggest gain first.</p>"
            + adds_section(wkd, roster, got, free) + "</div>")


def body() -> str:
    if not yahoo.archived_weeks():
        return (page.CSS + "<p>No rosters yet — the page fills in on the first rebuild once "
                "Yahoo has scheduled week 1.</p>")
    wkd = Week()
    free = yahoo.free_agents()
    teams = sorted(wkd.lg["teams"], key=lambda t: t["name"].lower())
    slugs = {t["team_key"]: "t" + t["team_key"].rsplit(".", 1)[-1] for t in teams}
    mine = next((t["team_key"] for t in teams if t["name"] == MY_TEAM), "")
    options = "".join(f"<option value='{escape(t['team_key'], quote=True)}'>"
                      f"{escape(t['name'])}</option>" for t in teams)
    start = datetime.strptime(wkd.data["week_start"], "%Y-%m-%d")
    end = datetime.strptime(wkd.data["week_end"], "%Y-%m-%d")
    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    cfg = script_json({"mine": mine, "teams": slugs})
    return (
        page.CSS + page.CARD_CSS
        + f"<p><strong>Week {wkd.week}</strong> &middot; {start:%b %-d} &ndash; {end:%b %-d}. "
        "One roster at a time: who to start, which slot to put him in, what he is up "
        "against, and who on the wire would beat him. "
        "Weighing a <a href='/cfb/trade/'>trade</a> or a "
        "<a href='/cfb/trade/#pickup'>pickup</a>?</p>"
        "<details class='section'><summary>How to read this page</summary>"
        "<p class='rd-note'><b>Start / sit</b> shows the lineup to set and colors what has "
        "to change to get there, by <b>GS proj</b>, this site's weekly projection (Yahoo's "
        "own sits beside it). <b class='rd-key-g'>Green</b> comes off the bench into "
        "the slot named; <b class='rd-key-r'>red</b> goes to the bench; "
        "<b class='rd-key-b'>blue</b> stays a starter but changes slot for the kickoff "
        "order: Yahoo locks a player at his own kickoff, so the earliest games take the "
        "position slots and the latest take the flex &mdash; if Saturday night's receiver "
        "is scratched, the open slot is one any back, receiver or tight end can fill. "
        "<b>Late-swap cover</b> is, once the changes are made, the best bench player who "
        "could still take that slot: eligible for it and not kicking off any earlier. A "
        "player whose game has started is <i>locked</i> where he sits.</p>"
        "<p class='rd-note'><b>Opp vs pos</b> is the opponent's row on the "
        "<a href='/cfb/strength/'>matchup strength</a> page: fantasy points allowed to that "
        "position against what the offenses it faced should have scored. 1.00 is par, green "
        f"is soft, and the rank runs from 1 (the toughest, red) to {wkd.n_def} (gives up the most, "
        "green); FCS defenses have "
        "no rating. <b>Weather</b> is the forecast for the game, in amber when it is bad "
        "enough to matter (rain, storms, snow, or gusts past 25 mph). <b>Car%</b> and "
        f"<b>Tgt%</b> are the last {RECENT_WEEKS} played weeks from the "
        "<a href='/cfb/usage/'>usage</a> page. <b>Waiver adds</b> sets each free agent "
        "against the weakest starter he could replace, so the gain is what the lineup total "
        f"would move by. Rebuilt several times a day (last: {built}).</p></details>"
        "<div class='pin-bar'><div class='rd-pick'><label>Team <select id='rd-team'>"
        f"{options}</select></label><button id='rd-star' type='button'></button></div></div>"
        + "".join(team_view(wkd, t, free) for t in teams)
        + f"<script type='application/json' id='rd-cfg'>{cfg}</script>"
        + page.switch_js("cfbMyTeam") + page.CARD_JS)


def generate():
    write_page(OUTPUT, f"CFB Team Dashboard {SEASON}", body(),
               subtitle="Start/sit, slot order, matchups, weather and waiver adds",
               description="Start/sit help for every college fantasy roster: the best lineup "
                           "by our weekly projections, the flex saved for late kickoffs, "
                           "matchups, weather and pickups.")


if __name__ == "__main__":
    generate()
