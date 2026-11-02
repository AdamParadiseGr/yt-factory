#!/usr/bin/env python3
"""YouTube Partner Program threshold tracker with a simple forecast.

Daily: records subscribers, public uploads in the last 90 days and (with OAuth) watch hours
of the last 12 months and Shorts views of the last 90 days into data/ypp_log.json.
On Mondays (or with --report) sends progress and a linear forecast to Telegram.

Thresholds below are the ones listed on YouTube's YPP page when this was written
(early access: 500 subs + 3 uploads in 90 days + 3,000 hours or 3M Shorts views;
full: 1,000 subs + 4,000 hours or 10M Shorts views). Check the page, they change.
"""
import datetime
import sys

import common
import ytapi

TIERS = {
    "early access": {"subs": 500, "hours": 3000, "shorts90": 3_000_000, "uploads90": 3},
    "full": {"subs": 1000, "hours": 4000, "shorts90": 10_000_000},
}


def forecast_date(points, target, window=28):
    """points: [(date, value)] ascending. Linear estimate of the date value reaches target."""
    if not points:
        return None
    last_d, last_v = points[-1]
    if last_v >= target:
        return last_d
    recent = [p for p in points if (last_d - p[0]).days <= window]
    days = (last_d - recent[0][0]).days
    if days < 7:
        return None
    slope = (last_v - recent[0][1]) / days
    if slope <= 0:
        return None
    return last_d + datetime.timedelta(days=int((target - last_v) / slope) + 1)


def snapshot(name, ch):
    cid = ch.get("youtube_channel_id")
    if not cid:
        return None
    info = ytapi.channel_info(cid)
    cutoff = common.now() - datetime.timedelta(days=90)
    ups = ytapi.uploads(info["uploads"])
    uploads90 = sum(1 for u in ups if datetime.datetime.fromisoformat(
        u["published"].replace("Z", "+00:00")) >= cutoff)
    snap = {"date": common.today(), "channel": name, "subs": info["subs"],
            "uploads90": uploads90, "hours": None, "shorts90": None}
    token = ytapi.access_token(name)
    if token:
        end = common.now().date()
        r = ytapi.rows(ytapi.analytics(
            token, startDate=str(end - datetime.timedelta(days=365)), endDate=str(end),
            metrics="estimatedMinutesWatched"))
        if r:
            snap["hours"] = round(r[0]["estimatedMinutesWatched"] / 60, 1)
        r = ytapi.rows(ytapi.analytics(
            token, startDate=str(end - datetime.timedelta(days=90)), endDate=str(end),
            metrics="views", dimensions="creatorContentType"))
        snap["shorts90"] = sum(x["views"] for x in r if x.get("creatorContentType") == "SHORTS")
    return snap


def fmt_eta(d):
    return d.isoformat() if d else "not enough data"


def report(name, log):
    rows = [r for r in log if r["channel"] == name]
    last = rows[-1]
    lines = [f"YPP progress: {name} ({last['date']})"]
    for tier, th in TIERS.items():
        lines.append(f"\n{tier}:")
        etas = {}
        for key, target in th.items():
            val = last.get(key)
            if val is None:
                lines.append(f"- {key}: no data (OAuth not configured)")
                continue
            pts = [(datetime.date.fromisoformat(r["date"]), r[key]) for r in rows if r.get(key) is not None]
            etas[key] = forecast_date(pts, target) if key != "uploads90" else None
            pct = min(100, round(100 * val / target))
            extra = "" if key == "uploads90" else f", forecast {fmt_eta(etas[key])}"
            lines.append(f"- {key}: {val:g} / {target:,} ({pct}%){extra}")
    lines.append("\nNote: this only shows channel thresholds. The program must also be "
                 "available in your country; that is checked separately every day.")
    return "\n".join(lines)


def main():
    log = common.load("data/ypp_log.json", [])
    sent = False
    for name in common.channel_names():
        try:
            snap = snapshot(name, common.channel(name))
        except Exception as e:  # noqa: BLE001
            print(f"ypp {name}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if not snap:
            print(f"ypp {name}: youtube_channel_id not set in channels/{name}.json", file=sys.stderr)
            continue
        log = [r for r in log if not (r["channel"] == name and r["date"] == snap["date"])] + [snap]
        common.save("data/ypp_log.json", log)
        if "--report" in sys.argv or common.now().weekday() == 0:
            common.tg_text(report(name, log))
            sent = True
    if not sent:
        print("snapshot saved")


if __name__ == "__main__":
    main()
