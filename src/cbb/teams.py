import pandas as pd

from . import paths, constants


def getTeams():
    """
    Helper function for getting master teams DF

    :return: Master DataFrame
    :rtype: DataFrame
    """
    df_back = pd.read_json(paths.MASTER_DICT)
    return df_back


def saveTeams(df):
    """
    Helper function for saving master teams DF

    :param df: Master DF to save
    :type df: DataFrame
    """
    df.to_json(paths.MASTER_DICT)


def getTeamInfo(team, debug=True):
    """
    Returns row from team array
    """
    master = getTeams()
    try:
        s_exploded = master["names"].explode()
        boolean_mask_exploded = s_exploded == team

        boolean_mask_original = boolean_mask_exploded.groupby(level=0).any()
        df_result = master[boolean_mask_original]
        if df_result.empty:
            if debug: print(f"getTeamInfo did not find match for: {team}")
            return None
        else:
            return df_result
    except:
        if debug: print(f"getTeamInfo had an exception for: {team}")
        return team


def getTeamNickname(team):
    """
    Get saved nickname for team

    :param team: Team Name
    :type team: string
    :return: Team Nickname
    :rtype: string
    """
    result = getTeamInfo(team)
    try:
        return list(result.short)[0]
    except:
        return team


def getTeamOfficialName(team, debug=True):
    """
    Get official name we are using for team.

    :param team: Team Name
    :type team: string
    :return: Official Name
    :rtype: string
    """
    result = getTeamInfo(team, debug)
    try:
        return list(result.team)[0]
    except:
        return None


def getTeamIndex(team, debug=True):
    """
    Get index of team from master dict.

    :param team: Team Name
    :type team: string
    :return: Official Name | None
    :rtype: string | None
    """
    result = getTeamInfo(team, debug)
    try:
        return list(result.index)[0]
    except:
        return None

def cleanTorvikNames(team):
    for i, char in enumerate(team):
        if char == "(":
            return team[:i]
        if team[i : i + 3] == "vs.":
            return team[:i]
    return team

def normalize_conf(name):
    for key, vals in constants.CONF_MAP.items():
        if name in vals:
            return key
    return name

def getTeamLogo(team, debug=True):
    master = getTeams()
    idx = getTeamIndex(team, debug)
    if idx != None:
        return "/assets/images/" + master.at[idx, "path"]
    return ""

def getTeamLogoShort(team, debug=True):
    master = getTeams()
    idx = getTeamIndex(team, debug)
    if idx != None:
        return  master.at[idx, "path"]
    return ""
    