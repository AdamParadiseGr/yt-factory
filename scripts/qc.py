#!/usr/bin/env python3
"""Automatic quality check between render and human review.

Reads summary.json + tasks_meta.json, inspects each finished task directory and writes
qc.json: {task_id: {"ok": bool, "problems": [...], "duration": float}}.
Checks: duration range, subtitles present, broken / blank / near-duplicate images
(difference hash), and an LLM check of the script for real people, brands and graphic
content. If no LLM key works, the script check is skipped (noted, not failed).
"""
import glob
import json
import os
import re
import subprocess
import sys

import common

TASKS_DIR = os.path.join("MoneyPrinterTurbo", "storage", "tasks")


def dhash(img, size=8):
    g = img.convert("L").resize((size + 1, size))
    px = list(g.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (px[row * (size + 1) + col] > px[row * (size + 1) + col + 1])
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def is_blank(img, min_std=6.0):
    g = list(img.convert("L").resize((32, 32)).getdata())
    mean = sum(g) / len(g)
    return (sum((v - mean) ** 2 for v in g) / len(g)) ** 0.5 < min_std


def near_duplicate_pairs(hashes, max_dist=4):
    pairs = 0
    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            if hamming(hashes[i], hashes[j]) <= max_dist:
                pairs += 1
    return pairs


def count_cues(srt_text):
    return len(re.findall(r"\d\d:\d\d:\d\d[,.]\d+\s*-->", srt_text))


def probe_duration(mp4):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4],
        capture_output=True, text=True, timeout=60)
    return float(out.stdout.strip())


def check_images(task_dir):
    from PIL import Image
    problems, hashes = [], []
    files = sorted(glob.glob(os.path.join(task_dir, "openai-image-*.png")))
    if len(files) < 4:
        problems.append(f"only {len(files)} generated images found")
    for f in files:
        try:
            with Image.open(f) as im:
                im.load()
                if is_blank(im):
                    problems.append(f"blank image {os.path.basename(f)}")
                hashes.append(dhash(im))
        except Exception:  # noqa: BLE001
            problems.append(f"broken image {os.path.basename(f)}")
    if hashes and near_duplicate_pairs(hashes) > max(1, len(hashes) // 4):
        problems.append("too many near-identical images")
    return problems


def check_script(script, audience="general"):
    kids = audience == "kids"
    extra = (", \"scary\": true/false (frightening, dark or upsetting for children aged 3-7), "
             "\"unsafe\": true/false (shows dangerous behaviour a child could imitate), "
             "\"too_complex\": true/false (vocabulary or themes too hard for ages 3-7)") if kids else ""
    prompt = ("Review this narration script for a " +
              ("children's (ages 3-7)" if kids else "general-audience") + " YouTube channel. "
              "Return JSON only: {\"real_people\": true/false (names or clearly identifiable "
              "real persons), \"brands\": true/false (real brands, trademarks, copyrighted "
              "characters or existing songs), \"graphic\": true/false (graphic violence, sexual "
              "content, hate)" + extra + ", \"reason\": short string}.\n\nSCRIPT:\n" + script[:4000])
    res, _ = common.llm_json(prompt, temperature=0)
    if not isinstance(res, dict):
        return None
    keys = ["real_people", "brands", "graphic"] + (["scary", "unsafe", "too_complex"] if kids else [])
    return [f"script: {k}" + (f" ({res.get('reason')})" if res.get("reason") else "")
            for k in keys if res.get(k) is True]


def main():
    try:
        summary = json.load(open("summary.json", encoding="utf-8"))
    except (OSError, ValueError):
        summary = {}
    meta = json.load(open("tasks_meta.json", encoding="utf-8"))
    out = {}
    for t in summary.get("tasks", []):
        if t.get("status") != "succeeded":
            continue
        i = t.get("index", 0) - 1
        m = meta[i] if 0 <= i < len(meta) else {}
        cfg = common.channel(m["channel"]) if m.get("channel") else {}
        qc_cfg = cfg.get("qc", {})
        lo, hi = qc_cfg.get("min_seconds", 25), qc_cfg.get("max_seconds", 75)
        task_dir = os.path.join(TASKS_DIR, t["task_id"])
        problems, duration = [], 0.0
        mp4s = sorted(glob.glob(os.path.join(task_dir, "final-*.mp4")))
        if not mp4s:
            problems.append("no final video file")
        else:
            try:
                duration = probe_duration(mp4s[0])
                if not lo <= duration <= hi:
                    problems.append(f"duration {duration:.0f}s outside {lo}-{hi}s")
            except Exception as e:  # noqa: BLE001
                problems.append(f"cannot read video ({type(e).__name__})")
        srt = os.path.join(task_dir, "subtitle.srt")
        if not os.path.exists(srt) or count_cues(open(srt, encoding="utf-8", errors="replace").read()) < 5:
            problems.append("subtitles missing or too short")
        problems += check_images(task_dir)
        if m.get("script"):
            sp = check_script(m["script"], cfg.get("audience", "general"))
            if sp is None:
                print(f"task {t['task_id']}: script check skipped (no LLM)", file=sys.stderr)
            else:
                problems += sp
        out[t["task_id"]] = {"ok": not problems, "problems": problems, "duration": duration}
        print(t["task_id"], "OK" if not problems else problems)
    json.dump(out, open("qc.json", "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
