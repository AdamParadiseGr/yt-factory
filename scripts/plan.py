#!/usr/bin/env python3
"""Generate story scripts for MoneyPrinterTurbo (stdlib only).

Writes tasks.json (MPT batch manifest) and tasks_meta.json (title/description/provenance
per task). LLM chain: Gemini free tier (key rotation) -> Groq free tier.

Variety: random genre + structure per script, biased by data/weights.json (written by
diversity.py), the last 40 titles are passed to the model, optional viewer ideas
(data/ideas.json), niche hints (data/niche.json) and recurring series with a character
bible (data/world/<channel>.json).
"""
import argparse
import json
import os
import random
import re
import sys

import common

SERIES_MAX_DEFAULT = 5


def weighted(options, weights):
    ws = [max(0.05, float(weights.get(o, 1.0))) for o in options]
    return random.choices(options, ws)[0]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "series"


def first_line(script):
    return re.split(r"(?<=[.!?])\s", script.strip(), maxsplit=1)[0][:160]


def pick_series(ch, bible):
    """Return None (standalone), {'mode':'new'} or {'mode':'continue','series':...}."""
    if random.random() >= ch.get("series_ratio", 0.3):
        return None
    limit = ch.get("series_max_episodes", SERIES_MAX_DEFAULT)
    open_series = [s for s in bible.get("series", []) if len(s["episodes"]) < limit]
    if open_series and random.random() < 0.7:
        return {"mode": "continue", "series": random.choice(open_series), "limit": limit}
    return {"mode": "new", "limit": limit}


def series_block(sctx, bible):
    if not sctx:
        return ""
    chars = bible.get("characters", {})
    if sctx["mode"] == "new":
        return ("This is episode 1 of a NEW mini-series of up to "
                f"{sctx['limit']} episodes. Invent 1-3 recurring characters with a one-sentence "
                "visual look each. End on a hook that makes viewers want episode 2.")
    s = sctx["series"]
    eps = "\n".join(f"- Episode {e['n']}: {e['summary']}" for e in s["episodes"])
    cast = "\n".join(f"- {n}: {c['look']}" for n, c in chars.items() if c.get("series") == s["id"])
    n = len(s["episodes"]) + 1
    ending = ("This is the FINAL episode: resolve the story." if n >= sctx["limit"]
              else "End on a hook for the next episode.")
    return (f"This is episode {n} of the series \"{s['title']}\" ({s['logline']}).\n"
            f"Previous episodes:\n{eps}\nRecurring characters:\n{cast}\n"
            f"The story must work for a new viewer but continue the plot. {ending}")


DEFAULT_BRIEF = "You write original short narrated stories for a YouTube Shorts channel."
DEFAULT_RULES = ["original plot and characters", "plain spoken English", "a strong first sentence",
                 "no stage directions, no headings, no emojis in the narration",
                 "no real people, no brands, no real-world trademarks",
                 "suitable for a general audience"]


def build_prompt(ch, genre, structure, used, sblock, idea, niche_hint):
    words = int(ch["target_seconds"] * ch.get("words_per_second", 2.4))
    avoid = "; ".join(used[-40:]) or "none yet"
    extra = []
    if sblock:
        extra.append(sblock)
    if idea:
        extra.append(f"Base the story on this viewer idea (keep it original): {idea}")
    if niche_hint:
        extra.append(f"Formats currently working in this niche (use as inspiration only): {niche_hint}")
    extra_text = "\n".join(extra)
    rules = "; ".join(ch.get("rules", DEFAULT_RULES))
    return f"""{ch.get('brief', DEFAULT_BRIEF)}
Write ONE piece: {genre}. Structure: {structure}.
Length: about {words} words of narration (about {ch['target_seconds']} seconds).
Rules: {rules}.
{extra_text}
Do not reuse these earlier titles or ideas: {avoid}.
Return JSON only with keys:
"title" (max 70 chars, intriguing, no clickbait lies),
"description" (2-3 sentences, plus 3 hashtags),
"tags" (list of 5 to 8 lowercase search tags),
"script" (the narration text),
"summary" (2 sentences describing what happens),
"scenes" (list of 8 to 10 short English visual descriptions of the scenes in order,
each concrete: who, where, lighting; no text in the image; whenever a recurring
character appears, repeat their exact look phrase in that scene),
"characters" (list of {{"name","look"}} for every recurring character that appears; may be empty),
"series_title" and "series_logline" (only for a new series, otherwise empty strings)."""


def update_bible(bible, sctx, item, title, summary):
    if not sctx:
        return None, None
    chars = bible.setdefault("characters", {})
    if sctx["mode"] == "new":
        s = {"id": slug(item.get("series_title") or title),
             "title": item.get("series_title") or title,
             "logline": item.get("series_logline") or summary, "episodes": []}
        bible.setdefault("series", []).append(s)
    else:
        s = sctx["series"]
    s["episodes"].append({"n": len(s["episodes"]) + 1, "title": title, "summary": summary})
    for c in item.get("characters") or []:
        if isinstance(c, dict) and c.get("name") and c.get("look") and c["name"] not in chars:
            chars[c["name"]] = {"look": c["look"], "series": s["id"]}
    return s["id"], len(s["episodes"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--out", default="tasks.json")
    ap.add_argument("--meta", default="tasks_meta.json")
    a = ap.parse_args()

    ch = common.channel(a.channel)
    override = [g.strip() for g in os.environ.get("GENRES_OVERRIDE", "").split("|") if g.strip()]
    if override:  # genres typed in the n8n control panel for this run
        ch["genres"] = override
    history = common.load("data/history.json", [])
    used = [h["title"] for h in history if h.get("channel") == a.channel]
    weights = common.load("data/weights.json", {}).get(a.channel, {})
    bible_path = f"data/world/{a.channel}.json"
    bible = common.load(bible_path, {"characters": {}, "series": []})
    ideas = common.load("data/ideas.json", [])
    niche = common.load("data/niche.json", {}).get(a.channel, {})
    niche_hint = "; ".join(niche.get("patterns", [])[:3])

    tasks, meta = [], []
    for _ in range(a.count):
        genre = weighted(ch["genres"], weights.get("genres", {}))
        structure = weighted(ch["structures"], weights.get("structures", {}))
        sctx = pick_series(ch, bible)
        idea_row = next((i for i in ideas if i.get("channel") == a.channel and not i.get("used")), None)
        idea = idea_row["text"] if idea_row and not sctx and random.random() < 0.5 else None
        item, model = common.llm_json(
            build_prompt(ch, genre, structure, used, series_block(sctx, bible), idea, niche_hint))
        if not item:
            print("all LLM keys exhausted or bad JSON; stopping early", file=sys.stderr)
            break
        try:
            title, script, scenes = item["title"], item["script"], item["scenes"]
            assert isinstance(scenes, list) and len(scenes) >= 4 and len(script) > 200
        except Exception as e:  # noqa: BLE001
            print(f"bad LLM output skipped: {type(e).__name__}", file=sys.stderr)
            continue
        summary = item.get("summary") or ""
        series_id, episode = update_bible(bible, sctx, item, title, summary)
        if idea:
            idea_row["used"] = True
        style = ch["image_style"]
        tasks.append({
            "video_subject": title,
            "video_script": script,
            "video_terms": [f"{s.rstrip('.')}, {style}" for s in scenes],
            "video_language": ch["language"],
            "voice_name": ch["voice_name"],
            "voice_rate": ch["voice_rate"],
            "video_source": "openai_image",
            "video_aspect": ch["aspect"],
            "font_name": ch["font_name"],
            "font_size": ch["font_size"],
            "subtitle_enabled": True,
        })
        meta.append({"channel": a.channel, "title": title,
                     "description": item.get("description", ""),
                     "tags": [str(t)[:30] for t in (item.get("tags") or [])][:8], "genre": genre,
                     "structure": structure, "series": series_id, "episode": episode,
                     "text_model": model, "voice": ch["voice_name"],
                     "image_model": "flux-1-schnell", "date": common.today(),
                     "made_for_kids": bool(ch.get("made_for_kids")), "script": script})
        used.append(title)
        history.append({"channel": a.channel, "title": title, "genre": genre,
                        "structure": structure, "first_line": first_line(script),
                        "series": series_id, "episode": episode, "summary": summary,
                        "date": common.today()})

    if not tasks:
        print("no tasks produced", file=sys.stderr)
        sys.exit(1)
    json.dump(tasks, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(meta, open(a.meta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    common.save("data/history.json", history)
    common.save(bible_path, bible)
    common.save("data/ideas.json", ideas)
    print(f"planned {len(tasks)} task(s)")


if __name__ == "__main__":
    main()
