#!/usr/bin/env python3
"""Weekly: pull stats of published videos, suggest a publish slot, rate genres.

Writes data/videos.json (per-video stats) and data/perf.json (genre factors used by
diversity.py). The slot advice needs at least 3 videos per 6-hour UTC slot; until then it
shows the prior (US evening). Views are normalised by age (views / sqrt(age in days)).
"""
import datetime
import statistics
import sys

import common
import ytapi

PRIOR = ("Prior (not enough own data yet): US evening, about 23:00-03:00 UTC "
         "(7-11 pm New York in summer, shift one hour in winter).")


def norm_views(v):
    return v["views"] / max(1.0, v["age_days"]) ** 0.5


def slot_report(videos, min_per_slot=3):
    slots = {}
    for v in videos:
        if v["age_days"] < 3:
            continue
        slots.setdefault(v["hour_utc"] // 6, []).append(norm_views(v))
    good = {s: statistics.median(x) for s, x in slots.items() if len(x) >= min_per_slot}
    if len(good) < 2:
        return PRIOR
    best = max(good, key=good.get)
    table = "; ".join(f"{s * 6:02d}-{s * 6 + 6:02d} UTC: {good[s]:.0f}" for s in sorted(good))
    return f"Best slot by your data: {best * 6:02d}:00-{best * 6 + 6:02d}:00 UTC. ({table})"


def genre_factors(videos, history, min_videos=3):
    by_title = {h["title"].strip().lower(): h for h in history}
    by_genre = {}
    for v in videos:
        h = by_title.get(v["title"].strip().lower())
        if h and v["age_days"] >= 3:
            by_genre.setdefault(h["genre"], []).append(norm_views(v))
    allv = [x for xs in by_genre.values() for x in xs]
    if len(allv) < 2 * min_videos:
        return {}
    overall = statistics.median(allv) or 1
    return {g: round(statistics.median(xs) / overall, 3)
            for g, xs in by_genre.items() if len(xs) >= min_videos}


def collect(cid):
    info = ytapi.channel_info(cid)
    ups = ytapi.uploads(info["uploads"])
    stats = ytapi.video_stats([u["id"] for u in ups])
    out, now = [], common.now()
    for u in ups:
        s = stats.get(u["id"])
        if not s:
            continue
        pub = datetime.datetime.fromisoformat(u["published"].replace("Z", "+00:00"))
        out.append({"id": u["id"], "title": u["title"], "views": s["views"],
                    "likes": s["likes"], "comments": s["comments"],
                    "seconds": ytapi.parse_iso_duration(s["duration"]),
                    "published": u["published"], "hour_utc": pub.hour,
                    "age_days": max(0.0, (now - pub).total_seconds() / 86400)})
    return out


def main():
    history = common.load("data/history.json", [])
    videos_all, perf, lines = {}, {}, []
    for name in common.channel_names():
        cid = common.channel(name).get("youtube_channel_id")
        if not cid:
            print(f"besttime {name}: youtube_channel_id not set", file=sys.stderr)
            continue
        try:
            vids = collect(cid)
        except Exception as e:  # noqa: BLE001
            print(f"besttime {name}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        videos_all[name] = vids
        perf[name] = {"genre_factor": genre_factors(
            vids, [h for h in history if h.get("channel") == name])}
        lines.append(f"{name}: {len(vids)} videos analysed\n{slot_report(vids)}")
        gf = perf[name]["genre_factor"]
        if gf:
            lines.append("Genre factor (1.0 = median): " +
                         "; ".join(f"{g[:30]} {f}" for g, f in sorted(gf.items(), key=lambda x: -x[1])))
    if videos_all:
        common.save("data/videos.json", videos_all)
        common.save("data/perf.json", perf)
        common.tg_text("Publishing time and genre performance\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
