"""The chart <img> is sized and unframed.

Slate frames every <img> (padding and a border on top of max-width:100%),
which panned the page sideways on a phone, and without width/height a lazy
chart reserved no space until it landed. gordstats.charts.save emits the
.gs-chart class custom.css resets, the PNG's own size, and the scroll box a
phone reads it in.
"""
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from gordstats import charts  # noqa: E402


def test_a_saved_chart_is_sized_and_unframed(tmp_path, monkeypatch):
    monkeypatch.setattr(charts, "CHART_DIR", tmp_path)
    plt.subplots(figsize=(4, 2))
    plt.plot([0, 1], [1, 0])
    tag = charts.save("sec", "line", alt="A line", dpi=50)

    assert (tmp_path / "sec" / "line.png").exists()
    assert tag.startswith('<div class="gs-chart-box"><img class="gs-chart"')
    w, h = (int(x) for x in re.search(r'width="(\d+)" height="(\d+)"', tag).groups())
    assert 150 <= w <= 220 and 70 <= h <= 120, (w, h)
    assert "style=" not in tag, "sizing belongs to .gs-chart, not an inline style"
