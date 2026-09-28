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
      when the daily run goes stale - **waiting on GitHub Actions being re-enabled for
      the account** (no workflow has ever run in this repo, tests included).
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
