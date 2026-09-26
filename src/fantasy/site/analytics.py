"""
Analytics (docs/fantasy/analytics/): the deeper studies, rendered.

This was a grid of eight cards - a link index standing between the reader and
every page behind it, giving equal billing to a page read every week and one
read once after the draft. Two of the eight were the history and the drafts of
the league whose home page is one tab away, and they have gone there.

What is left is what "analytics" ought to mean, and it is on the page rather
than linked from it:

  * what the fixture list has been worth (fantasy.site.schedule),
  * every claim, add and trade this league has made (fantasy.site.transactions),
  * what draft picks returned against what they cost (fantasy.site.adp),
  * what injuries cost each manager (fantasy.site.injuries).

All four are years of *this* league, out of the archive on the Pi. A reader's
own league gets what Sleeper will answer for: its waivers and trades
(gordstats.my_waivers), with the rest said plainly rather than left blank.
`my_league.takeover` picks between the two before the page paints.

The one season of schedule stats shown here is the current one. Every season,
and the two matrices beside it, stay on /fantasy/schedule/ - the whole set
inline is a page nobody can scroll.

    python -m fantasy.site.analytics
"""
from fantasy import paths
from fantasy.config import FORMAL_SEASON, LEAGUE_IDS
from fantasy.site import adp, injuries, layout, schedule, transactions
from fantasy.site.draft import PICKUP_MIN_WEEKS
from gordstats import my_league, my_league_data, my_waivers
from gordstats.frontmatter import add_front_matter

#: Pages that answer one question well and do not belong inline.
LINKS = [
    ("/fantasy/power/", "Power Rankings",
     "Every roster played through the rest of the season ten thousand times: "
     "who is actually good, rather than who has had the schedule."),
    ("/fantasy/waivers/", "Your league's waivers",
     "Who works the wire in your own league, what they paid, and every claim, "
     "add and trade across its seasons."),
    ("/fantasy/sync/", "Sync a league",
     "Attach your own Sleeper league to your account, and every page here "
     "reads it instead."),
    ("/fantasy/schedule/", "Schedule Stats, every season",
     "All-play standings and the records-versus-every-schedule matrix, "
     "season by season."),
    ("/fantasy/transactions/", "Waivers & Trades, season by season",
     "Every completed move, with what the players involved did afterwards."),
    ("/fantasy/draft/", "Draft Analytics",
     "The board, what each pick returned against what it cost, and the habits "
     "that show up across every draft this league has held."),
    ("/profile/", "Your profile",
     "Your account, the leagues you have connected and the teams you follow."),
]


def injury_section() -> str:
    """The All-Time Draft Injury Impacts block (note, tables, by-season chart)."""
    img, table, top = injuries.all_time_missed()
    premium = injuries.PREMIUM_ROUNDS
    top_pct = round((1 - injuries.STARTER_PCTL) * 100)
    min_games = injuries.MIN_SAMPLE_GAMES
    top_html = "" if top is None else f"""<h3>Most Impactful Injuries</h3>
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
<h3>Injury Breakdown by Season</h3>
{img}"""


def schedule_section() -> str:
    """What this season's fixture list has been worth."""
    season = next(iter(LEAGUE_IDS))          # newest first
    label = FORMAL_SEASON.get(season, season)
    return (f"<p>{label}. <strong>SOS</strong> is the difficulty of the schedule, "
            "<strong>SOV</strong> the combined win-loss record of the teams beaten, and "
            "<strong>Exp Wins</strong> what a Pythagorean expectation on points for and "
            "against says the record should have been. Sorted by SOS.</p>"
            f'<div class="table-scroll">{schedule.schedule_metrics(season).to_html()}</div>'
            '<p>Every season, the all-play standings and the records-versus-every-schedule '
            f'matrix: {layout.internal_link("/fantasy/schedule/", "Schedule Stats")}.</p>')


def transactions_section() -> str:
    """Every manager's activity, all seasons at once."""
    names = transactions._player_names()
    return (transactions._all_time_view(names, list(LEAGUE_IDS))
            + "<p>Season by season, with what the players involved did afterwards: "
            f'{layout.internal_link("/fantasy/transactions/", "Waivers & Trades")}.</p>')


def mine_section() -> str:
    """A reader's own league. Sleeper answers for its transactions; the rest of
    this page is years of one league's archive and has no equivalent."""
    return ("<div id='an-mine' hidden>"
            "<h2>Waivers &amp; trades</h2>" + my_waivers.section()
            + "<p class='hub-note'>Schedule strength, draft values and injury "
              "impacts are built from this site's own league archive - seasons of "
              "weekly scores, draft boards and injury reports that Sleeper does not "
              "hand back. They are on this page for that league only. Your league's "
              "history and drafts are on "
            + layout.internal_link("/fantasy/index.html", "League Home") + ".</p>"
            "</div>")


def built_section() -> str:
    sections = [
        ("schedule", "What the Schedule Was Worth", schedule_section()),
        ("transactions", "Waivers &amp; Trades", transactions_section()),
        ("adp", "Draft Values &amp; Busts", adp.all_time_section()),
        ("injuries", "Injury Impacts", injury_section()),
    ]
    nav = layout.section_nav([(a, t.replace("&amp;", "&")) for a, t, _ in sections])
    cards = "".join(
        f'<li><a href="{url}"><strong>{title}</strong><span>{blurb}</span></a></li>'
        for url, title, blurb in LINKS)
    return ("<div id='an-built'>"
            "<p>Years of this league, out of the archive. The pages read every "
            "week are in the bar above.</p>"
            + nav
            + "".join(f'<h2 id="{a}">{t}</h2>{html}' for a, t, html in sections)
            + f'<h2 id="more">Elsewhere</h2><ul class="an-links">{cards}</ul>'
            "</div>")


CSS = """<style>
.an-links{list-style:none;padding:0;margin:8px 0 18px;display:grid;gap:10px;
  grid-template-columns:repeat(auto-fit,minmax(min(280px,100%),1fr))}
.an-links a{display:block;border:1px solid #e2e8f0;border-radius:10px;background:#fff;
  padding:12px 14px;text-decoration:none;color:inherit}
.an-links a:hover{border-color:#cbd5e1}
.an-links strong{display:block;font-size:14.5px;color:#0f172a;margin:0 0 3px}
.an-links span{display:block;font-size:12.5px;color:#64748b;line-height:1.45}
.hub-note{font-size:13px;color:#475569;line-height:1.55;margin:10px 0 0}
@media (prefers-color-scheme: dark){
  .an-links a{background:#16203a;border-color:#2b3852}
  .an-links strong{color:#f1f5f9}
  .an-links span,.hub-note{color:#aab7c9}
}
</style>"""


def body() -> str:
    return (CSS + my_league.bar()
            + mine_section() + built_section()
            + my_league.takeover("an-mine", "an-built")
            + my_league_data.JS + my_league.JS + my_waivers.JS)


def generate():
    out = paths.WEB_ANALYTICS
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(add_front_matter(layout.HEAD + body(), "Fantasy Analytics",
                                    "Schedule, waivers, draft values and injuries"),
                   encoding="utf-8")
    print(f"Wrote Fantasy Analytics -> {out}")


if __name__ == "__main__":
    generate()
