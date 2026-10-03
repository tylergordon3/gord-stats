# Roadmap

Captured 2026-09-24. Grouped by theme, not priority order within a group.

The framing for all of it: **the site is for the public on a phone.** It was hard
to read at a tailgate because there is too much on screen. When an item below is
ambiguous, the tie-breaker is "fewer words, bigger targets, less chrome".

## 1. Readability and trimming (the stated main focus)

Nothing here is new functionality - it is all removing or tightening what is
already shipped.

### Home - Top 25 by Source
- [x] Retitle to **Top 25 Comparison**; drop the subtitle that just repeats the title
- [x] Add a "last updated" timestamp

### Home - This week's bets
- [x] Organise it; today it is an undifferentiated list
- [x] Timestamp for when the current recommendation was generated
- [x] Countdown to when the picks lock
- [x] Cut the long description at the bottom - nobody reads it. Keep only the
      season record of our picks + a "not gambling advice" disclaimer

### CFB rankings
- [x] Default the sort to GordStats
- [x] Description becomes just the generation timestamp
- [x] Keep the FPI / AP / GordStats glossary, drop the sources from the mini title

### NFL predictions (then mirror onto CFB predictions)
- [x] Drop the score / spread / win-prob line
- [x] Keep a shorter description but remove the "fitted fresh" section
- [x] Rename "The record" to something clearer
- [x] Drop the text between "week 2" and the week filter
- [x] "How it works" -> "How it Works", condensed
- [x] Apply the same cuts to the CFB predictions page

## 2. Prediction scorecard (NFL + CFB)

Headline metrics at the **top** of the predictions page, each one labelled so it
is obvious what it measures. Right/wrong, not accuracy:

- [x] How many winners the model called correctly
- [x] How often our projected spread was on the right side (we say -5.5, team
      wins by 7 -> correct)
- [x] How often the spread we suggested taking against the book was correct
      (we had A 36-30; DK had A -7.5; we said take B +7.5 - did that cash?)
- [x] The same for over/unders
- [x] Consider adding over/under predictions for the NFL in the first place

## 3. Usage pages (Fantasy NFL + CFB)

- [x] Position filter, defaulting to Overall, then RB / WR / TE with the stats
      that matter for that position
- [x] Drop QB, K and DEF from these pages
- [x] RB: carry share, plus a rank showing the carry count, with a minimum to
      qualify; snap %
- [x] WR/TE: snap %, routes run, target %; same sort of minimum
- [x] CFB especially: per-team breakdown, including RB backfield graphs

## 4. Navigation / information architecture

- [x] Standardise tab names across CFB and NFL fantasy: **League Home,
      Matchups, My Team**
- [x] Work out how to combine the rest. NFL has schedule stats, draft
      analytics, etc - could those become one "Analytics" section that is still
      easy to navigate?
- [x] When switching sport, decide whether to keep the user on the same tab

## 5. League sync

The sync half is built (46056842): `/fantasy/sync/` verifies a league with the
provider and stores it against the signed-in account, refresh rate-limited to
five minutes on the stored timestamp. No provider credentials are stored
because neither provider needs any.

- [x] Let users sync their own league: Sleeper for NFL, Yahoo for CFB only
- [x] Requires being signed in so the league stays attached to the account
- [x] Work out what we actually need to prompt the user for - a Sleeper league
      id (the long number in the league URL) or a Yahoo league key
      (`474.l.21318`). Nothing else: no username, password or token.
- [x] A "refresh my league" button, rate-limited by time
- [x] **Usage** reads your league (5d788857). The ownership column and the
      Fantasy filter re-point to a Sleeper league in the browser; everything
      else on the page is NFL-wide and does not move. Local-first, so it works
      signed out; syncing carries it between devices.
- [x] **Matchups** reads your league (e552ddd1). Every matchup, both lineups,
      live points, rendered beside the built page rather than mixed into it.
      Names and projections come from two small files the browser fetches only
      when someone is viewing their own league.
- [x] **My Team** reads your league (81dd68b02). The lineup planner is ported
      to JS and both implementations are asserted equal over generated rosters
      in a browser - which found a pre-existing bug: the Python's flex
      tie-break ran off set iteration order, so the same roster could come out
      differently between builds.
- [x] **Waiver adds for your own league** (386db822b). Same rule, thresholds
      and wording as the built page.
- [x] **League history, waivers and the draft read your league** - the three
      pages that are reads and arithmetic over Sleeper, each beside the built
      page rather than mixed into it.
- [x] **Power rankings for your own league** (ff5c9c8ef). The last of these
      and the only one that is a model: ten thousand seasons, in the reader's
      browser, in a Worker. The projection board is the part no browser could
      compute, so it is published (13 KB gzipped) and carries a per-player
      catch rate, which makes half-PPR and standard exact rather than
      approximate. Checked against the Python exactly where the answer is
      deterministic and inside Monte Carlo error where it is not; on this
      league the two agree to 0.7 of a power point. The published Rating
      blends FantasyPros, which is keyed to this league, so a reader's shows
      the simulation alone and says so.
- [x] **Yahoo withdrawn entirely** (c4eb8b71b). Its public API reaches only
      leagues a commissioner set public, and the rest need OAuth and a stored
      refresh token - which would turn a database worth very little if taken
      into one holding read access to other people's accounts, for leagues
      nobody has asked for. The `provider` column stays so this needs no
      migration if it is ever picked up.

**The migration was applied on 2026-09-25.** The `leagues` table is live and
verified: the endpoint's upsert updates rather than duplicating on a refresh,
and deleting a user cascades their leagues away. `users` and `favorites` were
untouched.

## 6. Bugs

- [x] **The fantasy section failed 6 of 29 scheduled runs** in the week to
      2026-09-25 (be37fe97c). Not the flaky Sleeper handshake, though that is
      the error that surfaced: `games-missed` re-derived every season on every
      run, and five of the six failures were on a season that ended months ago.
      A finished season is written once and skipped after, and the two
      consumers share one fetch. 32 Sleeper calls a run became 4.
- [x] **The FantasyPros id audit cried wolf on every build** (40405495f). It
      compared team names; three managers had renamed their teams. It compares
      roster overlap now, which is what an id actually means.

- [x] Fantasy NFL season-by-season shows `2627` where it should read
      `2026-2027`. The compact `2627` form is the internal season key
      (`fantasy.util.year_str`); it is leaking into the UI.

## Done

- [x] Fantasy section failing ~1 run in 4 on the Pi: Sleeper drops the odd TLS
      handshake and `sleeper_wrapper` retried nothing (0762a208).
- [x] **Section 1, readability and trimming**, in full (66c9ce1b, 01e8dcbe,
      8fdc8d2f). Worth knowing for the sections still to do: the bets card
      read as "just a list" because its classes had no CSS at all, and three
      separate pages led with a paragraph restating what the table or cards
      below already showed. Both are worth checking for before writing
      anything new.
- [x] **Section 6**, the `2627` season label (20f4cf60).
- [x] **Section 3, the usage pages** (66094cc4). Routes run is not obtainable:
      neither Sleeper nor nflverse/PFR publishes it, so Tgt/snap stands in.
- [x] **Section 4, navigation** (76b8cefb). Both fantasy leagues now carry the
      same five tabs and the switcher keeps the reader's tab across sports.
- [x] **Section 2, the prediction scorecard** (15efcb99). Both pages now render
      `gordstats.scorecard`. Two things learned that the remaining sections
      should reuse: the NFL page already had the over/under data captured and
      graded and simply never displayed it (check for that before building),
      and "our projected spread" is ~50% by construction, so it is framed as a
      calibration figure rather than a success rate.

## 7. Audit, 2026-09-27

A six-way review of the whole repo (CFB, fantasy/NFL, shared site code and
browser JS, Functions/deploy/security, CBB/WNBA, and a phone-width visual pass).
Everything below is tested; the commits carry the detail.

- [x] **One failed section no longer stops the site publishing** (4eaa3f80c).
      The Sep 23-24 fantasy failures had left CFB and NFL unpublished too. A
      conflicting pull no longer wedges the Pi.
- [x] **CBB ready for tipoff** (213dfd487): models retrained (the 2026 pickles
      would not load under scikit-learn 1.9) and pinned; KenPom year and
      auto-bids derived; Torvik from its CSVs; daily bracket pages back on and
      archived; NET waits for its first release; the live scoreboard is fed by
      the live tick for the first time.
- [x] **CFB numbers** (be3c60017, 9e666404f): picks locked on the day, spread
      pushes, TBD kickoffs, late games live, drop list, one in-season board
      (frozen at the draft, blended with box-score points), box-score archive
      never shrinks, zero games count in defence-vs-position, title-game
      rematches keep their own line.
- [x] **Fantasy numbers** (49949e2ed): a week counts once Sleeper moves past
      it, 2026-27 not graded as finished, season file refreshes, Waiver Watch
      back, usage shares include the QB, all-play sorts as numbers, the power
      page no longer says "no draft yet" on a Sleeper outage.
- [x] **Live matchups** (0b427741c): projection columns move during games;
      the live poll stays inside the week being played.
- [x] **Readers' leagues** (92768dc5b): superflex, taxi squads.
- [x] **Security** (87c2fa77c): the sign-in open redirect.
- [x] **Favourites** (d3714c3f8): a star set just before leaving is not undone.
- [x] **Security hardening** (b4ad43e19..3b3eba338): favourites write only
      changed rows under a per-account daily ceiling; league sync is bounded
      (40 Sleeper calls), claimed atomically and capped per account; score
      proxies cached; typed session tokens, ID-token `exp`/`email_verified`,
      no cross-site sign-out; Functions syntax-checked in CI. D1 migration
      004 applied 2026-09-27.
- [x] **Phone layout** (58d3c0a9e..9dcc721fc): the header scrolls away on
      phones and Fantasy's nav is one row (pinned chrome 475px -> 53px on
      /cfb/usage/); usage pages have one scroller and folded filters; logos
      fetched at their drawn size (/men/conference.html 19.9 MB -> ~1.6 MB);
      muted text, footer and live line pass contrast; bigger tap targets;
      charts and grids in dark mode; shorter intros.
- [x] **Pre-game projections archived** (1bdbbf60a): CFB and NFL matchups keep
      what GordStats projected before each kickoff; "going in" and the NFL
      accuracy table use only those. The NFL prediction archive no longer
      loses a game's pre-kickoff line to a mid-game capture.
- [x] **Fantasy title odds follow the real bracket** (82d33f99b), checked
      against 2023-24, 2024-25 and 2025-26 (each champion at 100%).
- [x] **CBB rehearsal** (ed89fde39): the in-season path run end to end; the
      live scoreboard crash on events with no description and unreadable,
      unbounded KenPom errors fixed.
- [x] **Bowls and the CFP** (fa8337cf6): the CFB section's postseason week.
- [x] **Matchups move with the games** (82a09fb3a..2f61290de, 36f9d43e6): each
      source's expected final and a win bar per source (GordStats and Sleeper /
      Yahoo) in its own row; readers' leagues poll Sleeper and ESPN; NFL game
      clocks were read off the wrong object and every live game counted as half
      over; readers' median trackers get real ceilings and floors.
- [x] **Top 25**: a team outside the AP poll is compared at its place in the votes.
- [x] **CFB predictions corrected by opponent-adjusted efficiency** (d2e834334):
      CFBD box-score stats, margin RMSE 16.18 -> 16.07 on 2020-25, better in all
      six seasons. Refit with `python -m cfb.backtest --report` once a season ends.
- [x] **CFB usage lists only rosterable players** (e1e6ae8f7): Power 4 + Notre Dame.
- [x] **CFB power plays out the rest of the season** (3c223e193): best lineup each
      week, median game, six-team reseeded bracket - playoff, bye and title odds.
- [x] **NFL power: backs, receivers and TEs halfway to Sleeper in season**
      (f241619f5): next-four-weeks RMSE 5.14 -> 5.05 on a 2023-25 replay.
- [x] **NFL efficiency correction: tried, not shipped.** nflverse team-week EPA and
      friends, adjusted the CFB way, never beat the score-only ratings on 2015-19
      (13.08) or 2020-25 (13.13 vs 13.12). Play-by-play with garbage time filtered
      is the only untried variant.
- [x] **CFB title odds through the playoffs** (ddfcc66a4): played rounds as they
      happened, seeds from the archived regular season.
- [x] **Tests never reach the network** (efaaf792c); the league-sync race that
      made one test flaky was a real 301-second retry-after (732e4dce0).
- [x] **League Home in one format** (c4e623174, 7d65771e2): the site's own league
      synced by id gets the built pages; a synced league's home is the built format
      (All-Time Metrics, team profiles) from Sleeper; History/Draft Review show this
      league when none is picked.
- [x] **League Home leads with the week** (4b4f3f3a0): matchups with live scores and
      the standings, for whichever league is on screen.
- [x] **Publishing** (5e632541f): the upload retried; status.json; a freshness issue
      when the daily run goes stale. GitHub Actions is back on (2026-09-30): the tests
      pass on every push (7cb233473) and the freshness check runs every two hours.
- [x] **Small fixes** (41db51a58, b2601de44, 29ac0e005): NFL points file junk rows
      and two unmatched players; the sync page says when a sync was cut short; tests
      never depend on a cache's age.
- [x] **"My teams this week" on Home** (b3747f44e): starred college teams' games,
      our pick, the line and the live score.
- [x] **My teams carries college basketball** (a897a3fa4): the day's games from the
      live scoreboard Worker, GordStats' ranks and the line, beside football from Nov 2.
      CBB has no per-game model, so a rank stands where football shows a pick.
- [x] **CBB scoreboard payload** (cf39e5e30): every game carried Torvik's whole table
      (~92 KB, unread) - ~30 MB on opening night, past KV's 25 MB limit.
- [x] **Links in texts work** (2026-09-28): the bare domain's redirect rule pointed at
      `https://gordstats.com{2}` (dead), and Cloudflare Bot Fight Mode challenged every
      preview fetcher - both fixed in the dashboard. Then robots.txt, a sitemap
      (a8a80319b) and a wide link-preview card (f9f72c084). Optional: add the site to
      Google Search Console and submit /sitemap.xml.
- [x] **Weekly recap + lineup accuracy, both leagues** (e3fdf872c): /fantasy/recap/ and
      /cfb/recap/ - scores, fifteen awards, and share of the best possible lineup started
      (week and season). NFL max points equal Sleeper's own for every team. Projection
      awards start with the first week the pregame archive fully covers (NFL week 4,
      CFB week 5). Possible next: the same for readers' synced leagues, in the browser.
- [ ] Late October: rerun the CBB rehearsal once KenPom posts 2027 preseason
      ratings (it answers 400 until then).
- [ ] Nov 3: check the Pi's first in-season CBB run, and that Torvik publishes
      `2027_fffinal.csv` and `ncaaw/2027_team_results.csv` (both 404 today).
- [ ] Still by hand each year: `nfl/config.SEASON`, `wnba_remaining.WEEK_DATES`,
      `cfb/lines.load(last=...)`, `cfb/schools.BRIDGE_SEASON`, and
      `data/cfb/games/<season>.parquet` for the next season's fit; then
      `python -m cfb.backtest --report` to refit the efficiency correction on the
      finished season, and `cfb.config.LEAGUE_CONFERENCES` if the league's pool moves.

## 8. Audit, 2026-09-28

Six reviews (security, a live phone sweep of 56 pages, fantasy/NFL code, CFB/CBB code, ops on
the Pi, features). Done the same night:

- [x] **Names are text** (39d1e82a8): page bodies are literal to Jekyll except tags marked with
      `frontmatter.liquid()` - a team named `{%x%}` used to fail the build; unescaped Yahoo/Sleeper
      team names on the CFB league, league power, draft review and NFL schedule pages.
- [x] **API on www only; visit counter capped; HSTS / no framing** (8cec18485).
- [x] **CBB opening night** (099d6ea7e): the scoreboard died on any non-D1 opponent; last
      season's NET/BPI/ATS/ranks; BPI not-released; tipoff Nov 1; timeouts.
- [x] **CBB scoreboard page + My teams** (a0227759c): 2-minute polling paused when hidden, feed
      text neutralised, dark cards; My teams shows the day's games.
- [x] **CBB lines archived** (7cbed974b): closing spread/total + final, data/cbb/lines/.

- [x] **Old Pages deployments deleted** (8,507, running 2026-09-28 night) and a rate-limit
      rule on www `/api/*` (added by the user).
- [x] **Pi** (ca0c9ebbd, 699cfc9c1): a conflicting rebase resolves in the Pi's favour; network
      blips skip a tick and mail at most hourly; ticks wait for new deps; fantasy live commits
      hourly during games; key files 600; data files rewritten only when changed (~7 MB/day).
- [x] **Wrong numbers** (4c6be0d83..4108e61ec): recap pickups from rosters, CFB power windows,
      no median in the playoffs (recaps and matchups), byes, finished-week cards, CFB Proj.
      in the playoffs, "time TBA" kickoffs, outside projections frozen at kickoff, stat
      corrections re-read once, week files after the rollover, readers' power on Monday.

- [x] **Since:** CBB game predictions on the scoreboard and My teams (1bef36312); bets card in
      sportsbook signs (ea41f47ce); CFB league power backfilled to the draft (4ae0271a6).
- [x] **ESPN leagues for readers** (6db064df4, b22d4c21a): `window.GSAPI` answers ESPN public
      leagues in Sleeper's shapes for every reader page; ids/URLs in the league bar; account sync by
      id with every season. Built on the WNBA league's real (anonymised) shapes + ESPN's football
      defaults; League Home, Matchups and My Team checked in a browser on a stubbed league.
- [ ] **ESPN follow-ups:** verify on the friend's public NFL league; confirm ESPN answers the
      Worker (account sync). A league added by id opens on the team last picked on My Team
      (d9abb9f7d); matching the reader's ESPN team automatically would need their login.

Open:
- [ ] **Dec/Jan:** bets card locks once for all bowls; "Week 20" labels; bowls lack CFBD weather
      and usage; NFL postponed games / TBD playoff placeholders; yearly CFB refit stuck on 2020-25.
- [x] **Phone polish** (f2dea6629..af7e8340a): power table header, CFB round column, finished
      slots and red tags in dark; women's History/Conf routed and lit; team pages light Rankings;
      clean URLs in nav/home/sitemap; no signed-out 401; CFB schedule controls on one row;
      distinct tab titles.
- [x] **Per-page preview images** (9b96f42c0, 6c79937f9): recaps, matchups, both power pages and
      the CFB Top 25 draw their own 1200x630 card (gordstats.share_card); the home page keeps the
      site card.
- [x] **Fantasy tabs** (ffa9989a0): Home · Matchups · Team · Power · Usage in both leagues; the
      Analytics archive is League Home's League Records (finding cards); /fantasy/injuries/.
- [x] **Share button** (31bc10572): recaps (week permalink + headline), matchups, both power
      pages and the home bets card; share sheet on phones, copied link elsewhere.
- [x] **Stakes / game of the week** (637a7e3a9): both sims split playoff odds on the next game;
      power pages' stakes table, matchups' game-of-the-week callout (ranked by 2p(1-p) x swing).
- [x] **Schedule difficulty** (b5a372b59): record vs all-play split into opponents' strength and
      timing (gordstats.schedule_luck); /fantasy/schedule/, League Records card, CFB League Home.
- [x] **Honest bets record** (gordstats.bet_record): the home card's locked picks in units (a unit on
      each week's single and parlay at -110) and against DraftKings' last line before kickoff, per
      pick and for the season; both predictions pages carry units on their two records against the
      book and a fifth tile, "Line moved our way", from each early-week call. At launch the CFB
      model's early-week lines moved toward it 127 of 213 times (+0.4 pts a call) while its spread
      calls ran 46% at the close and 97-105 at the open - it sees some of what the market later
      does, not enough to pay; totals at the open 59-49.
- [x] **Watch guide** (1df7cf8c7): /cfb/watch/ - the day in Eastern kickoff windows, each ranked by
      ESPN's matchup quality nudged for Top 25 matchups and playoff stakes; starred teams first,
      the reader's Yahoo players named, live games that are close late jump the queue.
- [x] **Phone pass, 2026-09-29** (d6faaac15..2bf3e3fbc): a 30-page audit at 390px. One sign-in
      offer a screen; 40-44px controls; CBB nav on one row; long tables keep their column names
      (stickyhead.js); matchups fold on a phone; the predictions record swipes; a 12px text floor;
      schedule cards 410 -> 185px with one pinned row; league tables lead with record and odds; the
      fantasy heatmap in dark; /cfb/ leads with numbers; CBB power, offseason scoreboard, tip-off.
- [x] **Watch guides in all three sports** (53066e4a8..6fa08e49a): one engine (gordstats.watch_page);
      /nfl/watch/ ranks by ESPN matchup quality with your Sleeper starters and your opponent's in
      each game; /cbb/watch/ is built in the browser from the live scoreboard feed, men's and women's.
- [x] **Team Stats, CFB and NFL** (8059ab835..c4e995fa1): one sortable, shaded table in tabs
      (gordstats.stats_page) with player leaderboards. CFB from CollegeFootballData (opponent-adjusted
      EPA/success, havoc, line yards, points per trip, box score, talent, player EPA); NFL from nflverse
      play-by-play (EPA, success, PROE, pace, red zone, leave-one-out opponent adjustment, QB CPOE).
      Every CFB team page carries an Advanced block with FBS ranks.
- [x] **NFL mirrors CFB** (49efb509d, df40ce9b2): /nfl/power/ (GordStats + FPI, odds, movement, stars),
      32 team pages with an Advanced block, /nfl/schedule/, and the bets card (shared gordstats.bets_card)
      on Home and /nfl/.
- [x] **CBB Team Stats** (dc975ed16): Torvik's efficiency, tempo, SOS; four factors once he publishes them.
- [x] **Playoff picture** (b31235a72): clinched / eliminated / magic number / win-and-in on both fantasy
      power pages (gordstats.clinch), never contradicting the sims.
- [x] **Recaps for readers' leagues** (0749184e6): Sleeper and ESPN, in the browser (gordstats.my_recap).
- [x] **Trade analyzer** (/fantasy/trade/, /cfb/trade/, under the Team tab): pick a deal and see both
      teams' points a week, record, playoff and title odds before and after (gordstats.trade_page).
      NFL and readers' Sleeper/ESPN leagues run gordstats.my_power's simulation in the browser; the
      college league ships its weekly projections and runs a JS port of cfb.league_sim. Both runs
      share their draws, so a trade of nothing changes nothing; rosters stay legal (drop the worst
      bench player / sign the best free agent at the position given up).
- [x] **Shared-module follow-ups**: GSAPI answers ESPN lineups for any played week on request
      (`{lineups:true}`) and caches each path per page; my_recap uses both and GSPlan's flex table;
      the recap's empty avatar disc has an initial; the Playoff Picture is a callout on both matchups
      pages (clinch.callout, docs/*/playoff-picture.json); Share on a reader's league sends
      `?league=<id>`, shown for the visit without replacing the recipient's own league.
- [x] **Phone, the last open items**: the reader's own power table in the built table's order and
      wash; /cfb/power/'s pinned bar one row (a Since menu); the CFB schedule's picks folded to one line
      (first game 799 -> 523px); bracketology and history intros were already trimmed.
- [x] **Quadbox** on all three watch guides: a List / Quadbox switch; each window's best four on one
      screen (sound on the best, never two on one broadcast channel - NFL assumes Sunday Ticket), the
      next in line, and an On now box that keeps its places and swaps out a game that ends or turns
      into a blowout (also now a -30 on the watch score in the second half).

- [x] **Game previews** (04a25cad8, eabb0cb75): /cfb/game/, /nfl/game/ and (from tip-off) /cbb/game/ -
      the call against the book, unit against unit with national ranks, players, form; linked from
      the schedules, watch guides and predictions.
- [x] **Playoff odds** (cdd9962d9): /cfb/playoff/ (2026-27 CFP rules) and /nfl/playoff/ on our model,
      beside ESPN FPI, with the likeliest bracket.
- [x] **Matchup Strength for the NFL league** (30b74a476): /fantasy/strength/, readers' leagues too.
- [x] **CBB stats fixes** (8fb302345): Torvik's four factors read by team (would have been empty in
      November), OR% allowed low-good, Siena's logo.
- [ ] **CBB previews, first real day (Nov 3):** check /cbb/game/ pages appear and the guide links them;
      women's previews need the women's T-Rank/four factors cached first.
- [x] **College and pro football together** (bf19fe541): /watch/ merges both watch guides (one list, one
      quadbox, both fantasy teams, live scores), and Home leads with a Tonight card on nights both play.
- [ ] **At tip-off:** put CBB in /watch/ and the Tonight card (its guide reads the live Worker feed).
- [x] **Waiver impact** (8761a06c3): Trades & Pickups' Pick up mode ranks the free agents by what each does
      to your title and playoff odds, both leagues and readers' own; NFL free agents now real players only.
- [x] **Playoff odds history** (09da6e6cf): kept build by build from 2026-10-01; a Wk column from a week on.
- [x] **Later in the season:** a chart of each team's playoff odds (da6de656b, both fantasy Power pages) over the season, from that history.
- [x] **NFL injuries, beyond the tag** (0d61dd29e, 4af15ac7c, 4cd418cec, 940545f65): ESPN's return dates
      instead of IR = 4 weeks; next man up (teammates' share of an injured player's points, measured
      2019-25) in the board, power, trades and pickups; this week's chance to play from status, role
      and the last practice (Doubtful plays 1%, not 25%), with pills on Team and Matchups.
- [x] **Injuries, next:** back-from-injury dip (9509baaad: by games missed - type adds nothing); expert feeds (Bluesky/Substack
      RSS of PTs and doctors - waiting on a list of accounts); CFB conference availability reports.

## 9. Audit, 2026-10-02

Seven reviews (security, fantasy/NFL code, CFB/CBB code, browser JS on 52 live pages, two phone
sweeps at 390/360/320 in both themes, ops/performance on the Pi), then fixes the same day:

- [x] **Security:** WNBA team names escaped and every generated include literal to Jekyll; the
      sign-in `next` can't resolve to `//host`; every JS `esc()` escapes `'`; Sleeper slot names
      can't break out of a class; CBB feed scores and days escaped; JSON in `<script>` through
      `jsonio.script_json`; Sleeper custom avatars only from sleepercdn.com; cross-site API writes
      refused (Sec-Fetch-Site / Origin); `nosniff`, `object-src 'none'`, `base-uri 'self'`.
- [x] **Wrong numbers, NFL:** the 2026 Super Bowl is ESPN week 4 (postseason weeks from ESPN's
      calendar); playoff odds pin the real seeds after week 18 and knock out real losers; an ESPN
      outage serves the cached schedule; a called-off game no longer freezes the week; power/team
      records are regular season only; TBD kickoffs on the watch guide and cards; ties are no
      winner to call; the bets card survives a week with no lines; a cancelled pick is a push.
- [x] **Wrong numbers, fantasy:** the bracket reseeds as Sleeper does (Python and the browser) and
      takes decided rounds; ties are half a win; Doubtful players out of Disagreements; weeks 1-3
      GS 0.0 for players who played; frozen projections keep their frozen play chance; IR in
      trades; dropped players no longer shift the trade sim's draws; played playoff weeks in the
      browser sim; an nflverse blip falls back to the stored points instead of publishing (and
      archiving) preseason-only power (the 2026-09-30 23:36 snapshot).
- [x] **Wrong numbers, CFB/CBB:** cancelled/postponed games dropped at the source (no double
      meeting with the replay); no "TBD at TBD" previews; the predictions card quoted the book on
      the other team's side for every away favourite; untimed Saturday games filed under Friday;
      playoff records count title games and the CFP; plays a game count every snap; CBB lines
      publish merges.
- [x] **Browser JS:** reader Matchups/Team showed everyone on bye when week-context was missing
      or a week old; the watch guides dropped Saturday's late games at midnight ET; a failed
      Yahoo proxy wrote "0.0 final" over every started player; trade-page timers, phantom trades
      and league-tagged share links; the league bar and the page could show different leagues;
      last season's league drawn as this week; home cards and the league strip wake at kickoff;
      CBB overtime; conference dropdown with a stale saved value or blocked storage.
- [x] **Phone:** /cfb|nfl|cbb/stats/ and /cfb/matchups/ scrolled sideways; Home's empty bar
      (`[hidden]` vs the theme); sticky header copies keep the frozen column when swiped; usage
      and DvP tables keep their column names; the theme's black table lines; trade analyzer's
      Pick up columns and squeezed names; dark logos and watch chips; 12px floor; ~40px targets;
      a 2-column phone chart on both power pages; real names on /fantasy/injuries/.
- [x] **Ops:** the Pi commits each run's data before Jekyll (a failed build no longer discards
      the captures); the theme is vendored (no GitHub download per build); CSS/JS hashed under
      /assets/v/ and cached for a year; the live tick runs CBB first, every gate every tick,
      failures through tick_trouble; timeouts on every HTTP call; deploy/linkcheck.py before each
      upload; wrangler logs pruned; CI skips the Pi's data commits and each Chromium gets its own
      profile; the watch-quad test no longer fails 23:00-01:10 ET.
- [x] **Page weight:** both matchups pages carry only the current week, the rest fetched on tap
      from docs/<section>/matchups/week-N.html (/cfb/matchups/ 1.45 MB -> 368 KB and 27.6k -> 5.7k
      elements; /fantasy/matchups/ 1.36 MB -> 516 KB - and no longer growing toward ~5 MB by the
      playoffs); the Median Tracker folds each team on a phone (1,888 -> 787px); /fantasy/draft/
      1.08 MB -> 514 KB, transactions 119 -> 40 KB, schedule 155 -> 93 KB
      (fantasy.site.styles.to_html: no per-cell ids or rules, same look).

- [x] **What's new** on Home and /changelog/ (gordstats.changelog): a line per user-facing
      feature, newest first; add one with every feature that ships.

- [x] **Layout shift** (9c41867c2): Web Analytics had League Home at 0.31-0.43, Power 0.74,
      Matchups 0.72, Team 0.54, trade 0.28, Home 0.13; every late-drawn block now has its room
      (week strip, league bar, My teams prompt, sign-in invite, trade analyzer, scrollbar gutter) -
      0.000-0.004 measured live. `pi analytics [days]` reports readers, pages, phones and speed.

Open:
- [ ] **Analytics again ~Oct 16** (`pi analytics 14`): new pages' adoption (trade, /watch/,
      stats, playoff odds, previews) - promote or trim; confirm CLS stays under 0.1. Profile
      signed-in still shifts ~0.05-0.16 in the first 50 ms (owner-only page; cause not found).
- [ ] **After the first in-season CBB daily run (Nov 1+):** `git rm --cached
      docs/men/conference.html docs/women/conference.html` and commit (now in .gitignore; removing
      them before tip-off would 404 /men/conference until the run rebuilds it).
- [x] **First deploy of these changes** (2026-10-02, twice): data recorded before Jekyll, `linkcheck:
      427 pages`, the gems stamp written, `/assets/v/<hash>/custom.css` served immutable.
- [x] **Git growth (~8 MB/day on the Pi):** (96a6e1880: archives by day/week, CFB caches ignored - ~0.7 MB/day) whole-season files rewritten in full
      (cfb usage/gameinfo/boxscores/predictions, nfl predictions, wnba_defense) - partition by week
      or move re-derivable caches out of git; stop rewriting wnba_defense for its stamp.
- [x] **Live ticks drop pregame captures** (6d8383388: gs_proj_live sidecar on the Pi) between hourly commits (they start from
      `git checkout -- docs data`): an ignored live file the daily run merges, like cbb/lines_live.
- [x] **Inline JS repeated on every fantasy page** (20d82b61a: docs/assets/js/gs-*.js) (GSAPI + league bar + GSL ~50 KB, GSRecap,
      GSWatch): move to /assets/js/ now that assets are content-hashed.
- [x] **/fantasy/power/** (ed575e647: styles.to_html, no per-cell ids; usage pages trimmed earlier) still renders pandas' own Styler HTML (203 KB, 426 ids): use
      `styles.to_html` and update test_phone_tables' shading test. Usage tables repeat
      `class="v-overall v-rb v-wr v-te"` on every cell (~300 KB on /cfb/usage/).
- [x] **Security, low:** (db8657c01: site write ceiling, session epoch, __Host- cookie; Report-Only CSP still open) a global daily D1 write cap (not just per account); session revocation
      (an epoch in the token); throttle failed league-sync lookups; a Report-Only `script-src`.
- [x] **SEO:** (0de537bc2: a description per page, h1s, previews kept all season + a 404 for expired ones) 38 pages share the site description; Home and /cbb/ have no h1; game previews
      404 a week after the game (a fallback to the schedule).
- [ ] **Readers' injury board** still counts a hold from the lagging week (needs a new board
      field); Sleeper two-week playoff rounds in the power sim; ESPN leagues have no reseed flag.
