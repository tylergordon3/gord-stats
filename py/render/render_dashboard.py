from datetime import date
from templates.dashboard import DASHBOARD_TEMPLATE

def render_dashboard(
    league: str,
    games: list,
    edges: list,
    rankings: list
) -> str:
    """
    league: "men" or "women"

    games: list of dicts:
      { "away": str, "home": str, "time": str }

    edges: list of dicts:
      { "team": str, "edge": float }

    rankings: list of dicts:
      { "team": str }
    """

    today = date.today().strftime("%Y-%m-%d")

    league_title = (
        "Men’s College Basketball"
        if league == "men"
        else "Women’s College Basketball"
    )

    today_games_html = "".join(
        f"<li><span><strong>{g['away']}</strong> @ {g['home']}</span>"
        f"<span>{g['time']}</span></li>"
        for g in games[:5]
    ) or "<li>No games today</li>"

    model_edges_html = "".join(
        f"<tr><td>{e['team']}</td><td>{e['edge']:+.1f}</td></tr>"
        for e in edges[:5]
    ) or "<tr><td colspan='2'>No edges available</td></tr>"

    rankings_html = "".join(
        f"<li>{r['team']}</li>"
        for r in rankings[:10]
    ) or "<li>No rankings available</li>"

    return DASHBOARD_TEMPLATE.format(
        LEAGUE_TITLE=league_title,
        TODAY=today,
        TODAY_GAMES=today_games_html,
        MODEL_EDGES=model_edges_html,
        RANKINGS=rankings_html,
    )