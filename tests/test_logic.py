import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import besttime  # noqa: E402
import compile as comp  # noqa: E402
import country_watch  # noqa: E402
import diversity  # noqa: E402
import plan  # noqa: E402
import qc  # noqa: E402
import ypp  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

D = datetime.date


def img(seed):
    im = Image.new("RGB", (64, 64), (seed * 40 % 255, 80, 160))
    d = ImageDraw.Draw(im)
    for k in range(seed + 2):
        d.rectangle([k * 5, k * 3, k * 5 + 20, k * 3 + 30 + seed], fill=(255 - seed * 30, k * 20, seed * 50))
    return im


class QC(unittest.TestCase):
    def test_blank_and_duplicates(self):
        self.assertTrue(qc.is_blank(Image.new("RGB", (64, 64), (10, 10, 10))))
        self.assertFalse(qc.is_blank(img(2)))
        a, b = qc.dhash(img(1)), qc.dhash(img(1))
        self.assertEqual(qc.hamming(a, b), 0)
        self.assertEqual(qc.near_duplicate_pairs([a, b, qc.dhash(img(4))]), 1)

    def test_cues(self):
        srt = "1\n00:00:00,000 --> 00:00:02,000\nHi\n\n2\n00:00:02,000 --> 00:00:04,000\nYo\n"
        self.assertEqual(qc.count_cues(srt), 2)


class Diversity(unittest.TestCase):
    def test_weights_favor_rare(self):
        w = diversity.compute_weights(["a", "b", "c"], ["a", "a", "a", "b"])
        self.assertGreater(w["c"], w["b"])
        self.assertGreater(w["b"], w["a"])
        self.assertAlmostEqual(sum(w.values()) / 3, 1.0, places=1)

    def test_perf_factor_clamped(self):
        w = diversity.compute_weights(["a", "b"], [], {"a": 5.0, "b": 0.1})
        self.assertAlmostEqual(w["a"] / w["b"], 1.3 / 0.7, places=1)

    def test_repeated_openings(self):
        rows = [{"first_line": "The old clock stopped."}, {"first_line": "The old clock was silent."},
                {"first_line": "Nobody came."}]
        self.assertEqual(diversity.repeated_openings(rows), [])
        rows[1]["first_line"] = "The old clock stopped again."
        self.assertEqual(diversity.repeated_openings(rows), [("the old clock stopped", 2)])

    def test_recent_window(self):
        h = [{"channel": "s", "date": "2026-10-30"}, {"channel": "s", "date": "2026-08-01"},
             {"channel": "x", "date": "2026-10-30"}]
        self.assertEqual(len(diversity.recent(h, "s", 30, D(2026, 11, 1))), 1)


class YPP(unittest.TestCase):
    def test_forecast(self):
        pts = [(D(2026, 10, 1) + datetime.timedelta(days=i), 100 + 10 * i) for i in range(15)]
        self.assertEqual(ypp.forecast_date(pts, 500), D(2026, 10, 15) + datetime.timedelta(days=int(260 / 10) + 1))
        self.assertIsNone(ypp.forecast_date(pts[:3], 500))
        self.assertIsNone(ypp.forecast_date([(p[0], 100) for p in pts], 500))
        self.assertEqual(ypp.forecast_date(pts, 120), pts[-1][0])


class Country(unittest.TestCase):
    page = ("<p>You can sign up for the YouTube Partner Program in the following areas:</p><ul>"
            "<li>Brazil</li><li>Germany</li><li>United States</li>{extra}</ul>")

    def test_found(self):
        f, ok = country_watch.analyze(self.page.format(extra="<li>Uzbekistan</li>"))
        self.assertTrue(f and ok)

    def test_not_found_and_language_menu_ignored(self):
        f, ok = country_watch.analyze("o‘zbek " + self.page.format(extra=""))
        self.assertTrue(ok and not f)

    def test_unparseable(self):
        self.assertEqual(country_watch.analyze("<html>nothing</html>"), (False, False))


class Compile(unittest.TestCase):
    def test_chapters(self):
        items = [{"title": "A", "duration": 45}, {"title": "B", "duration": 50}, {"title": "C", "duration": 3600}]
        self.assertEqual(comp.chapters(items), ["0:00 A", "0:45 B", "1:35 C"])
        self.assertEqual(comp.fmt_ts(3725), "1:02:05")

    def test_select(self):
        items = [{"task_id": str(i), "duration": 100, "date": f"2026-10-{10 + i}"} for i in range(8)]
        st = {str(i): {"status": "approved" if i < 7 else "rejected"} for i in range(8)}
        sel = comp.select(items, st, False)
        self.assertEqual(len(sel), 6)  # 600 s cap, rejected excluded
        st["7"]["status"] = "pending"
        self.assertEqual(len(comp.select(items, st, True)), 6)


class Best(unittest.TestCase):
    def vids(self, hour, views, n=3):
        return [{"hour_utc": hour, "views": views, "age_days": 9.0, "title": f"t{hour}{i}"} for i in range(n)]

    def test_prior_when_thin(self):
        self.assertEqual(besttime.slot_report(self.vids(1, 100)), besttime.PRIOR)

    def test_best_slot(self):
        r = besttime.slot_report(self.vids(1, 900) + self.vids(13, 100))
        self.assertIn("Best slot by your data: 00:00-06:00 UTC", r)

    def test_genre_factors(self):
        hist = [{"title": f"t{i}", "genre": "mystery" if i < 3 else "fable"} for i in range(6)]
        vids = [{"title": f"t{i}", "views": 900 if i < 3 else 100, "age_days": 9.0} for i in range(6)]
        f = besttime.genre_factors(vids, hist)
        self.assertGreater(f["mystery"], f["fable"])


class Plan(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(plan.first_line("Hello there. Next one."), "Hello there.")
        self.assertEqual(plan.slug("The Lost Key!"), "the-lost-key")
        picks = [plan.weighted(["a", "b"], {"a": 0, "b": 1}) for _ in range(400)]
        self.assertGreater(picks.count("b"), 340)   # weight 0 is floored to 0.05, so "a" is rare, not impossible

    def test_bible_update(self):
        bible = {"characters": {}, "series": []}
        item = {"series_title": "Moon Fox", "series_logline": "A fox.",
                "characters": [{"name": "Fen", "look": "small red fox, blue scarf"}]}
        sid, ep = plan.update_bible(bible, {"mode": "new", "limit": 5}, item, "T1", "S1")
        self.assertEqual((sid, ep), ("moon-fox", 1))
        sid, ep = plan.update_bible(bible, {"mode": "continue", "series": bible["series"][0], "limit": 5},
                                    {"characters": []}, "T2", "S2")
        self.assertEqual(ep, 2)
        self.assertIn("Fen", plan.series_block({"mode": "continue", "series": bible["series"][0], "limit": 5}, bible))


class Channels(unittest.TestCase):
    def test_all_channel_configs_have_required_keys(self):
        import common
        need = {"language", "voice_name", "voice_rate", "font_name", "font_size", "aspect",
                "image_style", "target_seconds", "genres", "structures"}
        for name in common.channel_names():
            cfg = common.channel(name)
            self.assertFalse(need - set(cfg), name)
            self.assertGreaterEqual(len(cfg["genres"]), 5)

    def test_kids_prompt_uses_kids_rules(self):
        import common
        kids = common.channel("kids")
        p = plan.build_prompt(kids, kids["genres"][0], kids["structures"][0], [], "", None, "")
        self.assertIn("children aged 3 to 7", p)
        self.assertIn("nothing scary", p)
        self.assertIn('"tags"', p)
        self.assertTrue(kids["made_for_kids"] and kids["comments"] is False)

    def test_stories_prompt_keeps_defaults(self):
        import common
        st = common.channel("stories")
        p = plan.build_prompt(st, st["genres"][0], st["structures"][0], [], "", None, "")
        self.assertIn("original short narrated stories", p)

    def test_llm_without_any_route_returns_none(self):
        import common
        for k in ("N8N_LLM_URL", "GEMINI_API_KEYS", "GROQ_API_KEYS", "OPENROUTER_API_KEYS"):
            os.environ.pop(k, None)
        os.environ["N8N_LLM_URL"] = "http://127.0.0.1:9/yt-llm"  # nothing listens: must fall through
        try:
            self.assertEqual(common.llm("x"), (None, None))
        finally:
            os.environ.pop("N8N_LLM_URL")

    def test_llm_json_strips_code_fence(self):
        import common
        orig = common.llm
        common.llm = lambda p, t=1.0: ("```json\n{\"a\": 1}\n```", "m")
        try:
            self.assertEqual(common.llm_json("x"), ({"a": 1}, "m"))
        finally:
            common.llm = orig


class N8nWorkflows(unittest.TestCase):
    def test_structure(self):
        import glob
        import json
        files = glob.glob(os.path.join(os.path.dirname(__file__), "..", "n8n", "workflows", "*.json"))
        self.assertEqual(len(files), 5)
        for f in files:
            wf = json.load(open(f, encoding="utf-8"))
            names = [n["name"] for n in wf["nodes"]]
            self.assertEqual(len(names), len(set(names)), f)
            for src, v in wf["connections"].items():
                self.assertIn(src, names, f)
                for outs in v["main"]:
                    for t in outs:
                        self.assertIn(t["node"], names, f)


if __name__ == "__main__":
    unittest.main()
