#!/usr/bin/env python3
"""Weekly compilation: approved Shorts of the last 7 days -> one 16:9 video (target 8-10 min).

Videos come from the "videos-*" workflow artifacts that produce.yml uploads (kept 14 days).
Only items marked "approved" in data/status.json are used (set by the n8n approval buttons);
with --include-pending all not-rejected items are used. Each vertical clip is placed over a
blurred copy of itself, chapters are written into the description. Needs gh CLI + GH_TOKEN.
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys

import common

MIN_CLIPS, MAX_SECONDS = 8, 600


def fmt_ts(sec):
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapters(items):
    """items: [{'title','duration'}] -> chapter lines starting at 0:00."""
    t, lines = 0.0, []
    for it in items:
        lines.append(f"{fmt_ts(t)} {it['title']}")
        t += it["duration"]
    return lines


def select(items, status, include_pending):
    ok = {"approved"} | ({"pending"} if include_pending else set())
    chosen = [i for i in items if status.get(i["task_id"], {}).get("status") in ok]
    chosen.sort(key=lambda i: (i.get("date", ""), i["task_id"]))
    out, total = [], 0.0
    for i in chosen:
        if total + i["duration"] > MAX_SECONDS:
            break
        out.append(i)
        total += i["duration"]
    return out


def sh(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def download(days, dest):
    repo = os.environ["GITHUB_REPOSITORY"]
    arts = json.loads(sh(["gh", "api", f"repos/{repo}/actions/artifacts?per_page=100"]))["artifacts"]
    cutoff = common.now() - datetime.timedelta(days=days)
    for a in arts:
        if a["expired"] or not a["name"].startswith("videos-"):
            continue
        if datetime.datetime.fromisoformat(a["created_at"].replace("Z", "+00:00")) < cutoff:
            continue
        sh(["gh", "run", "download", str(a["workflow_run"]["id"]), "-n", a["name"],
            "-D", os.path.join(dest, str(a["id"]))])
    items = []
    for js in glob.glob(os.path.join(dest, "*", "*.json")):
        meta = json.load(open(js, encoding="utf-8"))
        mp4 = js[:-5] + ".mp4"
        if os.path.exists(mp4):
            items.append({**meta, "file": mp4})
    return items


def normalise(src, dst):
    vf = ("[0:v]split[a][b];[a]scale=1280:720:force_original_aspect_ratio=increase,"
          "crop=1280:720,boxblur=30:5[bg];[b]scale=-2:720[fg];[bg][fg]overlay=(W-w)/2:0,"
          "format=yuv420p[v]")
    sh(["ffmpeg", "-y", "-i", src, "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
        "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", dst])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--include-pending", action="store_true")
    ap.add_argument("--work", default="compile_work")
    ap.add_argument("--out", default="compile_out")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    status = common.load("data/status.json", {})
    items = select(download(a.days, a.work), status, a.include_pending)
    if len(items) < MIN_CLIPS:
        common.tg_text(f"Weekly compilation skipped: {len(items)} usable clips, need {MIN_CLIPS}. "
                       "Approve more videos or run with --include-pending.")
        return
    parts = []
    for n, it in enumerate(items):
        dst = os.path.join(a.work, f"n{n:02d}.mp4")
        normalise(it["file"], dst)
        parts.append(dst)
    listing = os.path.join(a.work, "list.txt")
    open(listing, "w").write("".join(f"file '{os.path.abspath(p)}'\n" for p in parts))
    out_mp4 = os.path.join(a.out, f"collection-{common.today()}.mp4")
    sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", out_mp4])
    ch = chapters(items)
    res, _ = common.llm_json(
        "Write a YouTube title (max 70 chars) for a compilation of these short stories, plus a "
        "2-sentence description. JSON only: {\"title\",\"description\"}.\n" +
        "\n".join(i["title"] for i in items), temperature=0.7)
    title = (res or {}).get("title") or f"{items[0]['title']} and {len(items) - 1} more stories"
    desc = ((res or {}).get("description") or "A collection of short stories.") + \
        "\n\nChapters:\n" + "\n".join(ch)
    open(out_mp4[:-4] + ".txt", "w", encoding="utf-8").write(f"{title}\n\n{desc}\n")
    msg = f"Weekly compilation: {title}\n\n{desc}"
    if os.path.getsize(out_mp4) <= 50 * 1024 * 1024:
        common.tg_file(out_mp4, msg, "document")
    else:
        common.tg_text("[file over 50 MB, download it from this run's artifacts]\n" + msg)


if __name__ == "__main__":
    main()
