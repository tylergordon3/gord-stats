"""
The 2026-10-02 audit's page-weight fix: pandas Styler markup.

/fantasy/draft/ was 1.05 MB, half of it pandas' bookkeeping - an id on every
cell (9,318), an ID rule per coloured cell (~168 KB of CSS in 102 <style>
blocks) and a random T_xxxxx uuid per render. fantasy.site.styles.to_html
renders the same tables with the colour as a style attribute, no unused ids or
classes, and a uuid hashed from the table. These tests hold it to "same look":
every cell ends up with exactly the declarations pandas gave it, and a cell
whose colour could lose to the table's own rules keeps its ID rule.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd

from fantasy.site import styles

ROOT = Path(__file__).resolve().parents[1]


class _Cells(HTMLParser):
    """Every <td>/<th> in document order: (tag, attrs, text)."""

    def __init__(self):
        super().__init__()
        self.cells, self._open = [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self._open = [tag, dict(attrs), ""]
            self.cells.append(self._open)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._open = None

    def handle_data(self, data):
        if self._open is not None:
            self._open[2] += data


def _rules(html: str) -> dict:
    """{selector: [(prop, value)]} from a table's <style> block."""
    css = re.search(r"<style[^>]*>(.*?)</style>", html, re.S)
    out = {}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css.group(1) if css else ""):
        decls = [(p.strip(), v.strip()) for p, v in re.findall(r"([\w-]+)\s*:\s*([^;]+?)\s*(?:;|$)", body)]
        for s in sel.split(","):
            out.setdefault(s.strip(), []).extend(decls)
    return out


def _effective(html: str) -> list:
    """Per cell: (tag, text, the declarations aimed at that one cell)."""
    rules, p = _rules(html), _Cells()
    p.feed(html)
    out = []
    for tag, attrs, text in p.cells:
        decls = list(rules.get(f"#{attrs['id']}", [])) if "id" in attrs else []
        if "style" in attrs:
            decls += [(a.strip(), b.strip()) for a, b in
                      (d.split(":", 1) for d in attrs["style"].split(";") if d.strip())]
        out.append((tag, text.strip(), decls))
    return out


def _sample(n: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return pd.DataFrame({"Team": [f"T{i}" for i in range(n)],
                         "Score": rng.normal(100, 15, n).round(1),
                         "Record": [f"{w}-{10 - w}" for w in rng.integers(0, 11, n)],
                         "Note": ["x"] * n})


def _styled(df):
    return (df.style.hide(axis="index")
            .background_gradient(text_color_threshold=styles.GRADIENT_INK, cmap="RdYlGn",
                                 subset=["Score"])
            .apply(styles.highlight_on_record, subset=["Record"])
            .apply(styles.style_total_bottom, axis=1, subset=pd.IndexSlice[df.index[-1]:, :])
            .set_table_styles([styles.GRID_TD, styles.GRID_TH, styles.TABLE_STYLE,
                               {"selector": "td.col0", "props": [("text-align", "left")]}],
                              overwrite=False)
            .set_table_attributes('class="sticky-table"'))


def test_every_cell_keeps_exactly_the_style_pandas_gave_it():
    df = _sample()
    raw, compact = _styled(df).to_html(), styles.to_html(_styled(df))
    assert _effective(compact) == _effective(raw)


def test_unstyled_cells_carry_no_id_and_coloured_ones_no_rule():
    html = styles.to_html(_styled(_sample()))
    assert not re.search(r'id="T_\w+_(row|level)\d+', html), "a cell still has an id"
    assert not re.search(r"#T_\w+_(row|level)\d+", html), "a per-cell CSS rule survived"
    assert 'style="background-color:' in html
    # The table's own rules stay, and the class they select is kept.
    assert re.search(r"#T_[0-9a-f]{8} td\.col0\{text-align:left\}", html)
    assert '<td class="col0">' in html
    # pandas' bookkeeping classes go.
    assert "data row" not in html and "col_heading" not in html


def test_the_table_id_is_stable_and_names_the_table():
    df = _sample()
    one, two = styles.to_html(_styled(df)), styles.to_html(_styled(df))
    assert one == two, "the same table rendered twice differs (random uuid?)"
    other = styles.to_html(_styled(_sample(13)))
    ids = [re.search(r'<table id="(T_[0-9a-f]+)"', h).group(1) for h in (one, other)]
    assert ids[0] != ids[1]
    assert styles.to_html(_styled(df), uuid="named").count('id="T_named"') == 1


def test_a_cell_that_could_lose_to_a_table_rule_keeps_its_id_rule():
    """`#T_x td.col0 {text-align:left}` outranks a per-cell ID rule; a style
    attribute would outrank it. So that cell is left exactly as pandas wrote it."""
    df = _sample(4)
    styled = _styled(df).apply(lambda c: ["text-align:right"] * len(c), subset=["Team"])
    raw, html = styled.to_html(), styles.to_html(styled)
    assert re.search(r"#T_\w+_row0_col0", html)
    assert 'id="T_' in html.split("<tbody>")[1]
    assert _effective(html) == _effective(raw)


def test_important_rules_inline_because_they_win_either_way():
    """The totals row's heavy rule is !important against a plain `td` border:
    it won as an ID rule and wins as an attribute."""
    html = styles.to_html(_styled(_sample(4)))
    last = html.split("<tr>")[-1]
    assert "border-top:3px solid black !important" in last
    assert "#T_" not in last


def test_compact_is_well_under_half_of_pandas():
    df = pd.DataFrame({"Player": [f"P{i}" for i in range(150)],
                       "Pos": ["RB"] * 150, "Pick": range(150),
                       "Delta": np.linspace(-20, 20, 150)})
    styled = lambda: (df.style.hide(axis="index")                       # noqa: E731
                      .background_gradient(cmap="RdYlGn", subset=["Delta"])
                      .set_table_styles([styles.GRID_TD, styles.GRID_TH], overwrite=False))
    raw, compact = styled().to_html(), styles.to_html(styled())
    assert len(compact) < 0.5 * len(raw), (len(compact), len(raw))


def test_cell_content_is_untouched():
    """Indentation between table tags goes; a cell's own markup does not."""
    df = pd.DataFrame({"Player": ['<span class="row-rank">1</span>A  B', "x\n  <b>y</b>"],
                       "N": [1.0, 2.0]})
    styled = df.style.hide(axis="index").background_gradient(subset=["N"])
    html = styles.to_html(styled)
    assert '<span class="row-rank">1</span>A  B</td>' in html
    assert "x\n  <b>y</b></td>" in html


def test_the_page_builders_render_through_the_compact_helper():
    """Every Styler on these pages goes through styles.to_html. (power.py is
    not listed: its tables use their own ID-rule wash, see test_phone_tables.)"""
    for mod in ("draft_current", "draft_recap", "draft_report", "draft_dna", "adp",
                "transactions", "schedule", "homepage", "records"):
        src = (ROOT / "src" / "fantasy" / "site" / f"{mod}.py").read_text()
        assert ".to_html()" not in src, f"{mod} renders a Styler with pandas' own to_html"


def test_draft_tables_render_compact():
    from fantasy.site import draft_current

    df = pd.DataFrame({"Pick": range(1, 21), "Player": [f"P{i}" for i in range(20)],
                       "Manager": ["Ann", "Bo"] * 10, "Pos": ["RB"] * 20, "Team": ["DET"] * 20,
                       "ADP": np.arange(1, 21, dtype=float),
                       "Δ": np.linspace(-12, 12, 20)})
    for html in (draft_current.pick_table(df), draft_current.manager_table(df)):
        assert not re.search(r'id="T_\w+_row', html)
        assert "background-color:" in html
