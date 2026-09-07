'''
Tests for the authenticated-session probes in runAiBot.py
(_session_has_li_at / _signed_in_markers / _real_session_ready).

These lock down a real bug: the referral-send flow force-navigated to
/feed/ to "verify" login, which tripped a LinkedIn challenge interstitial and
then wrongly reported "not signed in" - even when the session was fine. The
fixed probe decides from the li_at cookie and the CURRENT page's markers,
navigating nowhere (or only /feed/ as a last resort).
'''

import os

os.environ["AJA_SMOKE"] = "1"  # open_chrome.py skips browser creation on import

import pytest
from selenium.common.exceptions import NoSuchElementException

import runAiBot as bot


class _FakeElement:
    def __bool__(self):
        return True


class FakeDriver:
    """Minimal stand-in for a selenium driver, scriptable per test."""

    def __init__(self, url="https://www.linkedin.com/jobs/search/", cookies=None,
                 markers=False, feed_url=None, feed_markers=True):
        self._url = url
        self._cookies = list(cookies or [])
        self.marker_on = markers
        self._feed_url = feed_url
        self._feed_markers = feed_markers
        self.navigations = []

    @property
    def current_url(self):
        return self._url

    def get_cookies(self):
        return list(self._cookies)

    def get(self, url):
        self.navigations.append(url)
        self._url = self._feed_url if self._feed_url is not None else url
        if url == "https://www.linkedin.com/feed/":
            self.marker_on = self._feed_markers

    def find_element(self, by, value):
        if self.marker_on:
            return _FakeElement()
        raise NoSuchElementException(value)


# ---------------------------------------------------------------------------
# _session_has_li_at
# ---------------------------------------------------------------------------

def test_li_at_cookie_means_logged_in():
    d = FakeDriver(cookies=[{"name": "li_at", "value": "AQED...xyz"}])
    assert bot._session_has_li_at(d) is True


def test_no_cookies_means_not_logged_in():
    d = FakeDriver(cookies=[])
    assert bot._session_has_li_at(d) is False


def test_other_cookies_do_not_count():
    d = FakeDriver(cookies=[{"name": "csrf_token", "value": "x"}, {"name": "bcookie", "value": "y"}])
    assert bot._session_has_li_at(d) is False


# ---------------------------------------------------------------------------
# _signed_in_markers
# ---------------------------------------------------------------------------

def test_markers_present_on_logged_in_page():
    assert bot._signed_in_markers(FakeDriver(markers=True)) is True


def test_markers_absent_on_login_like_page():
    assert bot._signed_in_markers(FakeDriver(markers=False)) is False


# ---------------------------------------------------------------------------
# _real_session_ready - the bug this locks down
# ---------------------------------------------------------------------------

def test_ready_when_li_at_present_without_any_navigation():
    """Logged-in session must NOT be force-navigated (the old bug)."""
    d = FakeDriver(
        url="https://www.linkedin.com/jobs/search/?keywords=Product%20Manager",
        cookies=[{"name": "li_at", "value": "AQED...xyz"}],
        markers=False,
    )
    assert bot._real_session_ready(d) is True
    assert d.navigations == []  # no /feed/ probe, no login attempt


def test_ready_via_current_page_markers_without_navigation():
    """Post-scan page already renders the top nav -> no navigation needed."""
    d = FakeDriver(
        url="https://www.linkedin.com/jobs/search/?keywords=Product%20Manager",
        cookies=[],
        markers=True,
    )
    assert bot._real_session_ready(d) is True
    assert d.navigations == []


def test_falls_back_to_feed_probe_when_current_page_ambiguous():
    """Blank/unauthenticated page -> /feed/ probe runs and can pass."""
    d = FakeDriver(url="about:blank", cookies=[], markers=False,
                   feed_url="https://www.linkedin.com/feed/", feed_markers=True)
    assert bot._real_session_ready(d) is True
    assert d.navigations == ["https://www.linkedin.com/feed/"]


def test_feed_probe_fails_on_login_redirect():
    """/feed/ bouncing to a login page means the session is genuinely bad."""
    d = FakeDriver(url="about:blank", cookies=[], markers=False,
                   feed_url="https://www.linkedin.com/login")
    assert bot._real_session_ready(d) is False


def test_missing_session_on_extraneous_page_is_not_logged_in():
    """On a login page with no session, the /feed/ probe bounces to authwall."""
    d = FakeDriver(url="https://www.linkedin.com/login", cookies=[], markers=False,
                   feed_url="https://www.linkedin.com/login")
    assert bot._real_session_ready(d) is False