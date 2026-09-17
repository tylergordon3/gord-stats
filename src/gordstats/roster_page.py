"""
The look and the moving parts both team dashboards share (/cfb/roster/ and
/fantasy/roster/): the stylesheet, the team menu that remembers "my team", the
change pills, and the box that lists a roster's changes.

A row's colour says what the lineup plan (gordstats.lineup) does with the
player: green comes off the bench, red goes to it, blue stays a starter but
changes slot for the kickoff order.
"""
from html import escape

CSS = """<style>
.rd-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;margin:6px 0 10px}
.rd-head img.rd-tlogo{width:44px;height:44px;border-radius:50%;border:0;padding:0;margin:0;
  box-shadow:none;background:none}
.rd-head .rd-nm{font-size:20px;font-weight:700;color:#0f172a;line-height:1.2}
.rd-head .rd-sub{font-size:13px;color:#64748b}
.rd-tiles{display:flex;flex-wrap:wrap;gap:8px;margin-left:auto}
.rd-tile{border:1px solid #e2e8f0;border-radius:10px;padding:6px 12px;background:#fff;
  text-align:center;min-width:92px}
.rd-tile b{display:block;font-size:18px;color:#0f172a}
.rd-tile span{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#64748b}
.rd-tile.up b{color:#15803d}
.rd-pick{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0}
.rd-pick select,.rd-pick button{font:inherit;font-size:13px;padding:5px 9px;border-radius:8px;
  border:1px solid #cbd5e1;background:#fff;color:#0f172a}
.rd-pick button{cursor:pointer;background:#f8fafc}
.rd-pick button.on{background:#fef3c7;border-color:#f59e0b;color:#92400e;cursor:default}
.rd-moves{margin:4px 0 12px;padding:10px 14px;border-left:4px solid #2a78d6;background:#f1f6fd;
  border-radius:0 8px 8px 0;font-size:14px;line-height:1.6;color:#0f172a}
.rd-moves.ok{border-left-color:#16a34a;background:#f0fdf4}
.rd-moves ul{margin:0;padding:0;list-style:none}
.rd-moves li{padding:3px 0}
.rd-moves-h{font-weight:700;font-size:15px;margin-bottom:4px}
.rd-pill{display:inline-block;min-width:64px;text-align:center;padding:1px 8px;border-radius:9px;
  font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.02em;margin-right:6px}
.rd-pill.in{background:#16a34a;color:#fff}
.rd-pill.out{background:#dc2626;color:#fff}
.rd-pill.swap{background:#2563eb;color:#fff}
.rd-pill.warn{background:#d97706;color:#fff}
.rd-to{display:block;font-size:12px;font-weight:700;margin-top:2px}
table.rd td.rd-mv{min-width:84px}
table.rd td.rd-mv .rd-pill{margin-right:0}
table.rd tbody tr.rd-in td{background:#dcfce7;color:#0f172a}
table.rd tbody tr.rd-out td{background:#fee2e2;color:#0f172a}
table.rd tbody tr.rd-swap td{background:#dbeafe}
table.rd tbody tr.rd-in td:first-child{box-shadow:inset 4px 0 0 #16a34a}
table.rd tbody tr.rd-out td:first-child{box-shadow:inset 4px 0 0 #dc2626}
table.rd tbody tr.rd-swap td:first-child{box-shadow:inset 4px 0 0 #2563eb}
table.rd tbody tr.rd-in td.rd-p .nm{font-weight:700}
.rd-legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:#475569;margin:0 0 6px}
.rd-legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;
  vertical-align:-1px}
.rd-legend i.in{background:#16a34a}.rd-legend i.out{background:#dc2626}
.rd-legend i.swap{background:#2563eb}
.rd-scroll{overflow-x:auto}
table.rd{width:100%;border-collapse:collapse;font-size:14px}
table.rd th{background:#eef2f7;color:#334155;padding:6px 8px;text-align:center;font-size:11.5px;
  text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;border:1px solid #e2e8f0}
table.rd td{padding:5px 8px;border:1px solid #eef2f7;color:#0f172a;background:#fff;
  text-align:center;white-space:nowrap}
table.rd td.rd-p{text-align:left}
table.rd td.rd-p .nm{font-weight:600}
table.rd td.rd-p img{width:18px;height:18px;vertical-align:-3px;margin:0 6px 0 0;border:0;
  padding:0;box-shadow:none;background:none}
table.rd td.rd-g{text-align:left;font-size:13px}
table.rd td.rd-g .bye{color:#b91c1c;font-weight:600}
table.rd td.rd-g .fin{color:#64748b}
table.rd td.rd-g .live{color:#b91c1c;font-weight:700}
table.rd tr.rd-bn td{color:#64748b;background:#fafbfc}
table.rd tr.rd-bn td.rd-p .nm{font-weight:500}
table.rd tr.rd-split td{border-top:3px solid #cbd5e1}
table.rd td.rd-slot{font-weight:700;font-size:12.5px}
.rd-lbl{font-size:12px;color:#64748b;margin-left:4px}
.rd-tag{display:inline-block;margin-left:6px;padding:0 6px;border-radius:8px;font-size:11px;
  font-weight:700;text-transform:uppercase}
.rd-tag.lock{background:#e2e8f0;color:#475569}
.rd-inj{margin-left:5px;color:#b91c1c;font-weight:700;font-size:12px}
.rd-rk{display:block;font-size:11px;color:#475569}
.rd-wx .sub{display:block;font-size:11px;color:#64748b}
.rd-wx.bad{font-weight:700;color:#b45309}
.rd-cov{font-size:12.5px;text-align:left !important}
.rd-cov.none{color:#94a3b8}
.rd-cov.warn{color:#b45309;font-weight:600}
.rd-note{font-size:13px;color:#4a5a68;margin:6px 0 12px;line-height:1.55}
.rd-gain{color:#15803d;font-weight:700}
@media (prefers-color-scheme: dark){
  .rd-head .rd-nm,.rd-tile b{color:#e8eef7}
  .rd-head .rd-sub,.rd-tile span,.rd-lbl,.rd-rk,.rd-wx .sub,.rd-note{color:#aab7c9}
  .rd-tile{background:#16203a;border-color:#2b3852}
  .rd-tile.up b,.rd-gain{color:#4ade80}
  .rd-pick select,.rd-pick button{background:#16203a;color:#dde5ef;border-color:#2b3852}
  .rd-pick button.on{background:#453312;border-color:#b45309;color:#ffd08a}
  .rd-moves{background:#1b2540;color:#dde5ef}
  .rd-moves.ok{background:#12291c}
  table.rd th{background:#223052;color:#dde5ef;border-color:#2b3852}
  table.rd td{background:#16203a;border-color:#2b3852;color:#dde5ef}
  table.rd tr.rd-bn td{background:#131c33;color:#aab7c9}
  table.rd tr.rd-split td{border-top-color:#475569}
  table.rd tbody tr.rd-in td{background:#12351f;color:#e8eef7}
  table.rd tbody tr.rd-out td{background:#3f1a1d;color:#e8eef7}
  table.rd tbody tr.rd-swap td{background:#172f5c;color:#e8eef7}
  .rd-legend{color:#aab7c9}
  table.rd td.rd-g .fin{color:#aab7c9}
  .rd-wx.bad,.rd-cov.warn{color:#ffb457}
  .rd-tag.lock{background:#2b3852;color:#cbd5e1}
  .rd-cov.none{color:#64748b}
}
</style>"""


# One view per team, the menu shows one. The choice rides in the hash (so a
# link can name a team) and "my team" in localStorage, under a key the rest of
# that section's pages can read.
_SWITCH_JS = """{% raw %}<script>
(function(){
  var CFG=JSON.parse(document.getElementById('rd-cfg').textContent);
  var pick=document.getElementById('rd-team'), star=document.getElementById('rd-star');
  function mine(){
    try{var s=localStorage.getItem('cfbMyTeam'); if(s&&CFG.teams[s]) return s;}catch(e){}
    return CFG.mine;
  }
  function show(key){
    if(!CFG.teams[key]) key=mine()||Object.keys(CFG.teams)[0];
    pick.value=key;
    Array.prototype.forEach.call(document.querySelectorAll('.rd-view'),function(v){
      v.style.display=v.dataset.key===key?'':'none';});
    var is=key===mine();
    star.classList.toggle('on',is);
    star.textContent=is?'\\u2605 My team':'\\u2606 Make this my team';
    history.replaceState(null,'','#'+CFG.teams[key]);
  }
  pick.addEventListener('change',function(){show(pick.value);});
  star.addEventListener('click',function(){
    try{localStorage.setItem('cfbMyTeam',pick.value);}catch(e){}
    show(pick.value);});
  var want=location.hash.replace(/^#/,''), start=null;
  Object.keys(CFG.teams).forEach(function(k){ if(CFG.teams[k]===want) start=k; });
  show(start||mine());
})();
</script>{% endraw %}"""


def switch_js(storage_key: str) -> str:
    return _SWITCH_JS.replace("cfbMyTeam", storage_key)


PILL = {"in": "&#9650; Start", "out": "&#9660; Bench", "swap": "&#8644; Move"}


def move_cell(kind: str, new_slot: str) -> str:
    """The Change column: the pill, and the slot he is headed for."""
    if not kind:
        return "<td class='rd-mv'></td>"
    return (f"<td class='rd-mv'><span class='rd-pill {kind}'>{PILL[kind]}</span>"
            + (f"<span class='rd-to'>&rarr; {escape(new_slot)}</span>" if kind != "out" else "")
            + "</td>")


def legend() -> str:
    return ("<div class='rd-legend'><span><i class='in'></i>Bench &rarr; start</span>"
            "<span><i class='out'></i>Starter &rarr; bench</span>"
            "<span><i class='swap'></i>Swap slots for kickoff order</span></div>")


def moves_box(changes: list, warns: list, gain: float, flex: str) -> str:
    """The changes, one line each, in the colours the table rows carry.

    changes  [{"kind", "name", "proj", "now", "new", "when", "sort"}] - name is
             plain text, when the kickoff as it should read, sort its order
    warns    ready-made html sentences (a tagged starter nobody can cover)
    """
    def label(c, with_proj=True):
        v = c.get("proj")
        return (f"<b>{escape(c['name'])}</b>"
                + (f" ({v:.1f})" if with_proj and v is not None else ""))

    by_kind = {k: [c for c in changes if c["kind"] == k] for k in ("in", "out", "swap")}
    lines = []
    for c in sorted(by_kind["in"], key=lambda c: c.get("sort") or ""):
        lines.append(f"<li><span class='rd-pill in'>{PILL['in']}</span> {label(c)} at "
                     f"<b>{escape(c['new'])}</b><span class='rd-lbl'>{c['when']}</span></li>")
    for c in by_kind["out"]:
        lines.append(f"<li><span class='rd-pill out'>{PILL['out']}</span> {label(c)}"
                     f"<span class='rd-lbl'>now {escape(c['now'])}</span></li>")
    for c in sorted(by_kind["swap"], key=lambda c: c.get("sort") or ""):
        why = ("latest kickoff, keeps the flex open" if c["new"] == flex
               else "earlier kickoff, takes the position slot")
        lines.append(f"<li><span class='rd-pill swap'>{PILL['swap']}</span> "
                     f"{label(c, False)} {escape(c['now'])} &rarr; <b>{escape(c['new'])}</b>"
                     f"<span class='rd-lbl'>{c['when']} &middot; {why}</span></li>")
    warn_items = [f"<li><span class='rd-pill warn'>! Watch</span> {w}</li>" for w in warns]
    if not lines:
        return ("<div class='rd-moves ok'><div class='rd-moves-h'>&#10003; No changes</div>"
                "The lineup as set is the best one by projection, and the flex already "
                "holds the latest kickoffs."
                + (f"<ul>{''.join(warn_items)}</ul>" if warn_items else "") + "</div>")
    n = len(lines)
    empty = (" &middot; a starting slot is sitting empty"
             if len(by_kind["in"]) > len(by_kind["out"]) else "")
    head = (f"<div class='rd-moves-h'>{n} change{'' if n == 1 else 's'} to make"
            + (f" &middot; <span class='rd-gain'>+{gain:.1f} projected</span>"
               if gain >= 0.05 else "") + empty + "</div>")
    return f"<div class='rd-moves'>{head}<ul>{''.join(lines + warn_items)}</ul></div>"


def heat(value, low=0.85, high=1.15) -> str:
    """Cell background for a defence-vs-position rating: green where it gives
    points up, red where it does not (the matchup-strength page's scale)."""
    if value is None or value != value:
        return ""
    t = min(max((float(value) - low) / max(high - low, 1e-9), 0.0), 1.0)
    r, g, b = (211, 47, 47) if t < 0.5 else (46, 125, 50)
    return f"background:rgba({r},{g},{b},{abs(t - 0.5) * 2 * 0.45:.2f})"


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# AccuWeather icon codes, the ones ESPN's feeds carry.
WX_RAIN = {12, 13, 14, 18, 39, 40}
WX_STORM = {15, 16, 17, 41, 42}
WX_SNOW = {19, 20, 21, 22, 23, 24, 25, 26, 29, 43, 44}


def wx_icon(cond) -> str:
    if cond is None:
        return ""
    if cond in WX_SNOW:
        return "&#10052;&#65039;"
    if cond in WX_STORM:
        return "&#9928;&#65039;"
    if cond in WX_RAIN:
        return "&#127783;&#65039;"
    if cond in (11, 37):
        return "&#127787;&#65039;"
    if cond == 32:
        return "&#128168;"
    if cond in (1, 2, 30, 33, 34):
        return "&#9728;&#65039;"
    if cond in (3, 4, 5, 35, 36):
        return "&#9925;"
    return "&#9729;&#65039;"
