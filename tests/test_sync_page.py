"""The sync page says when a sync was cut short.

functions/api/leagues.js answers `complete: false` with an `unfinished`
block when an account hits its league cap or one sync runs out of Sleeper
calls; the page showed "Found 20 leagues" either way.
"""
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "src" / "gordstats" / "league_sync.py").read_text()


def test_both_success_lines_carry_the_note():
    assert "d.complete===false && d.unfinished && d.unfinished.note" in PAGE
    assert "done(msgId,'Synced '" in PAGE, "adding one league ignores the note"
    assert "done('ls-user-msg','Found '" in PAGE, "finding by username ignores the note"
    assert "note?'warn':'ok'" in PAGE and ".ls-msg.warn{" in PAGE
