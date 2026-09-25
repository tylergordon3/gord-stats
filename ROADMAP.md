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
- [ ] **Waiver adds for your own league.** The lineup is done; the wire is not.
      It needs a free-agent pool for an arbitrary league (everyone priced,
      minus everyone rostered there) scored against the weakest starter - the
      data is all shipped already, so this is renderer work rather than new
      plumbing.
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
