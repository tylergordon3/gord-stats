"""
"How this works": a short explanation of each ranking, prediction and number
on the site, kept off the page that shows it.

Each explanation is a page of its own at /how/<topic>/ - linkable, shareable,
found by search - and /how/ lists them all. Beside the thing it explains a
page puts button(topic): a small "How this works" chip that is a plain link
to that page, and that docs/assets/js/gs-how.js turns into a dialog over the
page - it fetches the explainer once and shows its <article>, so the page
itself carries none of the text. A page with a button loads the script once
with JS_TAG.

    from gordstats import how
    html = f"<h2>Rankings {how.button('cfb-rankings')}</h2>" + ... + how.JS_TAG

The words are written here, in readers' words, for a fan who knows spreads,
percentages and fantasy basics but not the modeling terms: one plain sentence
saying what the number is, how it is made (the real term in parentheses after
the plain one), what to keep in mind, and when it changes. Every claim was
checked against the code that makes the number (the comments by each topic
say where); change the explainer in the same commit as the model.

Styled in assets/css/custom.css (HOW THIS WORKS). Built in the daily run's
render-home block, next to the changelog.

    python -m gordstats.how
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from gordstats import js_assets, paths, share_button
from gordstats.frontmatter import add_front_matter

OUT = paths.DOCS / "how"
BASE = "/how/"

# The dialog's behavior. JS is the file inline (the browser tests run it);
# JS_TAG is what a page carries, once, wherever it has a button.
JS = js_assets.inline("gs-how.js")
JS_TAG = js_assets.tag("gs-how.js", attrs=" defer")
# The same tag for a page Jekyll runs Liquid over as it is - one not written
# through frontmatter.add_front_matter: Home (cbb.render.render_home writes
# its own front matter) and the hand-written /men/ and /women/ scoreboards.
LIQUID_TAG = ("<script defer src=\"{{ '/assets/js/gs-how.js' | fingerprint | relative_url }}\">"
              "</script>")

GROUPS = ("Rankings and predictions", "Game day", "Fantasy football", "College basketball")


@dataclass(frozen=True)
class Topic:
    """One explainer. `name` is short ("CFB rankings": the button's label
    for a screen reader); `title` is the page's heading and the dialog's.
    `summary` is the one line under it on /how/ and in search results.

    The body is HTML of our own writing: `lede` one plain sentence (what is
    this number?), `how` the paragraphs or lists of how it is made, `limits`
    what to keep in mind, `updates` when it changes, `curious` an optional
    last paragraph of detail for the enthusiast. `pages` are where the thing
    is on the site, `related` other topic ids."""
    id: str
    group: str
    name: str
    title: str
    summary: str
    lede: str
    how: tuple[str, ...]
    limits: tuple[str, ...]
    updates: str
    curious: str = ""
    pages: tuple[tuple[str, str], ...] = ()
    related: tuple[str, ...] = field(default_factory=tuple)


def _p(*paras: str) -> tuple[str, ...]:
    return tuple(paras)


# When the Pi rebuilds the site (deploy/gordstats-daily.timer: 05,11,17,23:30 ET,
# each up to 15 minutes late).
DAILY = "four times a day, around 5:30 and 11:30 AM and PM Eastern"
DAILY_ = DAILY[0].upper() + DAILY[1:]

TOPICS: list[Topic] = [
    # ------------------------------------------------------------ CFB rankings
    # cfb.ratings: ridge regression on margins (alpha 0.25), 180-day half-life,
    # home field fitted and unpenalized, each team shrunk toward its conference
    # (unpenalized conference levels, _fit_levels); cfb.games + cfb.fcs: ESPN
    # FBS and FCS scoreboards since 2014, regular season only, below-D1 teams
    # pooled; cfb.efficiency: 13 CFBD per-game metrics, each opponent-adjusted,
    # stacked as ~0.78 x rating + efficiency value; RMSE on 2020-25 FBS games
    # 16.18 -> 16.07 (efficiency) -> 15.88 (FCS + conferences, cfb.backtest
    # --report 2026-10-03); home edge ~3.0 = 0.78 x 2.83 + 0.78 intercept;
    # cfb.site.power: AP (ESPN), FPI (ESPN), SP+ and Elo (CFBD).
    Topic(
        id="cfb-rankings", group="Rankings and predictions", name="CFB rankings",
        title="How the CFB rankings work",
        summary="What the GordStats college football rating means, what goes into it, and how "
                "it compares with the AP poll and ESPN's FPI.",
        lede="A team's GordStats rating is how many points better than an average FBS team it "
             "would be on a neutral field: a +14 team would be a two-touchdown favorite over "
             "an average one.",
        how=_p(
            "<p>Using every FBS and FCS game since 2014, the model finds the one number per "
            "team that best fits all the final margins at once, plus a home-field edge (about "
            "3 points lately). Because every team is rated together, beating a good team counts "
            "more than beating a bad one, and an FCS opponent counts as itself, not as a "
            "generic one.</p>",
            "<p>Recent games count most: a game counts half as much after 180 days. A pull "
            "toward its conference's average keeps a team with few games from swinging wildly "
            "(ridge regression).</p>",
            "<p>It's then blended with how well a team plays snap to snap, adjusted for "
            "opponents: expected points added per play (EPA), success rate, explosiveness and "
            "more (<a href='/how/team-stats/'>what these mean</a>).</p>",
            "<p>Alongside ours: the <strong>AP</strong> poll, ESPN's <strong>FPI</strong> (its "
            "own points-better-than-average rating), and two other computer ratings, "
            "<strong>SP+</strong> and <strong>Elo</strong>.</p>",
        ),
        limits=_p(
            "<p>Injuries, transfers and coaching changes count only once they show up on the "
            "field. Early in the season it leans on last year. Bowl and playoff games are "
            "left out.</p>",
        ),
        updates=f"{DAILY_}.",
        curious="Scores come from ESPN, the efficiency stats from CollegeFootballData. Tested on "
                "every 2020-25 FBS game, each predicted only from earlier games, the efficiency "
                "blend cut the typical miss (root-mean-square error, RMSE) from 16.18 to 16.07 "
                "points, and rating FCS teams individually with the conference pull took it to "
                "15.88. Blowouts count in full (no cap on margin), and garbage time stays in: "
                "taking it out tested worse.",
        pages=(("CFB rankings", "/cfb/power/"),),
        related=("cfb-predictions", "playoff-odds", "team-stats"),
    ),
    # --------------------------------------------------------- CFB predictions
    # cfb.ratings (margin = rating gap + home field, FCS sides by their own
    # rating via cfb.fcs; total = base + two pace numbers, a separate ridge,
    # alpha 4.0, FCS still pooled there); cfb.predict (win chance =
    # Phi(margin / sigma), sigma from data/cfb/model_validation.json: 15.88
    # once `cfb.backtest --report` is rerun with the FCS archive, 16.07
    # before); validation (2026-10-03 report): 4,238 FBS games 2020-25, RMSE
    # 15.88, winners 72.6%, closing line 15.38, 3+ point calls 49.1% ATS
    # (1,783); 2026 weeks 1-5 replayed: 13.7 -> 12.7 MAE vs the book's 11.6;
    # cfb.results (graded on the last prediction archived before kickoff;
    # spread calls need 3+ points); cfb.odds (ESPN's DraftKings line).
    Topic(
        id="cfb-predictions", group="Rankings and predictions", name="CFB predictions",
        title="How the CFB predictions work",
        summary="How each college football game's spread, total and win chance are made, how "
                "they're graded, and how they've done.",
        lede="Our call on each game is a predicted margin (shown as a spread), a total and a "
             "win chance, all from the GordStats ratings.",
        how=_p(
            "<p><strong>Margin:</strong> the home team's rating minus the visitor's, plus home "
            "field (none at a neutral site). <strong>Total:</strong> a second model rates how "
            "high- or low-scoring each team's games run; both teams' numbers are added to a "
            "typical game's total.</p>",
            "<p><strong>Win chance:</strong> on games it hadn't seen, the model typically missed "
            "by about 16 points. Allowing for misses that size (a normal distribution with a "
            "15.88-point standard deviation), a 7-point favorite wins about 67% of the "
            "time.</p>",
            "<p><strong>The record:</strong> each prediction is saved before kickoff and graded "
            "on that number. Against the spread (DraftKings, via ESPN), a pick counts only "
            "when we differ from the book by 3+ points.</p>",
        ),
        limits=_p(
            "<p>Predicting all 4,238 FBS-vs-FBS games of 2020-25 from earlier games only, it "
            "picked 72.6% of winners. The closing line (the last line before kickoff) is "
            "sharper: its typical miss is 15.4 points to our 15.9, and our 3+ point "
            "disagreements won 49.1% against "
            "the spread, short of the 52.4% needed to profit.</p>",
            "<p>It knows nothing about injuries, weather or depth charts.</p>",
        ),
        updates=f"{DAILY_}, with every newly finished game and the latest lines.",
        curious="During a game, the schedule and each game page also show ESPN's live win "
                "probability, labeled as ESPN's; ours stays the number we set before kickoff. "
                "For the first five weeks of 2026 every FCS team was priced as one generic "
                "opponent, which cost those games about 2 points a game; the record keeps "
                "those predictions as they were made.",
        pages=(("CFB predictions", "/cfb/predictions/"), ("CFB schedule", "/cfb/schedule/")),
        related=("cfb-rankings", "bets-record", "game-previews"),
    ),
    # ------------------------------------------------------------ NFL rankings
    # nfl.ratings: the CFB model with alpha 4.0 and a 180-day half-life, tuned
    # walk-forward on 2015-19 and frozen; nfl.games: ESPN, every completed game
    # since 2014 incl. playoffs; home field fitted (1.75 on 2026-10-02);
    # nfl.site.power: FPI with Off/Def/ST, Odds tab = ESPN's simulations.
    Topic(
        id="nfl-rankings", group="Rankings and predictions", name="NFL rankings",
        title="How the NFL rankings work",
        summary="What the GordStats NFL rating means, what goes into it, and how it compares "
                "with ESPN's FPI.",
        lede="A team's GordStats NFL rating is how many points better than an average team it "
             "would be on a neutral field: a +7 team would be a touchdown favorite over an "
             "average one.",
        how=_p(
            "<p>Using every NFL game since 2014, playoffs included, the model finds the one "
            "number per team that best fits all the final margins at once, plus a home-field "
            "edge (under 2 points lately). Because every team is rated together, beating a "
            "good team counts more than beating a bad one.</p>",
            "<p>Recent games count most: a game counts half as much after 180 days. A strong "
            "pull toward average keeps one blowout from swinging a team (ridge regression). "
            "The settings were tuned on 2015-19 and locked before testing on 2020-25.</p>",
            "<p>Next to ours is ESPN's <strong>FPI</strong>, its own points-better-than-average "
            "rating, split into offense, defense and special teams. The Odds tab shows ESPN's "
            "own season simulations.</p>",
        ),
        limits=_p(
            "<p>It sees final scores only, so a quarterback injury or trade counts only once it "
            "shows up in results. Early in the season the ratings are mostly last year's.</p>",
        ),
        updates=f"{DAILY_}, with every newly finished game.",
        pages=(("NFL rankings", "/nfl/power/"),),
        related=("nfl-predictions", "playoff-odds", "team-stats"),
    ),
    # --------------------------------------------------------- NFL predictions
    # nfl.predict: win chance = Phi(margin / 13.1157), sigma from
    # data/nfl/model_validation.json; 1,693 games 2020-25: RMSE 13.12 (14.22
    # home-field-only), winners 63.7%; nfl.site.predictions: EDGE 3.0 for a
    # lean, ESPN's odds[0] line, record on the last pre-kickoff capture,
    # 52.4% break-even.
    Topic(
        id="nfl-predictions", group="Rankings and predictions", name="NFL predictions",
        title="How the NFL predictions work",
        summary="How each NFL game's spread, total and win chance are made, how they're graded, "
                "and how they've done.",
        lede="Our call on each NFL game is a predicted margin (shown as a spread), a total and "
             "a win chance, all from the GordStats ratings.",
        how=_p(
            "<p><strong>Margin:</strong> the home team's rating minus the visitor's, plus home "
            "field. <strong>Total:</strong> a second model rates how high- or low-scoring each "
            "team's games run; both teams' numbers are added to a typical game's total.</p>",
            "<p><strong>Win chance:</strong> on games it hadn't seen, the model typically missed "
            "by about 13 points. Allowing for misses that size (a normal distribution with a "
            "13.12-point standard deviation), a 3-point favorite wins about 59% of the time "
            "and a 7-point favorite about 70%.</p>",
            "<p><strong>The record:</strong> each prediction is saved before kickoff and graded "
            "on that number. When we differ from the book's line (via ESPN) by 3 or more "
            "points, that's a lean, and only leans count against the spread or the total. "
            "Pushes don't count; 52.4% is break-even at -110.</p>",
        ),
        limits=_p(
            "<p>Predicting all 1,693 games of 2020-25 from earlier games only, it picked 63.7% "
            "of winners, and its 13.12-point typical miss beats the 14.22 of a guess that "
            "knows only which team is at home. It knows nothing about injuries, weather or "
            "quarterback news.</p>",
        ),
        updates=f"{DAILY_}, with every newly finished game and the latest lines.",
        curious="During a game, the schedule and each game page also show ESPN's live win "
                "probability, labeled as ESPN's; ours stays the number we set before kickoff.",
        pages=(("NFL predictions", "/nfl/"), ("NFL schedule", "/nfl/schedule/")),
        related=("nfl-rankings", "bets-record", "game-previews"),
    ),
    # ------------------------------------------------------------- bets record
    # gordstats.bets_card (pick_week: single = widest spread gap inside the
    # gates, parlay = next 3 widest spreads or totals; LOCK_HOUR 9 ET);
    # cfb.site.homecards (gates 3-10), nfl.site.homecards (3-6);
    # gordstats.bet_record (units at -110, parlay rules, CLV, "moved our way"
    # from the first capture within 7 days of kickoff); close = last capture
    # before kickoff (CFB: the later of two DraftKings captures).
    Topic(
        id="bets-record", group="Rankings and predictions", name="the bets record",
        title="How the bets record works",
        summary="How the weekly bet and parlay are picked, how they're scored in units, and "
                "why we track the closing line.",
        lede="Each week the model makes one bet and one three-leg parlay where it disagrees "
             "most with the sportsbook, and we keep an honest record of both.",
        how=_p(
            "<p><strong>The picks:</strong> the single bet is the game where our spread differs "
            "most from the book's, by 3 to 10 points in college or 3 to 6 in the NFL (bigger "
            "gaps usually mean news the model can't see). The parlay takes "
            "the next three biggest gaps, spreads or totals. Picks lock at 9 AM Eastern on "
            "the week's first game day.</p>",
            "<p><strong>Units:</strong> each bet is one unit at standard -110 odds, so a win "
            "pays 0.91 and a loss costs 1. A parlay loses if any leg loses; a pushed leg "
            "drops out.</p>",
            "<p><strong>The closing line:</strong> each pick is also checked against the last "
            "line before kickoff. Beating it (closing line value, CLV), like taking -3 on a "
            "team that closed at -5, is the best sign a bet was smart, win or lose. \"Line "
            "moved our way\" counts how often it moved toward us after our first look.</p>",
        ),
        limits=_p(
            "<p>In testing (2020-25), the model's college disagreements of 3+ points won 49.1% "
            "against the spread, below the 52.4% needed to profit. Not gambling advice.</p>",
        ),
        updates=f"Graded {DAILY}, as games finish.",
        pages=(("Home", "/"), ("CFB predictions", "/cfb/predictions/"), ("NFL", "/nfl/")),
        related=("cfb-predictions", "nfl-predictions"),
    ),
    # ------------------------------------------------------------ playoff odds
    # cfb.playoff / nfl.playoff: N_SIMS 10,000, fixed seeds; each game from the
    # predicted margin plus a per-team rating shock (sd now + weekly drift)
    # and game noise sized so a game next week keeps the printed win chance;
    # calibrated to the spread of remaining wins 2015-2025. CFB 2026-27: 4
    # power-conference champions, best-ranked other champion-or-not (G6 bid),
    # Notre Dame if top 12, at-large; straight seeding, top 4 byes; committee
    # stand-in = wins vs an average top-25 team's on the schedule + rating/10.
    # NFL: 7 a conference, only the 1 seed a bye; tiebreaks h2h, division,
    # conference record, then a coin.
    Topic(
        id="playoff-odds", group="Rankings and predictions", name="playoff odds",
        title="How the playoff odds work",
        summary="How we get each team's chance to make the College Football Playoff or the "
                "NFL playoffs, earn a bye and win it all.",
        lede="Playoff odds are how often a team makes the playoffs, earns a bye and wins the "
             "title when we play the rest of the season out 10,000 times (a Monte Carlo "
             "simulation).",
        how=_p(
            "<p>Each game left is decided at random by the win chances on the predictions "
            "page. Each simulated season also nudges every rating a little, more "
            "for games further off, since the ratings are uncertain too.</p>",
            "<p><strong>College:</strong> 12 teams. The ACC, Big 12, Big Ten and SEC champions "
            "are in, plus the best-ranked team from the other conferences, Notre Dame if it "
            "ranks in the top 12, and at-large teams. Seeds go straight by ranking; the top 4 "
            "get byes. In place of the committee, we rank teams by how their wins compare with "
            "what an average top-25 team would win on the same schedule (strength of record), "
            "plus a little for rating.</p>",
            "<p><strong>NFL:</strong> seven teams per conference, the four division winners "
            "seeded first; only the 1 seed gets a bye. Ties are broken by head-to-head, then "
            "division and conference record; past that, a coin flip.</p>",
        ),
        limits=_p(
            "<p>The real committee can differ from ours. Injuries aren't modeled. The FPI "
            "column is ESPN's own odds.</p>",
        ),
        updates=f"{DAILY_}; the odds move only when games finish.",
        curious="The rating nudges were sized so the spread of each team's win totals matches "
                "real seasons since 2015. Conference title games are played between the two "
                "best conference records. Once the real playoff matchups are set, those are "
                "used.",
        pages=(("CFB playoff odds", "/cfb/playoff/"), ("NFL playoff odds", "/nfl/playoff/")),
        related=("cfb-rankings", "nfl-rankings"),
    ),
    # ----------------------------------------------------------- game previews
    # gordstats.preview_page (The call, Unit vs unit with national ranks and
    # percentile bars, the biggest gap named at a 0.3 percentile gap, players
    # to watch, last 4 games against our line); cfb/nfl site.previews (which
    # games: last week, this week, next week once lined; CFB FBS v FBS);
    # gs-winprob.js (ESPN summary `winprobability`, read every 60 s while live,
    # shown from kickoff; ours stays the pregame call).
    Topic(
        id="game-previews", group="Game day", name="game previews",
        title="What a game preview shows",
        summary="What's on each college and NFL game page: our call against the book's, unit "
                "against unit, players to watch and recent form.",
        lede="Every game gets a page of its own: our call next to the sportsbook's, each "
             "offense lined up against the other team's defense, the players to watch and "
             "recent form.",
        how=_p(
            "<ul><li><strong>The call:</strong> the same prediction as the predictions page "
            "(favorite, spread, win chance, projected score) beside the book's line and ESPN "
            "FPI's win chance. After the game, it shows the call we saved before kickoff.</li>"
            "<li><strong>Unit vs unit:</strong> each offense against the other team's defense, "
            "stat by stat, with national ranks (1st is best). The longer bar has the edge, and "
            "the biggest gap on each side is spelled out.</li>"
            "<li><strong>Players to watch:</strong> the quarterback, the busiest running back "
            "and the two busiest receivers, with how efficient each has been.</li>"
            "<li><strong>Recent form:</strong> the last four games, and how each finished "
            "against our pregame line.</li>"
            "<li><strong>Win probability:</strong> once a game starts, ESPN's live win "
            "chance, charted play by play.</li>"
            "<li><strong>Watch score:</strong> how worth watching it should be, from the "
            "<a href='/how/watch-guide/'>watch guide</a>.</li></ul>",
        ),
        limits=_p(
            "<p>Season stats are thin early in the year. A lean is a disagreement with the "
            "book, not a tip. College previews cover only games between two FBS teams.</p>",
        ),
        updates=f"{DAILY_}, for last week's games, this week's, and next week's "
                "once they have a line.",
        curious="College stats come from CollegeFootballData, NFL stats from nflverse's free "
                "play-by-play data. For what they mean, see <a href='/how/team-stats/'>the team "
                "stats explainer</a>. The live chart is ESPN's own model, read from ESPN about "
                "once a minute during the game; our pregame number stays in The call.",
        pages=(("CFB schedule", "/cfb/schedule/"), ("NFL schedule", "/nfl/schedule/")),
        related=("team-stats", "watch-guide", "cfb-predictions", "nfl-predictions"),
    ),
    # ------------------------------------------------------------- watch guide
    # gordstats.watch_page.judge (ESPN matchup quality; each nudge closes 25%
    # of the gap to 100; spread stands in without it); cfb.site.watch (Top 25
    # matchup, playoff stakes by FPI); nfl.site.watch (both winning records);
    # gs-watch.js (starred +100, fantasy +5/+2 capped 20, live: OT +40, 4th
    # within 8 +30, favorite trailing in the 2nd half +15, blowout -30 at
    # 21/17; quadbox: best four, no shared channel, SWAP 15; 60 s polling).
    Topic(
        id="watch-guide", group="Game day", name="the watch guide",
        title="How the watch guide ranks games",
        summary="How each game's watch score is set, what moves a game up while it's on, and "
                "how Quadbox picks four games for one screen.",
        lede="The watch guide ranks each day's college and NFL games by how worth watching "
             "they should be, grouped by kickoff time.",
        how=_p(
            "<p><strong>Watch score (0-100):</strong> it starts from ESPN's matchup quality, a "
            "rating of how good both teams are and how close the game should be. A Top 25 "
            "matchup or playoff stakes in college, or two winning teams in the NFL, each "
            "close a quarter of the gap to 100 (60 becomes 70).</p>",
            "<p><strong>Your teams:</strong> a starred team goes to the top, and games with "
            "your fantasy starters move up a little.</p>",
            "<p><strong>Live:</strong> a game moves up for overtime, a one-score fourth quarter "
            "or an underdog leading in the second half, and drops for a blowout.</p>",
            "<p><strong>Quadbox:</strong> four games on one screen, never two on the same "
            "channel, the best top left with its sound on. A game loses its box when it ends, "
            "turns into a blowout or something much better comes on.</p>",
        ),
        limits=_p(
            "<p>It's a guess at entertainment, not a ranking of the teams. The Watch number on "
            "a game is its pregame score; the order also counts your teams and what's "
            "happening live.</p>",
        ),
        updates=f"The day's games are set {DAILY}; live scores and the order refresh every "
                "minute during games.",
        curious="During games: overtime adds 40, a fourth quarter within 8 points adds 30, the "
                "favorite trailing in the second half adds 15, and a blowout (21 points in "
                "college, 17 in the NFL) takes off 30. Each fantasy starter adds 5, each bench "
                "player 2, up to 20. Without ESPN's matchup quality, the closeness of the "
                "spread stands in. In basketball season the all-sports guide adds each day's "
                "20 best men's and women's college basketball games, scored the CBB guide's way.",
        pages=(("All sports", "/watch/"), ("CFB watch guide", "/cfb/watch/"),
               ("NFL watch guide", "/nfl/watch/")),
        related=("game-previews", "cbb-watch"),
    ),
    # -------------------------------------------------------------- team stats
    # cfb.advanced / cfb.site.stats: CFBD WEPA (opponent-adjusted EPA), raw
    # splits with excludeGarbageTime, success 50/70/100%; nfl.advanced:
    # nflverse pbp, success = EPA > 0, explosive = pass 20+ / run 10+, garbage
    # time = Q4 with win prob under 5% or over 95%, opponent adjustment from
    # opponents' other games; gordstats.stats_page: national percentile shading
    # (defense columns marked "better": low).
    Topic(
        id="team-stats", group="Game day", name="team stats",
        title="What the team stats mean",
        summary="What expected points added, success rate, explosiveness and opponent "
                "adjustment mean in the college and NFL team stats tables.",
        lede="The team stats show how well each team moves the ball and stops it, play by "
             "play, adjusted for opponents.",
        how=_p(
            "<p>Most columns are built on <strong>expected points added (EPA)</strong>: how "
            "much a play changed the points a team could expect to score on that drive, given "
            "down, distance and field position. A 10-yard gain on 3rd-and-5 is worth more "
            "than one on 3rd-and-15. For a defense, lower is better.</p>",
            "<p><strong>Success rate</strong> is the share of plays that keep an offense on "
            "schedule (college: at least half the yards needed on 1st down, 70% on 2nd, all "
            "on 3rd and 4th; NFL: any play with positive EPA). "
            "<strong>Explosiveness</strong> measures the big plays.</p>",
            "<p><strong>Adjusted</strong> numbers account for opponents: CollegeFootballData's "
            "opponent-adjusted EPA in college; in the NFL, each team's number corrected by how "
            "good its opponents were in their other games. Garbage time (a "
            "fourth quarter already decided) is left out of the NFL rates and college's "
            "unadjusted numbers.</p>",
            "<p>Shading shows a team's national percentile, even with a conference filter "
            "on.</p>",
        ),
        limits=_p(
            "<p>Early in the season the sample is a few games, and one blowout can skew it.</p>",
        ),
        updates=f"College stats refresh every 12 hours; NFL stats {DAILY}, once the "
                "play-by-play is published.",
        pages=(("CFB team stats", "/cfb/stats/"), ("NFL team stats", "/nfl/stats/")),
        related=("game-previews", "cfb-rankings", "nfl-rankings"),
    ),
    # ----------------------------------------------------------------- pick'em
    # gordstats.pickem: the week Tue-Mon ET, week 1 = the NFL opener's; every
    # NFL game + FEATURED (10) college games by the watch score; slate only
    # appended to; lock = kickoff, never moved once passed; 'v' (no points)
    # for a tie, cancelled/postponed, moved out of the week, unplayed 3 days
    # on; GordStats = the favorite by the last archived pre-kickoff chance
    # (cfb/nfl.results.on_record), values re-ranked among open games each run.
    # functions/api/pickem.js: locks on the server's clock, each value once,
    # ties ranked by most right picks; the CFB live tick posts college finals.
    Topic(
        id="pickem", group="Game day", name="pick'em",
        title="How the weekly picks contest works",
        summary="How confidence points score, which games are in a week, when picks lock and "
                "how the GordStats entry picks.",
        lede="Pick'em is a free weekly contest: pick the winner of every NFL game and the "
             "week's ten biggest college games, then rank your picks by how sure you are.",
        how=_p(
            "<p><strong>Confidence points:</strong> with 25 games, each pick gets a different "
            "value from 1 to 25. A right pick scores its value, a wrong one nothing, so put "
            "your biggest numbers on your surest picks.</p>",
            "<p><strong>The games:</strong> every NFL game plus the ten college games the "
            "<a href='/how/watch-guide/'>watch guide</a> rates highest. Once a week opens, a "
            "game can be added but never dropped.</p>",
            "<p><strong>Locks:</strong> each game locks at its own kickoff, by our server's "
            "clock. Its pick and value are then fixed; your other values stay free for the "
            "games still to come.</p>",
            "<p><strong>GordStats plays too:</strong> it takes our model's favorite in every "
            "game, giving its biggest values to the games it's surest of, from its last "
            "prediction before kickoff.</p>",
        ),
        limits=_p(
            "<p>A tie, or a canceled or postponed game, scores nothing for anyone, and so "
            "does a game you leave unpicked. Equal points on the leaderboard go to whoever "
            "has more right picks.</p>",
        ),
        updates=f"Picks save as you make them. College finals post within minutes on game "
                f"days; NFL finals {DAILY}.",
        curious="A week runs Tuesday through Monday, so a midweek NFL game never falls between "
                "two weeks, and week 1 is the NFL's opening week. The leaderboard shows the name "
                "you choose, never your email.",
        pages=(("Pick'em", "/pickem/"),),
        related=("watch-guide", "nfl-predictions", "cfb-predictions"),
    ),
    # ----------------------------------------------------------- fantasy power
    # fantasy.league.power: DEFAULT_SIMS 10,000; true rate mu + N(0, mu_se);
    # gamma weekly scores; two-state injury chain, MEAN_ABSENCE_WEEKS 3; ESPN
    # return dates then Sleeper tags; next-man-up and return dip; lineup on
    # projection; median game; played weeks locked; seeds wins then points;
    # rating = 100 x points per week / league mean. fantasy.projections:
    # MARKET_WEIGHT 0.8 (consensus ADP turned into points), PRIOR_GAMES 5 (a
    # plain weighted average with points per game), Sleeper blend 50/50 for
    # RB/WR/TE. fantasy.site.consensus: Rating = equal-weight average with
    # FantasyPros League Analyzer (vorpPerc). Luck = wins - all-play
    # expectation.
    Topic(
        id="fantasy-power", group="Fantasy football", name="fantasy power rankings",
        title="How the fantasy power rankings work",
        summary="How each roster is rated, and how playing the season out 10,000 times gives "
                "every team's playoff and title odds.",
        lede="The power rankings rate each roster by the points its best lineup should score "
             "from here, then play the rest of the season out 10,000 times (a Monte Carlo "
             "simulation) for playoff and title odds.",
        how=_p(
            "<p><strong>Projections:</strong> a player's preseason projection is 80% his "
            "average draft position (ADP) turned into points and 20% our usage model. Once "
            "games are played, his real points per game count too, with the preseason "
            "projection worth five games.</p>",
            "<p><strong>Each simulated week:</strong> every team starts its best projected "
            "lineup, and scores vary around each projection. Injuries carry over: a known one "
            "lasts until ESPN's expected return, teammates absorb the work, and a player's "
            "first games back are projected a little lower.</p>",
            "<p><strong>Wins:</strong> each week counts twice, once for the head-to-head game "
            "and once against the league median. Weeks already played are locked in.</p>",
            "<p><strong>Rating:</strong> our projected points per week, with 100 the league "
            "average. The published Rating averages ours with the FantasyPros League "
            "Analyzer. <strong>Luck</strong> is wins above what your scores would have earned "
            "playing every team every week (all-play).</p>",
        ),
        limits=_p(
            "<p>The odds are only as good as the projections, which can't see a breakout "
            "coming.</p>",
        ),
        updates=f"{DAILY_}, and again as soon as a week's stats are final.",
        curious="Running backs, receivers and tight ends are blended half-and-half with "
                "Sleeper's recent weekly projections. Each run first draws every player's true "
                "scoring rate, since we can't be sure of it, then each week's score around it "
                "(a gamma distribution). New injuries in the simulation last three weeks on "
                "average. Your own league's page runs the same model in your browser, with "
                "your league's playoff format (reseeding, two-week rounds) and without the "
                "FantasyPros blend.",
        pages=(("Fantasy power rankings", "/fantasy/power/"),),
        related=("fantasy-stakes", "injuries", "trade-analyzer", "cfb-league"),
    ),
    # ------------------------------------------------------- stakes / picture
    # fantasy.league.power + cfb.league_sim: playoff_if_win / _if_loss from
    # the same runs; gordstats.stakes: game of the week = max 2p(1-p) x (swing
    # A + swing B); gordstats.clinch: conservative arithmetic (chasers win out,
    # ties go against the team), Magic, Win and in, "A win: 99%" from the sims;
    # gordstats.odds_chart: last snapshot of each week.
    Topic(
        id="fantasy-stakes", group="Fantasy football", name="stakes and the playoff picture",
        title="How stakes and the playoff picture work",
        summary="What a game's swing means, how the game of the week is chosen, and how "
                "clinched, eliminated and magic numbers are worked out.",
        lede="Stakes show how much next week's game matters: each team's playoff chance if it "
             "wins, against its chance if it loses.",
        how=_p(
            "<p>We split the power rankings' simulated seasons by how next week's game went. "
            "The <strong>swing</strong> is the gap between the two chances, in percentage "
            "points.</p>",
            "<p>The <strong>game of the week</strong> is the one expected to move the playoff "
            "race most: big swings for both teams, in a game that could go either way.</p>",
            "<p>The <strong>playoff picture</strong> is plain arithmetic, not simulation. "
            "<strong>Clinched</strong> and <strong>eliminated</strong> hold in every possible "
            "finish, even if every team chasing wins out and every tie goes against the team "
            "in question. <strong>Magic</strong> is the number of wins that clinches a spot "
            "whatever anyone else does. <strong>Win and in</strong> means a head-to-head win "
            "this week clinches.</p>",
            "<p>The <strong>odds chart</strong> follows each team's playoff and title odds week "
            "by week.</p>",
        ),
        limits=_p(
            "<p>A swing is about next week's game only; the weeks after still matter. The "
            "simulated odds never say 100% until the arithmetic clinches it, or 0% until it "
            "eliminates.</p>",
        ),
        updates="With the power rankings. NFL stakes appear once the previous week's stats are "
                "final, usually midweek.",
        curious="The game of the week scores each game by the two swings added together, times "
                "how close it is to a coin flip: 2p(1-p) for a win chance p, largest at "
                "50/50.",
        pages=(("Fantasy power rankings", "/fantasy/power/"),
               ("CFB league power", "/cfb/league/power/")),
        related=("fantasy-power", "cfb-league"),
    ),
    # ---------------------------------------------------- fantasy projections
    # fantasy.site.matchups: GS = power-model mu with in-season form, x
    # clip((implied total / slate average)^0.6, 0.70, 1.30), defense inverted;
    # fantasy.league.availability (Q/D priced from 2016-25 reports by role and
    # last practice); ext_projections: Consensus = plain mean of Sleeper, ESPN,
    # FantasyPros; Pts = mean of all four x chance to play; win% =
    # Phi(diff / sqrt(var)) on GS (a second bar on Sleeper's); live expected
    # final = points + projection x share left; accuracy MAE / bias / r on
    # pre-kickoff numbers. cfb.weekly: tilt by our predicted score, -30% /
    # +10%; Yahoo (Rotowire) only.
    Topic(
        id="fantasy-projections", group="Fantasy football", name="fantasy projections",
        title="How the fantasy projections work",
        summary="How the GordStats weekly projection is made, how it compares with Sleeper, "
                "ESPN and FantasyPros, and how live win chances work.",
        lede="Every player gets a weekly projection from us and from Sleeper, ESPN and "
             "FantasyPros, and ours add up to a live win chance for each matchup.",
        how=_p(
            "<p><strong>GordStats projection:</strong> a player's season projection, raised or "
            "lowered up to 30% by how many points the betting market expects his team "
            "to score (its implied total) against the week's average. A defense goes the "
            "other way.</p>",
            "<p><strong>Injuries:</strong> Out and IR count zero. Questionable and Doubtful "
            "players count their projection times their chance to play (the \"plays\" pill; "
            "see <a href='/how/injuries/'>injuries</a>).</p>",
            "<p><strong>Consensus</strong> averages Sleeper, ESPN and FantasyPros; the gray "
            "<strong>Pts</strong> number averages all four.</p>",
            "<p><strong>Win chance:</strong> from each lineup's projected total and how much it "
            "could vary (a normal distribution). Live, a player's expected final is his "
            "points so far plus his projection for the rest of his game.</p>",
            "<p><strong>Accuracy:</strong> each source's average miss and bias (running high or "
            "low) on finished weeks, ours only from numbers saved before kickoff.</p>",
        ),
        limits=_p(
            "<p>One week is noisy; judge sources over many. The college league compares ours "
            "with Yahoo's only, and adjusts by our predicted score for each game, not the "
            "market's.</p>",
        ),
        updates=f"{DAILY_}, and every 10 minutes from half an hour before kickoff "
                "while games are on; live scores refresh every minute.",
        pages=(("Fantasy matchups", "/fantasy/matchups/"), ("CFB league matchups", "/cfb/matchups/")),
        related=("injuries", "fantasy-power", "recaps"),
    ),
    # ---------------------------------------------------------------- injuries
    # fantasy.league.availability (2016-25 nflverse reports; role from snap
    # share over the last 4 games, lead 60%+, share 35%+; last practice;
    # Questionable lead + full 88.8%, depth + DNP 30.4%); injury_report (ESPN
    # return dates; flat Sleeper fallback 4 weeks IR, 1 week Out);
    # opportunity (2019-25, RB .324/.150/.110 ...); return_dip (-8.4% after
    # one missed game; -16.5% then -12.3% after two or more); expert_posts
    # (PT, Dr, News accounts on X, last 7 days, injury word near his name).
    Topic(
        id="injuries", group="Fantasy football", name="injuries",
        title="How injuries are counted",
        summary="How we count a Questionable player, how long an injured player stays out, who "
                "picks up his work, and what the PT, Dr and News links are.",
        lede="A player on the injury report counts at his projection times his chance to play, "
             "and an injury carries into the weeks ahead, for him and his teammates.",
        how=_p(
            "<p><strong>Chance to play:</strong> for a Questionable or Doubtful player, how "
            "often similar players played, from the official injury reports of 2016-25, "
            "matched by role (from snap share) and last practice. A "
            "Questionable starter who practiced fully played 89% of the time; a backup who "
            "didn't practice, 30%.</p>",
            "<p><strong>How long he's out:</strong> ESPN's expected return date, or, without "
            "one, four weeks for injured reserve and one for Out.</p>",
            "<p><strong>Next man up:</strong> teammates behind him pick up part of his points, "
            "by shares measured in 2019-25; the next running back up gets about a third.</p>",
            "<p><strong>Back from injury:</strong> a returning player is projected 8% lower "
            "after one missed game, and 17% then 12% lower in his first two games after a "
            "longer absence.</p>",
            "<p><strong>PT, Dr and News</strong> link to a recent post on X about his injury "
            "from physical therapists, a former team doctor or national insiders.</p>",
        ),
        limits=_p(
            "<p>A late scratch beats any model. All of this is for NFL leagues; college "
            "players count Yahoo's injury tags at fixed rates.</p>",
        ),
        updates=f"{DAILY_}, with ESPN's latest injury list and posts.",
        pages=(("Your team", "/fantasy/roster/"), ("Fantasy matchups", "/fantasy/matchups/"),
               ("Fantasy power rankings", "/fantasy/power/")),
        related=("fantasy-projections", "fantasy-power", "trade-analyzer"),
    ),
    # ---------------------------------------------------------- trade analyzer
    # gordstats.trade_page / gs-trade.js: the season sim run twice, same draws
    # (stable / pool); NFL 5,000 runs a trade, 2,000 a pickup; CFB 20,000;
    # verdict on title odds (about even when the two changes are within 1
    # point; "helps / hurts you both" when both move 0.5+ the same way);
    # roster limits (drop lowest-projected non-starter, sign the best free
    # agent); Pick up ranked by title then playoff odds.
    Topic(
        id="trade-analyzer", group="Fantasy football", name="the trade analyzer",
        title="How the trade analyzer works",
        summary="How a trade or a waiver pickup is judged: the rest of the season played out "
                "with and without it, with the same luck both times.",
        lede="The trade analyzer shows what a deal or a pickup does to both teams' points per "
             "week, projected record and playoff and title odds.",
        how=_p(
            "<p>Using the power rankings' simulation, it plays the rest of the season out "
            "thousands of times with the rosters as they are, then again after the deal. Both "
            "runs get the same luck, so the difference is the trade itself.</p>",
            "<p><strong>The verdict</strong> compares how much the deal moves each team's title "
            "odds: within a percentage point of each other is about even, and if both rise "
            "(or both fall) it helps (or hurts) you both.</p>",
            "<p><strong>Rosters stay legal:</strong> a team taking more players than it sends "
            "drops its lowest-projected bench player, and one sending more signs the best "
            "free agent at the position it gave up.</p>",
            "<p><strong>Pick up</strong> tries each top free agent on your team, dropping your "
            "lowest-projected bench player if the roster is full, and ranks them by what they "
            "do to your title and playoff odds.</p>",
        ),
        limits=_p(
            "<p>It values players on rest-of-season projections, so it can't see a role change "
            "coming or weigh a win now against one later.</p>",
        ),
        updates=f"Projections and rosters {DAILY}; each deal is worked out in your browser "
                "when you pick it.",
        curious="An NFL trade is played out 5,000 times each way and a pickup 2,000; the "
                "college league plays 20,000. Same luck means each player gets the same "
                "simulated weeks whichever roster he's on.",
        pages=(("NFL league trades", "/fantasy/trade/"), ("CFB league trades", "/cfb/trade/")),
        related=("fantasy-power", "cfb-league", "injuries"),
    ),
    # ------------------------------------------------------------------- usage
    # fantasy.league.usage (Sleeper weekly stats: snap, carry, target, air
    # share, red-zone looks, targets per snap); cfb.usage (CFBD: targets from
    # play text, no snaps); RECENT_WEEKS 3 beside the season; shares over the
    # team's own players.
    Topic(
        id="usage", group="Fantasy football", name="usage",
        title="What the usage numbers mean",
        summary="Snap, carry and target shares over the last three weeks and the season: who is "
                "getting the work, and where the numbers come from.",
        lede="Usage shows each player's share of his team's work (snaps, carries and targets) "
             "over the last three weeks, with the season figure beside it.",
        how=_p(
            "<p>A share is the player's carries, targets or snaps out of his team's total. "
            "Recent weeks next to the season show who is gaining work: a back with 55% of the "
            "carries lately against 40% on the season is taking over the job.</p>",
            "<p><strong>NFL:</strong> from Sleeper's weekly stats. Air share is his share of "
            "the team's air yards (how far its passes traveled downfield, caught or not); "
            "red-zone looks are carries and targets inside the 20; targets per snap stands in "
            "for a target rate, since routes run aren't published for free.</p>",
            "<p><strong>College:</strong> from CollegeFootballData. Targets aren't published, "
            "so we count them from the play-by-play text. College snap counts aren't free "
            "either, so shares of touches stand in.</p>",
        ),
        limits=_p(
            "<p>Three weeks is a small window: a blowout or an injury mid-game can bend it. In "
            "college, a pass whose receiver can't be matched counts for the team only.</p>",
        ),
        updates=f"{DAILY_}; during a week in progress, the games already played count.",
        pages=(("NFL usage", "/fantasy/usage/"), ("CFB usage", "/cfb/usage/")),
        related=("injuries", "fantasy-projections"),
    ),
    # ------------------------------------------------- strength and schedule
    # fantasy.league.defense (Sleeper fan_pts_allow_*, vs league average at the
    # position, shrunk to 1.00 under 5 games); cfb.defense (ESPN box scores in
    # league scoring vs par from our predicted points); gordstats.strength_page
    # (next 6 weeks, weighted by projection, byes out); gordstats.schedule_luck
    # (all-play, vs normal; schedule = strength + timing, in wins; median left
    # out).
    Topic(
        id="schedule-strength", group="Fantasy football", name="strength and schedule difficulty",
        title="How strength and schedule difficulty work",
        summary="Defense against each position, the schedule ahead for your roster, and what "
                "the schedule has cost or given each team so far.",
        lede="Strength rates how many fantasy points each defense gives up to each position, and "
             "schedule difficulty shows how many wins each team's schedule has cost or given "
             "it.",
        how=_p(
            "<p><strong>Defense vs position:</strong> 1.00 is average. A defense at 1.20 has "
            "allowed 20% more than usual to that position: one to attack. NFL figures come "
            "from Sleeper in this league's scoring; college ones from ESPN box scores in the "
            "Yahoo league's scoring, against what each offense was expected to score. Under "
            "five games, a defense is pulled toward 1.00.</p>",
            "<p><strong>Schedule ahead:</strong> the next six weeks of opponents for your "
            "players, each weighted by his projection. Byes are left out.</p>",
            "<p><strong>Schedule difficulty</strong> compares your actual wins with what your "
            "scores would have earned playing every team every week (all-play), so −1.5 means "
            "the schedule has cost you a win and a half. It splits into opponent strength "
            "(did you face high scorers?) and timing (did you meet them on their big "
            "weeks?).</p>",
        ),
        limits=_p(
            "<p>Defense numbers swing a lot on a few games. The NFL figures aren't adjusted for "
            "the offenses each defense faced. The median game is left out of schedule "
            "difficulty, since no schedule changes it.</p>",
        ),
        updates=f"{DAILY_}, as games finish.",
        pages=(("NFL strength", "/fantasy/strength/"), ("CFB strength", "/cfb/strength/"),
               ("Schedule difficulty", "/fantasy/schedule/")),
        related=("fantasy-power", "usage"),
    ),
    # ------------------------------------------------------------------ recaps
    # gordstats.recap: best lineup by actual points (IR out; == Sleeper ppts,
    # tests/test_recap.py), accuracy = started / max, season = sum / sum,
    # awards and their rules, projection awards need full pregame coverage;
    # written once the week is final, rebuilt later for stat corrections.
    Topic(
        id="recaps", group="Fantasy football", name="weekly recaps",
        title="How the weekly recaps work",
        summary="What each award means, and how lineup accuracy measures the points left on the "
                "bench.",
        lede="Each week's recap hands out awards and grades how close every manager came to "
             "starting their best possible lineup.",
        how=_p(
            "<p><strong>Best possible lineup:</strong> the most a roster could have scored that "
            "week, filling every slot with the eligible player who actually scored the most "
            "(injured reserve left out). In Sleeper leagues it matches Sleeper's own max "
            "points.</p>",
            "<p><strong>Lineup accuracy:</strong> points started out of that best total; "
            "<strong>Left</strong> is the points left on the bench. The season figure is total "
            "points over total best, so big weeks count more.</p>",
            "<p><strong>Awards</strong> include the luckiest win (the lowest-scoring winner), "
            "the toughest loss (the highest-scoring loser), cost them the game (a loser whose "
            "best lineup would have won), most left on the bench, beat or missed the "
            "projection, bench star, pickup of the week, and the week's biggest riser and "
            "faller in the power rankings.</p>",
            "<p><strong>Med W / Med L</strong> is each team's second result of the week: a win "
            "or loss against the week's median score.</p>",
        ),
        limits=_p(
            "<p>The best lineup uses hindsight, so nobody hits 100% often. Projection awards "
            "appear only in weeks where every starter had a projection saved before "
            "kickoff.</p>",
        ),
        updates="Written once every game of the week is final, and refreshed in later updates "
                "so stat corrections land.",
        pages=(("NFL league recap", "/fantasy/recap/"), ("CFB league recap", "/cfb/recap/")),
        related=("fantasy-projections", "fantasy-power"),
    ),
    # -------------------------------------------------------------- CFB league
    # cfb.projections (Yahoo rank -> points curve from 2 seasons in league
    # scoring), cfb.in_season (frozen at the draft, preseason worth 5 games),
    # cfb.weekly (tilt by our predicted score, -30% / +10%, bye 0, Yahoo tags
    # this week), cfb.league_sim (SIMS 20,000; team-week normal, sd from
    # max(2, 0.55 x proj); median; 6 make it, 2 byes, reseeded);
    # cfb.site.league_power (Pts/wk, Bench, Anchor).
    Topic(
        id="cfb-league", group="Fantasy football", name="CFB league rankings",
        title="How the CFB league rankings work",
        summary="How the college fantasy league's rosters are ranked, and how 20,000 simulated "
                "seasons give playoff and title odds.",
        lede="The college league's power page ranks each Yahoo roster by its best lineup's "
             "projected points per week, then plays the rest of the season out 20,000 times (a "
             "Monte Carlo simulation) for playoff and title odds.",
        how=_p(
            "<p><strong>Projections:</strong> a player's preseason projection is his Yahoo "
            "draft rank turned into points, using the last two seasons in this league's "
            "scoring. Once games are played, his real points count too, with the preseason "
            "projection worth five games.</p>",
            "<p><strong>Each week:</strong> a player's projection rises or falls with our "
            "predicted score for his team's game, a bye counts zero, and Yahoo's injury tags "
            "apply to the current week.</p>",
            "<p><strong>Each simulated week:</strong> every roster starts its best projected "
            "lineup, and its total varies around that. Simulated wins, head-to-head and "
            "against the median, are added to the current Yahoo standings.</p>",
            "<p><strong>Bench</strong> is the value behind the starters; <strong>Anchor</strong> "
            "is the starter worth the most over a replacement-level player (the best at his "
            "position that no team needs to start).</p>",
        ),
        limits=_p(
            "<p>It's simpler than the NFL league's model: no injury carry-over, and how much a "
            "week's score can vary is a fixed share of its projection. Only Power 4 and Notre "
            "Dame players are in the pool.</p>",
        ),
        updates=f"{DAILY_}.",
        pages=(("CFB league power", "/cfb/league/power/"),),
        related=("fantasy-stakes", "trade-analyzer", "fantasy-power"),
    ),
    # ------------------------------------------------------------ CBB rankings
    # cbb.predictions.full_prediction (men: 0.4 GordTor + 0.4 GordKen + 0.05
    # each of T-Rank, KenPom, NET, BPI ranks; missing NET/BPI renormalized);
    # predict_womens (0.5 Gord + 0.3 T-Rank + 0.2 NET); stacked sklearn
    # ensembles predicting "in the tournament"; seed_helper (4 a line, 6 on 11
    # and 16); live.js legend (GORD = Ovr rank, NET, WAB, "Seed" = theScore's
    # rank: AP in season, the seed in March); render_power (T-Rank, averaged
    # with BPI once current).
    Topic(
        id="cbb-rankings", group="College basketball", name="college basketball rankings",
        title="How the college basketball rankings work",
        summary="What the GORD rank and the bracketology field are made from, and what NET, "
                "WAB and the rest of the scoreboard mean.",
        lede="GORD is our ranking of how strong each team's case for the NCAA tournament is, and "
             "it picks and seeds the 68 teams on the bracketology page.",
        how=_p(
            "<p>Machine-learning models learned from past seasons which teams make the "
            "tournament, using stats like adjusted offense and defense, strength of schedule "
            "and wins above bubble.</p>",
            "<p><strong>Men:</strong> two models, one on Bart Torvik's T-Rank stats and one on "
            "KenPom's, make 80% of the score; the T-Rank, KenPom, NET and ESPN BPI rankings "
            "add 5% each. <strong>Women:</strong> 50% model, 30% T-Rank, 20% NET.</p>",
            "<p><strong>The field:</strong> conference champions (the top team in each "
            "conference until its tournament is played), then the best of the rest, to 68. "
            "Seeds go straight down the order, four per line, six on the 11 and 16 lines.</p>",
            "<p><strong>On the scoreboard:</strong> GORD #N is a team's place in that order; NET "
            "is the NCAA's own ranking; WAB (wins above bubble) is wins beyond what a bubble "
            "team would have against the same schedule; Seed is the AP ranking during the "
            "season and the tournament seed in March.</p>",
        ),
        limits=_p(
            "<p>It ranks a résumé, not who would win on a neutral floor, and the committee's "
            "bracketing rules aren't modeled.</p>",
        ),
        updates="Once a day in season, Nov 1 to Apr 10.",
        curious="Each model is a stacked ensemble: several different models whose answers "
                "another model combines. NET and BPI join once they're released for the "
                "season; until then the other parts share their weight. The separate Power "
                "Rankings page is Torvik's T-Rank, averaged with BPI once it's current.",
        pages=(("Men's scoreboard", "/men/"), ("Women's scoreboard", "/women/"),
               ("CBB power rankings", "/cbb/power/")),
        related=("cbb-predictions", "cbb-watch"),
    ),
    # --------------------------------------------------------- CBB predictions
    # cbb.game_model: pace = tempo x tempo / average; points = AdjOE x opp
    # AdjDE / average x pace / 100; margin = scale x diff + home edge (men
    # 2.53, women 2.67); win = Phi(margin / sd), sd 11.59 men / 11.97 women;
    # 2025-26: 70.2% of 5,315 men's games, 75.3% of 3,827 women's (the season
    # it was fitted on); lines from theScore; not yet graded against them.
    Topic(
        id="cbb-predictions", group="College basketball", name="college basketball predictions",
        title="How the college basketball predictions work",
        summary="How each college basketball game's pick, margin and win chance are made from "
                "Bart Torvik's efficiency ratings.",
        lede="For each college basketball game the scoreboard shows our pick: the favorite, by "
             "how many points, and its chance to win.",
        how=_p(
            "<p>It's a simple formula (the standard possession model) built on Bart Torvik's "
            "adjusted efficiency ratings. The game's pace comes from both teams' usual tempo "
            "(possessions per game), and each side's points from its adjusted offense against "
            "the other's adjusted defense (points per 100 possessions, corrected for "
            "opponents). Home court adds about 2.5 points, none at a neutral site.</p>",
            "<p><strong>Win chance:</strong> results land about 12 points from the prediction "
            "on a typical night. Allowing for misses that size (a normal distribution with an "
            "11.6-point standard deviation for men, 12.0 for women), a 3-point favorite wins "
            "about 60% of the time.</p>",
            "<p>On last season's games, the same season it was tuned on, it picked 70.2% of "
            "men's winners (5,315 games) and 75.3% of women's (3,827).</p>",
        ),
        limits=_p(
            "<p>It isn't graded against the betting line yet. It knows nothing about injuries. "
            "Before Torvik's in-season numbers arrive, men's picks use T-Rank's preseason "
            "ratings and women's games get no pick.</p>",
        ),
        updates="Ratings once a day in season; scores and picks on the scoreboard every 10 "
                "minutes from 11 AM to 1:30 AM Eastern.",
        pages=(("Men's scoreboard", "/men/"), ("Women's scoreboard", "/women/")),
        related=("cbb-rankings", "cbb-watch"),
    ),
    # --------------------------------------------------------------- CBB watch
    # cbb.render.render_watch: grade = 100 x 0.5^((rank - 1) / 100) by GORD
    # rank (unranked #365); strength = harmonic mean; closeness = 100 x (1 -
    # |2p - 1|); score = strength x (0.5 + 0.5 x closeness / 100); Top 25 and
    # tournament nudges; live: within 6 in the last five minutes, OT,
    # underdog ahead in the second half; blowout 18.
    Topic(
        id="cbb-watch", group="College basketball", name="the CBB watch guide",
        title="How the CBB watch guide ranks games",
        summary="How each college basketball game's watch score comes from both teams' ranks "
                "and how close the game should be.",
        lede="The college basketball watch guide ranks each day's games by how worth watching "
             "they should be, grouped by tip-off time.",
        how=_p(
            "<p><strong>Watch score (0-100):</strong> it starts from both teams' GORD ranks, "
            "where #1 counts 100, #101 half that and #201 a quarter. The two are combined so "
            "the weaker team counts most (a harmonic mean). A game that's a coin flip by "
            "our model keeps all of that; a sure thing keeps half.</p>",
            "<p>A Top 25 matchup and a tournament game each close a quarter of the gap to 100 "
            "(the NCAA tournament counts twice). <strong>Toss-up</strong> marks a game "
            "between 42% and 58%; <strong>Upset watch</strong>, an underdog at 35% or "
            "better.</p>",
            "<p>Your starred teams go first. While games are on, a game moves up for a finish "
            "within 6 points in the last five minutes, overtime, or an underdog ahead in the "
            "second half, and drops for a blowout.</p>",
        ),
        limits=_p(
            "<p>It's a guess at entertainment, not a ranking of the teams. Early in the season, "
            "before GORD has ranked anyone, Bart Torvik's T-Rank stands in; a team neither "
            "ranks counts as #365.</p>",
        ),
        updates="Live scores every three minutes while a game is on; the day's games with the "
                "daily update.",
        pages=(("CBB watch guide", "/cbb/watch/"),),
        related=("cbb-predictions", "cbb-rankings", "watch-guide"),
    ),
]


BY_ID: dict[str, Topic] = {t.id: t for t in TOPICS}


def url(topic: str) -> str:
    """The explainer's own page."""
    return f"{BASE}{topic}/"


def _get(topic: str) -> Topic:
    try:
        return BY_ID[topic]
    except KeyError:
        raise KeyError(f"no 'How this works' topic {topic!r}; known: {', '.join(BY_ID)}") from None


def button(topic: str, label: str = "How this works") -> str:
    """The small "How this works" chip, to sit beside the heading or control
    it explains. A link to the explainer's page; with JS_TAG on the page, a
    tap opens it in a dialog instead."""
    t = _get(topic)
    return (f"<a class='gs-how' href='{escape(url(t.id), quote=True)}' "
            f"data-how='{escape(t.id, quote=True)}' "
            f"data-how-title='{escape(t.title, quote=True)}' aria-haspopup='dialog' "
            f"aria-label='{escape(label, quote=True)}: {escape(t.name, quote=True)}'>"
            "<span class='gs-how-chip'><span class='gs-how-i' aria-hidden='true'>i</span>"
            f"{escape(label)}</span></a>")


def section_note(topic: str, label: str = "How this works") -> str:
    """The button on a line of its own - under a section's heading or at the
    foot of a table, where there is no heading to sit beside."""
    return f"<p class='gs-how-note'>{button(topic, label)}</p>"


def article(topic: str) -> str:
    """The explanation itself: what the dialog shows, and the explainer
    page's body. gs-how.js finds it by its class; data-title is the dialog's
    heading."""
    t = _get(topic)
    out = [f"<article class='how-article' id='how-{escape(t.id, quote=True)}' "
           f"data-title='{escape(t.title, quote=True)}'>",
           f"<p class='how-lede'>{t.lede}</p>",
           "<h2>How it works</h2>", *t.how,
           "<h2>Keep in mind</h2>", *t.limits,
           "<h2>When it updates</h2>", f"<p>{t.updates}</p>"]
    if t.curious:
        out.append(f"<div class='how-curious'><h2>For the curious</h2><p>{t.curious}</p></div>")
    out.append("</article>")
    return "".join(out)


def _page_body(t: Topic) -> str:
    out = [share_button.row(url(t.id), f"How this works: {t.name}"), article(t.id)]
    if t.pages:
        links = " &middot; ".join(f"<a href='{escape(href, quote=True)}'>{escape(label)}</a>"
                                  for label, href in t.pages)
        out.append(f"<p class='how-where'><strong>Where to find it:</strong> {links}</p>")
    rel = [BY_ID[r] for r in t.related if r in BY_ID]
    if rel:
        links = " &middot; ".join(f"<a href='{escape(url(r.id), quote=True)}'>{escape(r.name)}</a>"
                                  for r in rel)
        out.append(f"<p class='how-where'><strong>Related:</strong> {links}</p>")
    out.append("<p class='how-where'><a href='/how/'>&larr; Every explainer</a></p>")
    return "".join(out)


def index_body() -> str:
    """/how/: every explainer, grouped by sport."""
    out = []
    for group in GROUPS:
        items = [t for t in TOPICS if t.group == group]
        if not items:
            continue
        out.append(f"<h2 class='how-group'>{escape(group)}</h2><ul class='how-list'>")
        for t in items:
            out.append(f"<li><a href='{escape(url(t.id), quote=True)}'>{escape(t.title)}</a>"
                       f"<span>{escape(t.summary)}</span></li>")
        out.append("</ul>")
    return "".join(out)


INDEX_TITLE = "How this works"
INDEX_DESCRIPTION = ("How GordStats makes its rankings, predictions, playoff odds and fantasy "
                     "numbers, in plain words.")


def generate() -> None:
    """docs/how/<topic>/index.html for every topic, and docs/how/index.html."""
    for t in TOPICS:
        out = OUT / t.id / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(add_front_matter(_page_body(t), t.title, description=t.summary,
                                        updated=False), encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(add_front_matter(
        index_body(), INDEX_TITLE, "How every ranking, prediction and number here is made",
        description=INDEX_DESCRIPTION, updated=False), encoding="utf-8")
    print(f"Wrote {len(TOPICS)} explainers -> {OUT}")


if __name__ == "__main__":
    generate()
