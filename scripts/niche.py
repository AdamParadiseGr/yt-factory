#!/usr/bin/env python3
"""Weekly niche monitor: what short videos in your niche got most views this week.

Uses search.list (100 quota units per query of the 10,000 daily) with the channel's
"niche_queries". The LLM extracts format patterns (hook type, length, theme); plan.py passes
the top patterns to the story prompt as inspiration only. Titles are never copied.
"""
import datetime
import sys

import common
import ytapi


def main():
    store = common.load("data/niche.json", {})
    since = (common.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for name in common.channel_names():
        queries = common.channel(name).get("niche_queries", [])
        if not queries:
            continue
        ids = {}
        for q in queries:
            try:
                d = ytapi.get("search", part="snippet", q=q, type="video", order="viewCount",
                              videoDuration="short", publishedAfter=since, maxResults=10,
                              relevanceLanguage="en")
            except Exception as e:  # noqa: BLE001
                print(f"niche {name} '{q}': {type(e).__name__}", file=sys.stderr)
                continue
            for it in d.get("items", []):
                ids[it["id"]["videoId"]] = it["snippet"]["title"]
        if not ids:
            continue
        stats = ytapi.video_stats(list(ids))
        top = sorted(stats.items(), key=lambda kv: -kv[1]["views"])[:15]
        listing = "\n".join(f"{v['views']} views | {v['title']}" for _, v in top)
        res, _ = common.llm_json(
            "These are the most viewed short videos this week in a storytelling niche. Return "
            "JSON only: {\"patterns\": [up to 5 short descriptions of formats or hooks that "
            "seem to work (theme, hook style, tone), no titles copied]}.\n\n" + listing,
            temperature=0.3)
        patterns = res.get("patterns", []) if isinstance(res, dict) else []
        store[name] = {"date": common.today(), "patterns": patterns,
                       "hot_titles": [v["title"] for _, v in top[:5]]}
        common.tg_text(f"Niche watch: {name}\n" + "\n".join(f"- {p}" for p in patterns) +
                       "\n\nTop titles:\n" + "\n".join(f"- {t}" for t in store[name]["hot_titles"]))
    common.save("data/niche.json", store)


if __name__ == "__main__":
    main()
