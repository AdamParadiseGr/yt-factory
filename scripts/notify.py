#!/usr/bin/env python3
"""Send one line to Telegram (used by workflows when a job fails)."""
import sys

import common

common.tg_text(" ".join(sys.argv[1:]) or "yt-factory: notification")
