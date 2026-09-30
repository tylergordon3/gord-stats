"""
The league's records: League Home's finding cards, and the injury study's page.

The NFL fantasy sub-nav was Home · Matchups · Team · Usage · Analytics, and
Analytics was two things filed together: the power rankings, read every week,
and years of this league's archive - what the schedule was worth, waivers and
trades, draft values, injuries - four long tables inline, 7.4 phone screens,
with the power rankings in a link list at the bottom (2026-09-29). The tab is
Power now, and the archive is here: a card each on League Home, leading with
what the page behind it found (gordstats.hub).

    /fantasy/schedule/       what the schedule was worth, every season
    /fantasy/transactions/   waivers and trades, season by season
    /fantasy/draft/          draft values and busts, and the boards
    /fantasy/injuries/       what injuries cost each manager (this page)

A reader's own league gets its history, drafts and waivers - what Sleeper will
answer for - in the same cards, drawn from the league on screen.

    python -m fantasy.site.records     # writes /fantasy/injuries/
"""
import re
import shutil

import pandas as pd

from fantasy import paths
from fantasy.config import FORMAL_SEASON, LEAGUE_IDS, ROSTER_NAMES
from fantasy.site import adp, injuries, layout, schedule, transactions
from fantasy.site.draft import PICKUP_MIN_WEEKS
from gordstats import hub, schedule_luck
from gordstats.recap import ordinal
from gordstats.frontmatter import add_front_matter

INJURIES_OUT = paths.WEB_FANTASY_DIR / "injuries" / "index.html"
# The Analytics page this replaced; removed on the Pi as the new page is
# written, so the 301 in docs/_redirects is what answers its address.
OLD_ANALYTICS = paths.WEB_FANTASY_DIR / "analytics"


def _quiet(fn):
    """A finding is a nicety: if working it out fails, the card shows its
    description instead, and League Home still builds."""
    try:
        return fn()
    except Exception as exc:                                # noqa: BLE001
        print(f"  ! records finding {fn.__name__}: {type(exc).__name__}: {exc}")
        return ""


def _spaced(name: str) -> str:
    """The injury archive keeps names run together ("AnthonyRichardson")."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name))


def _year(season: str) -> str:
    return str(season)[:4]


def schedule_finding() -> str:
    """Whom the schedule has cost most this season (gordstats.schedule_luck);
    before anybody is a real win down, the luckiest record against its
    Pythagorean expectation, or the toughest schedule by opponents' records."""
    season = next(iter(LEAGUE_IDS))                         # newest first
    got = schedule_luck.finding(*schedule.difficulty(season), when=" this season")
    if got:
        return got
    table = schedule.schedule_metrics(season).data
    best, gap = None, 0.0
    for _, r in table.iterrows():
        m = re.match(r"([\d.]+) \((\d+)\)", str(r["Exp W (Actual)"]))
        if m and int(m.group(2)) - float(m.group(1)) > gap:
            best, gap = r, int(m.group(2)) - float(m.group(1))
    if best is not None and gap >= 0.5:
        exp, won = re.match(r"([\d.]+) \((\d+)\)", best["Exp W (Actual)"]).groups()
        return (f"Luckiest this season: {best['Team']}, {won} wins where its "
                f"points earned {float(exp):.1f}")
    top = table.sort_values("SOS", ascending=False).iloc[0]
    return f"Toughest schedule this season: {top['Team']}"


def transactions_finding() -> str:
    seasons = list(LEAGUE_IDS)
    total = pd.concat([transactions.activity(transactions._load_tx(s)) for s in seasons])
    total = total.groupby("Manager").sum().sort_values(["Total Adds", "Waiver Claims"],
                                                       ascending=False)
    top = total.iloc[0]
    return (f"{top.name} works the wire hardest: {int(top['Total Adds'])} adds "
            f"in {len(seasons)} seasons")


def draft_finding() -> str:
    best = adp._all_seasons().sort_values("vsFinish", ascending=False).iloc[0]
    return (f"Best pick ever: {best['Player']} ({best['Manager']}, {_year(best['Season'])}), "
            f"taken {ordinal(int(best['overall_pick']))}, finished "
            f"{ordinal(int(best['final_rank']))}")


def injury_finding() -> str:
    detail = injuries._load_detail()
    hurt = detail[detail["Games Missed"] > 0].sort_values("Est. Pts Lost", ascending=False)
    top = hurt.iloc[0]
    manager = ROSTER_NAMES.get(int(top["roster_id"]), top.get("Owner", ""))
    return (f"Costliest injury: {_spaced(top['Name'])} ({manager}, {_year(top['season'])}), "
            f"{int(top['Games Missed'])} games, about {int(round(top['Est. Pts Lost']))} points")


def built_cards() -> str:
    """The site league's records, for League Home."""
    return hub.cards([
        ("/fantasy/schedule/", "What the schedule was worth", _quiet(schedule_finding),
         "Schedule difficulty - opponents' strength and timing - all-play records and every "
         "schedule swapped, each season"),
        ("/fantasy/transactions/", "Waivers & trades", _quiet(transactions_finding),
         "Every claim, add and trade, and what the players did afterwards"),
        ("/fantasy/draft/", "Draft values & busts", _quiet(draft_finding),
         "Each draft's board, what every pick returned, and each manager's habits"),
        ("/fantasy/injuries/", "Injury impacts", _quiet(injury_finding),
         "Games and points each manager lost to injuries, every season"),
    ]) + _elsewhere()


def mine_cards() -> str:
    """A reader's own league: what Sleeper will answer for. The findings are
    worked out in the browser on those pages, so these lead with what each
    holds."""
    return hub.cards([
        ("/fantasy/history/", "League history", "",
         "Champions, every season's table and the head-to-head grid"),
        ("/fantasy/draft-review/", "Draft review", "",
         "Every draft, and what each pick returned against where it went"),
        ("/fantasy/waivers/", "Waivers & trades", "",
         "Who works the wire, what they paid, and every trade"),
    ]) + _elsewhere()


def _elsewhere() -> str:
    return ("<p class='fc-note'>Your account and the leagues you follow: "
            "<a href='/profile/'>Profile</a> &middot; "
            "<a href='/fantasy/sync/'>Sync a league</a>.</p>")


# --------------------------------------------------------------------------- #
# /fantasy/injuries/ - the study that only ever lived inline on Analytics
# --------------------------------------------------------------------------- #

def injury_section() -> str:
    """The All-Time Draft Injury Impacts block (note, tables, by-season chart)."""
    img, table, top = injuries.all_time_missed()
    premium = injuries.PREMIUM_ROUNDS
    top_pct = round((1 - injuries.STARTER_PCTL) * 100)
    min_games = injuries.MIN_SAMPLE_GAMES
    top_html = "" if top is None else f"""<h2>Most Impactful Injuries</h2>
<p>The single most damaging player absences across all seasons, ranked by estimated points lost.
<strong>Drafted</strong> is where the manager got the player: the draft slot (round.pick), or the
week a pickup was added.</p>
<div class="table-scroll">
{top.to_html()}
</div>"""
    return f"""<p>Eligible players: drafted by a team (accountable all {injuries.REG_WEEKS} weeks), plus
    waiver / free-agent pickups held at least {PICKUP_MIN_WEEKS} weeks — a pickup only answers for games
    missed while actually on the roster (add week until dropped or traded).<br>
    Not eligible: short-term streamers, and pickups of players drafted that season
    (their missed games are already charged to the drafter).</p>
<p>Not all missed games hurt equally, so each injury is also weighted by how much the player mattered:<br>
<strong>High-Impact Games Missed</strong> — games missed by players drafted in the first {premium} rounds
or scoring at weekly-starter pace: top {top_pct}% <em>median</em> weekly points among drafted players at
their position that season, with at least {min_games} games played (so a couple of spike weeks
don't count as starter production).<br>
<strong>Est. Pts Lost</strong> — games missed &times; the player's median weekly score, so losing a stud
costs far more than losing a bench stash.</p>
<div class="table-scroll">
{table.to_html()}
</div>
{top_html}
<h2>Injury Breakdown by Season</h2>
{img}"""


def generate():
    INJURIES_OUT.parent.mkdir(parents=True, exist_ok=True)
    seasons = sorted(FORMAL_SEASON.get(s, s) for s in LEAGUE_IDS)
    INJURIES_OUT.write_text(add_front_matter(
        layout.HEAD + injury_section(), "Injury Impacts",
        f"What injuries cost each manager, {seasons[0]} to {seasons[-1]}",
        description="Games and points each manager in the league has lost to injuries, "
                    "every season."), encoding="utf-8")
    print(f"Wrote Injury Impacts -> {INJURIES_OUT}")
    if OLD_ANALYTICS.exists():
        shutil.rmtree(OLD_ANALYTICS)
        print(f"Removed the old Analytics page ({OLD_ANALYTICS}); _redirects answers it")


if __name__ == "__main__":
    generate()
