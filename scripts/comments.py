#!/usr/bin/env python3
"""Weekly comment digest: continuation ideas and questions for you to answer yourself.

Reads public comments of recent uploads (YT_API_KEY is enough), asks the LLM for story ideas
and questions, stores the ideas in data/ideas.json (plan.py uses them) and sends a digest.
Nothing is ever posted back to YouTube.
"""
import sys
import urllib.error

import common
import ytapi

MAX_VIDEOS, PER_VIDEO = 8, 40


def fetch_comments(video_id):
    try:
        d = ytapi.get("commentThreads", part="snippet", videoId=video_id,
                      maxResults=PER_VIDEO, order="relevance", textFormat="plainText")
    except urllib.error.HTTPError:  # comments disabled
        return []
    return [i["snippet"]["topLevelComment"]["snippet"]["textDisplay"][:300] for i in d.get("items", [])]


def main():
    ideas = common.load("data/ideas.json", [])
    known = {i["text"].lower() for i in ideas}
    for name in common.channel_names():
        cfg = common.channel(name)
        if cfg.get("comments") is False:
            print(f"comments {name}: skipped (comments are disabled for made-for-kids videos)")
            continue
        cid = cfg.get("youtube_channel_id")
        if not cid:
            print(f"comments {name}: youtube_channel_id not set", file=sys.stderr)
            continue
        try:
            info = ytapi.channel_info(cid)
            ups = ytapi.uploads(info["uploads"], limit=MAX_VIDEOS)
        except Exception as e:  # noqa: BLE001
            print(f"comments {name}: {type(e).__name__}", file=sys.stderr)
            continue
        blocks = []
        for u in ups:
            cs = fetch_comments(u["id"])
            if cs:
                blocks.append(f"VIDEO: {u['title']}\n" + "\n".join(f"- {c}" for c in cs))
        if not blocks:
            continue
        prompt = ("Below are viewer comments on short story videos. Return JSON only: "
                  "{\"ideas\": [up to 5 original story ideas inspired by what viewers ask for or "
                  "react to, one sentence each], \"questions\": [up to 5 real viewer questions "
                  "worth answering, quoted briefly with the video title], \"mood\": one sentence}. "
                  "Ignore spam and insults.\n\n" + "\n\n".join(blocks)[:12000])
        res, _ = common.llm_json(prompt, temperature=0.4)
        if not isinstance(res, dict):
            continue
        new = [t for t in res.get("ideas", []) if isinstance(t, str) and t.lower() not in known]
        for t in new:
            ideas.append({"channel": name, "text": t, "source": "comments",
                          "date": common.today(), "used": False})
        common.tg_text(f"Comment digest: {name}\nMood: {res.get('mood', '')}\n\nIdeas added to the "
                       "queue:\n" + "\n".join(f"- {t}" for t in new) +
                       "\n\nQuestions to answer yourself:\n" +
                       "\n".join(f"- {q}" for q in res.get("questions", [])))
    common.save("data/ideas.json", ideas)


if __name__ == "__main__":
    main()
