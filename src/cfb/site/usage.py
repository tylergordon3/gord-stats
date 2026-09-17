"""
Usage (docs/cfb/usage/): who is getting the carries and the targets.

The projection pages answer "how good is this player". This answers the
question a college fantasy league actually argues about on a Tuesday - which
back is ahead in a committee, and who the ball is going to now - because a
season projection divided by twelve games cannot see a backfield split 60/40
in September and 80/20 in November.

Everything here is per game, from cfb.usage: carries and targets against the
team's own totals, over the last three played weeks and over the season, with
PPA (CFBD's predicted points added) as the efficiency column beside them.

    python -m cfb.site.usage
"""
from html import escape

import pandas as pd

from cfb import schools as schools_mod
from cfb import usage as usage_mod
from cfb.config import SEASON, WEB_DIR
from cfb.site import write_page

RECENT_WEEKS = 3
MIN_TOUCHES = 4                 # below this a share is one carry of noise
POSITIONS = ("QB", "RB", "WR", "TE")

_CSS = """<style>
table.us{width:100%;border-collapse:collapse;font-size:14px}
table.us th{background:#eef2f7;color:#334155;padding:6px 9px;text-align:center;font-size:12px;
  text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;border:1px solid #e2e8f0;
  position:sticky;top:0;z-index:2}
table.us td{padding:5px 9px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.us td.us-name{text-align:left;font-weight:600}
table.us td.us-team{text-align:left;color:#475569}
table.us tbody tr:nth-child(even) td{background:#f8fafc}
.us-bar{display:inline-block;width:52px;height:7px;border-radius:4px;background:#e2e8f0;
  vertical-align:middle;margin-right:6px;overflow:hidden}
.us-bar i{display:block;height:100%;background:#2a78d6}
.us-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0}
.us-controls select,.us-controls input{font:inherit;font-size:13px;padding:5px 8px;
  border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:#0f172a}
.us-note{font-size:13px;color:#4a5a68;margin:6px 0 12px;line-height:1.55}
.us-scroll{overflow-x:auto;max-height:70vh;overflow-y:auto}
.us-lead{font-size:12px;color:#64748b}
@media (prefers-color-scheme: dark){
  table.us th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.us td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.us tbody tr:nth-child(even) td{background:#1b2540}
  table.us td.us-team,.us-note,.us-lead{color:#aab7c9}
  .us-bar{background:#2b3852}
  .us-controls select,.us-controls input{background:#16203a;color:#dde5ef;border-color:#2b3852}
}
</style>"""

_JS = """{% raw %}<script>
(function(){
  var table=document.querySelector('table.us'); if(!table) return;
  var rows=Array.prototype.slice.call(table.tBodies[0].rows);
  var team=document.getElementById('us-team'), pos=document.getElementById('us-pos'),
      find=document.getElementById('us-find');
  function apply(){
    var t=team.value, p=pos.value, q=(find.value||'').toLowerCase();
    rows.forEach(function(r){
      var ok=(!t||r.dataset.team===t)&&(!p||r.dataset.pos===p)
        &&(!q||r.dataset.name.indexOf(q)>=0);
      r.style.display=ok?'':'none';});
  }
  [team,pos].forEach(function(el){el.addEventListener('change',apply);});
  find.addEventListener('input',apply);
})();
</script>{% endraw %}"""


def _bar(share) -> str:
    if share is None or pd.isna(share):
        return "&mdash;"
    pct = max(0.0, min(float(share), 1.0))
    return (f"<span class='us-bar'><i style='width:{pct * 100:.0f}%'></i></span>"
            f"{pct:.0%}")


def _pct(value) -> str:
    return "&mdash;" if value is None or pd.isna(value) else f"{float(value):.0%}"


def _rows(recent: pd.DataFrame, season: pd.DataFrame) -> str:
    """One row per player: the recent share with its bar, the season share
    beside it in grey, and the raw counts behind both."""
    whole = season.set_index(["team", "athlete_id"])
    out = []
    for _, r in recent.iterrows():
        key = (r["team"], r["athlete_id"])
        season_row = whole.loc[key] if key in whole.index else None
        season_car = None if season_row is None else season_row["car_share"]
        season_tgt = None if season_row is None else season_row["tgt_share"]
        ppa = "&mdash;" if pd.isna(r["ppa"]) else f"{r['ppa']:+.2f}"
        yards = r["rush_yds"] + r["rec_yds"]
        tds = r["rush_td"] + r["rec_td"]
        out.append(
            f'<tr data-team="{escape(str(r["team"]), quote=True)}"'
            f' data-pos="{escape(str(r["pos"]), quote=True)}"'
            f' data-name="{escape(str(r["player"]).lower(), quote=True)}">'
            f'<td class="us-name">{escape(str(r["player"]))}</td>'
            f'<td class="us-team">{escape(str(r["team"]))}</td>'
            f'<td>{escape(str(r["pos"]))}</td><td>{int(r["games"])}</td>'
            f'<td>{int(r["carries"])}</td><td>{_bar(r["car_share"])}</td>'
            f'<td class="us-lead">{_pct(season_car)}</td>'
            f'<td>{int(r["targets"])}</td><td>{_bar(r["tgt_share"])}</td>'
            f'<td class="us-lead">{_pct(season_tgt)}</td>'
            f'<td>{int(r["rec"])}</td><td>{yards:.0f}</td><td>{tds:.0f}</td>'
            f'<td>{ppa}</td></tr>')
    return "".join(out)


def body() -> str:
    frame = usage_mod.load()
    if frame.empty:
        return (_CSS + "<p>No games have been played yet — this page fills in once "
                "<code>python -m cfb.usage</code> has a week to read.</p>")
    fbs = set(schools_mod.load()["schools"])
    frame = frame[frame["team"].isin(fbs)]
    weeks = sorted(int(w) for w in frame["week"].unique())
    recent_weeks = weeks[-RECENT_WEEKS:]

    recent = usage_mod.shares(frame, weeks=RECENT_WEEKS)
    season = usage_mod.shares(frame)
    recent = recent[recent["pos"].isin(POSITIONS)]
    recent = recent[(recent["carries"] + recent["targets"]) >= MIN_TOUCHES]
    recent = recent.sort_values(["car_share", "tgt_share"], ascending=False)

    teams = sorted(recent["team"].unique())
    options = "".join(f'<option value="{escape(t, quote=True)}">{escape(t)}</option>'
                      for t in teams)
    pos_options = "".join(f'<option value="{p}">{p}</option>' for p in POSITIONS)
    controls = (
        "<div class='pin-bar'><div class='us-controls'>"
        f"<label>Team <select id='us-team'><option value=''>All</option>{options}</select></label>"
        f"<label>Position <select id='us-pos'><option value=''>All</option>{pos_options}</select></label>"
        "<label>Find <input id='us-find' type='search' placeholder='player'></label>"
        "</div></div>")

    span = (f"week {recent_weeks[0]}" if len(recent_weeks) == 1
            else f"weeks {recent_weeks[0]}&ndash;{recent_weeks[-1]}")
    head = ("<tr><th>Player</th><th>Team</th><th>Pos</th><th>G</th>"
            "<th>Car</th><th>Car share</th><th class='us-lead'>Season</th>"
            "<th>Tgt</th><th>Tgt share</th><th class='us-lead'>Season</th>"
            "<th>Rec</th><th>Yds</th><th>TD</th><th>PPA</th></tr>")
    return (
        _CSS
        + f"<p>Every FBS skill player's share of his own team's carries and targets over "
        f"the last three played weeks (<strong>{span}</strong>), with the season share "
        "beside it. The two columns together are the backfield answer: a back at 55% of "
        "the carries over three weeks against 40% on the season is taking the job.</p>"
        "<details class='section'><summary>Where these come from</summary>"
        "<p class='us-note'>Carries, receptions and yards are the box scores; the "
        "denominators are the team's own players added up, so a share cannot exceed what "
        "the team ran. <strong>Targets</strong> are not published anywhere as a stat — "
        "they are counted out of the play-by-play text, matching the intended receiver by "
        "jersey number and surname inside his own roster, so a pass whose receiver cannot "
        "be matched counts for the team but not for a player. <strong>PPA</strong> is "
        "CollegeFootballData's predicted points added per play, the efficiency number "
        "beside the volume ones. Snap counts do not exist free for college football; "
        "share of touches is the honest substitute.</p></details>"
        + controls
        + f"<div class='us-scroll'><table class='us'><thead>{head}</thead>"
        f"<tbody>{_rows(recent, season)}</tbody></table></div>" + _JS)


def generate():
    write_page(WEB_DIR / "usage" / "index.html", "CFB Usage", body(),
               subtitle=f"{SEASON} — carry and target share, week by week")


if __name__ == "__main__":
    generate()
