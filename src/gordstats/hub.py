"""
A section landing page: a grid of cards, one per page it gathers.

Both fantasy leagues grew a tail of pages that are read occasionally and were
taking up permanent room in the sub-nav - eight chips on the NFL side, which
wrapped to three rows on a phone. The nav now carries the four pages a league
is actually read for and one Analytics chip, and this renders what sits behind
that chip: each page named, with a line saying what it answers, so the choice
is made from the descriptions rather than from the titles alone.
"""
from html import escape

CSS = """<style>
.hub{display:grid;gap:13px;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));
  margin:14px 0 6px}
.hub-card{display:block;border:1px solid #e2e8f0;border-radius:12px;padding:15px 17px;
  background:#fff;text-decoration:none;box-shadow:0 1px 2px rgba(15,23,42,.05)}
.hub-card:hover{border-color:#2a78d6;box-shadow:0 2px 10px rgba(42,120,214,.13)}
.hub-icon{font-size:20px;line-height:1}
.hub-title{display:block;margin:7px 0 3px;font-size:17px;font-weight:800;color:#0f172a}
.hub-sub{display:block;font-size:13.5px;color:#475569;line-height:1.45}
.hub-note{font-size:13px;color:#64748b;margin:0 0 4px}
@media (max-width:560px){
  .hub{gap:9px}
  .hub-card{padding:12px 14px;border-radius:10px}
  .hub-title{font-size:16px;margin-top:5px}
  .hub-sub{font-size:13px}
}
@media (prefers-color-scheme: dark){
  .hub-card{background:#16203a;border-color:#2b3852;box-shadow:none}
  .hub-card:hover{border-color:#6aa9f0}
  .hub-title{color:#f1f5f9}
  .hub-sub,.hub-note{color:#aab7c9}
}
</style>"""


def cards(items: list) -> str:
    """`items` is (url, icon, title, one-line description) per card."""
    return CSS + "<div class='hub'>" + "".join(
        f"<a class='hub-card' href='{escape(str(url), quote=True)}'>"
        f"<span class='hub-icon' aria-hidden='true'>{icon}</span>"
        f"<span class='hub-title'>{escape(str(title))}</span>"
        f"<span class='hub-sub'>{escape(str(sub))}</span></a>"
        for url, icon, title, sub in items) + "</div>"
