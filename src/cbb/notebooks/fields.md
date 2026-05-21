**data.keys() -> metadata, data**
1. data['metadata']
    - pulled_at
    - pulled_at_readable
    - league_id
    - season  
2. data['data'].keys():  
    - draftDetail  
        * drafted = True  
        * inProgress = False  
    - gameId = 5  
    - id = 1039832288   
    - members  
        * List of team dicts  
            - displayName  
            - firstName  
            - id  
            - lastName  
            - notificationSettings  
    - schedule
        * List of matchup dicts
            - away (same keys as home)
            - home
                * cumulativeScore
                    - losses
                    - scoreByStat
                        * keys 0, 1, 17, 2, 3, 6
                        * values ineligble, rank, result, score
                    - statBySlot
                    - ties
                    - wins
                * gamesPlayed
                * pointsByScoringPeriod
                    - dict with keys 1-10 for day in matchup
                * rosterForCurrentScoringPeriod
                    - appliedStatTotal
                    - entries - List of player dicts
                        * acquisitionDate
                        * acquisitionType
                        * injuryStatus
                        * lineupSlotId
                        * pendingTransactionIds
                        * playerId
                        * playerPoolEntry
                            - appliedStatTotal
                            - id
                            - keeperValue
                            - keeperValueFuture
                            - lineupLocked
                            - onTeamId
                            - player - dict of player...
                            - rosterLocked
                            - status
                            - tradeLocked
                        * status
                * rosterForMatchupPeriod
                    - appliedStatTotal (650)
                    - entries - List of player dicts
                        * acquisitionDate
                        * acquisitionType
                        * injuryStatus
                        * lineupSlotId
                        * pendingTransactionIds
                        * playerId
                        * playerPoolEntry
                            - appliedStatTotal
                            - id
                            - keeperValue
                            - keeperValueFuture
                            - lineupLocked
                            - onTeamId
                            - player - dict of player...
                                * active
                                * defaultPositionId
                                * droppable
                                * eligibleSlots
                                * firstName
                                * fullName
                                * id
                                * injured
                                * injuryStatus
                                * jersey
                                * lastName
                                * lastNewsDate
                                * proTeamId
                                * stats
                                    - appliedStats
                                    - appliedTotal
                                    - id
                                    - proTeamId
                                    - scoringPeriodId
                                    - seasonId
                                    - statSourceId
                                    - statSplitTypeId
                                    - stats (dict 0-44 keys)
                            - rosterLocked
                            - status
                            - tradeLocked
                        * status
                * rosterForMatchupPeriodDelayed
                    - same as two above, differences unknown as of now
                * teamId
                * tiebreak
                * totalPoints
                * totalPointsLive
            - id
            - matchupPeriodId
            - winner
    - scordingPeriodId
    - seasonId
    - segmentId
    - settings
    - status
    - teams - list
        * abbrev
        * currentProjectedRank
        * divisionId
        * draftDayProjectedRank
        * draftStrategy
        * id
        * isActive
        * logo (url)
        * logoType
        * name
        * owners
        * playoffSeed
        * points
        * pointsAdjusted
        * pointsDelta
        * primaryOwner
        * rankCalculatedFinal
        * rankFinal
        * record
            - away
            - division
            - home
            - overall
        * roster
        * tradeBlock
        * transactionCounter
        * valuesByStat
        * waiverRank

