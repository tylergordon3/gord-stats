"""
What's new: the site's changelog, newest first.

Home carries the latest few as a "What's new" card (home_card(), placed by
cbb.render.render_home under the reader's My teams card) and /changelog/ lists them all (generate(), built in
the daily run's render-home block).

The list is written by hand, in readers' words: what they can now see or do,
not how it was built. One line an entry, a link to where it is when there is
one place. When a feature ships, add it at the top in the same commit.

It is a Python list rather than a YAML file because the Pi's runtime carries
no YAML parser (see render_home._countdown_targets), and a list here is
checked by the tests the moment it is edited.

    python -m gordstats.changelog
"""
from datetime import date
from html import escape

from gordstats import paths
from gordstats.frontmatter import add_front_matter

OUT = paths.DOCS / "changelog" / "index.html"
HOME_SHOWN = 3

# (date, title, one line, link or None) - newest first.
ENTRIES = [
    ("2026-10-02", "Back from injury, a little lower",
     "A player's first games back are projected below his usual rate - about 8% after one "
     "missed game, 17% then 12% after a longer absence - as returning players have scored "
     "since 2019. In the power rankings, trades and your team page.", "/fantasy/power/"),
    ("2026-10-02", "Faster pages on a phone",
     "The CFB schedule opens in half the time, the usage tables are half the size, and the "
     "fantasy pages share their code, so after the first one each loads about half as much.",
     "/cfb/schedule/"),
    ("2026-10-02", "Injury news for more players",
     "The link beside an injury pill now comes from four injury experts and the national "
     "insiders - PT, Dr or News - and only when the post is about the injury.",
     "/fantasy/roster/"),
    ("2026-10-02", "Playoff odds over the season",
     "Both fantasy leagues' Power pages chart every team's playoff and title odds week by week, "
     "with your team picked out.", "/fantasy/power/"),
    ("2026-10-02", "Tweets of the week",
     "The funniest college football and NFL posts on X, sent in by readers and voted up by "
     "you - on Home, with a page of their own.", "/tweets/"),
    ("2026-10-02", "Pages that stay put",
     "Nothing jumps down the page while it loads: League Home, Matchups, Team, the trade "
     "analyzer and Home hold their places as the live parts draw.", None),
    ("2026-10-02", "Faster, steadier pages",
     "Matchups pages a third the size; no sideways scrolling on a phone; logos you can see in "
     "dark mode; the fantasy playoff bracket reseeds the way Sleeper does.", None),
    ("2026-10-01", "Injuries, beyond the tag",
     "ESPN's return dates, the teammates who pick up his work, and Questionable or Doubtful "
     "priced by role and the last practice - with physical therapists' takes linked.",
     "/fantasy/roster/"),
    ("2026-10-01", "Waiver impact",
     "Trades & Pickups' Pick up mode ranks every free agent by what he does to your playoff "
     "and title odds.", "/fantasy/trade/"),
    ("2026-10-01", "College and pro football together",
     "One watch guide for every game of the day, and a Tonight card on Home on nights both "
     "play.", "/watch/"),
    ("2026-09-30", "Game previews",
     "Every college and NFL game gets its own page: our call against the book, unit against "
     "unit, the players to watch and recent form.", "/cfb/predictions/"),
    ("2026-09-30", "Playoff odds",
     "The rest of the season played out on our model - the College Football Playoff field and "
     "the NFL bracket, with the likeliest matchups.", "/cfb/playoff/"),
    ("2026-09-30", "Trade analyzer",
     "Pick a deal and see what it does to both teams' points, record and title odds - for both "
     "leagues and your own.", "/fantasy/trade/"),
    ("2026-09-30", "Team stats",
     "One sortable table per sport: opponent-adjusted efficiency for college and pro football, "
     "Torvik's numbers for college basketball.", "/cfb/stats/"),
    ("2026-09-30", "NFL rankings, team pages and schedule",
     "The NFL gets what college football has: our ratings beside ESPN's, a page for every "
     "team, and the week's bets.", "/nfl/power/"),
    ("2026-09-30", "Watch guides, with Quadbox",
     "Every game of the day by kickoff window, ranked by how worth watching it is - or four at "
     "a time for one screen. College football, NFL and college basketball.", "/cfb/watch/"),
    ("2026-09-30", "Playoff picture",
     "Clinched, eliminated and magic numbers on both fantasy power pages.", "/fantasy/power/"),
    ("2026-09-29", "Stakes and schedule difficulty",
     "The game of the week (the one that moves the playoff race most), every team's stakes, "
     "and what the schedule did to each record.", "/fantasy/schedule/"),
    ("2026-09-29", "An honest bets record",
     "Our weekly picks counted in units and against the closing line.", "/cfb/predictions/"),
    ("2026-09-29", "Share buttons and updated times",
     "Recaps, matchups and rankings share with a preview card; every page says when it was "
     "last updated, in your own time zone.", None),
    ("2026-09-28", "ESPN leagues",
     "Connect a public ESPN league as well as Sleeper: matchups, your team, power rankings "
     "and history drawn for it.", "/fantasy/sync/"),
    ("2026-09-28", "Weekly recaps",
     "Every week of both leagues in review - awards, lineup accuracy and who left points on "
     "the bench.", "/fantasy/recap/"),
    ("2026-09-28", "My teams this week",
     "Star a college team and its games - our pick and the live score - collect on Home.", "/"),
    ("2026-09-27", "College football through the bowls",
     "Predictions, rankings and title odds run through bowl season and the playoff.",
     "/cfb/power/"),
    ("2026-09-25", "Bring your own league",
     "Connect your Sleeper league and see your matchups, your team's best lineup, power "
     "rankings and head-to-head history; sign in to keep it on every device.",
     "/fantasy/sync/"),
]


def _when(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d:%b} {d.day}"


def _item(day: str, title: str, text: str, link) -> str:
    head = escape(title)
    if link:
        head = f"<a href='{escape(link, quote=True)}'>{head}</a>"
    return (f"<li><span class='cl-when'>{_when(day)}</span>"
            f"<b class='cl-t'>{head}</b> <span class='cl-x'>{escape(text)}</span></li>")


CSS = """<style>
.cl-list{list-style:none;margin:0;padding:0}
.cl-list li{padding:9px 0;border-top:1px solid #eef2f7;line-height:1.45;font-size:14.5px;color:#334155}
.cl-list li:first-child{border-top:0;padding-top:2px}
.cl-when{display:inline-block;min-width:3.4em;margin-right:6px;font-size:12px;font-weight:700;
  letter-spacing:.03em;text-transform:uppercase;color:var(--gs-muted,#5d6b7e)}
.cl-t{color:#0f172a}
.cl-t a{color:inherit}
.cl-x{display:block;margin-top:2px}
/* Near the top of Home each entry is two lines at most; /changelog/ has it whole. */
.gs-whatsnew .cl-x{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cl-day{margin:22px 0 4px;font-size:13px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;
  color:var(--gs-muted,#5d6b7e)}
@media (prefers-color-scheme: dark){
  .cl-list li{border-top-color:#2b3852;color:#cbd5e1}
  .cl-t{color:#f1f5f9}
}
</style>"""


def home_card(n: int = HOME_SHOWN) -> str:
    """Home's "What's new": the latest `n` entries and a link to the rest."""
    items = "".join(_item(*e) for e in ENTRIES[:n])
    return (CSS + "<section class='home-card gs-whatsnew'><div class='home-card-head'>"
            "<h2>What's new</h2><a class='home-card-link' href='/changelog/'>All changes &rarr;</a>"
            f"</div><ul class='cl-list'>{items}</ul></section>")


def body() -> str:
    """Every entry, grouped under its day."""
    out, day = [CSS], None
    for e in ENTRIES:
        if e[0] != day:
            if day is not None:
                out.append("</ul>")
            day = e[0]
            d = date.fromisoformat(day)
            out.append(f"<h2 class='cl-day'>{d:%B} {d.day}, {d.year}</h2><ul class='cl-list'>")
        out.append(_item(*e).replace(f"<span class='cl-when'>{_when(e[0])}</span>", ""))
    if day is not None:
        out.append("</ul>")
    return "".join(out)


def generate() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        body(), "What's new", "New features and changes, newest first", updated=False,
        description="What's new on GordStats: new pages, features and fixes, newest first."),
        encoding="utf-8")
    print(f"Wrote changelog -> {OUT}")


if __name__ == "__main__":
    generate()
