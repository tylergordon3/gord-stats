"""
Team profiles - one manager at a time, picked from a dropdown, on the fantasy
home page (docs/fantasy/). Everything comes from fantasy.league.head_to_head's
game log, so the two books stay apart the same way: regular season (weeks
1-14, head-to-head only - no median game) and winners-bracket playoff games.

Every team's profile is rendered at build time and the dropdown only shows
one; the choice is remembered per browser. The graphics are inline SVG and
HTML bars rather than PNGs so they follow the site's light and dark themes,
and every mark carries its numbers as text or a hover title.

    python -m fantasy.site.team_profiles     # prints a summary per team
"""
from html import escape

import pandas as pd

from fantasy.config import ROSTER_NAMES, formal_season
from fantasy.league import head_to_head as h2h

MIN_SPLIT_GAMES = 3          # meetings before an opponent can be a nemesis or a favourite

CSS = """<style>
.tp{--tp-win:#1a7f4b;--tp-loss:#b3382c;--tp-ink:#0f172a;--tp-muted:#64748b;
  --tp-rule:#e2e8f0;--tp-card:#fff;--tp-soft:#f8fafc;--tp-winbg:#d5efdd;--tp-lossbg:#fde2dd;
  margin:6px 0 22px}
@media (prefers-color-scheme: dark){
  .tp{--tp-win:#5fd08f;--tp-loss:#ff8f84;--tp-ink:#e6edf6;--tp-muted:#9fb0c6;
    --tp-rule:#2b3852;--tp-card:#16203a;--tp-soft:#1b2540;--tp-winbg:#18402c;--tp-lossbg:#4a2227}
  .tp-seasons td.champ{color:#facc15}
}
.tp-pick{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 12px}
.tp-pick label{font-weight:700;color:var(--tp-ink)}
.tp-pick select{font-size:15px;padding:6px 10px;border-radius:8px;border:1px solid var(--tp-rule);
  background:var(--tp-card);color:var(--tp-ink);min-width:220px}
.tp-card{background:var(--tp-card);border:1px solid var(--tp-rule);border-radius:12px;padding:16px}
.tp-head{display:flex;align-items:center;gap:14px;margin-bottom:14px}
.tp-head img{width:56px;height:56px;border-radius:50%;flex:none;border:none;padding:0;
  box-shadow:none;background:none;object-fit:cover}
.tp-head .tp-name{font-size:22px;font-weight:800;color:var(--tp-ink);line-height:1.15}
.tp-head .tp-sub{font-size:13px;color:var(--tp-muted)}
.tp-trophy{font-size:13px;font-weight:700;color:#a16207;margin-left:6px;white-space:nowrap}
.tp-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:0 0 16px}
.tp-tile{background:var(--tp-soft);border:1px solid var(--tp-rule);border-radius:10px;padding:9px 11px}
.tp-tile .k{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--tp-muted);font-weight:700}
.tp-tile .v{font-size:22px;font-weight:800;color:var(--tp-ink);font-variant-numeric:tabular-nums;line-height:1.2}
.tp-tile .s{font-size:12px;color:var(--tp-muted)}
.tp-rivals{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px;margin:0 0 18px}
.tp-rival{border-left:4px solid var(--tp-muted);background:var(--tp-soft);border-radius:6px;padding:8px 11px}
.tp-rival.rival{border-color:#2a78d6}.tp-rival.nemesis{border-color:var(--tp-loss)}
.tp-rival.victim{border-color:var(--tp-win)}
.tp-rival .k{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--tp-muted);font-weight:700}
.tp-rival .v{font-size:17px;font-weight:800;color:var(--tp-ink)}
.tp-rival .s{font-size:12px;color:var(--tp-muted)}
.tp h4{margin:14px 0 4px;font-size:15px;color:var(--tp-ink)}
.tp .tp-note{font-size:12px;color:var(--tp-muted);margin:0 0 6px}
.tp svg{display:block;width:100%;height:auto}
.tp svg text{fill:var(--tp-muted);font-size:inherit}
.tp svg .axis{stroke:var(--tp-rule)}
.tp svg .zero{stroke:var(--tp-muted);stroke-dasharray:3 3}
.tp svg circle.w{fill:var(--tp-win)}.tp svg circle.l{fill:var(--tp-loss)}
.tp svg circle.po{stroke:var(--tp-ink);stroke-width:2}
.tp svg circle{stroke:var(--tp-card);stroke-width:1.5}
.tp-vs{width:100%;border-collapse:collapse;font-size:13px}
.tp-vs td{padding:4px 6px;border-bottom:1px solid var(--tp-rule);color:var(--tp-ink);white-space:nowrap;
  background:transparent}
.tp-vs td.opp{font-weight:700;width:1%}
.tp-vs td.rec{text-align:center;font-variant-numeric:tabular-nums;width:1%}
.tp-vs td.avg{color:var(--tp-muted);font-variant-numeric:tabular-nums;width:1%;text-align:right}
.tp-vs td.bars{width:60%;padding:4px 10px}
.tp-bar{display:grid;grid-template-columns:1fr 1fr;align-items:center;height:16px}
.tp-bar .l{display:flex;justify-content:flex-end;border-right:2px solid var(--tp-muted);height:100%;align-items:center}
.tp-bar .r{display:flex;justify-content:flex-start;height:100%;align-items:center}
.tp-bar i{display:block;height:12px}
.tp-bar .l i{background:var(--tp-loss);border-radius:4px 0 0 4px}
.tp-bar .r i{background:var(--tp-win);border-radius:0 4px 4px 0}
.tp-po{font-size:11px;font-weight:700;border-radius:4px;padding:0 4px;margin-left:5px;
  background:var(--tp-soft);border:1px solid var(--tp-rule);color:var(--tp-ink)}
.tp-seasons{width:100%;border-collapse:collapse;font-size:13px}
.tp-seasons th{font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--tp-muted);
  text-align:center;padding:5px 6px;border-bottom:1px solid var(--tp-rule);background:transparent}
.tp-seasons td{text-align:center;padding:5px 6px;border-bottom:1px solid var(--tp-rule);
  color:var(--tp-ink);font-variant-numeric:tabular-nums;background:transparent}
.tp-seasons td.fin{font-weight:700}
.tp-seasons td.champ{color:#a16207}
.tp-key{font-size:12px;color:var(--tp-muted);margin:4px 0 0}
.tp-key b.w{color:var(--tp-win)}.tp-key b.l{color:var(--tp-loss)}
.tp-vs td,.tp-seasons td,.tp-seasons th{border-left:none!important;border-right:none!important}
.tp .strip-narrow{display:none}
@media (max-width:640px){
  .tp .strip-wide{display:none}.tp .strip-narrow{display:block}
  .tp-vs td.avg.score{display:none}
  .tp-vs td.bars{width:45%}
}
.tp-team[hidden]{display:none!important}
</style>"""

JS = """<script>
(function(){
  var sel=document.getElementById('tp-select');if(!sel)return;
  function show(v){document.querySelectorAll('.tp-team').forEach(function(el){el.hidden=el.getAttribute('data-team')!==v;});}
  var saved=null;try{saved=localStorage.getItem('tp-team');}catch(e){}
  if(saved&&sel.querySelector('option[value="'+saved+'"]'))sel.value=saved;
  show(sel.value);
  sel.addEventListener('change',function(){show(sel.value);try{localStorage.setItem('tp-team',sel.value);}catch(e){}});
})();
</script>"""


def team_log(rid: int) -> pd.DataFrame:
    """Every counted game from one manager's side: season, week, kind, round,
    final, opp, pf, pa, margin, result (W/L/T)."""
    g = h2h.games()
    if g.empty:
        return pd.DataFrame()
    mine = g[(g["a"] == rid) | (g["b"] == rid)].copy()
    is_a = mine["a"] == rid
    mine["opp"] = mine["b"].where(is_a, mine["a"]).astype(int)
    mine["pf"] = mine["a_pts"].where(is_a, mine["b_pts"]).astype(float)
    mine["pa"] = mine["b_pts"].where(is_a, mine["a_pts"]).astype(float)
    mine["margin"] = mine["pf"] - mine["pa"]
    mine["result"] = ["T" if pd.isna(w) else ("W" if int(w) == rid else "L") for w in mine["winner"]]
    for col in ("round", "final"):
        if col not in mine:
            mine[col] = None
    return mine.sort_values(["season", "week"]).reset_index(drop=True)[
        ["season", "week", "kind", "round", "final", "opp", "pf", "pa", "margin", "result"]]


def _rec(df: pd.DataFrame) -> str:
    w, l, t = (int((df["result"] == x).sum()) for x in "WLT")
    return f"{w}&ndash;{l}" + (f"&ndash;{t}" if t else "")


def _pct(df: pd.DataFrame) -> float:
    return ((df["result"] == "W").sum() + 0.5 * (df["result"] == "T").sum()) / len(df) if len(df) else 0.0


def _season_name(code: str) -> str:
    return formal_season(code)


def _finish(log: pd.DataFrame, season: str) -> str:
    """The winners-bracket result for one season."""
    po = log[(log["kind"] == "playoff") & (log["season"] == season)]
    if po.empty:
        g = h2h.games()
        decided = set(g.loc[g["kind"] == "playoff", "season"])
        return "Missed playoffs" if season in decided else "In progress"
    last = po.sort_values("week").iloc[-1]
    if bool(last["final"]):
        return "Champion" if last["result"] == "W" else "Runner-up"
    return {1: "Lost quarterfinal", 2: "Lost semifinal"}.get(int(last["round"] or 0), "Playoffs")


def _splits(log: pd.DataFrame) -> pd.DataFrame:
    """Per opponent, both books together and apart."""
    rows = []
    for opp, g in log.groupby("opp"):
        reg, po = g[g["kind"] == "regular"], g[g["kind"] == "playoff"]
        rows.append({"opp": int(opp), "games": len(g), "w": int((g["result"] == "W").sum()),
                     "l": int((g["result"] == "L").sum()), "pct": _pct(g),
                     "reg_w": int((reg["result"] == "W").sum()), "reg_l": int((reg["result"] == "L").sum()),
                     "po_w": int((po["result"] == "W").sum()), "po_l": int((po["result"] == "L").sum()),
                     "margin": float(g["margin"].mean()), "pf": float(reg["pf"].mean()) if len(reg) else None,
                     "pa": float(reg["pa"].mean()) if len(reg) else None})
    return pd.DataFrame(rows)


def rivals(log: pd.DataFrame) -> dict:
    """Rival: the most meetings, the closest average margin breaking ties -
    the pairing that is both frequent and even. Nemesis / favourite opponent:
    the worst and best record against, over at least MIN_SPLIT_GAMES games."""
    sp = _splits(log)
    if sp.empty:
        return {}
    sp["closeness"] = sp["margin"].abs()
    out = {"rival": sp.sort_values(["games", "closeness"], ascending=[False, True]).iloc[0]}
    enough = sp[sp["games"] >= MIN_SPLIT_GAMES]
    if not enough.empty:
        nem = enough.sort_values(["pct", "margin"]).iloc[0]
        fav = enough.sort_values(["pct", "margin"], ascending=False).iloc[0]
        if nem["pct"] < 0.5:
            out["nemesis"] = nem
        if fav["pct"] > 0.5:
            out["victim"] = fav
    return out


def _margin_strip(log: pd.DataFrame, name: str) -> str:
    """Two drawings of the same strip - the wide one, and a narrower one with
    its own geometry for a phone, where scaling the wide one down shrinks every
    dot to a speck. CSS shows one."""
    if log.empty:
        return ""
    return (f'<div class="strip-wide">{_strip_svg(log, name, 640.0, 5.5, 11)}</div>'
            f'<div class="strip-narrow">{_strip_svg(log, name, 340.0, 4.5, 10)}</div>'
            '<p class="tp-key">One dot per game, by margin: <b class="w">wins</b> right of zero, '
            '<b class="l">losses</b> left; ringed dots are playoff games. Hover or tap a dot for the game.</p>')


def _strip_svg(log: pd.DataFrame, name: str, width: float, r: float, font: int) -> str:
    """Every game as a dot on one margin axis - wins right of zero, losses
    left, playoff games ringed - stacked where they would overlap."""
    lim = max(20.0, float(log["margin"].abs().max()))
    lim = float(int(lim / 20 + 1) * 20)
    pad = 18.0
    x = lambda m: pad + (m + lim) / (2 * lim) * (width - 2 * pad)  # noqa: E731
    placed, dots = [], []
    for g in log.sort_values("margin").itertuples(index=False):
        cx = x(g.margin)
        level = 0
        while any(abs(cx - px) < 2 * r + 1 and lvl == level for px, lvl in placed):
            level += 1
        placed.append((cx, level))
        cls = {"W": "w", "L": "l"}.get(g.result, "l") + (" po" if g.kind == "playoff" else "")
        tip = (f"{_season_name(g.season)} "
               + (f"playoff round {int(g.round)}" if g.kind == "playoff" else f"week {g.week}")
               + f": {g.result} vs {ROSTER_NAMES.get(g.opp, g.opp)}, {g.pf:.1f}-{g.pa:.1f} "
               f"({g.margin:+.1f})")
        dots.append((cx, level, cls, tip))
    levels = max(l for _, l in placed) + 1
    base = 12 + levels * (2 * r + 1)
    height = base + 30
    circles = "".join(
        f'<circle class="{cls}" cx="{cx:.1f}" cy="{base - r - lvl * (2 * r + 1):.1f}" r="{r}">'
        f"<title>{escape(tip)}</title></circle>" for cx, lvl, cls, tip in dots)
    ticks = "".join(
        f'<text x="{x(t):.1f}" y="{base + 18:.0f}" text-anchor="middle">{t:+.0f}</text>'
        if t else f'<text x="{x(0):.1f}" y="{base + 18:.0f}" text-anchor="middle">0</text>'
        for t in range(int(-lim), int(lim) + 1, int(lim / 4) if lim >= 40 else 10))
    return (f'<svg viewBox="0 0 {width:.0f} {height:.0f}" role="img" style="font-size:{font}px" '
            f'aria-label="Every game {escape(name)} has played, by margin">'
            f'<line class="axis" x1="{pad}" x2="{width - pad}" y1="{base}" y2="{base}"/>'
            f'<line class="zero" x1="{x(0):.1f}" x2="{x(0):.1f}" y1="4" y2="{base}"/>'
            f"{circles}{ticks}</svg>")


def _vs_table(log: pd.DataFrame, rival_id) -> str:
    sp = _splits(log)
    if sp.empty:
        return ""
    sp = sp.sort_values(["pct", "margin"], ascending=False)
    most = max(int(sp["w"].max()), int(sp["l"].max()), 1)
    rows = []
    for s in sp.itertuples(index=False):
        po = (f'<span class="tp-po" title="Playoff record against">PO {s.po_w}&ndash;{s.po_l}</span>'
              if s.po_w + s.po_l else "")
        name = ROSTER_NAMES.get(s.opp, str(s.opp)) + (" &#9733;" if s.opp == rival_id else "")
        avg = (f"{s.pf:.1f}&ndash;{s.pa:.1f}" if s.pf is not None else "")
        rows.append(
            f'<tr><td class="opp">{name}</td>'
            f'<td class="bars"><div class="tp-bar" title="{s.w} wins, {s.l} losses">'
            f'<div class="l"><i style="width:{100 * s.l / most:.0f}%"></i></div>'
            f'<div class="r"><i style="width:{100 * s.w / most:.0f}%"></i></div></div></td>'
            f'<td class="rec">{s.reg_w}&ndash;{s.reg_l}{po}</td>'
            f'<td class="avg score" title="Average score, regular season">{avg}</td>'
            f'<td class="avg" title="Average margin, every meeting">{s.margin:+.1f}</td></tr>')
    return ('<div class="table-scroll"><table class="tp-vs"><tbody>' + "".join(rows)
            + "</tbody></table></div>"
            '<p class="tp-key">Bars: <b class="l">losses</b> left, <b class="w">wins</b> right, every '
            'meeting. Then the regular-season record (PO: playoffs), the average regular-season score, '
            'and the average margin. &#9733; rival.</p>')


def _seasons_table(log: pd.DataFrame) -> str:
    rows = []
    for season in sorted(log["season"].unique(), reverse=True):
        reg = log[(log["season"] == season) & (log["kind"] == "regular")]
        if reg.empty:
            continue
        fin = _finish(log, season)
        cls = "fin champ" if fin == "Champion" else "fin"
        rows.append(f"<tr><td>{_season_name(season)}</td><td>{_rec(reg)}</td>"
                    f"<td>{reg['pf'].mean():.1f}</td><td>{reg['pa'].mean():.1f}</td>"
                    f"<td>{reg['margin'].mean():+.1f}</td><td class='{cls}'>{fin}</td></tr>")
    return ('<div class="table-scroll"><table class="tp-seasons"><thead><tr><th>Season</th>'
            "<th>Record</th><th>PF/g</th><th>PA/g</th><th>Margin</th><th>Playoffs</th></tr></thead>"
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _tile(k: str, v: str, s: str = "") -> str:
    return f'<div class="tp-tile"><div class="k">{k}</div><div class="v">{v}</div><div class="s">{s}</div></div>'


def _rival_card(kind: str, label: str, row) -> str:
    if row is None:
        return ""
    name = ROSTER_NAMES.get(int(row["opp"]), str(row["opp"]))
    return (f'<div class="tp-rival {kind}"><div class="k">{label}</div><div class="v">{escape(name)}</div>'
            f'<div class="s">{int(row["w"])}&ndash;{int(row["l"])} in {int(row["games"])} meetings, '
            f'avg margin {row["margin"]:+.1f}</div></div>')


def profile(rid: int, team: dict) -> str:
    name = ROSTER_NAMES.get(rid, f"Team {rid}")
    log = team_log(rid)
    if log.empty:
        return f'<div class="tp-card"><p>No games on record for {escape(name)} yet.</p></div>'
    reg, po = log[log["kind"] == "regular"], log[log["kind"] == "playoff"]
    wins, losses = reg[reg["result"] == "W"], reg[reg["result"] == "L"]
    seasons = sorted(log["season"].unique())
    titles = [s for s in seasons if _finish(log, s) == "Champion"]
    trips = sum(1 for s in seasons if not po[po["season"] == s].empty)

    avatar = (f'<img src="{escape(team.get("avatar") or "")}" alt="" loading="lazy">'
              if team.get("avatar") else "")
    trophy = (f'<span class="tp-trophy">&#127942; {", ".join(_season_name(s) for s in titles)}</span>'
              if titles else "")
    team_name = team.get("name") or ""
    head = (f'<div class="tp-head">{avatar}<div><div class="tp-name">{escape(name)}{trophy}</div>'
            f'<div class="tp-sub">{escape(team_name) + " &middot; " if team_name else ""}'
            f"{len(seasons)} season{'s' if len(seasons) != 1 else ''}, "
            f"{trips} playoff trip{'s' if trips != 1 else ''}</div></div></div>")

    tiles = "".join([
        _tile("Regular season", _rec(reg), f"{_pct(reg):.0%} &middot; head-to-head"),
        _tile("Playoffs", _rec(po) if len(po) else "&mdash;",
              f"{len(titles)} title{'s' if len(titles) != 1 else ''}"),
        _tile("Points for", f"{reg['pf'].mean():.1f}", "per game"),
        _tile("Points against", f"{reg['pa'].mean():.1f}", "per game"),
        _tile("Margin in wins", f"+{wins['margin'].mean():.1f}" if len(wins) else "&mdash;",
              f"biggest +{wins['margin'].max():.1f}" if len(wins) else ""),
        _tile("Margin in losses", f"{losses['margin'].mean():.1f}" if len(losses) else "&mdash;",
              f"worst {losses['margin'].min():.1f}" if len(losses) else ""),
    ])
    rv = rivals(log)
    rival_row = rv.get("rival")
    # One opponent can be both the rival and the nemesis (or favourite): one card, both labels.
    labels = {"rival": ["Rival"]}
    extra = []
    for kind, label in (("nemesis", "Nemesis"), ("victim", "Favorite opponent")):
        row = rv.get(kind)
        if row is None:
            continue
        if rival_row is not None and int(row["opp"]) == int(rival_row["opp"]):
            labels["rival"].append(label)
        else:
            extra.append(_rival_card(kind, label, row))
    cards = _rival_card("rival", " &amp; ".join(labels["rival"]), rival_row) + "".join(extra)
    return (f'<div class="tp-card">{head}<div class="tp-tiles">{tiles}</div>'
            f'<div class="tp-rivals">{cards}</div>'
            f"<h4>Every game</h4>{_margin_strip(log, name)}"
            f"<h4>Against each manager</h4>"
            + _vs_table(log, int(rival_row["opp"]) if rival_row is not None else None)
            + f"<h4>Season by season</h4>{_seasons_table(log)}</div>")


def section(teams: dict | None = None) -> str:
    """The whole block: picker plus every profile, one shown at a time."""
    teams = teams or {}
    ids = sorted(ROSTER_NAMES, key=lambda i: ROSTER_NAMES[i])
    options = "".join(
        f'<option value="{rid}">{escape(ROSTER_NAMES[rid])}'
        + (f" &mdash; {escape(teams[rid]['name'])}" if teams.get(rid, {}).get("name") else "")
        + "</option>" for rid in ids)
    panels = "".join(
        f'<div class="tp-team" data-team="{rid}"{"" if i == 0 else " hidden"}>'
        f"{profile(rid, teams.get(rid) or {})}</div>" for i, rid in enumerate(ids))
    return (CSS + '<div class="tp"><div class="tp-pick"><label for="tp-select">Team</label>'
            f'<select id="tp-select">{options}</select>'
            '<span class="tp-note">Regular season is head-to-head only; playoffs are '
            "winners-bracket elimination games.</span></div>"
            f"{panels}</div>" + JS)


if __name__ == "__main__":
    for rid, name in sorted(ROSTER_NAMES.items()):
        log = team_log(rid)
        rv = rivals(log)
        print(name, _rec(log[log["kind"] == "regular"]), _rec(log[log["kind"] == "playoff"]),
              {k: ROSTER_NAMES[int(v["opp"])] for k, v in rv.items()})
