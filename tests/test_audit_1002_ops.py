"""
The 2026-10-02 audit's operations fixes: what the Pi's two scripts keep when a
build fails, how the live tick fails, the vendored theme, content-hashed
assets, the link check before publish, and the browser tests' profiles.

The deploy scripts are run for real here, in a scratch repo with a bare
origin, against stubs for everything that would reach the Pi's tools (the
sections, Jekyll, wrangler) - the parts under test are the scripts' own git
and control flow.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "deploy"))
import linkcheck  # noqa: E402

needs_bash = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("git")
                                     and shutil.which("flock")),
                                reason="needs bash, git and flock")


# --------------------------------------------------------------------------- #
# A scratch Pi: a clone of a bare origin holding the real deploy scripts, a
# HOME with the secrets file, and stubs on PATH.
# --------------------------------------------------------------------------- #

PY_STUB = r"""#!/bin/bash
# python: the sections, the live gates and the link check, by argument.
case "$*" in
  "-m gordstats.daily"*) echo "capture $(date +%s%N)" >> data/captures.txt
                         exit "${DAILY_RC:-0}" ;;
  "-m cbb.live"*)        echo cbb >> "$HOME/gates"; exit "${CBB_RC:-3}" ;;
  "-m wnba.wnba_live"*)  echo wnba >> "$HOME/gates"; exit "${WNBA_RC:-3}" ;;
  "-m fantasy.live"*)    echo fantasy >> "$HOME/gates"; exit "${FANTASY_RC:-3}" ;;
  "-m cfb.live"*)        echo cfb >> "$HOME/gates"
                         [ "${CFB_RC:-3}" -eq 0 ] && echo "tick $(date +%s%N)" >> data/live.txt
                         exit "${CFB_RC:-3}" ;;
  "deploy/linkcheck.py"*) exit "${LINK_RC:-0}" ;;
esac
exit 0
"""
BUNDLE_STUB = r"""#!/bin/bash
[ "$1" = exec ] || exit 0
[ -n "${JEKYLL_FAIL:-}" ] && { echo "jekyll: boom" >&2; exit 1; }
mkdir -p docs/_site && echo built > docs/_site/index.html
"""
WRANGLER_STUB = """#!/bin/bash
echo upload >> "$HOME/uploads"
exit "${WRANGLER_RC:-0}"
"""


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def pi(tmp_path):
    origin, repo, home, stubs = (tmp_path / "origin.git", tmp_path / "pi",
                                 tmp_path / "home", tmp_path / "stubs")
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(repo))
    _git(repo, "config", "user.name", "pi")
    _git(repo, "config", "user.email", "pi@pi")
    (repo / "deploy").mkdir()
    for name in ("pi-deploy.sh", "pi-live.sh", "publish.sh"):
        shutil.copy2(ROOT / "deploy" / name, repo / "deploy" / name)
    for name, text in {"pyproject.toml": "[project]\n", "Gemfile": "gem 'jekyll'\n",
                       "Gemfile.lock": "GEM\n", "data/seed.txt": "seed\n",
                       "docs/page.md": "page\n",
                       ".gitignore": ".venv/\ndocs/_site/\nvendor/\n.last_*\n"
                                     ".live_trouble_since\n"}.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "push", "-q", "origin", "main")

    venv = repo / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "activate").write_text(":\n")
    stamp = subprocess.run(["sha256sum", "pyproject.toml"], cwd=repo, capture_output=True,
                           text=True).stdout.split()[0]
    (repo / ".venv" / ".requirements-sha256").write_text(stamp + "\n")

    (home / "secrets").mkdir(parents=True)
    (home / "secrets" / "gord-stats.env").write_text("CLOUDFLARE_API_TOKEN=x\nTASKS=x\n")
    stubs.mkdir()
    for name, text in {"python": PY_STUB, "bundle": BUNDLE_STUB, "wrangler": WRANGLER_STUB,
                       "sleep": "#!/bin/bash\n:\n"}.items():
        (stubs / name).write_text(text)
        (stubs / name).chmod(0o755)

    def run(script, **env):
        full = {"PATH": f"{stubs}:{os.environ['PATH']}", "HOME": str(home),
                "LANG": "C.UTF-8", **{k: str(v) for k, v in env.items()}}
        return subprocess.run(["bash", f"deploy/{script}"], cwd=repo, env=full,
                              capture_output=True, text=True, timeout=120)

    return {"repo": repo, "origin": origin, "home": home, "run": run}


def _origin_file(pi, path):
    return _git(pi["origin"], "show", f"main:{path}")


# --------------------------------------------------------------------------- #
# Finding 1: a failed build used to cost the run's captures.
# --------------------------------------------------------------------------- #

@needs_bash
def test_a_failed_jekyll_build_keeps_the_runs_data_and_the_next_run_pushes_it(pi):
    """The captures were committed after the upload, so a Jekyll or wrangler
    failure (both `set -e` exits) left them uncommitted for the next clean
    slate - `git checkout -- docs data` - to throw away: closing lines, CLV,
    the odds history. Now they are committed before Jekyll and pushed after."""
    out = pi["run"]("pi-deploy.sh", JEKYLL_FAIL=1)
    assert out.returncode != 0, out.stdout + out.stderr
    repo = pi["repo"]
    assert _git(repo, "log", "-1", "--format=%s").startswith("Daily refresh (x) ")
    assert _git(repo, "status", "--porcelain", "--", "data") == "", "the capture is committed"
    first = (repo / "data" / "captures.txt").read_text()
    assert not (pi["home"] / "uploads").exists(), "a failed build must not be uploaded"

    out = pi["run"]("pi-deploy.sh")
    assert out.returncode == 0, out.stdout + out.stderr
    pushed = _origin_file(pi, "data/captures.txt")
    assert pushed.startswith(first) and pushed.count("capture") == 2, \
        "the failed run's capture must reach origin with the next run's"


@needs_bash
def test_a_failed_upload_keeps_the_data_too(pi):
    out = pi["run"]("pi-deploy.sh", WRANGLER_RC=1)
    assert out.returncode != 0 and "failed three times" in out.stderr
    assert _git(pi["repo"], "status", "--porcelain", "--", "data") == ""
    assert "captures.txt" in _git(pi["repo"], "show", "--stat", "--format=", "HEAD")


@needs_bash
def test_the_link_check_stops_the_publish(pi):
    out = pi["run"]("pi-deploy.sh", LINK_RC=1)
    assert out.returncode != 0
    assert not (pi["home"] / "uploads").exists()


@needs_bash
def test_a_clean_run_publishes_then_pushes_and_stamps_the_gems(pi):
    out = pi["run"]("pi-deploy.sh")
    assert out.returncode == 0, out.stdout + out.stderr
    assert (pi["home"] / "uploads").read_text().count("upload") == 1
    assert "capture" in _origin_file(pi, "data/captures.txt")
    stamp = (pi["repo"] / "vendor" / "bundle" / ".gems-sha256").read_text().strip()
    assert len(stamp) == 64, "pi-live.sh compares against this"


@needs_bash
def test_old_wrangler_logs_are_pruned(pi):
    """~/.config/.wrangler/logs had 1,512 files on 2026-10-02 and nothing
    deleted any."""
    logs = pi["home"] / ".config" / ".wrangler" / "logs"
    logs.mkdir(parents=True)
    old, new = logs / "wrangler-2026-09-01_00-00-00_000.log", logs / "wrangler-now.log"
    old.write_text("x")
    new.write_text("x")
    month_ago = time.time() - 30 * 86400
    os.utime(old, (month_ago, month_ago))
    out = pi["run"]("pi-deploy.sh")
    assert out.returncode == 0, out.stdout + out.stderr
    assert not old.exists() and new.exists()


# --------------------------------------------------------------------------- #
# Findings 4 and 7: the live tick runs every gate and fails through
# tick_trouble.
# --------------------------------------------------------------------------- #

def _gates(pi):
    return (pi["home"] / "gates").read_text().split()


@needs_bash
def test_a_failing_gate_no_longer_stops_the_others_or_mails_every_tick(pi):
    """From Nov 1 a WNBA gate failing (an expired ESPN cookie) stopped the tick
    before the CBB push and mailed every ten minutes."""
    out = pi["run"]("pi-live.sh", WNBA_RC=1, CFB_RC=0)
    assert out.returncode == 0, "the first hour of trouble is a quiet skip"
    assert _gates(pi) == ["cbb", "wnba", "fantasy", "cfb"], "CBB first, then every gate"
    assert "wnba (rc=1)" in out.stdout
    assert (pi["home"] / "uploads").exists(), "what the other gates rebuilt still publishes"
    assert (pi["repo"] / ".live_trouble_since").exists()

    # An hour of it: one mail (exit 1), and the next one an hour later.
    (pi["repo"] / ".live_trouble_since").write_text(str(int(time.time()) - 3700))
    out = pi["run"]("pi-live.sh", WNBA_RC=1)
    assert out.returncode == 1 and "for over an hour: wnba (rc=1)" in out.stdout
    out = pi["run"]("pi-live.sh", WNBA_RC=1)
    assert out.returncode == 0


@needs_bash
def test_a_quiet_tick_clears_the_trouble(pi):
    (pi["repo"] / ".live_trouble_since").write_text(str(int(time.time()) - 100))
    out = pi["run"]("pi-live.sh")
    assert out.returncode == 0, out.stdout + out.stderr
    assert not (pi["repo"] / ".live_trouble_since").exists()
    assert not (pi["home"] / "uploads").exists(), "nothing fired, nothing built"


@needs_bash
def test_a_failed_live_build_is_trouble_not_a_mail_and_keeps_the_hourly_commit(pi):
    out = pi["run"]("pi-live.sh", CFB_RC=0, JEKYLL_FAIL=1)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "jekyll build failed" in out.stdout
    assert (pi["repo"] / ".live_trouble_since").exists()
    assert not (pi["home"] / "uploads").exists()
    repo = pi["repo"]
    assert _git(repo, "log", "-1", "--format=%s").startswith("Live update (cfb) ")
    tick = (repo / "data" / "live.txt").read_text()

    # The next tick discards nothing that was committed, and pushes it.
    out = pi["run"]("pi-live.sh", CFB_RC=0)
    assert out.returncode == 0, out.stdout + out.stderr
    assert _origin_file(pi, "data/live.txt").startswith(tick.strip())
    assert not (repo / ".live_trouble_since").exists()


@needs_bash
def test_a_failed_live_upload_is_trouble_not_a_mail(pi):
    out = pi["run"]("pi-live.sh", CFB_RC=0, WRANGLER_RC=1)
    assert out.returncode == 0, out.stdout + out.stderr
    assert (pi["repo"] / ".live_trouble_since").exists()


@needs_bash
def test_the_tick_waits_for_the_daily_run_to_install_new_gems(pi):
    """pi-live.sh never runs `bundle install`; a Gemfile.lock it pulls before
    the daily run has installed it would fail every tick's build."""
    stamp = pi["repo"] / "vendor" / "bundle" / ".gems-sha256"
    stamp.parent.mkdir(parents=True)
    stamp.write_text("not-what-is-installed\n")
    out = pi["run"]("pi-live.sh", CFB_RC=0)
    assert out.returncode == 0 and "Ruby gems changed" in out.stdout
    assert not (pi["home"] / "uploads").exists()
    assert _gates(pi)[0] == "cbb", "the CBB push does not need gems and still ran"


# --------------------------------------------------------------------------- #
# Finding 4: the gates themselves answer 3 for an unreachable feed.
# --------------------------------------------------------------------------- #

@pytest.fixture
def cbb_in_season(monkeypatch):
    from datetime import date, timedelta

    from cbb import live
    from cbb.render import render_home

    monkeypatch.setattr(render_home, "CBB_TIPOFF", date.today() - timedelta(days=1))
    monkeypatch.setattr(render_home, "CBB_SEASON_END", date.today() + timedelta(days=1))
    monkeypatch.setattr(live, "in_hours", lambda now: True)
    monkeypatch.setenv("INGEST_KEY", "k")
    from cbb import lines, live_scraper, push_scores
    monkeypatch.setattr(lines, "record", lambda leagues: None)
    monkeypatch.setattr(live_scraper, "get_current_live_dataset", lambda k: {"games": {}})
    pushed = []
    monkeypatch.setattr(push_scores, "push", pushed.append)
    return live, live_scraper, push_scores, pushed


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status}", response=resp)


def test_cbb_gate_pushes(cbb_in_season):
    live, *_rest, pushed = cbb_in_season
    assert live.main() == 0 and len(pushed) == 1


@pytest.mark.parametrize("exc", [requests.ConnectionError("down"), requests.Timeout("slow"),
                                 _http_error(503), _http_error(429)])
def test_cbb_gate_skips_a_feed_that_is_down(cbb_in_season, monkeypatch, exc):
    live, live_scraper, _push, pushed = cbb_in_season

    def boom(k):
        raise exc
    monkeypatch.setattr(live_scraper, "get_current_live_dataset", boom)
    assert live.main() == 3 and pushed == []


def test_cbb_gate_skips_a_worker_that_is_down_but_fails_on_a_refusal(cbb_in_season,
                                                                      monkeypatch):
    live, _scraper, push_scores, _pushed = cbb_in_season

    def down(payload):
        raise _http_error(502)
    monkeypatch.setattr(push_scores, "push", down)
    assert live.main() == 3

    def refused(payload):
        raise _http_error(401)                  # a rotated INGEST_KEY: ours to fix
    monkeypatch.setattr(push_scores, "push", refused)
    with pytest.raises(requests.HTTPError):
        live.main()


@pytest.mark.parametrize("exc", [RuntimeError("Redirected by ESPN - cookies expired"),
                                 requests.ConnectionError("down")])
def test_wnba_gate_skips_when_the_fantasy_fetch_fails(monkeypatch, exc):
    from wnba import wnba_fantasy, wnba_live, wnba_remaining

    def boom():
        raise exc
    monkeypatch.setattr(wnba_live, "maybe_refresh_schedule", lambda: None)
    monkeypatch.setattr(wnba_fantasy, "fetch_and_save", boom)
    monkeypatch.setattr(wnba_remaining, "main",
                        lambda argv: pytest.fail("nothing to rebuild from"))
    assert wnba_live.main(["--force"]) == 3


# --------------------------------------------------------------------------- #
# Finding 9: the link check.
# --------------------------------------------------------------------------- #

def _site(tmp_path, pages, extra=()):
    site = tmp_path / "site"
    for path, html in pages.items():
        (site / path).parent.mkdir(parents=True, exist_ok=True)
        (site / path).write_text(html)
    for path in extra:
        (site / path).parent.mkdir(parents=True, exist_ok=True)
        (site / path).write_text("x")
    return site


def test_linkcheck_fails_on_a_missing_script_or_stylesheet(tmp_path, capsys):
    site = _site(tmp_path, {
        "index.html": "<link rel='stylesheet' href='/assets/v/abc/custom.css'>"
                      "<script src='/assets/v/abc/share.js'></script>",
    }, extra=["assets/v/abc/custom.css"])
    assert linkcheck.main([str(site)]) == 1
    assert "/assets/v/abc/share.js" in capsys.readouterr().out


def test_linkcheck_only_warns_about_links_and_images(tmp_path, capsys):
    site = _site(tmp_path, {
        "index.html": "<a href='/gone/'>x</a><img src='/assets/images/gone.png'>"
                      "<link rel='icon' href='/favicon.ico'>",
    })
    assert linkcheck.main([str(site)]) == 0
    out = capsys.readouterr().out
    assert "/gone/" in out and "gone.png" in out and "/favicon.ico" in out


def test_linkcheck_resolves_what_cloudflare_pages_serves(tmp_path):
    site = _site(tmp_path, {
        "index.html": "<a href='/men/history'>clean URL</a>"
                      "<a href='/cfb/power/'>directory</a>"
                      "<a href='/fantasy/live/'>redirected</a>"
                      "<a href='sub/'>relative</a>"
                      "<a href='https://www.gordstats.com/cfb/power/'>absolute, ours</a>"
                      "<a href='https://example.com/nothing'>not ours</a>"
                      "<a href='#top'>fragment</a><a href='mailto:x@y'>mail</a>"
                      "<a href='/api/me'>a Function</a>"
                      "<b data-src='gs'>a source name, not a URL</b>"
                      "<script>const u = '<a href=\"/in/a/script\">';</script>",
        "men/history.html": "", "cfb/power/index.html": "", "sub/index.html": "",
    }, extra=["_redirects"])
    (site / "_redirects").write_text("# comment\n/fantasy/live/*  /fantasy/draft/  301\n")
    assets, links, pages = linkcheck.check(str(site))
    assert (assets, links, pages) == ({}, {}, 4)


def test_linkcheck_flags_liquid_that_never_rendered(tmp_path):
    site = _site(tmp_path, {"index.html": "<a href=\"{{ '/x/' | relative_url }}\">x</a>"})
    _assets, links, _pages = linkcheck.check(str(site))
    assert list(links) == ["{{ '/x/' | relative_url }}"]


def test_both_deploy_scripts_check_the_build_before_publishing():
    deploy = (ROOT / "deploy" / "pi-deploy.sh").read_text()
    live = (ROOT / "deploy" / "pi-live.sh").read_text()
    assert "python deploy/linkcheck.py docs/_site" in deploy
    assert "python deploy/linkcheck.py --quiet docs/_site" in live
    # pi-deploy.sh's order is run for real above (test_the_link_check_stops_the_publish).
    assert live.index("linkcheck.py") < live.index('publish "$PROJECT"')


# --------------------------------------------------------------------------- #
# Finding 2: the theme is vendored, not fetched per build.
# --------------------------------------------------------------------------- #

def test_the_theme_is_vendored_not_fetched():
    config = (DOCS / "_config.yml").read_text()
    assert not any(line.startswith("remote_theme:") for line in config.splitlines()), \
        "a remote_theme is a GitHub download on every build"
    assert "- jekyll-remote-theme" not in config
    for path in ("_sass/jekyll-theme-slate.scss", "_sass/rouge-github.scss",
                 "assets/css/style.scss", "_includes/head-custom.html",
                 "_includes/head-custom-google-analytics.html",
                 "assets/images/bg_hr.png", "assets/images/blacktocat.png",
                 "assets/images/icon_download.png", "assets/images/sprite_download.png"):
        assert (DOCS / path).is_file(), path
    assert "{% include head-custom.html %}" in (DOCS / "_layouts" / "default.html").read_text()
    gems = (ROOT / "Gemfile").read_text()
    for plugin in ("jekyll-seo-tag",):
        assert plugin in config and f'gem "{plugin}"' in gems


# --------------------------------------------------------------------------- #
# Finding 3: assets are versioned by content, and only hashed paths are
# immutable.
# --------------------------------------------------------------------------- #

def test_the_layout_versions_its_assets_by_content_not_build_time():
    import re

    layout = (DOCS / "_layouts" / "default.html").read_text()
    assert "site.time" not in layout, "a version per build is a cache miss per publish"
    refs = re.findall(r"\{\{ '(/assets/(?:css|js)/[^']+)'( \| fingerprint)?", layout)
    assert len(refs) >= 8
    unhashed = [path for path, hashed in refs if not hashed and "style.css" not in path]
    assert unhashed == []


def test_only_the_hashed_path_is_immutable():
    """An immutable rule on a path that is also loaded unversioned (live.js
    from /men/) would pin a stale script in readers' browsers for a year."""
    rules, current = {}, None
    for line in (DOCS / "_headers").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            current = line.strip()
            rules[current] = []
        else:
            rules[current].append(line.strip())
    immutable = [path for path, headers in rules.items()
                 if any("immutable" in h for h in headers)]
    assert immutable == ["/assets/v/*"]
    assert "Cache-Control: public, max-age=31536000, immutable" in rules["/assets/v/*"]


def _jekyll_works():
    if not shutil.which("bundle"):
        return False
    try:
        return subprocess.run(["bundle", "exec", "jekyll", "--version"], cwd=ROOT,
                              capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _jekyll_works(), reason="no bundled Jekyll here (the Pi and the PC have one)")
def test_the_fingerprint_plugin_writes_hashed_copies_and_drops_stale_ones(tmp_path):
    import hashlib

    src, out = tmp_path / "src", tmp_path / "out"
    (src / "_plugins").mkdir(parents=True)
    shutil.copy2(DOCS / "_plugins" / "fingerprint.rb", src / "_plugins")
    (src / "_layouts").mkdir()
    (src / "_layouts" / "default.html").write_text(
        "<script src=\"{{ '/assets/js/a.js' | fingerprint | relative_url }}\"></script>"
        "{{ content }}")
    (src / "assets" / "js").mkdir(parents=True)
    (src / "_config.yml").write_text("safe: false\nplugins_dir: _plugins\n")
    (src / "index.md").write_text("---\nlayout: default\n---\nhi\n")

    def build(js):
        (src / "assets" / "js" / "a.js").write_text(js)
        res = subprocess.run(["bundle", "exec", "jekyll", "build", "--quiet", "--source",
                              str(src), "--destination", str(out)], cwd=ROOT,
                             capture_output=True, text=True, timeout=120)
        assert res.returncode == 0, res.stderr
        return hashlib.md5(js.encode()).hexdigest()[:12]

    first = build("one()")
    assert f'src="/assets/v/{first}/a.js"' in (out / "index.html").read_text()
    assert (out / "assets" / "v" / first / "a.js").read_text() == "one()"
    assert (out / "assets" / "js" / "a.js").exists(), "the plain name is still served"

    second = build("two()")
    assert f'src="/assets/v/{second}/a.js"' in (out / "index.html").read_text()
    assert not (out / "assets" / "v" / first).exists(), "a rebuild in place drops the old copy"

    (src / "_layouts" / "default.html").write_text("{{ '/assets/js/typo.js' | fingerprint }}")
    res = subprocess.run(["bundle", "exec", "jekyll", "build", "--quiet", "--source", str(src),
                          "--destination", str(out)], cwd=ROOT, capture_output=True,
                         text=True, timeout=120)
    assert res.returncode != 0 and "typo.js" in res.stderr + res.stdout, \
        "an unknown asset fails the build rather than shipping an unversioned URL"


# --------------------------------------------------------------------------- #
# Finding 5: the CBB pages the in-season daily run rewrites stay out of git.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path, ignored", [
    ("docs/men/conference.html", True), ("docs/women/conference.html", True),
    ("docs/men/predict_2026-11-05.html", True), ("docs/women/predict_2027-03-15.html", True),
    ("docs/men/history.html", False), ("docs/women/history.html", False),
    ("docs/men/index.html", False), ("docs/_data/countdowns.yml", False),
    ("docs/assets/data/predictions/men/2027/2026-11-05.json", False),
])
def test_cbb_generated_pages_are_ignored_and_their_sources_are_not(path, ignored):
    if not shutil.which("git"):
        pytest.skip("no git")
    res = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT)
    assert (res.returncode == 0) == ignored


# --------------------------------------------------------------------------- #
# Finding 6: a profile per Chromium, and CI skips the Pi's data commits.
# --------------------------------------------------------------------------- #

def test_every_chromium_gets_its_own_profile_and_reap_deletes_it(monkeypatch):
    import browser_util

    launched = []

    class FakeProc:
        def __init__(self, argv, **kw):
            launched.append(argv)

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(browser_util.subprocess, "Popen", FakeProc)
    a, b = browser_util.launch("chrome", 9555), browser_util.launch("chrome", 9556)
    dirs = [next(x.split("=", 1)[1] for x in argv if x.startswith("--user-data-dir="))
            for argv in launched]
    assert dirs[0] != dirs[1] and all(Path(d).is_dir() for d in dirs)
    assert "--remote-debugging-port=9555" in launched[0]
    browser_util.reap(a)
    browser_util.reap(b)
    assert not any(Path(d).exists() for d in dirs)


def test_ci_skips_the_pis_data_commits_but_not_code():
    import yaml

    job = yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml").read_text())["jobs"]["tests"]
    cond = job["if"]
    assert "'Daily refresh ('" in cond and "'Live update ('" in cond
    assert "head_commit.message" in cond, "pull requests (no head_commit) must still run"
