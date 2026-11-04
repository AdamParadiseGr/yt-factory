#!/usr/bin/env python3
"""Send QC-passed videos to Telegram for review (stdlib only).

Reads summary.json (MPT batch output), tasks_meta.json and qc.json. For every video that
passes QC it: copies the mp4 + a json sidecar to outbox/ (uploaded as a workflow artifact,
used later by compile.py), sends the video, sends translated titles, records provenance and
marks the video "pending" in data/status.json. If APPROVAL_BUTTONS=1 the message carries
inline buttons whose callbacks are handled by n8n (see n8n/README.md).
"""
import glob
import json
import os
import shutil
import sys

import common

MAX = 50 * 1024 * 1024  # Telegram bot upload limit
BUTTONS = os.environ.get("APPROVAL_BUTTONS") == "1"


def rows(tid):
    return [[("Одобрить", f"approve:{tid}"), ("Переделать", f"redo:{tid}")],
            [("Другой заголовок", f"retitle:{tid}"), ("Отклонить", f"reject:{tid}")]]


def main():
    try:
        summary = json.load(open("summary.json", encoding="utf-8"))
    except (OSError, ValueError):
        common.tg_text("Render step produced no summary - open the workflow run logs.")
        sys.exit(1)
    meta = json.load(open("tasks_meta.json", encoding="utf-8"))
    try:
        qcs = json.load(open("qc.json", encoding="utf-8"))
    except (OSError, ValueError):
        qcs = {}
    status = common.load("data/status.json", {})
    prov = common.load("data/provenance.json", [])
    os.makedirs("outbox", exist_ok=True)
    sent = 0
    for t in summary.get("tasks", []):
        i = t.get("index", 0) - 1  # MPT batch indices start at 1
        m = meta[i] if 0 <= i < len(meta) else {"title": "", "description": ""}
        if t.get("status") != "succeeded":
            common.tg_text(f"Task {t.get('index')} failed at {t.get('failed_stage')}: "
                           f"{str(t.get('error'))[:300]}")
            continue
        tid = t["task_id"]
        qc = qcs.get(tid, {"ok": True, "problems": [], "duration": 0})
        if not qc["ok"]:
            common.tg_text(f"Auto-rejected by QC: {m['title']}\n- " + "\n- ".join(qc["problems"]))
            status[tid] = {"status": "auto_rejected", "title": m["title"], "date": common.today()}
            continue
        for path in sorted(glob.glob(os.path.join("MoneyPrinterTurbo", "storage", "tasks", tid, "final-*.mp4"))):
            shutil.copy(path, os.path.join("outbox", f"{tid}.mp4"))
            json.dump({**{k: v for k, v in m.items() if k != "script"}, "task_id": tid,
                       "duration": qc.get("duration", 0)},
                      open(os.path.join("outbox", f"{tid}.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            tag = f"[{m.get('genre', '')}]"
            if m.get("series"):
                tag += f" series {m['series']} ep {m.get('episode')}"
            caption = f"{m['title']}\n{tag}\n\n{m['description']}"
            if m.get("made_for_kids"):
                caption += "\n\nStudio: set audience to 'Yes, it's made for kids'."
            buttons = rows(tid) if BUTTONS else None
            if os.path.getsize(path) > MAX:
                common.tg_text(f"[too big for Telegram, see workflow artifacts]\n{caption}", buttons)
            else:
                common.tg_file(path, caption, "video", buttons)
            loc = m.get("localizations")
            if loc:
                lines = [f"Translations for: {m['title']}"]
                for lang, v in loc.items():
                    lines.append(f"\n[{lang}] {v['title']}\n{v.get('description', '')}")
                common.tg_text("\n".join(lines))
            prov.append({"task_id": tid, "date": common.today(), "channel": m.get("channel"),
                         "title": m["title"], "genre": m.get("genre"), "series": m.get("series"),
                         "text_model": m.get("text_model"), "image_model": m.get("image_model"),
                         "voice": m.get("voice"), "tts": "kokoro" if str(m.get("voice", "")).startswith("kokoro:") else "edge-tts",
                         "assembler": "MoneyPrinterTurbo@" + os.environ.get("MPT_REF", "main"),
                         "synthetic_media": True})
            status[tid] = {"status": "pending", "title": m["title"], "channel": m.get("channel"),
                           "description": m.get("description", ""), "tags": m.get("tags", []),
                           "made_for_kids": bool(m.get("made_for_kids")), "date": common.today()}
            sent += 1
    common.save("data/status.json", status)
    common.save("data/provenance.json", prov)
    print(f"delivered {sent} video(s)")


if __name__ == "__main__":
    main()
