#!/usr/bin/env python3
"""Weekly diversity counter.

Counts genres, structures, repeated openings and series use over the last 30 days and
writes data/weights.json (used by plan.py): rarely used options get a higher weight. If
data/perf.json exists (written by besttime.py) a mild performance factor (0.7-1.3) is
applied once a genre has at least 3 videos. Sends a short report to Telegram.
"""
import collections
import datetime
import re

import common

WINDOW_DAYS = 30


def recent(history, channel, days=WINDOW_DAYS, today=None):
    today = today or common.now().date()
    out = []
    for h in history:
        if h.get("channel") != channel:
            continue
        try:
            age = (today - datetime.date.fromisoformat(h.get("date", ""))).days
        except ValueError:
            continue
        if age <= days:
            out.append(h)
    return out


def compute_weights(options, used, perf=None):
    """used: list of option names seen recently. Returns {option: weight}, mean ~ 1."""
    counts = collections.Counter(used)
    raw = {o: 1.0 / (1 + counts[o]) for o in options}
    if perf:
        for o in options:
            f = perf.get(o)
            if f is not None:
                raw[o] *= min(1.3, max(0.7, f))
    mean = sum(raw.values()) / len(raw)
    return {o: round(v / mean, 3) for o, v in raw.items()}


def opening_key(first_line):
    return " ".join(re.findall(r"[a-z']+", first_line.lower())[:4])


def repeated_openings(rows):
    c = collections.Counter(opening_key(r.get("first_line", "")) for r in rows if r.get("first_line"))
    return [(k, n) for k, n in c.items() if n > 1 and k]


def main():
    history = common.load("data/history.json", [])
    perf_all = common.load("data/perf.json", {})
    weights = common.load("data/weights.json", {})
    lines = []
    for name in sorted({h.get("channel") for h in history if h.get("channel")}):
        ch = common.channel(name)
        rows = recent(history, name)
        genre_perf = perf_all.get(name, {}).get("genre_factor", {})
        weights[name] = {
            "genres": compute_weights(ch["genres"], [r.get("genre") for r in rows], genre_perf),
            "structures": compute_weights(ch["structures"], [r.get("structure") for r in rows]),
        }
        gc = collections.Counter(r.get("genre") for r in rows)
        sc = collections.Counter(r.get("structure") for r in rows)
        series_rows = [r for r in rows if r.get("series")]
        lines.append(f"Channel {name}: {len(rows)} videos in {WINDOW_DAYS} days")
        lines.append("Genres: " + "; ".join(f"{g[:28]} x{gc[g]}" for g in ch["genres"]))
        lines.append("Structures: " + "; ".join(f"{s[:28]} x{sc[s]}" for s in ch["structures"]))
        rep = repeated_openings(rows)
        lines.append("Repeated openings: " + (", ".join(f"'{k}' x{n}" for k, n in rep) or "none"))
        lines.append(f"Series episodes: {len(series_rows)} of {len(rows)}")
        if rows and max(gc.values()) / len(rows) > 0.5 and len(rows) >= 6:
            lines.append("WARNING: one genre is over half of all videos.")
    common.save("data/weights.json", weights)
    if lines:
        common.tg_text("Diversity report\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
