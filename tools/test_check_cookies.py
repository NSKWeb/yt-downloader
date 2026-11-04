"""Tests for the cookies.txt validator.

The point of the tool is the verdict, so the cases that matter are the ones a
user hits: a good export, one taken while signed out, an expired one, a
truncated one, and one for the wrong site.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_cookies as cc  # noqa: E402

HEADER = "# Netscape HTTP Cookie File\n"


def jar(*rows: str) -> str:
    return HEADER + "".join(row + "\n" for row in rows)


def row(domain, name, value="v", expires=0, flag="TRUE", path="/", secure="TRUE"):
    return "\t".join([domain, flag, path, secure, str(expires), name, value])


def verdict(text: str) -> tuple[bool, str]:
    cookies, problems = cc.parse(text)
    lines, ok = cc.report(cookies, problems)
    return ok, "\n".join(lines)


class TestParse:
    def test_reads_seven_tab_separated_fields(self):
        cookies, problems = cc.parse(jar(row(".youtube.com", "SID")))
        assert problems == []
        assert cookies[0]["domain"] == "youtube.com"
        assert cookies[0]["name"] == "SID"

    def test_ignores_blank_lines_and_comments(self):
        text = HEADER + "\n# a comment\n" + row(".youtube.com", "SID") + "\n\n"
        cookies, problems = cc.parse(text)
        assert problems == []
        assert len(cookies) == 1

    def test_reports_missing_header(self):
        _, problems = cc.parse(row(".youtube.com", "SID") + "\n")
        assert any("header" in p for p in problems)

    def test_reports_wrong_field_count(self):
        _, problems = cc.parse(HEADER + "youtube.com\tTRUE\t/\n")
        assert any("7 tab-separated fields" in p for p in problems)

    def test_reports_non_numeric_expiry(self):
        _, problems = cc.parse(jar(row(".youtube.com", "SID", expires="soon")))
        assert any("not a number" in p for p in problems)


class TestVerdict:
    def test_session_cookie_is_accepted(self):
        ok, out = verdict(jar(row(".youtube.com", "SID")))
        assert ok
        assert "OK" in out

    def test_each_session_cookie_name_counts(self):
        for name in ("SID", "SSID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "HSID"):
            ok, _ = verdict(jar(row(".youtube.com", name)))
            assert ok, name

    def test_google_domain_counts_as_youtube(self):
        ok, _ = verdict(jar(row(".google.com", "__Secure-1PSID")))
        assert ok

    def test_signed_out_export_is_rejected(self):
        """A jar of consent cookies looks fine but carries no session."""
        ok, out = verdict(jar(row(".youtube.com", "PREF"), row(".youtube.com", "CONSENT")))
        assert not ok
        assert "not signed in" in out

    def test_expired_session_is_rejected(self):
        past = int(time.time()) - 3600
        ok, out = verdict(jar(row(".youtube.com", "SID", expires=past)))
        assert not ok
        assert "expired" in out

    def test_future_expiry_is_accepted(self):
        future = int(time.time()) + 3600
        ok, _ = verdict(jar(row(".youtube.com", "SID", expires=future)))
        assert ok

    def test_other_site_is_rejected(self):
        ok, out = verdict(jar(row(".example.com", "SID")))
        assert not ok
        assert "no YouTube cookies" in out

    def test_empty_value_is_not_a_session(self):
        ok, out = verdict(jar(row(".youtube.com", "SID", value="")))
        assert not ok
        assert "not signed in" in out

    def test_malformed_file_is_rejected_even_with_a_session(self):
        """A session row plus a broken row is still a file to re-export."""
        ok, out = verdict(jar(row(".youtube.com", "SID")) + "broken\trow\n")
        assert not ok
        assert "malformed" in out

    def test_empty_input_is_rejected(self):
        ok, _ = verdict("")
        assert not ok


class TestCli:
    def test_exit_zero_on_a_good_file(self, tmp_path, capsys):
        path = tmp_path / "cookies.txt"
        path.write_text(jar(row(".youtube.com", "SID")))
        assert cc.main(["check_cookies.py", str(path)]) == 0
        assert "OK" in capsys.readouterr().out

    def test_exit_one_on_a_bad_file(self, tmp_path):
        path = tmp_path / "cookies.txt"
        path.write_text("nonsense")
        assert cc.main(["check_cookies.py", str(path)]) == 1

    def test_missing_file_is_an_error(self, tmp_path, capsys):
        assert cc.main(["check_cookies.py", str(tmp_path / "nope.txt")]) == 1
        assert "no such file" in capsys.readouterr().err

    def test_reads_stdin_when_no_path(self, monkeypatch, capsys):
        import io

        monkeypatch.setattr(sys, "stdin", io.StringIO(jar(row(".youtube.com", "SID"))))
        assert cc.main(["check_cookies.py"]) == 0
        assert "<stdin>" in capsys.readouterr().out


class TestEncodingArtefacts:
    """A file from Notepad or a copy-paste must not read as malformed.

    The downloader strips these before handing the jar to yt-dlp, so a checker
    that rejects them would disagree with the deployment it is checking for.
    """

    def test_utf8_bom_is_ignored(self):
        ok, out = verdict("\ufeff" + jar(row(".youtube.com", "SID")))
        assert ok
        assert "OK" in out

    def test_crlf_endings_are_accepted(self):
        ok, _ = verdict(jar(row(".youtube.com", "SID")).replace("\n", "\r\n"))
        assert ok

    def test_lone_cr_endings_are_accepted(self):
        ok, _ = verdict(jar(row(".youtube.com", "SID")).replace("\n", "\r"))
        assert ok
