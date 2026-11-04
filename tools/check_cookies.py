#!/usr/bin/env python3
"""Validate a cookies.txt before it is handed to YTDLP_COOKIES.

A cookies file that is malformed, for the wrong site, or expired looks fine to
the downloader: it starts up, reports `cookies: true`, and then every download
fails with the same 403 the file was meant to clear. The failure is far from the
cause, so this checks the file first and says what is wrong.

Reads a path argument, or stdin when given none:

    python3 tools/check_cookies.py ~/Downloads/cookies.txt
    cat cookies.txt | python3 tools/check_cookies.py

Exit code 0 means the file is usable for YouTube; 1 means it is not.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# yt-dlp sends every cookie in the jar, so the site set is what matters, not the
# filename. YouTube needs at least one of these; the first two are the ones that
# carry a signed-in session, the rest are consent/state cookies that a
# signed-out export also has.
SESSION_COOKIES = {"SID", "SSID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "HSID"}

YOUTUBE_DOMAINS = ("youtube.com", "youtu.be", "google.com")


def parse(text: str) -> tuple[list[dict], list[str]]:
    """Return (cookies, problems). A Netscape file is tab-separated, 7 fields."""
    cookies: list[dict] = []
    problems: list[str] = []
    saw_header = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("#"):
            if "Netscape HTTP Cookie File" in line:
                saw_header = True
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            problems.append(f"line {lineno}: expected 7 tab-separated fields, found {len(fields)}")
            continue
        domain, _flag, path, secure, expires, name, value = fields
        try:
            expiry = int(expires)
        except ValueError:
            problems.append(f"line {lineno}: expiry {expires!r} is not a number")
            expiry = 0
        cookies.append(
            {
                "domain": domain.lstrip("."),
                "path": path,
                "secure": secure,
                "expires": expiry,
                "name": name,
                "value": value,
            }
        )
    if not saw_header:
        problems.append(
            "no '# Netscape HTTP Cookie File' header; "
            "the file is probably not a cookies.txt export"
        )
    return cookies, problems


def report(cookies: list[dict], problems: list[str]) -> tuple[list[str], bool]:
    """Return (lines, ok)."""
    lines: list[str] = []
    for problem in problems:
        lines.append(f"  problem: {problem}")

    if not cookies:
        lines.append("  no cookies found")
        return lines, False

    now = int(time.time())
    youtube = [c for c in cookies if any(c["domain"].endswith(d) for d in YOUTUBE_DOMAINS)]
    session = [c for c in youtube if c["name"] in SESSION_COOKIES and c["value"]]
    # A zero expiry is a session cookie: valid until the browser closes, which is
    # exactly what a fresh export holds.
    live = [c for c in session if c["expires"] == 0 or c["expires"] > now]
    expired = [c for c in session if c["expires"] and c["expires"] <= now]

    domains = sorted({c["domain"] for c in cookies})
    lines.append(f"  cookies total    : {len(cookies)}")
    lines.append(f"  youtube/google   : {len(youtube)}")
    lines.append(f"  session cookies  : {len(session)} ({', '.join(sorted({c['name'] for c in session})) or 'none'})")
    lines.append(f"  domains          : {', '.join(domains[:6])}{' ...' if len(domains) > 6 else ''}")

    if expired:
        lines.append(f"  expired          : {len(expired)} ({', '.join(sorted({c['name'] for c in expired}))})")

    ok = bool(live) and not problems
    if not youtube:
        lines.append("  -> no YouTube cookies. Export cookies.txt while signed in to youtube.com")
    elif not session:
        lines.append("  -> YouTube cookies are present but none carry a session.")
        lines.append("     The browser was not signed in when the file was exported.")
    elif not live:
        lines.append("  -> every session cookie has expired. Export a fresh cookies.txt.")
    elif problems:
        lines.append("  -> the file is readable but malformed; re-export it")
    else:
        lines.append("  -> OK: paste this file's contents as YTDLP_COOKIES")
    return lines, ok


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        source = Path(argv[1])
        if not source.is_file():
            print(f"no such file: {source}", file=sys.stderr)
            return 1
        text = source.read_text(errors="replace")
        label = str(source)
    else:
        text = sys.stdin.read()
        label = "<stdin>"

    print(f"checking {label}")
    cookies, problems = parse(text)
    lines, ok = report(cookies, problems)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
