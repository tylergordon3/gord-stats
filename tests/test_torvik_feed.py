"""The Torvik table comes from two plain CSVs now, not a browser scrape.

Two traps in them, both hit while building it: fffinal's rows carry more fields
than its header names (pandas then shifts every column into the index), and
the browser check answers 200 with an HTML page, which must fail rather than
read as an empty season.
"""
import pytest

RESULTS = ("rank,team,conf,record,adjoe,oe Rank,adjde,de Rank,barthag,rank,WAB,adjt\n"
           "1,Duke,ACC,32-2,128.1,1,90.8,1,0.98,1,13.7,65.8\n"
           "2,Saint Mary's,WCC,28-5,118.0,20,95.0,15,0.90,2,5.1,62.0\n")
FACTORS = ("TeamName,eFG%,Rk,eFG% Def,Rk,FTR,Rk,FTR Def,Rk,OR%,Rk,DR%,Rk,TO%,Rk,TO% Def.,Rk,"
           "3P%,rk,3pD%,rk,2p%,rk,2p%D,rk,ft%,rk,ft%D,rk,3P rate,rk,3P rate D,rk\n"
           "Duke,56.8,5,46.2,3,37.8,20,23.7,5,38.2,4,24.9,10,15.7,40,18.2,90,35.1,50,30.4,10,"
           "60.2,3,46.6,12,75.0,30,70.0,100,44.5,60,45.7,300,99,1,2,3\n"
           "Saint Mary's,52.0,80,48.0,40,30.0,100,28.0,90,33.0,50,27.0,60,17.0,120,17.0,150,"
           "34.0,90,32.0,60,51.0,90,48.0,60,72.0,90,71.0,80,40.0,120,40.0,150,99,1,2,3\n")


class _Resp:
    def __init__(self, text, ctype):
        self.text, self.headers = text, {"content-type": ctype}

    def raise_for_status(self):
        pass


def _serve(monkeypatch, factors=FACTORS, ctype="text/csv"):
    from cbb.scrape import torvik

    def get(url, **kw):
        return _Resp(RESULTS, "text/csv") if "team_results" in url else _Resp(factors, ctype)
    monkeypatch.setattr(torvik.requests, "get", get)
    return torvik


def test_the_two_files_make_the_main_tables_columns(monkeypatch):
    torvik = _serve(monkeypatch)
    got = torvik.table("M", 2027)
    assert got["headers"] == torvik.HEADERS
    duke = dict(zip(got["headers"], got["rows"][0]))
    assert duke["Team"] == "Duke" and duke["G"] == "34" and duke["Rec"] == "32-2"
    # The four factors land in their own columns despite fffinal's extra fields.
    assert duke["EFG%"] == "56.8" and duke["DRB"] == "24.9" and duke["3PRD"] == "45.7"
    assert duke["Adj T."] == "65.8" and duke["WAB"] == "13.7"


def test_the_browser_check_page_is_a_failure_not_an_empty_season(monkeypatch):
    torvik = _serve(monkeypatch, factors="<html>Verifying your browser...</html>",
                    ctype="text/html; charset=UTF-8")
    with pytest.raises(RuntimeError, match="did not return a CSV"):
        torvik.table("W", 2027)


def test_files_that_no_longer_agree_on_names_fail_loudly(monkeypatch):
    torvik = _serve(monkeypatch, factors=FACTORS.replace("Saint Mary's", "St. Mary's"))
    with pytest.raises(RuntimeError, match="matched only 1 of 2"):
        torvik.table("M", 2027)
