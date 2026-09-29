"""
Finding cards: the league's records, each card leading with what it found.

League Home (both leagues) closes its first screen with the league's archive -
the schedule's luck, waivers and trades, draft values, injuries, the draft
review. Those pages used to sit behind an Analytics tab, filed with the power
rankings, which are read every week; the tab became Power and the archive came
here (2026-09-29).

An earlier Analytics page was a grid of plain link cards - a title and a line
of what the page was about - and read as a menu standing in the way ("clunky").
So each card here leads with the finding itself, a name and a number from the
page behind it ("Dak Prescott went 122nd and finished 7th"), with the page's
name as a small label above and what else it holds below. A card whose finding
cannot be worked out still shows, with its description instead.
"""
from html import escape

CSS = """<style>
.fc{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(min(280px,100%),1fr));
  margin:10px 0 8px}
.fc-card{display:flex;flex-direction:column;gap:4px;border:1px solid #e2e8f0;border-radius:12px;
  padding:12px 15px;background:#fff;text-decoration:none;color:inherit;
  box-shadow:0 1px 2px rgba(15,23,42,.05)}
.fc-card:hover{border-color:#2a78d6;box-shadow:0 2px 10px rgba(42,120,214,.13)}
.fc-label{font-size:11.5px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;
  color:var(--accent,#C2410C)}
.fc-find{font-size:15.5px;font-weight:700;color:#0f172a;line-height:1.35}
.fc-sub{font-size:13px;color:#64748b;line-height:1.45}
.fc-sub::after{content:" \\2192"}
.fc-note{font-size:13px;color:#64748b;margin:2px 0 0}
@media (max-width:560px){
  .fc{gap:8px}
  .fc-card{padding:11px 13px;border-radius:10px}
  .fc-find{font-size:15px}
}
@media (prefers-color-scheme: dark){
  .fc-card{background:#16203a;border-color:#2b3852;box-shadow:none}
  .fc-card:hover{border-color:#6aa9f0}
  .fc-label{color:#fdba74}
  .fc-find{color:#f1f5f9}
  .fc-sub,.fc-note{color:#aab7c9}
}
</style>"""


def cards(items: list) -> str:
    """`items`: (url, label, finding, what else the page holds) per card. The
    finding may be empty - the card then leads with the description."""
    out = []
    for url, label, finding, sub in items:
        lead = finding or sub
        rest = sub if finding else ""
        out.append(f"<a class='fc-card' href='{escape(str(url), quote=True)}'>"
                   f"<span class='fc-label'>{escape(str(label))}</span>"
                   f"<span class='fc-find'>{escape(str(lead))}</span>"
                   + (f"<span class='fc-sub'>{escape(str(rest))}</span>" if rest else "")
                   + "</a>")
    return CSS + "<div class='fc'>" + "".join(out) + "</div>"
