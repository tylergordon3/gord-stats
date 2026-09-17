"""
Team dashboard (docs/fantasy/roster/): one NFL roster's week on one screen.

The NFL twin of the college dashboard (cfb.site.roster), sharing its look
(gordstats.roster_page) and its lineup planner (gordstats.lineup). Per team,
for the week being played:

  * Start / sit  the roster exactly as it is set, coloured by what to change:
                 green comes off the bench, red goes to it, blue stays a
                 starter but changes slot so the latest kickoffs hold the FLEX
                 - Sleeper locks a player at his own kickoff, so a Monday
                 night scratch is only fixable if the hole is a flex.
  * The game     opponent and kickoff, the team's implied total from the
                 betting line, what the defence across from him has allowed to
                 his position (fantasy.league.defense), and the forecast.
  * Waiver adds  free agents projected to outscore somebody this roster would
                 otherwise start.

The projection is the blend the matchups page tracks with: this site's weekly
number averaged with Sleeper's, ESPN's and FantasyPros' where they have the
player. Free agents only have the first two on record, and say so.

    python -m fantasy.site.roster
"""
import json
from collections import Counter
from datetime import datetime
from html import escape

import pandas as pd

from fantasy import paths
from fantasy.config import LEAGUE_TZ, MY_MANAGER, UPCOMING_SEASON, UPCOMING_YEAR
from fantasy.league import defense
from fantasy.league import ext_projections as ext
from fantasy.league import matchups as data_mod
from fantasy.league import suggestions
from fantasy.site import layout
from fantasy.site import matchups as mu
from gordstats import lineup as planner
from gordstats import matchup_page as ui
from gordstats import roster_page as page
from gordstats.frontmatter import add_front_matter

FLEX = "FLEX"
OFF = {"BN", "IR", "TAXI"}
RESERVE = ("IR", "TAXI")
ADDS_SHOWN = 8
MIN_GAIN = 0.5                  # an add worth less than this is a coin flip, not advice
STORAGE_KEY = "nflMyTeam"


class Week:
    """Everything every team's view reads, worked out once."""

    def __init__(self):
        try:
            weeks = data_mod.capture(year=UPCOMING_YEAR)
        except Exception as exc:                            # noqa: BLE001
            print(f"[roster] using the archive only ({exc})")
            weeks = data_mod.archived_weeks(UPCOMING_YEAR)
        self.weeks = weeks
        if not weeks:
            return
        datas = {w: data_mod.week_matchups(w, UPCOMING_YEAR) for w in weeks}
        open_weeks = [w for w in weeks if not data_mod.week_final(datas[w])]
        self.week = open_weeks[0] if open_weeks else weeks[-1]
        self.data = datas[self.week]
        self.slots = data_mod.league()["roster_positions"]
        self.board_frame = mu._board(weeks, datas)
        self.board = {str(r.sleeper_id): {"player": r.player, "pos": r.pos, "team": r.team}
                      for r in self.board_frame.drop_duplicates("sleeper_id")
                      .itertuples(index=False)}
        self.registry = mu._registry()
        self.games = self._games()
        self.by_team = data_mod.team_games(self.games)
        self.weather = {g["game_id"]: g.get("weather") for g in self.games}
        self.wk = data_mod.week_projections(self.board_frame, self.games,
                                            injuries=mu.injury_status(self.data))

        # Every source that has a player, ours included - the matchups page's
        # tracking number. Sleeper's is refetched for the whole league here,
        # since the archive keeps it for rostered players only.
        self.sources = mu.outside_sources(self.data)
        try:
            everyone = data_mod.sleeper_projections(self.week, UPCOMING_YEAR)
            self.sleeper_all = {pid: v["pts"] for pid, v in everyone.items()
                                if v.get("pts") is not None}
            self.injuries = {pid: v.get("injury") or "" for pid, v in everyone.items()}
        except Exception as exc:                            # noqa: BLE001
            print(f"[roster] rostered Sleeper projections only ({exc})")
            self.sleeper_all, self.injuries = dict(self.sources.get("sleeper") or {}), {}

        try:
            table = defense.ratings(data=defense.capture(UPCOMING_YEAR))
        except Exception as exc:                            # noqa: BLE001
            print(f"[roster] archived defence ratings only ({exc})")
            table = defense.ratings()
        self.dvp = table
        self.dvp_ranks = defense.ranks(table) if not table.empty else {}

    def _games(self) -> list:
        """The week's games, with the forecast. An archive written before the
        scoreboard parser kept weather has none, so it is read once more."""
        games = self.data["games"]
        if games and not any("weather" in g for g in games):
            try:
                fresh = {g["game_id"]: g for g in data_mod.espn_games(self.week, UPCOMING_YEAR)}
                games = [{**g, "weather": (fresh.get(g["game_id"]) or {}).get("weather")}
                         for g in games]
            except Exception as exc:                        # noqa: BLE001
                print(f"[roster] no forecast ({exc})")
        return games

    def gs(self, pid: str, team: str = ""):
        if pid in self.wk.index and not pd.isna(self.wk.loc[pid, "proj_week"]):
            return float(self.wk.loc[pid, "proj_week"])
        if team and team not in self.by_team:
            return 0.0                                      # a bye, board or not
        return None

    def blend(self, pid: str, team: str = ""):
        """The mean of every source that has him; a bye is zero whatever a
        season-long source says."""
        if team and team not in self.by_team:
            return 0.0
        vals = [self.gs(pid, team), self.sleeper_all.get(pid)]
        vals += [src.get(pid) for key, src in self.sources.items() if key != "sleeper"]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None


# --------------------------------------------------------------------------- #
# Cells
# --------------------------------------------------------------------------- #

def _when(g: dict | None) -> str:
    if not g or not g.get("date"):
        return "bye"
    local = datetime.fromisoformat(g["date"].replace("Z", "+00:00")).astimezone(LEAGUE_TZ)
    return f"{local:%a %-I:%M}{local:%p}".replace("AM", "a").replace("PM", "p")


def _kick(g: dict | None):
    return pd.Timestamp(g["date"]) if g and g.get("date") else None


def opp_cell(wkd: Week, g: dict | None, pos: str) -> str:
    if not g:
        return "<td>&mdash;</td>"
    table = wkd.dvp
    if table.empty or g["opp"] not in table.index or pos not in table:
        return "<td title='No finished week to rate this defence on yet'>&mdash;</td>"
    value = float(table.loc[g["opp"], pos])
    rank = wkd.dvp_ranks[pos][g["opp"]]
    games = int(table.loc[g["opp"], "games"])
    return (f"<td style='{page.heat(value)}' title='Fantasy points {escape(g['opp'])} has "
            f"allowed to {pos}s against the league average, over {games} game"
            f"{'' if games == 1 else 's'}; 1.00 is par. Rank 1 gives up the most.'>{value:.2f}"
            f"<span class='rd-rk'>{page.ordinal(rank)} of {len(table)}</span></td>")


def total_cell(g: dict | None, pos: str) -> str:
    """The market's number for his side: his team's implied total, or for a
    defence the total it is expected to allow."""
    if not g:
        return "<td>&mdash;</td>"
    value = g.get("implied_against") if pos == "DEF" else g.get("implied_for")
    if value is None:
        return "<td title='No line posted yet'>&mdash;</td>"
    return (f"<td>{value:.1f}" + ("<span class='rd-rk'>allowed</span>" if pos == "DEF" else "")
            + "</td>")


def weather_cell(wkd: Week, g: dict | None) -> str:
    if not g:
        return "<td>&mdash;</td>"
    wx = wkd.weather.get(g["game_id"])
    if not wx:
        return "<td class='rd-wx' title='No forecast yet - they appear a few days out'>&mdash;</td>"
    if wx.get("indoors"):
        return "<td class='rd-wx'>&#127967;&#65039; Indoors</td>"
    cond = wx.get("cond")
    bad = cond in page.WX_RAIN or cond in page.WX_STORM or cond in page.WX_SNOW \
        or (wx.get("temp") is not None and wx["temp"] <= 32)
    bits = ([f"{wx['temp']:.0f}&deg;"] if wx.get("temp") is not None else []) \
        + ([escape(wx["text"])] if wx.get("text") else [])
    return (f"<td class='rd-wx{' bad' if bad else ''}'>{page.wx_icon(cond)} "
            + " ".join(bits) + "</td>")


def player_cell(card: dict, extra: str = "") -> str:
    inj = (f"<span class='rd-inj'>{escape(card['injury'])}</span>" if card.get("injury") else "")
    return (f"<td class='rd-p'>{mu._logo(card['team']).replace('mu-logo', 'rd-logo')}"
            f"<span class='nm'>{escape(card['name'])}</span>"
            f"<span class='rd-lbl'>{escape(card['pos'])} &middot; {escape(card['team'] or 'FA')}"
            f"</span>{inj}{extra}</td>")


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def card_info(wkd: Week, card: dict, proj, note: str = "proj") -> dict:
    """The fields gordstats.roster_page.player_card draws, for one player."""
    g = wkd.by_team.get(card["team"])
    pos = card["pos"]
    info = {"name": card["name"], "pos": pos, "team": card["team"] or "FA",
            "logo": mu._logo(card["team"]).replace("mu-logo", "rd-logo"),
            "game": mu.game_cell(g), "proj": proj, "proj_note": note,
            "inj": card.get("injury") or ""}
    if not g:
        return info
    info["opp_label"] = f"{'vs' if g.get('home') else '@'} {g['opp']}"
    table = wkd.dvp
    if not table.empty and g["opp"] in table.index and pos in table:
        info["opp_value"] = float(table.loc[g["opp"], pos])
        info["opp_rank"] = wkd.dvp_ranks[pos][g["opp"]]
    bits = []
    wx = wkd.weather.get(g["game_id"])
    if wx and wx.get("indoors"):
        bits.append("&#127967;&#65039; indoors")
    elif wx:
        cond = wx.get("cond")
        text = (f"{page.wx_icon(cond)} "
                + (f"{wx['temp']:.0f}&deg; " if wx.get("temp") is not None else "")
                + escape(wx.get("text") or ""))
        bad = cond in page.WX_RAIN or cond in page.WX_STORM or cond in page.WX_SNOW
        bits.append(f"<b style='color:#b45309'>{text}</b>" if bad else text)
    total = g.get("implied_against") if pos == "DEF" else g.get("implied_for")
    if total is not None:
        bits.append(f"team total {total:.1f}" if pos != "DEF" else f"allows {total:.1f}")
    if bits:
        info["extra"] = f"<div class='rd-c-sub'>{' &middot; '.join(bits)}</div>"
    return info


def _plain(t: dict) -> str:
    """"Team name (Manager)" as text - for the menu and the sort."""
    name, mgr = t.get("name") or "", t.get("manager") or ""
    return name + (f" ({mgr})" if mgr and mgr not in name else "")


def lineup_table(wkd: Week, rows: list, cards: dict, got: dict, proj: dict, pts: dict,
                 now_total: float, best_total: float) -> str:
    body, phone, benched = [], [], False
    for r in rows:
        pid, slot = r["pid"], r["slot"]
        bench = slot in OFF
        split = " rd-split" if bench and not benched else ""
        benched = benched or bench
        if pid == "0":
            phone.append({"name": "Empty slot", "slot": slot, "new": slot, "kind": "",
                          "pos": "", "team": "", "game": "", "proj": None})
            body.append(f"<tr class='rd-st'><td class='rd-slot'>{escape(slot)}</td>"
                        "<td class='rd-mv'></td><td class='rd-p' colspan='10'>"
                        "<span class='rd-inj'>Empty slot</span></td></tr>")
            continue
        card = cards[pid]
        g = wkd.by_team.get(card["team"])
        new = got["slot"][pid]
        kind = planner.change(slot, new, OFF)
        state = (g or {}).get("state") or "pre"
        tag = "<span class='rd-tag lock'>locked</span>" if g and state in ("in", "post") else ""
        cover = got["cover"].get(pid)
        if new in OFF or cover is None:
            cover_td = "<td class='rd-cov none'>&mdash;</td>"
        elif cover:
            c = cards[cover[0]]
            cover_td = (f"<td class='rd-cov'>{escape(c['name'])} <span class='rd-lbl'>"
                        f"{ui.fmt(proj.get(cover[0]))} &middot; "
                        f"{_when(wkd.by_team.get(c['team']))}</span></td>")
        else:
            cover_td = (f"<td class='rd-cov {'warn' if card.get('injury') else 'none'}'>"
                        "nobody later</td>")
        scored = pts.get(pid)
        pts_td = (f"<td>{ui.fmt(scored)}</td>" if g and state in ("in", "post")
                  and scored is not None else "<td>&mdash;</td>")
        phone.append({**card_info(wkd, card, proj.get(pid)), "slot": slot, "new": new,
                      "kind": kind, "locked": bool(g) and state in ("in", "post")})
        body.append(
            f"<tr class='{'rd-bn' if bench else 'rd-st'}{split}{' rd-' + kind if kind else ''}'>"
            f"<td class='rd-slot'>{escape(slot)}</td>" + page.move_cell(kind, new)
            + player_cell(card, tag) + f"<td class='rd-g'>{mu.game_cell(g)}</td>"
            + total_cell(g, card["pos"]) + opp_cell(wkd, g, card["pos"]) + weather_cell(wkd, g)
            + f"<td><b>{ui.fmt(proj.get(pid))}</b></td>"
            f"<td>{ui.fmt(wkd.gs(pid, card['team']))}</td>"
            f"<td>{ui.fmt(wkd.sleeper_all.get(pid))}</td>" + pts_td + cover_td + "</tr>")
    head = ("<tr><th title='Where he is set right now'>Slot</th>"
            "<th title='What to do with him'>Change</th><th>Player</th><th>Game</th>"
            "<th title='His team&#39;s implied points from the spread and total; for a "
            "defence, what it is expected to allow'>Team total</th>"
            "<th title='What the opposing defence has allowed to this position against the "
            "league average. 1.00 is par; rank 1 gives up the most.'>Opp vs pos</th>"
            "<th>Weather</th>"
            "<th title='Every projection on record for him, averaged: GordStats, Sleeper, "
            "ESPN and FantasyPros'>Proj</th><th>GS</th><th>Sleeper</th><th>Pts</th>"
            "<th title='Once the changes are made: the best bench player who could still take "
            "this slot - eligible for it and not kicking off any earlier'>Late-swap cover</th></tr>")
    slot_rank = {}
    for i, name in enumerate(wkd.slots):
        slot_rank.setdefault(name, i)
    return (page.legend()
            + f"<div class='rd-desk rd-scroll'><table class='rd'><thead>{head}</thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>"
            + page.phone_lineup(phone, slot_rank, OFF, now_total, best_total))


def adds_section(wkd: Week, cards: dict, got: dict, proj: dict, free: pd.DataFrame) -> str:
    """Free agents who project past someone this roster would start: each set
    against the weakest unlocked starter in a slot he could take."""
    def unlocked(team):
        g = wkd.by_team.get(team)
        return bool(g) and (g.get("state") or "pre") == "pre"

    starters = [pid for pid in got["start"] if unlocked(cards[pid]["team"])]
    found = []
    for _, f in free.iterrows():
        pid, pos, team = str(f["sleeper_id"]), f["pos"], f["team"]
        if not unlocked(team) or (wkd.injuries.get(pid) or f.get("injury")) in suggestions.OUT:
            continue
        value = wkd.blend(pid, team)
        if not value or value <= 0:
            continue
        rivals = [s for s in starters if cards[s]["pos"] == pos
                  or (got["slot"][s] == FLEX and pos in data_mod.FLEX_POSITIONS)]
        if not rivals:
            continue
        worst = min(rivals, key=lambda s: proj.get(s) or 0.0)
        gain = value - (proj.get(worst) or 0.0)
        if gain >= MIN_GAIN:
            found.append((gain, f, value, worst))
    if not found:
        return ("<p class='rd-note'>Nobody in the free-agent pool projects to outscore a "
                "starter on this roster this week.</p>")
    found.sort(key=lambda r: -r[0])
    body, phone = [], []
    for gain, f, value, worst in found[:ADDS_SHOWN]:
        pid = str(f["sleeper_id"])
        card = {"name": f["player"], "pos": f["pos"], "team": f["team"],
                "injury": wkd.injuries.get(pid) or ""}
        g = wkd.by_team.get(f["team"])
        info = card_info(wkd, card, value)
        info["extra"] = (info.get("extra") or "") + (
            f"<div class='rd-c-do' style='color:#15803d'>+{gain:.1f} over "
            f"{escape(cards[worst]['name'])} ({ui.fmt(proj.get(worst))})</div>")
        phone.append({**info, "slot": f["pos"], "new": f["pos"], "kind": ""})
        body.append(
            "<tr>" + player_cell(card) + f"<td class='rd-g'>{mu.game_cell(g)}</td>"
            + total_cell(g, f["pos"]) + opp_cell(wkd, g, f["pos"]) + weather_cell(wkd, g)
            + f"<td><b>{value:.1f}</b></td><td>{ui.fmt(wkd.gs(pid, f['team']))}</td>"
            f"<td>{ui.fmt(wkd.sleeper_all.get(pid))}</td>"
            f"<td class='rd-cov'>{escape(cards[worst]['name'])} "
            f"<span class='rd-lbl'>{ui.fmt(proj.get(worst))}</span></td>"
            f"<td class='rd-gain'>+{gain:.1f}</td>"
            f"<td>{'&mdash;' if f.get('mu') is None or pd.isna(f['mu']) else f'{f['mu']:.1f}'}</td></tr>")
    head = ("<tr><th>Add</th><th>Game</th><th>Team total</th><th>Opp vs pos</th><th>Weather</th>"
            "<th title='GordStats and Sleeper averaged - the two sources on record for a "
            "free agent'>Proj</th><th>GS</th><th>Sleeper</th><th>Would start over</th>"
            "<th>Gain</th><th title='Points per game the projection model expects from here "
            "on - whether he is worth keeping past Sunday'>Season ppg</th></tr>")
    return (f"<div class='rd-desk rd-scroll'><table class='rd'><thead>{head}</thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>" + page.phone_adds(phone))


def drop_note(owned: pd.DataFrame, manager: str) -> str:
    mine = suggestions.drops(owned[owned["manager"] == manager]) if not owned.empty else owned
    if mine is None or mine.empty:
        return ""
    names = ", ".join(f"{escape(str(r['player']))} ({escape(r['pos'])}, "
                      f"{r['points']:.1f})" for _, r in mine.iterrows())
    return ("<p class='rd-note'><b>To make room:</b> the weakest holds on this roster over "
            f"what their position hands out for free &mdash; {names}. More on the "
            "<a href='/fantasy/transactions/'>waivers page</a>.</p>")


def team_view(wkd: Week, side: dict, foe: dict | None, free: pd.DataFrame,
              owned: pd.DataFrame) -> str:
    key = str(side["roster_id"])
    team = wkd.data["teams"].get(key) or {}
    rows = mu.roster_rows(side, team.get("reserve") or [], wkd.slots)
    cards = {r["pid"]: mu.player_card(r["pid"], wkd.data, wkd.board, wkd.registry)
             for r in rows if r["pid"] != "0"}
    proj = {pid: wkd.blend(pid, c["team"]) for pid, c in cards.items()}
    kick = {pid: _kick(wkd.by_team.get(c["team"])) for pid, c in cards.items()}
    locked = {pid for pid, c in cards.items()
              if ((wkd.by_team.get(c["team"]) or {}).get("state") or "pre") in ("in", "post")}
    players = [{"id": r["pid"], "pos": cards[r["pid"]]["pos"], "slot": r["slot"]}
               for r in rows if r["pid"] != "0"]
    counts = Counter(s for s in wkd.slots if s not in OFF)
    got = planner.plan(players, counts, proj, kick, locked, flex=FLEX,
                       flex_positions=data_mod.FLEX_POSITIONS, bench="BN", reserve=RESERVE)

    def total(slots):
        return sum(proj.get(p["id"]) or 0.0 for p in players if slots[p["id"]] not in OFF)
    now_total = total({p["id"]: p["slot"] for p in players})
    best_total = total(got["slot"])
    gain = best_total - now_total

    changes = []
    for p in players:
        kind = planner.change(p["slot"], got["slot"][p["id"]], OFF)
        if kind:
            g = wkd.by_team.get(cards[p["id"]]["team"])
            changes.append({"kind": kind, "name": cards[p["id"]]["name"],
                            "proj": proj.get(p["id"]), "now": p["slot"],
                            "new": got["slot"][p["id"]], "when": _when(g),
                            "sort": (g or {}).get("date") or "~"})
    warns = [f"<b>{escape(cards[pid]['name'])}</b> is <b>{escape(cards[pid]['injury'])}</b> "
             f"and kicks off {_when(wkd.by_team.get(cards[pid]['team']))} with no eligible "
             "bench player left to play after him &mdash; decide before the earlier games lock."
             for pid in got["start"]
             if cards[pid].get("injury") and pid in got["cover"] and not got["cover"][pid]]

    foe_team = (wkd.data["teams"].get(str(foe["roster_id"])) or {}) if foe else {}
    avatar = mu._avatar(team).replace("mu-tlogo", "rd-tlogo")
    head = (
        f"<div class='rd-head'>{avatar}<div><div class='rd-nm'>{escape(team.get('name') or '')}</div>"
        f"<div class='rd-sub'>{escape(team.get('manager') or '')} &middot; {mu._record(team)} "
        f"&middot; week {wkd.week}"
        + (f" vs <b>{escape(_plain(foe_team))}</b>" if foe_team else "")
        + " &middot; <a href='/fantasy/matchups/'>matchup</a> &middot; "
        f"<a href='/fantasy/usage/#own={escape(key, quote=True)}'>usage</a></div></div>"
        "<div class='rd-tiles'>"
        f"<div class='rd-tile'><b>{now_total:.1f}</b><span>As set</span></div>"
        f"<div class='rd-tile{' up' if gain >= MIN_GAIN else ''}'><b>{best_total:.1f}</b>"
        "<span>Best lineup</span></div></div></div>")
    return (f"<div class='rd-view' data-key='{escape(key, quote=True)}' style='display:none'>"
            + head + "<h2>Start / sit</h2>" + page.moves_box(changes, warns, gain, FLEX)
            + lineup_table(wkd, rows, cards, got, proj, side.get("players_points") or {},
                           now_total, best_total)
            + "<h2>Waiver adds</h2><p class='rd-note'>Free agents projected to outscore "
            "someone this roster would otherwise start this week, biggest gain first.</p>"
            + adds_section(wkd, cards, got, proj, free)
            + drop_note(owned, team.get("manager") or "") + "</div>")


def body() -> str:
    wkd = Week()
    if not wkd.weeks:
        return (page.CSS + f"<p>No rosters yet — Sleeper posts the {UPCOMING_SEASON} schedule "
                "once the draft is done, and this page fills in on the next rebuild.</p>")
    try:
        free, owned = suggestions.pools(UPCOMING_YEAR)
        free = free[free["active"] & ~free["basis"].isin(suggestions.FILLER)]
    except Exception as exc:                                # noqa: BLE001
        print(f"[roster] no free-agent pool ({exc})")
        free = owned = pd.DataFrame()

    sides = [(s, next((o for o in m["sides"] if o is not s), None))
             for m in wkd.data["matchups"] for s in m["sides"]]
    teams = wkd.data["teams"]
    sides.sort(key=lambda pair: _plain(teams.get(str(pair[0]["roster_id"])) or {}).lower())
    slugs = {str(s["roster_id"]): f"t{s['roster_id']}" for s, _ in sides}
    mine = next((k for k in slugs if (teams.get(k) or {}).get("manager") == MY_MANAGER), "")
    options = "".join(f"<option value='{k}'>{escape(_plain(teams.get(k) or {}))}</option>"
                      for k in slugs)
    built = datetime.now(LEAGUE_TZ).strftime("%b %-d, %-I:%M %p %Z")
    n_def = len(wkd.dvp)
    cfg = json.dumps({"mine": mine, "teams": slugs}).replace("</", "<\\/")
    return (
        page.CSS + page.CARD_CSS
        + f"<p><strong>Week {wkd.week}</strong>. One roster at a time: who to start, which "
        "slot to put him in, what he is up against, and who on the wire would beat him.</p>"
        "<details class='section'><summary>How to read this page</summary>"
        "<p class='rd-note'><b>Start / sit</b> shows the roster exactly as it is set and "
        "colours what to change. <b style='color:#16a34a'>Green</b> comes off the bench into "
        "the slot named; <b style='color:#dc2626'>red</b> goes to the bench; "
        "<b style='color:#2563eb'>blue</b> stays a starter but changes slot for the kickoff "
        "order: Sleeper locks a player at his own kickoff, so Thursday's and the early "
        "Sunday games take the position slots and the latest take the FLEX &mdash; if Monday "
        "night's receiver is scratched, the open slot is one any back, receiver or tight end "
        "can fill. <b>Late-swap cover</b> is, once the changes are made, the best bench "
        "player who could still take that slot. A player whose game has started is "
        "<i>locked</i> where he sits.</p>"
        "<p class='rd-note'><b>Proj</b> is every projection on record for the player "
        "averaged &mdash; this site's (<b>GS</b>), Sleeper's, ESPN's and FantasyPros' &mdash; "
        "the number the <a href='/fantasy/matchups/'>matchups</a> page tracks with; free "
        "agents have only the first two. <b>Team total</b> is his side's implied points "
        "from the spread and total. <b>Opp vs pos</b> is what the defence across from him "
        "has allowed to his position against the league average: 1.00 is par, green is "
        f"soft, rank 1 of {n_def or 32} gives up the most, and ratings on fewer than "
        f"{defense.FULL_WEIGHT_GAMES} games are pulled toward par. <b>Weather</b> is ESPN's "
        "forecast, in amber for rain, storms, snow or a freeze. <b>Waiver adds</b> sets each "
        "free agent against the weakest starter he could replace, so the gain is what the "
        f"lineup total would move by. Rebuilt with the matchups page (last: {built}).</p>"
        "</details>"
        "<div class='pin-bar'><div class='rd-pick'><label>Team <select id='rd-team'>"
        f"{options}</select></label><button id='rd-star' type='button'></button></div></div>"
        + "".join(team_view(wkd, s, foe, free, owned) for s, foe in sides)
        + f"<script type='application/json' id='rd-cfg'>{cfg}</script>"
        + page.switch_js(STORAGE_KEY) + page.CARD_JS)


def generate():
    out = paths.WEB_ROSTER
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(layout.HEAD + body(), "Team Dashboard",
                                    "Start/sit, slot order, matchups, weather and waiver adds"),
                   encoding="utf-8")
    print(f"Wrote Team Dashboard -> {out}")


if __name__ == "__main__":
    generate()
