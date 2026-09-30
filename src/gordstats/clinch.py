"""
Who is in, who is out, and what the rest need: the playoff picture from the
standings and the games left, for both fantasy leagues' power pages.

The simulations already give every team its playoff odds, but odds cannot say
"clinched": 100% in twenty thousand runs is not a proof, and a reader told a
team is in wants it to be. So this is arithmetic, not simulation - a check on
the standings as they stand and the most and fewest wins each team can still
finish with - and it is conservative on purpose. Every team is treated as able
to win every game it has left, even games it plays against another chaser, and
every tie on wins goes against the team being asked about, since the points-
for tiebreak cannot be known ahead. Whatever it calls settled is settled; a
team it leaves open may in truth be settled already by a tighter count.

A team's games left count the median game too, where the league plays one: a
week is two results, head to head and against the median, and the standings
(Sleeper's, rebuilt by fantasy.league.power.actual_results; Yahoo's) carry
both. With N playoff places, and B first-round byes:

  * Clinched: even losing every game left, fewer than N other teams can reach
    its current win total. Bye and top seed are the same test against B and 1.
  * Eliminated: even winning out, N other teams already have more wins than
    its best possible total. Out of the bye race, the same against B.
  * Magic number: the wins that clinch a place whatever else happens -
    one more than the Nth-highest total any other team can still reach, less
    the team's wins. The classic magic number counts a team's wins plus one
    chaser's losses, and that is exact only when one chaser stands between it
    and the line; with six places and a pack level on wins, one chaser's loss
    need not lower the bar at all (the next team sits at the same total). So
    the published number is the conservative one: the classic count against
    the team with the (N+1)th most possible wins, the team's own wins only.
    Losses by the chasers can still bring it down - it is recounted every
    build - but none is counted in advance. Shown only while it is no more
    than the games left; past that the team needs results elsewhere.
  * Win and in: a head-to-head win this week clinches, whatever else
    happens (its opponent takes the loss, everyone else is assumed to win
    out). "Win both and in", in a median league: the head-to-head game and
    the median together do it. "Must win": a head-to-head loss knocks it out.
  * "A win: 99%": not arithmetic. The simulations' odds with a win this week
    (the stakes split, gordstats.stakes), shown where they are 99% or more
    but a win does not clinch - so a page never says "in" for something the
    arithmetic cannot promise.

The odds printed beside the statuses are the simulation's, held off 100%
until the arithmetic says clinched and off 0% until it says eliminated.

Once no team has a game left, the seeds are known outright (wins, then points
for, the rule both leagues play) and the statuses follow them exactly.

Every status is a statement about every legal finish, and the simulations only
play legal finishes, so a clinched team makes the playoffs in every run and an
eliminated one in none (check() says where they disagree; the adapters print
it, since a disagreement means the two were handed different standings).

    teams = {"9": {"name": "George", "wins": 6, "losses": 2, "left": 20, "pf": 812.4,
                   "odds": 0.74, "opp": "7", "win": 0.83}, ...}

`opp` and `win` only for a week not yet played (the stakes week); `odds` from
the season simulation.
"""
import math
from html import escape

EPS = 1e-9
NEAR = 0.99                     # a win's odds from here up earn a chip of their own

CSS = """<style>
/* The theme boxes every cell in #373737; this table draws rows only, so the
   playoff and bye lines are the only lines that stand out. */
table.clp{width:100%;border-collapse:collapse;font-size:14px;border:0;margin:0}
div.table-scroll table.clp{width:100%}
table.clp th,table.clp td{border:0;border-bottom:1px solid #e2e8f0;padding:6px 8px;
  text-align:center;white-space:nowrap}
table.clp th{font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;color:#334155;
  background:#eef2f7}
table.clp th:first-child{text-align:left}
table.clp td{color:#0f172a;background:#fff;vertical-align:middle}
table.clp td.t{text-align:left;font-weight:700;max-width:190px;overflow:hidden;
  text-overflow:ellipsis}
table.clp .sd{display:inline-block;min-width:1.4em;font-size:12px;font-weight:600;color:#64748b}
table.clp td.mg b{font-weight:800}
table.clp td.dim{color:#64748b;font-weight:400}
/* The playoff line under the Nth seed, the bye line (dashed) under the Bth. */
table.clp tr.cut td{border-bottom:2px solid #475569}
table.clp tr.bye td{border-bottom:2px dashed #94a3b8}
table.clp tr.gone td{color:#64748b}
.cl-chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:700;
  line-height:1.55}
.cl-in{background:#dcfce7;color:#166534}
.cl-lock{background:#15803d;color:#fff}
.cl-out{background:#e2e8f0;color:#475569}
.cl-go{background:#dbeafe;color:#1e40af}
.cl-near{border:1px solid #93c5fd;color:#1e40af;padding:0 7px}
.cl-must{background:#ffedd5;color:#9a3412}
.cl-sub{display:block;font-size:12px;font-weight:600;color:#64748b;line-height:1.3}
.cl-note{font-size:13px;color:#4a5a68;margin:6px 0 12px}
/* A 390px screen holds all five columns: the name gives way first. */
@media (max-width:600px){
  table.clp th{font-size:12px;letter-spacing:0}
  table.clp th,table.clp td{padding:6px 5px}
  table.clp td.t{max-width:104px}
}
@media (prefers-color-scheme: dark){
  table.clp th{color:#dde5ef;background:#223052}
  table.clp th,table.clp td{border-bottom-color:#2b3852}
  table.clp td{color:#dde5ef;background:#16203a}
  table.clp .sd{color:#aab7c9}
  table.clp td.dim{color:#7f8ea3}
  table.clp tr.cut td{border-bottom-color:#aab7c9}
  table.clp tr.bye td{border-bottom-color:#6b7b93}
  table.clp tr.gone td{color:#8a9ab0}
  .cl-in{background:#14532d;color:#bbf7d0}
  .cl-lock{background:#22c55e;color:#052e16}
  .cl-out{background:#334155;color:#cbd5e1}
  .cl-go{background:#1e3a8a;color:#dbeafe}
  .cl-near{border-color:#3b82f6;color:#bfdbfe}
  .cl-must{background:#7c2d12;color:#fed7aa}
  .cl-sub{color:#aab7c9}
  .cl-note{color:#aab7c9}
}
</style>"""


def byes(field: int) -> int:
    """First-round byes in a bracket of `field`: the top seeds sit out until
    the rest is a power of two (six teams, two byes) - both leagues' rule."""
    if field <= 1:
        return 0
    return (1 << math.ceil(math.log2(field))) - field


def _best(t: dict) -> float:
    return float(t["wins"]) + float(t["left"])


def _reach(teams: dict, key: str, total: float, drop: dict = None) -> int:
    """Other teams that can still finish level with `total` or above - a
    level finish counts against `key`, the tiebreak being unknowable."""
    drop = drop or {}
    return sum(1 for k, t in teams.items()
               if k != key and _best(t) - drop.get(k, 0) >= total - EPS)


def _past(teams: dict, key: str, best: float, add: dict = None) -> int:
    """Other teams already sure to finish above `best`."""
    add = add or {}
    return sum(1 for k, t in teams.items()
               if k != key and float(t["wins"]) + add.get(k, 0) > best + EPS)


def standing(teams: dict) -> list:
    """Keys in seed order as things stand: wins, then points for."""
    return sorted(teams, key=lambda k: (-float(teams[k]["wins"]),
                                        -float(teams[k].get("pf") or 0.0), str(k)))


def picture(teams: dict, spots: int, bye_spots: int = 0, median: bool = False) -> dict:
    """{key: status} for every team - see the module notes for each test.

    status: clinched, eliminated, bye (clinched one), no_bye, top (the top
    seed), magic (int, or None when settled or out of its own reach),
    win_in, both_in, must_win, near (odds with a win, when that is the story).
    """
    out = {}
    if all(float(t["left"]) <= EPS for t in teams.values()):
        # The regular season is over and the tiebreak is on the table.
        order = standing(teams)
        for i, k in enumerate(order):
            out[k] = {"clinched": i < spots, "eliminated": i >= spots,
                      "bye": bool(bye_spots) and i < bye_spots,
                      "no_bye": bool(bye_spots) and i >= bye_spots, "top": i == 0,
                      "magic": None, "win_in": False, "both_in": False, "must_win": False,
                      "near": None}
        return out

    for key, t in teams.items():
        w, left = float(t["wins"]), float(t["left"])
        s = {"clinched": _reach(teams, key, w) < spots,
             "eliminated": _past(teams, key, w + left) >= spots,
             "bye": bool(bye_spots) and _reach(teams, key, w) < bye_spots,
             "no_bye": bool(bye_spots) and _past(teams, key, w + left) >= bye_spots,
             "top": _reach(teams, key, w) < 1,
             "magic": None, "win_in": False, "both_in": False, "must_win": False,
             "near": None}
        others = sorted((_best(o) for k, o in teams.items() if k != key), reverse=True)
        if not s["clinched"] and not s["eliminated"] and len(others) >= spots:
            magic = max(0, math.floor(others[spots - 1] - w + EPS) + 1)
            s["magic"] = magic if magic <= left + EPS else None
        opp = t.get("opp")
        if opp in teams and left >= 1 and not s["clinched"] and not s["eliminated"]:
            beaten = {opp: 1}                        # the opponent took the loss
            s["win_in"] = _reach(teams, key, w + 1, drop=beaten) < spots
            s["both_in"] = (median and not s["win_in"] and left >= 2
                            and _reach(teams, key, w + 2, drop=beaten) < spots)
            s["must_win"] = _past(teams, key, w + left - 1, add={opp: 1}) >= spots
            p = t.get("win")
            if (not s["win_in"] and not s["both_in"] and p is not None and p == p
                    and float(p) >= NEAR):
                s["near"] = float(p)
        out[key] = s
    return out


def pct(p) -> str:
    """Never a flat 0% or 100% for what is merely very likely or unlikely."""
    if p is None or p != p:
        return "—"
    p = float(p)
    if 0 < p < 0.005:
        return "<1%"
    if 0.995 <= p < 1:
        return ">99%"
    return f"{round(100 * p)}%"


def label(s: dict) -> tuple:
    """(chip text, tone, note under it) or (None, None, "") for no chip."""
    note = ""
    if s["eliminated"]:
        return "Eliminated", "out", ""
    if s["top"]:
        return "Clinched #1", "lock", ""
    if s["bye"]:
        return "Clinched bye", "lock", ""
    if s["clinched"]:
        return "Clinched", "in", "no bye" if s["no_bye"] else ""
    if s["must_win"]:
        note = "a loss: out"
    if s["win_in"]:
        return "Win and in", "go", note
    if s["both_in"]:
        return "Win both and in", "go", note
    if s["near"] is not None:
        # Rounded down, never to 100%: a simulated certainty is not a proof.
        return f"A win: {pct(min(s['near'], 0.999))}", "near", note
    if s["must_win"]:
        return "Must win", "must", ""
    return None, None, ""


def check(teams: dict, status: dict) -> list:
    """Where the arithmetic and the simulations disagree - which only happens
    when they were handed different standings or schedules."""
    bad = []
    for k, s in status.items():
        t = teams[k]
        odds, win = t.get("odds"), t.get("win")
        if s["clinched"] and odds is not None and odds < 1 - EPS:
            bad.append(f"{t['name']}: clinched, but the sims say {odds:.4f}")
        if s["eliminated"] and odds is not None and odds > EPS:
            bad.append(f"{t['name']}: eliminated, but the sims say {odds:.4f}")
        if s["win_in"] and win is not None and win == win and win < 1 - EPS:
            bad.append(f"{t['name']}: win and in, but a win is {win:.4f} in the sims")
    return bad


def _names(keys: list, teams: dict) -> str:
    names = [escape(str(teams[k]["name"])) for k in keys]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def summary(teams: dict, status: dict, week: int | None = None) -> str:
    """One line: who is in, who is out, who can settle it this week - the
    section's lead, and the line a matchups page could open with."""
    order = standing(teams)

    def by(test):
        return [k for k in order if test(status[k])]
    parts = []
    locked, gone = by(lambda s: s["clinched"]), by(lambda s: s["eliminated"])
    if locked:
        parts.append(f"<b>Clinched</b>: {_names(locked, teams)}.")
    if gone:
        parts.append(f"<b>Eliminated</b>: {_names(gone, teams)}.")
    now = by(lambda s: s["win_in"] or s["both_in"])
    if now:
        parts.append(f"<b>Can clinch {f'in week {week}' if week else 'this week'}</b>: "
                     f"{_names(now, teams)}.")
    if not locked and not gone:
        open_ = by(lambda s: s["magic"] is not None)
        if open_:
            k = min(open_, key=lambda k: status[k]["magic"])
            m = status[k]["magic"]
            parts.append(f"Nobody has clinched or been knocked out yet; the closest is "
                         f"<b>{escape(str(teams[k]['name']))}</b>, {m} more "
                         f"win{'s' if m != 1 else ''} from sure.")
        else:
            parts.append("Too early for anyone to be sure: no team can yet clinch on its own "
                         "wins, even winning out.")
    return " ".join(parts)


def _record(t: dict) -> str:
    """W-L with the median game in it; a tied game is half of each."""
    return f"{_num(t['wins'])}-{_num(t['losses'])}"


def _num(v) -> str:
    v = float(v)
    return str(int(v)) if v == int(v) else f"{v:.1f}"


def _games_left(teams: dict, median: bool) -> str:
    left = {int(round(float(t["left"]))) for t in teams.values()}
    most = max(left)
    if most == 0:
        return "The regular season is over."
    lead = "Each team has" if len(left) == 1 else "Up to"
    weeks = most // 2
    how = (f" - {weeks} week{'s' if weeks != 1 else ''} of a head-to-head game and the median"
           if median and most % 2 == 0 else "")
    return f"{lead} {most} game{'s' if most != 1 else ''} left{how}."


def _odds(p, s: dict):
    """The simulated odds, held off 100% until the arithmetic says clinched
    and off 0% until it says eliminated: every run of a simulation landing
    one way is not a proof, and beside a status column it would read as one."""
    if p is None or p != p:
        return None
    p = float(p)
    if not s["clinched"]:
        p = min(p, 0.999)
    if not s["eliminated"]:
        p = max(p, 0.001)
    return p


def section(teams: dict, spots: int, bye_spots: int = 0, median: bool = False,
            week: int | None = None) -> str:
    """The Playoff Picture: every team in seed order with its record, what it
    has settled or needs, and its simulated odds; the playoff and bye lines
    drawn between the rows. Columns nobody has anything in stay off the
    table, so early in the season it is the standings, the line and the odds.
    `week` is the week being played, named in the lead when a win this week
    can settle something."""
    if not teams:
        return ""
    status = picture(teams, spots, bye_spots, median)
    order = standing(teams)
    chips = {k: label(status[k]) for k in order}
    # One column for what each team has settled or needs: its chip, or else
    # its magic number. Two columns put the odds off a 390px screen, and they
    # are mostly blank in turn - a settled team has no magic number, an open
    # one early in the season no chip. Headed Magic until a chip appears.
    any_chip = any(c[0] for c in chips.values())
    show_need = any_chip or any(status[k]["magic"] is not None for k in order)
    show_odds = any(teams[k].get("odds") is not None for k in order)

    shown = set()                     # what the legend has to explain

    def need(s: dict, chip: tuple) -> str:
        text, tone, note = chip
        if text:
            if tone == "near" and s["magic"] is not None and not note:
                note = f"magic {s['magic']}"
                shown.add("magic")
            return (f"<td><span class='cl-chip cl-{tone}'>{escape(text)}</span>"
                    + (f"<span class='cl-sub'>{escape(note)}</span>" if note else "") + "</td>")
        if s["magic"] is not None:
            shown.add("magic")
            return (f"<td class='mg'>{'Magic ' if any_chip else ''}<b>{s['magic']}</b></td>")
        if s["clinched"] or s["eliminated"]:
            return "<td></td>"
        shown.add("magic")
        return "<td class='dim'>\u2014</td>"

    rows = []
    for i, k in enumerate(order, 1):
        t, s = teams[k], status[k]
        cls = " ".join(c for c, on in (("cut", i == spots),
                                       ("bye", bool(bye_spots) and i == bye_spots),
                                       ("gone", s["eliminated"])) if on)
        cells = [f"<td class='t' title='{escape(str(t['name']), quote=True)}'>"
                 f"<span class='sd'>{i}</span>{escape(str(t['name']))}</td><td>{_record(t)}</td>"]
        if show_need:
            cells.append(need(s, chips[k]))
        if show_odds:
            cells.append(f"<td>{escape(pct(_odds(t.get('odds'), s)))}</td>")
        rows.append((f"<tr class='{cls}'>" if cls else "<tr>") + "".join(cells) + "</tr>")

    heads = ("<th>Team</th><th>W-L</th>"
             + ("<th>Status</th>" if any_chip else
                "<th title='Wins that clinch a place, whatever else happens'>Magic</th>"
                if show_need else "")
             + ("<th>Playoffs</th>" if show_odds else ""))
    lead = (f"<p>The top {spots} make the playoffs"
            + (f" and the top {bye_spots} skip the first round" if bye_spots else "")
            + f". {_games_left(teams, median)} {summary(teams, status, week)}</p>")

    notes = ["Seeded as things stand, on wins and then points for: the solid line is the "
             "playoff cut" + (", the dashed one the byes" if bye_spots else "") + "."]
    if "magic" in shown:
        notes.append("<b>Magic</b>: more wins that clinch a place whatever anyone else does "
                     "(losses by the teams chasing can bring it down too); &mdash; means the "
                     "team needs results elsewhere.")
    if any(chips[k][1] not in (None, "near") for k in order):
        notes.append("Every status but a win's odds is arithmetic, true in every finish - a "
                     "tie on wins counted against the team, since points for can't be known "
                     "ahead.")
    if any_chip:
        if any(status[k]["win_in"] or status[k]["both_in"] for k in order):
            notes.append("<b>Win and in</b>: a head-to-head win this week clinches, whatever "
                         "else happens" + ("; <b>win both</b> adds the median" if any(
                             status[k]["both_in"] for k in order) else "") + ".")
        if any(status[k]["near"] is not None for k in order):
            notes.append("<b>A win: 99%</b> is the simulations' odds with a win - likely, "
                         "not certain.")
    if show_odds:
        notes.append("<b>Playoffs</b>: the simulated chance.")
    return (CSS + lead + "<div class='table-scroll'><table class='clp'><thead><tr>" + heads
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
            + f"<p class='cl-note'>{' '.join(notes)}</p>")
