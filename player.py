import pandas as pd

class PlayerDatabase:
    def __init__(self):
        self.list = []

    def add(self, player):
        self.list.append(player)

    def getPlayers(self, sleeperIDs):
        toReturn = []
        for player in self.list:
            if player.sleeper_id in sleeperIDs:
                toReturn.append(player)
        return toReturn
       
class Player:
    def __init__(self, search_name, name, team, position, sleeper_id, stats_id, record):
        self.search_name = search_name
        self.name = name
        self.position = position
        self.team = team
        self.sleeper_id = sleeper_id
        self.stats_id = stats_id
        self.record = record

    def getPoints(self, week):
        # df.loc[df['column_name'] == some_value]
        req_week = self.record.loc[self.record['week'] == week]
        return req_week['points']


class Record:
    def __init___ (self, week, team, points):
        self.df = pd.DataFrame(zip(week, team, points), columns = ['week', 'team', 'points'])