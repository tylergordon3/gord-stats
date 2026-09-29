"""
The Share button: a page's link, sent to a chat (docs/assets/js/share.js does
the sending, on every page; this writes the button).

    share_button.button("/fantasy/recap/week-3/", "Week 3: The Standard ...")

On a phone the tap opens the share sheet with the address and the line, and the
chat shows the page's own preview card (gordstats.share_card); elsewhere it
copies both. The address should be the one that keeps saying the same thing -
a recap's week page rather than the recap's front page, which moves on - and
the line is what the sender would otherwise have typed.

Styled once, in assets/css/custom.css (.gs-share).
"""
from html import escape

# A share glyph drawn inline (an arrow leaving a box), so it follows the
# button's colour in both themes and needs no icon font.
_ICON = ("<svg class='gs-share-icon' viewBox='0 0 24 24' width='16' height='16' aria-hidden='true' "
         "fill='none' stroke='currentColor' stroke-width='2.2' stroke-linecap='round' "
         "stroke-linejoin='round'><path d='M12 3v12'/><path d='M7 8l5-5 5 5'/>"
         "<path d='M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6'/></svg>")


def button(url: str, text: str = "", title: str = "", label: str = "Share") -> str:
    attrs = f" data-url='{escape(url, quote=True)}'"
    if text:
        attrs += f" data-text='{escape(text, quote=True)}'"
    if title:
        attrs += f" data-title='{escape(title, quote=True)}'"
    return (f"<button type='button' class='gs-share'{attrs}>{_ICON}"
            f"<span class='gs-share-label'>{escape(label)}</span></button>")


def row(url: str, text: str = "", title: str = "", label: str = "Share") -> str:
    """The button on a line of its own, right-aligned above what it shares."""
    return f"<div class='gs-share-row'>{button(url, text, title, label)}</div>"
