#!/usr/bin/env python3
"""Add translated titles/descriptions to tasks_meta.json (one LLM call per video).

YouTube lets you add a title/description per language in Studio (Details -> Translations);
this only prepares the text, deliver.py sends it next to the video.
"""
import json
import sys

import common

LANG_NAMES = {"es": "Spanish", "pt": "Portuguese (Brazil)", "hi": "Hindi", "de": "German",
              "fr": "French", "ar": "Arabic", "id": "Indonesian", "tr": "Turkish"}


def main():
    meta = json.load(open("tasks_meta.json", encoding="utf-8"))
    for m in meta:
        langs = [l for l in common.channel(m["channel"]).get("localize", []) if l in LANG_NAMES]
        if not langs:
            continue
        names = ", ".join(f"{l} ({LANG_NAMES[l]})" for l in langs)
        prompt = ("Translate this YouTube title and description into each language. Keep the "
                  "hashtags unchanged. Return JSON only: an object whose keys are the language "
                  "codes and whose values are {\"title\",\"description\"}. Title max 70 chars.\n"
                  f"Languages: {names}\nTITLE: {m['title']}\nDESCRIPTION: {m['description']}")
        res, _ = common.llm_json(prompt, temperature=0.3)
        if isinstance(res, dict):
            m["localizations"] = {l: res[l] for l in langs
                                  if isinstance(res.get(l), dict) and res[l].get("title")}
        else:
            print(f"localization skipped for '{m['title']}'", file=sys.stderr)
    json.dump(meta, open("tasks_meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
