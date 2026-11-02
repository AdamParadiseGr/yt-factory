#!/usr/bin/env python3
"""Daily check of YouTube's official list of YPP-available countries.

Sends a Telegram alert when "Uzbekistan" first appears in the list, and when the page can no
longer be parsed (3 failures in a row). It only reports what the official page says; the
program's terms, tax and payment requirements still have to be checked by you.
"""
import re
import sys

import common

URL = "https://support.google.com/youtube/answer/7101720?hl=en"
TARGET = "Uzbekistan"
SANITY = ("United States", "Brazil", "Germany")


def analyze(html):
    """Return (found, parsed_ok). Looks only at the text after the list's introduction."""
    m = re.search(r"in the following areas", html, re.I)
    if not m:
        return False, False
    window = html[m.end(): m.end() + 12000]
    if not all(s in window for s in SANITY):
        return False, False
    return re.search(rf"\b{TARGET}\b", window) is not None, True


def main():
    state = common.load("data/country_watch.json", {"found": False, "fails": 0})
    try:
        found, ok = analyze(common.http(URL, raw=True, timeout=60))
    except Exception as e:  # noqa: BLE001
        print(f"fetch failed: {type(e).__name__}", file=sys.stderr)
        found, ok = False, False
    state["checked"] = common.today()
    if not ok:
        state["fails"] = state.get("fails", 0) + 1
        if state["fails"] == 3:
            common.tg_text("YPP country watcher cannot read the official page for 3 days. "
                           f"Check it manually: {URL}")
    else:
        state["fails"] = 0
        if found and not state.get("found"):
            common.tg_text(f"{TARGET} now appears in YouTube's list of YPP-available areas.\n"
                           f"Verify on the official page: {URL}\n"
                           "Then check the program terms, AdSense payment address and tax "
                           "requirements for your case.")
        state["found"] = found
    common.save("data/country_watch.json", state)
    print(f"found={state['found']} fails={state['fails']}")


if __name__ == "__main__":
    main()
