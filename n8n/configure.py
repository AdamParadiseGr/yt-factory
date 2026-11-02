#!/usr/bin/env python3
"""Fill the placeholders in n8n/workflows/*.json in one go.

python3 n8n/configure.py YOUR_USER/yt-factory 123456789 GOOGLE_SHEET_ID DRIVE_FOLDER_ID
(telegram chat id, id of the Google Sheet with the "panel" tab, id of the Drive folder for approved videos)
"""
import glob
import os
import sys

if len(sys.argv) != 5:
    sys.exit(__doc__)
repo, chat, sheet, folder = sys.argv[1:]
pairs = {"YOUR_GITHUB_USER/yt-factory": repo, "YOUR_TELEGRAM_CHAT_ID": chat,
         "YOUR_GOOGLE_SHEET_ID": sheet, "YOUR_DRIVE_FOLDER_ID": folder}
for f in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflows", "*.json")):
    s = open(f, encoding="utf-8").read()
    for k, v in pairs.items():
        s = s.replace(k, v)
    open(f, "w", encoding="utf-8").write(s)
    print("updated", os.path.basename(f))
