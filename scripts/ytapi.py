"""Minimal YouTube Data / Analytics API helpers (stdlib only).

Public data uses YT_API_KEY. Analytics (watch hours, Shorts views) needs OAuth: secrets
YT_CLIENT_ID, YT_CLIENT_SECRET and YT_TOKENS (JSON {"<channel name>": "<refresh token>"}).
Set the OAuth consent screen to "In production" (unverified is fine for your own account),
otherwise refresh tokens of a "Testing" app expire after 7 days.
"""
import json
import os
import urllib.parse
import urllib.request

import common

API = "https://www.googleapis.com/youtube/v3"


def get(path, **params):
    key = os.environ.get("YT_API_KEY", "")
    if not key:
        raise RuntimeError("YT_API_KEY is not set")
    q = urllib.parse.urlencode({**params, "key": key})
    return common.http(f"{API}/{path}?{q}")


def channel_info(channel_id):
    d = get("channels", part="statistics,contentDetails", id=channel_id)
    it = d["items"][0]
    st = it["statistics"]
    return {"subs": int(st.get("subscriberCount", 0)), "views": int(st.get("viewCount", 0)),
            "videos": int(st.get("videoCount", 0)),
            "uploads": it["contentDetails"]["relatedPlaylists"]["uploads"]}


def uploads(playlist_id, limit=50):
    d = get("playlistItems", part="contentDetails,snippet", playlistId=playlist_id,
            maxResults=min(limit, 50))
    return [{"id": i["contentDetails"]["videoId"], "title": i["snippet"]["title"],
             "published": i["contentDetails"].get("videoPublishedAt") or i["snippet"]["publishedAt"]}
            for i in d.get("items", [])]


def video_stats(ids):
    out = {}
    for n in range(0, len(ids), 50):
        d = get("videos", part="statistics,contentDetails,snippet", id=",".join(ids[n:n + 50]))
        for v in d.get("items", []):
            st = v["statistics"]
            out[v["id"]] = {"views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                            "comments": int(st.get("commentCount", 0)),
                            "duration": v["contentDetails"]["duration"],
                            "title": v["snippet"]["title"],
                            "published": v["snippet"]["publishedAt"]}
    return out


def access_token(channel_name):
    cid, secret = os.environ.get("YT_CLIENT_ID"), os.environ.get("YT_CLIENT_SECRET")
    try:
        refresh = json.loads(os.environ.get("YT_TOKENS", "{}")).get(channel_name)
    except ValueError:
        refresh = None
    if not (cid and secret and refresh):
        return None
    body = urllib.parse.urlencode({"client_id": cid, "client_secret": secret,
                                   "refresh_token": refresh, "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["access_token"]


def analytics(token, **params):
    q = urllib.parse.urlencode({"ids": "channel==MINE", **params})
    return common.http(f"https://youtubeanalytics.googleapis.com/v2/reports?{q}",
                       headers={"authorization": f"Bearer {token}"})


def rows(report):
    cols = [c["name"] for c in report.get("columnHeaders", [])]
    return [dict(zip(cols, r)) for r in report.get("rows", [])]


def parse_iso_duration(s):
    import re
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    h, mi, se = (int(x or 0) for x in m.groups()) if m else (0, 0, 0)
    return h * 3600 + mi * 60 + se
