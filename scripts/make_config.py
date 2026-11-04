#!/usr/bin/env python3
"""Write MoneyPrinterTurbo/config.toml from environment variables (secrets stay in GitHub Secrets)."""
import json
import os
import sys

out = sys.argv[1] if len(sys.argv) > 1 else "MoneyPrinterTurbo/config.toml"
worker_url = os.environ.get("IMAGE_WORKER_URL", "").rstrip("/")
if not worker_url:
    sys.exit("IMAGE_WORKER_URL is not set")


def q(v):
    return json.dumps(v)  # valid TOML basic string


kokoro = os.environ.get("KOKORO_OK") == "1"
gemini_keys = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]
lines = [
    'log_level = "INFO"',
    'listen_host = "127.0.0.1"',
    "",
    "[app]",
    'llm_provider = "gemini"',
    f"gemini_api_key = {q(gemini_keys[0] if gemini_keys else '')}",
    # MPT's default Gemini model is a Pro preview (paid). Script generation is done by
    # scripts/plan.py, but keep MPT on a free-tier model in case it calls the LLM.
    f"gemini_model_name = {q(os.environ.get('GEMINI_MODELS', 'gemini-3.5-flash-lite').split(',')[0])}",
    'video_source = "openai_image"',
    f"openai_image_base_url = {q(worker_url + '/v1')}",
    f"openai_image_api_keys = [{q(os.environ.get('IMAGE_WORKER_TOKEN', ''))}]",
    'openai_image_model = "flux-1-schnell"',
    # Kokoro has no word timings, so subtitles come from Whisper; Edge keeps its own timings.
    f'subtitle_provider = "{"whisper" if kokoro else "edge"}"',
    "",
]
if kokoro:
    lines += ["[kokoro]", 'base_url = "http://127.0.0.1:8880/v1"', 'api_key = ""',
              'model_id = "kokoro"', "voices = []", "",
              "[whisper]", 'model_size = "small"', 'device = "cpu"', 'compute_type = "int8"', ""]
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"wrote {out}")
