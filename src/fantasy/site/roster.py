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
from fantasy.league import availability
from fantasy.league import defense
from fantasy.league import ext_projections as ext
from fantasy.league import matchups as data_mod
from fantasy.league import suggestions
from fantasy.site import layout
from fantasy.site import matchups as mu
from gordstats import lineup as planner
from gordstats import my_league, my_league_data, my_team, my_week
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

        # Every source that has a player, ours included - the matchups page's
        # tracking number. Sleeper's is refetched for the whole league here,
        # since the archive keeps it for rostered players only.
        self.sources = mu.outside_sources(self.data)
        everyone = {}
        try:
            everyone = data_mod.sleeper_projections(self.week, UPCOMING_YEAR)
            self.sleeper_all = {pid: v["pts"] for pid, v in everyone.items()
                                if v.get("pts") is not None}
            self.injuries = {pid: v.get("injury") or "" for pid, v in everyone.items()}
        except Exception as exc:                            # noqa: BLE001
            print(f"[roster] rostered Sleeper projections only ({exc})")
            self.sleeper_all, self.injuries = dict(self.sources.get("sleeper") or {}), {}

        # The chance each tagged player plays (fantasy.league.availability) -
        # free agents' tags from the league-wide pull, the archive's for the
        # rostered - and GordStats' number as the projection times it.
        tags = {pid: t for pid, t in self.injuries.items() if t}
        tags.update(mu.injury_status(self.data))
        positions = {pid: v.get("pos") or "" for pid, v in everyone.items()}
        positions.update({pid: v.get("pos") or "" for pid, v in
                          (self.data.get("projections") or {}).items()})
        self.chances = availability.week_chances(tags, self.week, UPCOMING_YEAR,
                                                 positions=positions)
        self.wk = availability.apply(data_mod.week_projections(self.board_frame, self.games),
                                     self.chances)
        # ESPN's expected return for anyone it holds out.
        self.backs = availability.return_labels(
            [pid for pid, c in self.chances.items() if c["status"] != "Questionable"],
            UPCOMING_YEAR, after=availability.week_end(self.games))
        self.pts = {pid: v for m in self.data["matchups"] for side in m["sides"]
                    for pid, v in (side.get("players_points") or {}).items()}

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

    def gs(self, pid: str, team: str = "", column: str = "proj_week"):
        """GordStats' number: the expected points (`proj_week`, the projection
        times the chance he plays) or the projection if he plays (`proj_full`)."""
        if pid in self.wk.index and not pd.isna(self.wk.loc[pid, column]):
            return float(self.wk.loc[pid, column])
        if team and team not in self.by_team:
            return 0.0                                      # a bye, board or not
        return None

    def chance(self, pid: str, team: str = "") -> float:
        """The chance he plays: the injury report's until his game starts, and
        once it has, certain if Sleeper has him in it."""
        c = self.chances.get(pid)
        if not c:
            return 1.0
        g = self.by_team.get(team)
        if g and (g.get("state") or "pre") != "pre" and availability.playing(
                (self.data.get("stats") or {}).get(pid), self.pts.get(pid)):
            return 1.0
        return float(c["p"])

    def if_plays(self, pid: str, team: str = ""):
        """The mean of every source that has him, if he plays; a bye is zero
        whatever a season-long source says."""
        if team and team not in self.by_team:
            return 0.0
        vals = [self.gs(pid, team, "proj_full"), self.sleeper_all.get(pid)]
        vals += [src.get(pid) for key, src in self.sources.items() if key != "sleeper"]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None

    def blend(self, pid: str, team: str = ""):
        """The number the lineup is set on: the sources' mean times the chance
        he plays - discounted once, since every source prices him as playing."""
        full = self.if_plays(pid, team)
        return None if full is None else full * self.chance(pid, team)


# --------------------------------------------------------------------------- #
# Cells
# --------------------------------------------------------------------------- #

def _inj(status: str) -> str:
    """Sleeper's designation as the matchups page shows it: Q, D, O, IR, PUP."""
    return mu.INJURY_TAGS.get(status, status[:3].upper()) if status else ""


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
            f"{'' if games == 1 else 's'}; 1.00 is par. Rank 1 is the toughest defence; the higher the number the more it gives up.'>{value:.2f}"
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


def with_avail(wkd: Week, pid: str, card: dict) -> dict:
    """The card with the chance he plays while his game is still to come, and
    ESPN's expected return when it holds him out (mu.avail_badges draws both)."""
    c = wkd.chances.get(pid)
    g = wkd.by_team.get(card.get("team"))
    if c and not card.get("injury"):
        card["injury"] = c["status"]        # the official report has him; Sleeper not yet
    if c and g and (g.get("state") or "pre") == "pre":
        card["avail"] = c
    if pid in wkd.backs:
        card["back"] = wkd.backs[pid]
    return card


def player_cell(card: dict, extra: str = "") -> str:
    inj = (f"<span class='rd-inj' title='{escape(card['injury'], quote=True)}'>"
           f"{escape(_inj(card['injury']))}</span>" if card.get("injury") else "")
    inj += mu.avail_badges(card)
    return (f"<td class='rd-p'>{mu._logo(card['team']).replace('mu-logo', 'rd-logo')}"
            f"<span class='nm'>{escape(card['name'])}</span>"
            f"<span class='rd-lbl'>{escape(card['pos'])} &middot; {escape(card['team'] or 'FA')}"
            f"</span>{inj}{extra}</td>")


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def _if_plays_title(wkd: Week, pid: str, card: dict) -> str:
    """A title on a discounted projection: what he projects to if he plays."""
    a = card.get("avail")
    full = wkd.if_plays(pid, card.get("team") or "")
    if not a or full is None or a["p"] >= 1:
        return ""
    return (f" title='{full:.1f} if he plays, times the {a['p'] * 100:.0f}% chance he "
            "does'")


def card_info(wkd: Week, card: dict, proj, note: str = "proj") -> dict:
    """The fields gordstats.roster_page.player_card draws, for one player."""
    g = wkd.by_team.get(card["team"])
    pos = card["pos"]
    info = {"name": card["name"], "pos": pos, "team": card["team"] or "FA",
            "logo": mu._logo(card["team"]).replace("mu-logo", "rd-logo"),
            "game": mu.game_cell(g), "proj": proj, "proj_note": note,
            "inj": _inj(card.get("injury") or "")}
    badges = mu.avail_badges(card)
    if badges:
        info["extra"] = f"<div class='rd-c-sub rd-c-av'>{badges}</div>"
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
        bits.append(f"<b class='rd-key-w'>{text}</b>" if bad else text)
    total = g.get("implied_against") if pos == "DEF" else g.get("implied_for")
    if total is not None:
        bits.append(f"team total {total:.1f}" if pos != "DEF" else f"allows {total:.1f}")
    if bits:
        info["extra"] = ((info.get("extra") or "")
                         + f"<div class='rd-c-sub'>{' &middot; '.join(bits)}</div>")
    return info


def _plain(t: dict) -> str:
    """"Team name (Manager)" as text - for the menu and the sort."""
    name, mgr = t.get("name") or "", t.get("manager") or ""
    return name + (f" ({mgr})" if mgr and mgr not in name else "")


def lineup_table(wkd: Week, rows: list, cards: dict, got: dict, proj: dict, pts: dict,
                 now_total: float, best_total: float, actual: dict = None) -> str:
    body, phone, benched = [], [], False
    slot_rank = {}
    for i, name in enumerate(wkd.slots):
        slot_rank.setdefault(name, i)
    # The phone view's Current side keeps the roster as it is, empty slots and all.
    current = {r["pid"]: i for i, r in enumerate(rows)}
    for i, r in enumerate(rows):
        if r["pid"] == "0":
            phone.append({"name": "Empty slot", "slot": r["slot"], "new": "BN", "kind": "",
                          "pos": "", "team": "", "game": "", "proj": None, "order": i,
                          "ghost": True})
    # The table is the lineup to set, in lineup order.
    filled = [r for r in rows if r["pid"] != "0"]
    filled.sort(key=lambda r: (slot_rank.get(got["slot"][r["pid"]], 99),
                               -(proj.get(r["pid"]) or 0.0)))
    for r in filled:
        pid, slot = r["pid"], r["slot"]
        bench = got["slot"][pid] in OFF
        split = " rd-split" if bench and not benched else ""
        benched = benched or bench
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
                      "kind": kind, "locked": bool(g) and state in ("in", "post"),
                      "done": state == "post", "order": current[pid]})
        body.append(
            f"<tr class='{'rd-bn' if bench else 'rd-st'}{split}"
            f"{' rd-' + kind if kind else ''}{' rd-done' if state == 'post' else ''}'>"
            f"<td class='rd-slot'>{escape(new)}</td>" + page.move_cell(kind, slot)
            + player_cell(card, tag) + f"<td class='rd-g'>{mu.game_cell(g)}</td>"
            + total_cell(g, card["pos"]) + opp_cell(wkd, g, card["pos"]) + weather_cell(wkd, g)
            + (f"<td class='rd-spent' title='His game is over; the points "
               f"column is what he actually scored'>{ui.fmt(proj.get(pid))}</td>"
               if (actual or {}).get(pid) is not None
               else f"<td{_if_plays_title(wkd, pid, card)}><b>{ui.fmt(proj.get(pid))}</b></td>")
            + f"<td>{ui.fmt(wkd.gs(pid, card['team']))}</td>"
            f"<td>{ui.fmt(wkd.sleeper_all.get(pid))}</td>" + pts_td + cover_td + "</tr>")
    head = ("<tr><th title='Where he belongs this week'>Slot</th>"
            "<th title='What it takes to get him there'>Change</th><th>Player</th><th>Game</th>"
            "<th title='His team&#39;s implied points from the spread and total; for a "
            "defence, what it is expected to allow'>Team total</th>"
            "<th title='What the opposing defence has allowed to this position against the "
            "league average. 1.00 is par; rank 1 is the toughest, the highest number gives up the most.'>Opp vs pos</th>"
            "<th>Weather</th>"
            "<th title='Every projection on record for him, averaged: GordStats, Sleeper, "
            "ESPN and FantasyPros - times the chance he plays when he is on the injury "
            "report'>Proj</th><th>GS</th><th>Sleeper</th><th>Pts</th>"
            "<th title='Once the changes are made: the best bench player who could still take "
            "this slot - eligible for it and not kicking off any earlier'>Late-swap cover</th></tr>")
    phone.sort(key=lambda c: c["order"])
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
        card = with_avail(wkd, pid, {"name": f["player"], "pos": f["pos"], "team": f["team"],
                                     "injury": wkd.injuries.get(pid) or ""})
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


def settled(states: dict, pts: dict) -> dict:
    """{player: what he actually scored}, for games that are over.

    "Over" means final, not started. A game in progress carries partial points
    - a back with one carry in the first quarter is on 0.4 - and a projection
    is still the better guess at where he finishes. Only when the game is done
    does the scoreboard beat the forecast.
    """
    return {pid: pts[pid] for pid, state in states.items()
            if state == "post" and pts.get(pid) is not None}


def team_view(wkd: Week, side: dict, foe: dict | None, free: pd.DataFrame,
              owned: pd.DataFrame) -> str:
    key = str(side["roster_id"])
    team = wkd.data["teams"].get(key) or {}
    rows = mu.roster_rows(side, team.get("reserve") or [], wkd.slots)
    cards = {r["pid"]: with_avail(wkd, r["pid"], mu.player_card(r["pid"], wkd.data, wkd.board,
                                                                 wkd.registry))
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

    # A game that is over has an answer, not a forecast. Counting a finished
    # player at his projection made the team totals wrong by however much he
    # beat or missed it - a back projected for 20.6 who scored 35.3 still went
    # into "As set" as 20.6, which is the number a reader checks on a Sunday.
    #
    # Only when the game is *final*. A game in progress has partial points on
    # it, and the projection is still the better guess at where it lands.
    pts = side.get("players_points") or {}
    states = {pid: ((wkd.by_team.get(c["team"]) or {}).get("state") or "pre")
              for pid, c in cards.items()}
    actual = settled(states, pts)
    # `plan` keeps its projections: it chooses among players who have *not*
    # played, and the ones who have are locked where they sit either way.
    effective = {pid: actual.get(pid, proj.get(pid)) for pid in cards}

    def total(slots):
        return sum(effective.get(p["id"]) or 0.0 for p in players if slots[p["id"]] not in OFF)
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
    def odds(pid):
        a = cards[pid].get("avail")
        return (f" ({escape(availability.label(a['p']))})"
                if a and a["status"] in availability.PRICED else "")
    warns = [f"<b>{escape(cards[pid]['name'])}</b> is <b>{escape(_inj(cards[pid]['injury']))}</b>"
             f"{odds(pid)} and kicks off {_when(wkd.by_team.get(cards[pid]['team']))} "
             "with no eligible bench player left to play after him &mdash; decide before the earlier games lock."
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
            + lineup_table(wkd, rows, cards, got, proj, pts,
                           now_total, best_total, actual)
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
        # The theme's img{max-width:100%} makes a cell's logo count for nothing
        # in its column's width, so the widest player cell - now one with a
        # play-chance pill - overflowed into the Game column by the logo's width.
        + "<style>" + ui.PLAY_CSS + "\ntable.rd td.rd-p img{max-width:none}"
          "\n.rd .mu-play,.rd .mu-back{font-size:11px}"
          "\n.rd-c-av .mu-play,.rd-c-av .mu-back{margin:0 4px 0 0;font-size:11.5px}"
          "\n@media (prefers-color-scheme: dark){\n" + ui.PLAY_DARK + "\n}</style>"
        # The reader's own league renders above, and hides the built one - the
        # projections, defence-vs-position and weather below are this league's
        # sources for this league's players.
        + my_league.bar()
        + my_team.section()
        # Outside the built block, so a reader's own league keeps it too: the
        # trade page reads whichever league the bar has picked.
        + "<p class='rd-note'>Weighing a <a href='/fantasy/trade/'>trade</a> or a "
          "<a href='/fantasy/trade/#pickup'>pickup</a>? Play it out.</p>"
        + '<div id="mt-built">'
        + f"<p><strong>Week {wkd.week}</strong>. One roster at a time: who to start, which "
        "slot to put him in, what he is up against, and who on the wire would beat him.</p>"
        "<details class='section'><summary>How to read this page</summary>"
        "<p class='rd-note'><b>Start / sit</b> shows the lineup to set and colours what has "
        "to change to get there. <b class='rd-key-g'>Green</b> comes off the bench into "
        "the slot named; <b class='rd-key-r'>red</b> goes to the bench; "
        "<b class='rd-key-b'>blue</b> stays a starter but changes slot for the kickoff "
        "order: Sleeper locks a player at his own kickoff, so Thursday's and the early "
        "Sunday games take the position slots and the latest take the FLEX &mdash; if Monday "
        "night's receiver is scratched, the open slot is one any back, receiver or tight end "
        "can fill. <b>Late-swap cover</b> is, once the changes are made, the best bench "
        "player who could still take that slot. A player whose game has started is "
        "<i>locked</i> where he sits.</p>"
        "<p class='rd-note'><b>Proj</b> is every projection on record for the player "
        "averaged &mdash; this site's (<b>GS</b>), Sleeper's, ESPN's and FantasyPros' &mdash; "
        "the number the <a href='/fantasy/matchups/'>matchups</a> page tracks with; free "
        "agents have only the first two. A Questionable or Doubtful player's Proj is that "
        "times the chance he plays &mdash; the <b>plays 70%</b> pill, from ten seasons of "
        "official injury reports read by his role and his last practice before the final "
        "report; <b>back ~Nov 1</b> is ESPN's expected return for a player held out. "
        "<b>Team total</b> is his side's implied points from the spread and total. "
        "<b>Opp vs pos</b> is what the defence across from him has allowed to his "
        "position against the league average: 1.00 is par, green is "
        f"soft, the rank runs from 1 (the toughest, red) to {n_def or 32} (gives up the most, "
        "green), and ratings on fewer than "
        f"{defense.FULL_WEIGHT_GAMES} games are pulled toward par. <b>Weather</b> is ESPN's "
        "forecast, in amber for rain, storms, snow or a freeze. <b>Waiver adds</b> sets each "
        "free agent against the weakest starter he could replace, so the gain is what the "
        f"lineup total would move by. Rebuilt with the matchups page (last: {built}).</p>"
        "</details>"
        "<div class='pin-bar'><div class='rd-pick'><label>Team <select id='rd-team'>"
        f"{options}</select></label><button id='rd-star' type='button'></button></div></div>"
        + "".join(team_view(wkd, s, foe, free, owned) for s, foe in sides)
        + f"<script type='application/json' id='rd-cfg'>{cfg}</script>"
        + page.switch_js(STORAGE_KEY) + page.CARD_JS
        + "</div>"
        + my_league.JS + my_league_data.JS + my_week.JS
        + my_team.PLANNER_JS + my_team.VIEW_JS)


def generate():
    out = paths.WEB_ROSTER
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(layout.HEAD + body(), "Team Dashboard",
                                    "Start/sit, slot order, matchups, weather and waiver adds"),
                   encoding="utf-8")
    print(f"Wrote Team Dashboard -> {out}")


if __name__ == "__main__":
    generate()
