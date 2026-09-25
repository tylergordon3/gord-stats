"""
Retries for the flaky hosts this package talks to - Sleeper above all.

`sleeper_wrapper.base_api.BaseApi._call` is a bare `requests.get(url)`: no
timeout, no retry. api.sleeper.app drops the occasional TLS handshake
(`SSLEOFError: UNEXPECTED_EOF_WHILE_READING`), and because every League /
Drafts / Players call in this package goes through that one method, a single
dropped connection failed whichever rebuild step happened to be running and
took the whole fantasy section down with it - 6 of the 25 daily runs in the
fortnight to 2026-09-24, each time a different step.

`fantasy.live` already retries for the same reason (a spurious 404 there).
This patches the library so every other call site gets the same treatment.
Installed by `fantasy/__init__.py`, so importing anything under `fantasy`
is enough; it is idempotent.

`get_json` is the same behaviour for code that calls `requests` directly.
The first version of this only patched the library, and the matchups page -
which has its own `_get` - went on failing the daily run for the same reason
a fortnight later. Anything here that talks to api.sleeper.app should go
through one of the two.
"""
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = 20
ATTEMPTS = 3

_installed = False


def _session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=0.7,
        # 404 is deliberately absent: Sleeper returns it legitimately for a
        # bracket or a week that does not exist yet, and callers read that.
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def get_json(url, params=None, headers=None, timeout=TIMEOUT, attempts=ATTEMPTS):
    """GET and parse JSON, retrying a dropped connection.

    Headers are passed through untouched: some callers (ESPN) must send no
    User-Agent at all, because its edge 403s a browser-like one coming from a
    non-browser TLS stack.
    """
    session = _shared()
    last = None
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(url, params=params, headers=headers or {}, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last = e
            # A bad status is the server's answer, not a broken pipe: retrying
            # a 404 just waits six seconds to be told the same thing.
            if e.response is not None and e.response.status_code < 500:
                raise
            if attempt == attempts:
                raise
            time.sleep(2 * attempt)
    raise last                                    # pragma: no cover


_shared_session = None


def _shared() -> requests.Session:
    global _shared_session
    if _shared_session is None:
        _shared_session = _session()
    return _shared_session


def install():
    """Give `BaseApi._call` a timeout and retries. Safe to call repeatedly."""
    global _installed
    if _installed:
        return

    from sleeper_wrapper.base_api import BaseApi

    session = _session()

    def _call(self, url: str):
        """Retrying replacement for BaseApi._call.

        Keeps the library's contract: the parsed JSON, or the HTTPError
        itself when the status stays bad - callers test for that.
        """
        last = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                r = session.get(url, timeout=TIMEOUT)
                break
            except requests.RequestException as e:
                last = e
                if attempt == ATTEMPTS:
                    raise
                time.sleep(2 * attempt)
        else:  # pragma: no cover - the loop either breaks or raises
            raise last

        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            return e
        return r.json()

    BaseApi._call = _call
    _installed = True
