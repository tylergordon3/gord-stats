"""
The week in review for a fantasy league, and how much of each roster's best
lineup its manager actually started - shared by both fantasy sections:

    fantasy.site.recap   the NFL league (Sleeper)   -> /fantasy/recap/
    cfb.site.recap       the college league (Yahoo) -> /cfb/recap/

Each section turns its own week archive into a `Week` - the teams, the games,
every roster's starters and bench with what each player scored, and the ids of
the best lineup that roster could have started. Everything from there (the
awards, lineup accuracy, the page) is here, so the two leagues read alike.

Lineup accuracy is points started over the most the roster could have scored:
the best lineup by what each player actually scored, by the rule the matchups
pages already use for "best lineup" by projection (dedicated slots first, then
the flex), with injured-reserve players unavailable. Over a season it is total
points started over total maximum, so a big week counts for more than a quiet
one - the way Sleeper's own "max points" reads.

A page is written once a week is final and rebuilt with the section after
that, so a stat correction reaches it; each week has its own URL, which is the
one worth sending to the group chat (its preview line is the week's headline).
"""
import json
import statistics
from dataclasses import dataclass, field
from html import escape


@dataclass
class Player:
    id: str
    name: str
    pos: str
    pts: float
    slot: str = ""                  # the slot he started in; "" on the bench


@dataclass
class Side:
    key: str
    points: float                   # the official score
    starters: list                  # [Player], each with its slot
    bench: list                     # [Player] who could have started: IR left out
    best: set                       # ids of the best lineup by points scored
    proj: float | None = None       # GordStats before kickoff, for these starters

    @property
    def started(self) -> float:
        return round(sum(p.pts for p in self.starters), 2)

    @property
    def max(self) -> float:
        best = sum(p.pts for p in self.starters + self.bench if p.id in self.best)
        # Never under what was started: a player started out of position (or
        # a slot rule this side does not model) cannot make a lineup "better
        # than the best".
        return round(max(best, self.started), 2)

    @property
    def left(self) -> float:
        return round(self.max - self.started, 2)

    @property
    def pct(self) -> float:
        return self.started / self.max if self.max > 0 else 1.0


@dataclass
class Team:
    name: str
    manager: str = ""
    avatar: str = ""


@dataclass
class Pickup:
    key: str                        # the team that added him
    player: Player
    started: bool


@dataclass
class Week:
    number: int
    teams: dict                     # {key: Team}
    games: list                     # [(key, key)] head to head
    sides: dict                     # {key: Side}
    median: bool = False            # a second game against the week's median
    flex: dict = field(default_factory=dict)    # {flex slot: positions it takes}
    pickups: list = field(default_factory=list)  # [Pickup] added for this week
    power: dict = field(default_factory=dict)    # {key: (rank before, rank after)}

    def median_score(self) -> float:
        return statistics.median(s.points for s in self.sides.values())


@dataclass
class Award:
    label: str
    key: str                        # the team it goes to
    stat: str                       # the number, formatted
    detail: str = ""                # one line of why, already HTML
    tone: str = ""                  # "good" / "bad": the card's accent


def num(x: float) -> str:
    """A score as the league shows it: two places, no trailing zeros."""
    s = f"{x:.2f}"
    return s.rstrip("0").rstrip(".")


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def accepts(slot: str, pos: str, flex: dict) -> bool:
    return slot == pos or pos in flex.get(slot, ())


def swap(side: Side, flex: dict):
    """The one lineup call that cost the most: a player left on the bench who
    belonged in the best lineup, over a starter who did not - and who could
    have taken that starter's slot, so a benched quarterback is never set
    against a receiver. (benched, started) or None."""
    sat = [p for p in side.bench if p.id in side.best]
    out = [p for p in side.starters if p.id not in side.best]
    found = None
    for b in sat:
        for s in out:
            if accepts(s.slot, b.pos, flex) and b.pts > s.pts:
                if found is None or b.pts - s.pts > found[0]:
                    found = (b.pts - s.pts, b, s)
    return (found[1], found[2]) if found else None


def _who(p: Player) -> str:
    """A player as an award names him: "Name, POS" - a defense is its school
    or team already, and "PIT D/ST, DEF" says it twice."""
    return escape(p.name) if p.pos in ("DEF", "") else f"{escape(p.name)}, {p.pos}"


def _swap_line(pair) -> str:
    if not pair:
        return ""
    b, s = pair
    return (f"Started {escape(s.name)} ({num(s.pts)}) over "
            f"{escape(b.name)} ({num(b.pts)})")


def results(week: Week) -> dict:
    """{key: (opponent, margin)} - margin positive for the winner."""
    out = {}
    for a, b in week.games:
        m = week.sides[a].points - week.sides[b].points
        out[a], out[b] = (b, m), (a, -m)
    return out


def awards(week: Week) -> list:
    """The week's awards, most talked-about first. An award with nobody to
    give it to (no projections archived, no pickup started) is left out."""
    S, T = week.sides, week.teams
    res = results(week)
    order = sorted(S.values(), key=lambda s: s.points, reverse=True)
    n = len(order)

    def name(k):
        return escape(T[k].name)

    def top_starter(s):
        return max(s.starters, key=lambda p: p.pts, default=None)

    out = []
    top, low = order[0], order[-1]
    lead = top_starter(top)
    out.append(Award("High score", top.key, num(top.points),
                     f"Led by {escape(lead.name)}, {num(lead.pts)}" if lead else "", "good"))
    out.append(Award("Low score", low.key, num(low.points),
                     f"Left {num(low.left)} on the bench" if low.left >= 5 else
                     f"{n - 1} teams scored more", "bad"))

    decided = [(k, o, m) for k, (o, m) in res.items() if m > 0]
    if decided:
        k, o, m = max(decided, key=lambda x: x[2])
        out.append(Award("Blowout", k, f"by {num(m)}",
                         f"Over {name(o)}, {num(S[k].points)}&ndash;{num(S[o].points)}", "good"))
        k, o, m = min(decided, key=lambda x: x[2])
        out.append(Award("Nail-biter", k, f"by {num(m)}",
                         f"Over {name(o)}, {num(S[k].points)}&ndash;{num(S[o].points)}"))
        k, o, m = min(decided, key=lambda x: S[x[0]].points)
        more = sum(1 for s in order if s.points > S[k].points)
        out.append(Award("Luckiest win", k, num(S[k].points),
                         f"{more} team{'s' if more != 1 else ''} scored more &mdash; "
                         f"just not {name(o)}", "good"))
        loser = max((o for _, o, _ in decided), key=lambda o: S[o].points)
        fewer = sum(1 for s in order if s.points < S[loser].points)
        out.append(Award("Toughest loss", loser, num(S[loser].points),
                         f"Would have beaten {fewer} of the other {n - 1} teams", "bad"))

    # Lost a game the bench would have won: the loser's best lineup beats
    # what the winner actually scored.
    cost = [(k, o, S[k].max - S[o].points) for k, (o, m) in res.items()
            if m < 0 and S[k].max > S[o].points]
    if cost:
        k, o, by = max(cost, key=lambda x: x[2])
        out.append(Award("Cost them the game", k, f"lost by {num(-res[k][1])}",
                         f"Best lineup: {num(S[k].max)}. " + _swap_line(swap(S[k], week.flex)),
                         "bad"))

    by_pct = sorted(S.values(), key=lambda s: (s.pct, s.points), reverse=True)
    best = by_pct[0]
    perfect = [s.key for s in by_pct if s.left < 0.005]
    others = [name(k) for k in perfect if k != best.key]
    out.append(Award("Best lineup", best.key, f"{best.pct * 100:.1f}%",
                     ("The best possible lineup" + (f" &mdash; so did {', '.join(others)}"
                                                    if others else ""))
                     if best.key in perfect else f"{num(best.left)} short of the best possible",
                     "good"))
    worst = max(S.values(), key=lambda s: s.left)
    if worst.left > 0:
        out.append(Award("Most left on the bench", worst.key, num(worst.left),
                         _swap_line(swap(worst, week.flex)) or
                         f"{worst.pct * 100:.1f}% of the best lineup", "bad"))

    projected = [s for s in S.values() if s.proj]
    if len(projected) == n:
        up = max(projected, key=lambda s: s.points - s.proj)
        down = min(projected, key=lambda s: s.points - s.proj)
        if up.points > up.proj:
            out.append(Award("Beat the projection", up.key, f"+{num(up.points - up.proj)}",
                             f"{num(up.points)} against {num(up.proj)} projected", "good"))
        if down.points < down.proj:
            out.append(Award("Missed the projection", down.key,
                             f"&minus;{num(down.proj - down.points)}",
                             f"{num(down.points)} against {num(down.proj)} projected", "bad"))

    starters = [(s.key, p) for s in S.values() for p in s.starters]
    if starters:
        k, p = max(starters, key=lambda x: x[1].pts)
        out.append(Award("Player of the week", k, num(p.pts), _who(p), "good"))
    benched = [(s.key, p) for s in S.values() for p in s.bench]
    if benched:
        k, p = max(benched, key=lambda x: x[1].pts)
        if p.pts > 0:
            out.append(Award("Bench star", k, num(p.pts),
                             f"{_who(p)}, never left the bench"))
    started = [pk for pk in week.pickups if pk.started]
    if started:
        pk = max(started, key=lambda x: x.player.pts)
        out.append(Award("Pickup of the week", pk.key, num(pk.player.pts),
                         f"{_who(pk.player)}, added this week", "good"))

    moves = {k: before - after for k, (before, after) in week.power.items()}
    if moves:
        k = max(moves, key=moves.get)
        if moves[k] > 0:
            out.append(Award("Power riser", k, f"up {moves[k]}",
                             f"To {ordinal(week.power[k][1])} in the power rankings", "good"))
        k = min(moves, key=moves.get)
        if moves[k] < 0:
            out.append(Award("Power faller", k, f"down {-moves[k]}",
                             f"To {ordinal(week.power[k][1])} in the power rankings", "bad"))
    return out


def headline(week: Week) -> str:
    """One plain sentence for the page's lead and its link preview."""
    S, T = week.sides, week.teams
    top = max(S.values(), key=lambda s: s.points)
    parts = [f"{T[top.key].name} top-scored with {num(top.points)}"]
    worst = max(S.values(), key=lambda s: s.left)
    if worst.left >= 1:
        parts.append(f"{T[worst.key].name} left {num(worst.left)} on the bench")
    res = results(week)
    lost = [k for k, (o, m) in res.items() if m < 0 and S[k].max > S[o].points]
    if lost:
        parts.append(f"{len(lost)} team{' was' if len(lost) == 1 else 's were'} "
                     "beaten by their own bench")
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Week {week.number}: {text}."


def season(weeks: list) -> list:
    """Lineup accuracy to date: [{key, started, max, left, pct, perfect, weeks}],
    best first."""
    rows = {}
    for w in weeks:
        for k, s in w.sides.items():
            r = rows.setdefault(k, {"key": k, "started": 0.0, "max": 0.0,
                                    "perfect": 0, "weeks": 0})
            r["started"] += s.started
            r["max"] += s.max
            r["weeks"] += 1
            r["perfect"] += s.left < 0.005
    for r in rows.values():
        r["pct"] = r["started"] / r["max"] if r["max"] > 0 else 1.0
        r["left"] = round(r["max"] - r["started"], 2)
    return sorted(rows.values(), key=lambda r: (-r["pct"], r["key"]))


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #

CSS = """<style>
.rc-lead{font-size:16px;line-height:1.5;margin:0 0 12px;font-weight:600}
.rc-weeks{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 18px}
.rc-weeks a,.rc-weeks span{display:inline-block;min-width:36px;padding:6px 10px;border-radius:8px;
  border:1px solid #cbd5e1;text-align:center;font-size:13px;font-weight:700;text-decoration:none;color:#334155}
.rc-weeks span{background:#1B2340;border-color:#1B2340;color:#fff}
.rc h2{font-size:18px;margin:22px 0 10px}
/* The theme frames every image (padding, a ring): not a 22px avatar. */
.rc .rc-av{width:22px;height:22px;border-radius:50%;flex:none;object-fit:cover;background:#e2e8f0;
  margin:0;padding:0;border:0;box-shadow:none;max-width:none;display:inline-block}
.rc-games{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.rc-game{border:1px solid #e2e8f0;border-radius:10px;padding:8px 11px;background:#fff}
.rc-side{display:flex;align-items:center;gap:8px;font-size:14px;padding:3px 0}
.rc-side .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#475569}
.rc-side .sc{font-variant-numeric:tabular-nums;color:#475569}
.rc-side.w .nm,.rc-side.w .sc{color:#0f172a;font-weight:700}
.rc-med{font-size:11px;font-weight:700;border-radius:4px;padding:0 4px;min-width:14px;text-align:center}
.rc-med.w{background:#dcfce7;color:#166534}.rc-med.l{background:#fee2e2;color:#991b1b}
.rc-meta{font-size:12px;color:#64748b;margin-top:2px}
.rc-awards{display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
.rc-award{border:1px solid #e2e8f0;border-left:4px solid #94a3b8;border-radius:10px;padding:9px 12px;background:#fff}
.rc-award.good{border-left-color:#16a34a}.rc-award.bad{border-left-color:#dc2626}
.rc-award .lb{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#64748b}
.rc-award .row{display:flex;align-items:center;gap:8px;margin-top:4px}
.rc-award .tm{flex:1;min-width:0;font-weight:700;font-size:14.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rc-award .st{font-weight:800;font-size:16px;font-variant-numeric:tabular-nums;white-space:nowrap}
.rc-award .dt{font-size:12.5px;color:#475569;margin-top:3px;line-height:1.4}
.rc-acc{width:100%;border-collapse:collapse;font-size:13.5px}
.rc-acc th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#475569;background:#eef2f7;
  padding:6px 8px;text-align:right;white-space:nowrap}
.rc-acc th:first-child,.rc-acc td:first-child{text-align:left}
.rc-acc td{padding:6px 8px;border-top:1px solid #eef2f7;text-align:right;font-variant-numeric:tabular-nums;
  white-space:nowrap;vertical-align:middle}
/* Flex inside the cell, never on it: a flex td leaves the table's row layout. */
.rc-acc .tmw{display:flex;align-items:center;gap:7px;max-width:210px}
.rc-acc .tmw span{overflow:hidden;text-overflow:ellipsis}
.rc-acc .q5{background:#bbf7d0}.rc-acc .q4{background:#dcfce7}.rc-acc .q3{background:#fef9c3}
.rc-acc .q2{background:#fde2c8}.rc-acc .q1{background:#fecaca}
.rc-wrap{overflow-x:auto}
.rc-note{font-size:12.5px;color:#64748b;line-height:1.5;margin:8px 0 0}
@media (max-width:600px){
  .rc-acc .tmw{max-width:118px}
  .rc-acc th,.rc-acc td{padding:6px 5px}
  .rc-acc .pf{display:none}
}
@media (prefers-color-scheme: dark){
  .rc-weeks a{border-color:#3b4a66;color:#dde5ef}
  .rc-weeks span{background:#34d399;border-color:#34d399;color:#0b1220}
  .rc-game,.rc-award{background:#16203a;border-color:#2b3852}
  .rc-award.good{border-left-color:#34d399}.rc-award.bad{border-left-color:#f87171}
  .rc-side .nm,.rc-side .sc,.rc-award .dt{color:#aab7c9}
  .rc-side.w .nm,.rc-side.w .sc{color:#f1f5f9}
  .rc-meta,.rc-award .lb,.rc-note{color:#94a3b8}
  .rc-med.w{background:#14532d;color:#bbf7d0}.rc-med.l{background:#7f1d1d;color:#fecaca}
  .rc-acc th{background:#223052;color:#dde5ef}
  .rc-acc td{border-top-color:#2b3852}
  .rc-acc .q5{background:#166534}.rc-acc .q4{background:#14532d}.rc-acc .q3{background:#4d4415}
  .rc-acc .q2{background:#5a3417}.rc-acc .q1{background:#6b2121}
}
</style>"""


def _avatar(t: Team) -> str:
    if not t.avatar:
        return '<span class="rc-av"></span>'
    return (f'<img class="rc-av" src="{escape(t.avatar, quote=True)}" alt="" width="22" '
            'height="22" loading="lazy">')


def _q(pct: float) -> str:
    """A lineup-accuracy cell's shade: the bands most weeks actually fall in."""
    return ("q5" if pct >= 0.995 else "q4" if pct >= 0.95 else "q3" if pct >= 0.9
            else "q2" if pct >= 0.85 else "q1")


def _games(week: Week) -> str:
    S, T = week.sides, week.teams
    med = week.median_score() if week.median else None
    out = []
    for a, b in week.games:
        sa, sb = S[a], S[b]

        def side(s, won):
            chip = ""
            if med is not None:
                chip = (f'<span class="rc-med {"w" if s.points > med else "l"}" '
                        f'title="Against the median, {num(med)}">'
                        f'{"W" if s.points > med else "L"}</span>')
            return (f'<div class="rc-side{" w" if won else ""}">{_avatar(T[s.key])}'
                    f'<span class="nm">{escape(T[s.key].name)}</span>{chip}'
                    f'<span class="sc">{num(s.points)}</span></div>')
        m = abs(sa.points - sb.points)
        out.append('<div class="rc-game">' + side(sa, sa.points > sb.points)
                   + side(sb, sb.points > sa.points)
                   + f'<div class="rc-meta">by {num(m)} &middot; best lineups '
                   f'{num(sa.max)} / {num(sb.max)}</div></div>')
    note = (f'<p class="rc-note">W / L beside a score is its second game, against the '
            f'week\'s median ({num(med)}).</p>' if med is not None else "")
    return '<div class="rc-games">' + "".join(out) + "</div>" + note


def _awards(week: Week) -> str:
    T = week.teams
    cards = []
    for a in awards(week):
        cards.append(f'<div class="rc-award {a.tone}"><div class="lb">{a.label}</div>'
                     f'<div class="row">{_avatar(T[a.key])}<span class="tm">'
                     f'{escape(T[a.key].name)}</span><span class="st">{a.stat}</span></div>'
                     + (f'<div class="dt">{a.detail}</div>' if a.detail else "") + "</div>")
    return '<div class="rc-awards">' + "".join(cards) + "</div>"


def _accuracy(week: Week, to_date: list) -> str:
    T, S = week.teams, week.sides
    rows = []
    for r in to_date:
        s = S.get(r["key"])
        wk = (f'<td class="{_q(s.pct)}">{s.pct * 100:.1f}%</td><td>{num(s.left)}</td>'
              if s else "<td>&ndash;</td><td>&ndash;</td>")
        rows.append(f'<tr><td><span class="tmw">{_avatar(T[r["key"]])}<span>'
                    f'{escape(T[r["key"]].name)}</span></span></td>{wk}'
                    f'<td class="{_q(r["pct"])}">{r["pct"] * 100:.1f}%</td>'
                    f'<td>{num(r["left"])}</td><td class="pf">{r["perfect"]}</td></tr>')
    return ('<div class="rc-wrap"><table class="rc-acc"><thead><tr><th>Team</th>'
            f'<th>Wk {week.number}</th><th>Left</th><th>Season</th><th>Left</th>'
            '<th class="pf" title="Weeks with the best possible lineup">Perfect</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div>"
            '<p class="rc-note">Share of the best possible lineup each team started: points '
            'started over the most its roster could have scored that week, by what every '
            'player actually scored (injured reserve left out). <b>Left</b> is the '
            'difference - points left on the bench. The season figure is total points over '
            'total maximum.</p>')


def week_nav(numbers: list, current: int, base: str) -> str:
    chips = [f"<span>{n}</span>" if n == current else f'<a href="{base}week-{n}/">{n}</a>'
             for n in numbers]
    return '<nav class="rc-weeks" aria-label="Week">' + "".join(chips) + "</nav>"


def page(week: Week, weeks: list, base: str, links: str = "") -> str:
    """One week's recap: lead, scores, awards, lineup accuracy. `weeks` is
    every final week of the season (for the week chips and the season
    column); `links` goes under the lead - the section's own pointers."""
    to_date = season([w for w in weeks if w.number <= week.number])
    return (CSS + '<div class="rc">'
            + f'<p class="rc-lead">{escape(headline(week))}</p>' + links
            + week_nav([w.number for w in weeks], week.number, base)
            + "<h2>Scores</h2>" + _games(week)
            + "<h2>Awards</h2>" + _awards(week)
            + "<h2>Lineup accuracy</h2>" + _accuracy(week, to_date)
            + "</div>")


# --------------------------------------------------------------------------- #
# The pointer to it, on League Home and Matchups
# --------------------------------------------------------------------------- #

TEASER_CSS = """<style>
.rc-teaser{display:grid;gap:2px;margin:0 0 14px;padding:10px 13px;border:1px solid #e2e8f0;
  border-left:4px solid #EE8434;border-radius:10px;background:#fff;text-decoration:none;color:inherit}
.rc-teaser .lb{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#64748b}
.rc-teaser .tx{font-size:14.5px;font-weight:600;line-height:1.4;color:#0f172a}
.rc-teaser .go{font-size:13px;font-weight:700;color:#1d4ed8}
@media (prefers-color-scheme: dark){
  .rc-teaser{background:#16203a;border-color:#2b3852;border-left-color:#EE8434}
  .rc-teaser .tx{color:#f1f5f9}.rc-teaser .lb{color:#94a3b8}.rc-teaser .go{color:#93c5fd}
}
</style>"""


def write_latest(out_dir, week) -> None:
    """What the teaser needs, beside the pages; None clears it (no final
    week yet - a new season must not point at last year's)."""
    path = out_dir / "latest.json"
    if week is None:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps({"week": week.number, "headline": headline(week)}),
                    encoding="utf-8")


def teaser(out_dir, base: str) -> str:
    """A card for the newest recap: its headline, and the way in."""
    try:
        d = json.loads((out_dir / "latest.json").read_text())
    except (OSError, ValueError):
        return ""
    text = str(d["headline"]).split(": ", 1)[-1]
    return (TEASER_CSS + f'<a class="rc-teaser" href="{base}week-{int(d["week"])}/">'
            f'<span class="lb">Week {int(d["week"])} recap</span>'
            f'<span class="tx">{escape(text)}</span>'
            '<span class="go">Awards and lineup accuracy &rarr;</span></a>')
