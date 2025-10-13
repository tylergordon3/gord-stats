from sleeper_wrapper import League, Drafts

league_id = 1257466498994143232

# creates the league object and stores its basic data
league = League(league_id)
rosters = league.get_rosters()
users = league.get_users()

# gets the matchups for the first week
matchups = league.get_matchups(week=5)

# retrieves the standings and returns them with user information
standings = league.get_standings(rosters=rosters, users=users)


draft = Drafts(draft_id="1257466498994143233")
allPicks = draft.get_all_picks()

# allPicks format - dict
# dict_keys(['draft_id', 'draft_slot', 'is_keeper', 'metadata', 'pick_no', 'picked_by', 'player_id', 'reactions', 'roster_id', 'round'])
# metadata dict_keys(['first_name', 'injury_status', 'last_name', 'news_updated', 'number', 'player_id', 'position', 'sport', 'status', 'team', 'team_abbr', 'team_changed_at', 'years_exp'])

for pick in allPicks:
    print(pick['metadata'].keys())