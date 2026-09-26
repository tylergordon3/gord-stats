"""
A reader's power ranking takes the page over, and reads like the built one.

Two asks, both about the same page. Somebody who has synced a league is on
/fantasy/power/ for *that* league - two rankings of two different leagues on
one page only invites the question of whose numbers are on screen. And the
reader's table used to be its own little thing: `mp-t`, a rank column of its
own and a small bar under each power figure, beside a built table that is the
site's `sticky-table` with pandas' RdYlGn shading. The same question answered
twice, answered as though it were a different feature.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_built_league_is_wrapped_so_it_can_be_hidden():
    """Everything of this league's has to sit inside one element, or hiding it
    means hiding sections one at a time and forgetting the next one added."""
    from fantasy.site import power

    src = power.__file__ and open(power.__file__).read()
    assert "id='pw-built'" in src or 'id="pw-built"' in src
    # The reader's own section is outside the wrapper, or it goes with it.
    body = src[src.index("def body()"):]
    mine = body.index("id='mine'")
    built = body.index("pw-built")
    assert mine < built, "the reader's section is inside the wrapper"


def test_the_reader_hides_this_leagues_ranking():
    from gordstats import my_power

    assert "getElementById('pw-built')" in my_power.JS
    assert "built.hidden=true" in my_power.JS
    # The opening paragraph describes a blend this league has and a reader's
    # does not, so it goes too.
    assert "getElementById('pw-intro')" in my_power.JS
    assert "intro.hidden=true" in my_power.JS


def test_the_reader_table_is_the_sites_table():
    """`sticky-table` inside `.table-scroll` is what the built ranking uses and
    what custom.css is written against - the frozen first column, the sticky
    header, `.row-rank`. A table of its own got none of it."""
    from gordstats import my_power

    assert 'class="sticky-table"' in my_power.JS
    assert 'class="table-scroll"' in my_power.JS
    assert 'class="row-rank"' in my_power.JS
    for dead in ('class="mp-t"', "mp-power", "mp-track", "mp-rank", "mp-scroll"):
        assert dead not in my_power.JS, f"{dead} is back"


def test_the_reader_table_carries_the_built_columns():
    from fantasy.site import power
    from gordstats import my_power

    heads = re.findall(r"<th>([^<]+)</th>", my_power.JS)
    assert heads == ["Team", "Power", "Record", "Luck", "Proj. Record",
                     "Playoffs", "Title"], heads
    # Move needs an archive of previous builds, which a reader's league has
    # none of - so it is the one built column deliberately absent.
    assert "Move" not in heads
    built = open(power.__file__).read()
    assert '"Move"' in built, "the built table lost Move; this note is stale"


def test_record_and_luck_are_the_built_definition():
    """`fantasy.league.power.actual_records`, in the browser. Luck is the real
    record minus what an all-play schedule says the scores deserved, and the
    median win counts only in a league that plays one."""
    from gordstats import my_power

    js = my_power.JS[my_power.JS.index("function records("):]
    js = js[:js.index("\n  function table(")]
    assert "allplay[seat]+=(n-1)-rank" in js, "the all-play count drifted"
    assert "rank < Math.floor(n/2)" in js, "the median win drifted"
    # Not every league plays the median game; this one does, and assuming it
    # doubles everybody's record.
    assert "if(median &&" in js
    assert "perWeek=median?2:1" in js

    from fantasy.league import power as built
    src = open(built.__file__).read()
    assert "allplay += (n - 1) - ranks" in src, "the Python moved; the port has not"
    assert "median += ranks < n // 2" in src


def test_the_gradient_is_the_one_pandas_uses():
    """The built columns are shaded by pandas' RdYlGn over the column's own
    min and max. A reader's league shaded on any other scale is a different
    chart wearing the same colours."""
    from gordstats import my_power

    assert "RDYLGN" in my_power.JS
    # matplotlib's eleven anchors, ends first.
    assert "[165,0,38]" in my_power.JS and "[0,104,55]" in my_power.JS
    assert "(value-lo)/(hi-lo)" in my_power.JS
