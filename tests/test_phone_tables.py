"""
The league tables on a phone (the 2026-09-29 audit, at 390px).

Four standings/power tables showed the name and one or two numbers: a team
column 231-264px wide, or the site's 150px frozen-column floor, with record,
playoff odds and title odds past the edge. The numbers a reader came for now
sit beside the name, and the name gives way to an ellipsis. The fantasy power
heatmap was light-only - pale-yellow blocks on navy after dark - and the
finished cards on the team dashboard were 2.7:1.
"""
import re

import matplotlib
import numpy as np
import pandas as pd

from gordstats import contrast


def _heads(html: str) -> list[str]:
    return re.findall(r'<th[^>]*class="col_heading[^"]*"[^>]*>([^<]*)</th>', html)


def _power_table(week: int = 4) -> pd.DataFrame:
    return pd.DataFrame({
        "rank": [1, 2, 3], "manager": ["Ann", "Bo", "Cy"], "move": [2.0, 0.0, -1.0],
        "power": [108.0, 100.0, 92.0], "combined": [107.0, 100.0, 93.0],
        "ext_vorp": [106.0, 100.0, 94.0], "wins": [3, 2, 1], "losses": [1, 2, 3],
        "luck": [0.5, 0.0, -0.5], "proj_wins": [18.0, 14.0, 10.0],
        "playoff_odds": [0.9, 0.5, 0.1], "title_odds": [0.3, 0.1, 0.01],
        "week": [week] * 3})


def test_fantasy_power_puts_the_record_and_the_odds_beside_the_name():
    from fantasy.site import power

    heads = _heads(power._rankings_table(_power_table()))
    assert heads[:5] == ["Manager", "Record", "Playoffs", "Title", "Rating"], heads
    # Before a game is played there is no record; the odds still lead.
    heads = _heads(power._rankings_table(_power_table(week=0)))
    assert heads[:4] == ["Manager", "Playoffs", "Title", "Rating"], heads


def test_fantasy_power_shading_is_a_wash_the_theme_shows_through():
    """No opaque fill anywhere (the dark theme could not reach one), and the
    middle of a scale - a Move of 0, the average rating - is no colour."""
    from fantasy.site import power

    html = power._rankings_table(_power_table())
    style = html.split("</style>")[0]
    assert "background-color" not in style
    assert "var(--heat" in style
    heads = _heads(html)
    for col in ("Move", "Rating"):
        assert f"_row1_col{heads.index(col)}" not in style, f"the middle {col} is shaded"
        assert f"_row0_col{heads.index(col)}" in style, f"the top {col} is not"


def test_the_wash_keeps_the_ink_readable_in_both_themes():
    """--heat is how strong the ends of the ramp get, per theme. The inks are
    the site's sticky-table text (custom.css): slate by day, pale at night."""
    from fantasy.site import power

    css = power._TABLE_CSS
    light = float(re.search(r"\.pw-table\{--heat:([\d.]+)\}", css).group(1))
    dark = float(re.search(r"dark\)\{\s*\.pw-table\{--heat:([\d.]+)\}", css).group(1))
    ramp = matplotlib.colormaps["RdYlGn"]
    for heat, ink, cells in ((light, "#334155", ("#ffffff", "#f8fafc")),
                             (dark, "#dde5ef", ("#16203a", "#1b2540"))):
        for t in np.linspace(0, 1, 41):
            wash = tuple(round(c * 255) for c in ramp(t)[:3])
            for cell in cells:
                over = contrast.blend(wash, cell, heat * abs(2 * t - 1))
                assert contrast.ratio(ink, over) >= contrast.AA_NORMAL, (heat, t, cell)


def test_the_cfb_standings_lead_with_the_record_and_cap_the_name():
    from cfb.site import league

    lg = {"teams": [{"name": "Jackson's Brilliant Team", "rank": 1, "wins": 3, "losses": 1,
                     "manager": "Jack", "logo": "x.png", "points_for": 500.5,
                     "points_against": 400.25, "faab": 90, "moves": 4}]}
    html = league.standings_section(lg)
    heads = re.findall(r"<th>([^<]*)</th>", html)
    assert heads == ["Team", "Record", "PF", "PA", "FAAB", "Moves", "Manager"], heads
    assert "<span class=\"lg-nm\">Jackson&#x27;s Brilliant Team</span>" in html
    assert "title=\"Jackson&#x27;s Brilliant Team\"" in html, "no way to read the full name"
    # The logo may not shrink in the table's sums, or the name overruns the
    # pinned column; the cap itself is a phone rule.
    assert "max-width:none" in league._CSS
    phone = league._CSS[league._CSS.index("@media (max-width:600px)"):]
    assert re.search(r"\.lg-nm\{max-width:\d+px", phone)


def test_the_cfb_power_header_leads_with_record_playoffs_title():
    from cfb.site import league_power

    src = open(league_power.__file__).read()
    head = src[src.index("<thead><tr><th>Team</th>"):]
    order = [head.index(s) for s in ("<th>Record</th>", "{odds_heads}", ">Pts/wk</th>",
                                     ">Proj.</th>", "{move_heads}")]
    assert order == sorted(order), "the header is out of the row's order"
    row = src[src.index('f"<td>{_record(t)}</td>{odds}'):]
    assert row.index("{odds}") < row.index("{per_week}") < row.index("{proj_rec}")


def test_all_play_shows_the_season_before_the_weeks(tmp_path, monkeypatch):
    import json

    from fantasy.site import schedule

    rows = [{"week": w, "team_name": n, "points": p}
            for w in (1, 2) for n, p in (("hi", 150.0), ("mid", 100.0), ("lo", 50.0))]
    (tmp_path / "9999.json").write_text(json.dumps(rows))
    monkeypatch.setattr(schedule, "SEASON_DIR", tmp_path)
    styled = schedule.all_play("9999")
    assert list(styled.data.columns) == ["Team", "Total", "Win %", 1, 2]
    assert 'class="sticky-table sc-table"' in styled.to_html()


def test_a_winless_strength_of_victory_is_not_a_black_block(tmp_path, monkeypatch):
    """The ramp has no colour for a missing value; pandas wrote its "bad"
    colour out as #000000."""
    import json

    from fantasy.site import schedule

    # Two weeks, four teams; D loses both, so D has beaten nobody.
    games = {1: [("A", "D", 120.0, 90.0), ("B", "C", 110.0, 100.0)],
             2: [("C", "D", 120.0, 80.0), ("A", "B", 130.0, 100.0)]}
    rows, run = [], {}
    for week, pairs in games.items():
        for a, b, pa, pb in pairs:
            for team, opp, pts, opp_pts in ((a, b, pa, pb), (b, a, pb, pa)):
                pf, pa_, w, n = run.get(team, (0.0, 0.0, 0, 0))
                win = int(pts > opp_pts)
                run[team] = (pf + pts, pa_ + opp_pts, w + win, n + 1)
                pf, pa_, w, n = run[team]
                rows.append({"week": week, "team_name": team, "roster_id": ord(team),
                             "opp": ord(opp), "points": pts, "opp_points": opp_pts,
                             "win": win, "PF": pf, "PA": pa_, "h2h_wins": w,
                             "h2h_loss": n - w, "total_wins": w, "total_loss": n - w})
    (tmp_path / "9998.json").write_text(pd.DataFrame(rows).to_json(orient="records"))
    monkeypatch.setattr(schedule, "SEASON_DIR", tmp_path)

    styled = schedule.schedule_metrics("9998")
    assert styled.data["SOV"].isna().any(), "the fixture needs a winless team"
    assert "background-color: #000000" not in styled.to_html()


def test_finished_cards_recede_without_going_unreadable():
    from gordstats import roster_page

    css = roster_page.CSS + roster_page.CARD_CSS
    light = css.split("@media (prefers-color-scheme: dark)")[0] + \
        roster_page.CARD_CSS.split("@media (prefers-color-scheme: dark)")[0]
    for rule in (r"\.rd-card\.done \.rd-c-sub\{color:(#[0-9a-f]{6})",
                 r"\.rd-card\.done \.rd-c-nm\{color:(#[0-9a-f]{6})",
                 r"table\.rd tr\.rd-done td\{background:#f4f6f8;color:(#[0-9a-f]{6})",
                 r"table\.rd td\.rd-g \.fin\{color:(#[0-9a-f]{6})"):
        ink = re.search(rule, light).group(1)
        assert contrast.ratio(ink, "#f4f6f8") >= contrast.AA_NORMAL, (rule, ink)
    floor = css[css.rindex("@media (max-width:600px)"):]
    for cls in (".rd-c-slot", ".rd-c-opp", ".rd-c-proj small", ".rd-tag"):
        assert cls in floor, f"{cls} is not under the phone floor"
    assert "font-size:12px" in floor
