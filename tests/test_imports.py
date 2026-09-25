"""
Import-graph check.

The 2026-08 restructure moved every package and rewrote ~150 imports; one of
them was a dynamic `importlib.import_module(f"src.site.{module}")` that no
static rename touched and that only failed at page-build time.

This walks the AST instead of importing, so it runs without pandas, matplotlib
or a network — which is what makes it usable as a pre-commit check.
"""

import ast

import pytest

from conftest import SRC

OURS = {"cbb", "wnba", "fantasy", "gordstats"}
PY_FILES = sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _module_path(dotted: str):
    p = SRC.joinpath(*dotted.split("."))
    if (p / "__init__.py").exists():
        return p / "__init__.py"
    f = p.with_suffix(".py")
    return f if f.exists() else None


def _top_level_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.asname or a.name.split(".")[0] for a in node.names)
    return names


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(SRC)))
def test_intra_repo_imports_resolve(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    problems = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            if node.module.split(".")[0] not in OURS:
                continue
            target = _module_path(node.module)
            if target is None:
                problems.append(f"line {node.lineno}: no module {node.module}")
                continue
            defined = _top_level_names(target)
            for alias in node.names:
                if alias.name == "*" or alias.name in defined:
                    continue
                if _module_path(f"{node.module}.{alias.name}"):
                    continue
                problems.append(f"line {node.lineno}: {node.module} has no {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in OURS and _module_path(alias.name) is None:
                    problems.append(f"line {node.lineno}: no module {alias.name}")

    assert not problems, "\n".join(problems)


def test_no_dynamic_imports_of_the_old_package_name():
    """`importlib.import_module(f"src.site.{module}")` survived a rename that
    rewrote every static import, and broke every page build at runtime."""
    offenders = []
    for path in PY_FILES:
        text = path.read_text(encoding="utf-8")
        if "import_module" not in text:
            continue
        for line in text.splitlines():
            if "import_module" in line and '"src.' in line.replace("'", '"'):
                offenders.append(f"{path.relative_to(SRC)}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_no_module_level_infinite_loop():
    """GO.py ran `while True:` at module level, so merely importing it hung —
    a trap for anything that walks the package."""
    for path in PY_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in tree.body:
            if isinstance(node, ast.While) and isinstance(node.test, ast.Constant):
                assert not node.test.value, f"{path.relative_to(SRC)} loops forever on import"


# --------------------------------------------------------------------------- #
# Every call to Sleeper retries
# --------------------------------------------------------------------------- #

def test_nothing_calls_sleeper_without_a_retry():
    """Sleeper drops the occasional TLS handshake, and a bare requests.get
    against it fails whatever page it is behind.

    This was fixed once by patching sleeper_wrapper, and then the matchups
    page - which has its own _get - took the fantasy section of the daily run
    down for the same reason a fortnight later. So the rule lives in the file
    rather than in anyone's memory: a call to api.sleeper.app goes through
    fantasy.sleeper_retry (get_json, or the patched library) or through
    fantasy.live._get, which has its own retry loop.

    Only Sleeper. The other hosts here (ESPN, Yahoo, FantasyPros) have not
    shown this failure and are left alone.
    """
    import re
    from conftest import ROOT

    allowed = {
        "src/fantasy/sleeper_retry.py",   # the retry itself
        "src/fantasy/live.py",            # its own documented retry loop
    }
    # The URL is the argument, so look at what the call actually opens with -
    # a module can talk to four hosts and only one of them is Sleeper.
    marker = re.compile(r"SLEEPER|sleeper\.app", re.I)
    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in allowed:
            continue
        text = path.read_text()
        for call in re.finditer(r"\brequests\.(?:get|post)\(", text):
            arg = text[call.end():call.end() + 160]
            if marker.search(arg.split(")")[0]):
                line = text[:call.start()].count("\n") + 1
                offenders.append(f"{rel}:{line}")
    assert not offenders, (
        "these call Sleeper without a retry: " + ", ".join(offenders))
