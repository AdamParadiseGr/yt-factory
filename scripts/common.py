"""Shared helpers for all yt-factory scripts (stdlib only)."""
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) yt-factory"}


def path(*parts):
    return os.path.join(ROOT, *parts)


def load(rel, default):
    try:
        with open(path(rel), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(rel, obj):
    full = path(rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def channel(name):
    with open(path("channels", f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def channel_names():
    d = path("channels")
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def today():
    return now().date().isoformat()


def env_list(name):
    return [k.strip() for k in os.environ.get(name, "").split(",") if k.strip()]


def http(url, body=None, headers=None, timeout=60, method=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    h = {**UA, **({"content-type": "application/json"} if data else {}), **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h,
                                 method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = r.read()
    return payload.decode("utf-8", "replace") if raw else json.loads(payload or b"null")


# ---------- LLM: Gemini free tier (key rotation) -> Groq free tier ----------
GEMINI_MODELS = [m for m in os.environ.get(
    "GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-3.6-flash").split(",") if m]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")


def _via_n8n(prompt, temperature):
    """Key rotation with usage counters lives in the n8n 'LLM rotator' workflow."""
    url = os.environ.get("N8N_LLM_URL")
    if not url:
        return None, None
    try:
        d = http(url, {"prompt": prompt, "temperature": temperature},
                 {"x-token": os.environ.get("N8N_LLM_TOKEN", "")}, timeout=150)
        if isinstance(d, dict) and d.get("text"):
            return d["text"], d.get("model", "n8n")
    except Exception as e:  # noqa: BLE001
        print(f"n8n rotator unavailable ({type(e).__name__}), using direct keys", file=sys.stderr)
    return None, None


def llm(prompt, temperature=1.0):
    """Return (text, model_label) or (None, None). Always asks for a JSON object.

    Order: n8n rotator (if configured) -> Gemini keys -> Groq keys -> OpenRouter keys."""
    text, model = _via_n8n(prompt, temperature)
    if text:
        return text, model
    for key in env_list("GEMINI_API_KEYS"):
        for model in GEMINI_MODELS:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={key}")
            body = {"contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json",
                                         "temperature": temperature}}
            try:
                data = http(url, body, timeout=90)
                return data["candidates"][0]["content"]["parts"][0]["text"], model
            except urllib.error.HTTPError as e:
                print(f"gemini {model}: HTTP {e.code}", file=sys.stderr)
                if e.code in (429, 403):
                    break  # next key
            except Exception as e:  # noqa: BLE001
                print(f"gemini {model}: {type(e).__name__}", file=sys.stderr)
    for key in env_list("GROQ_API_KEYS"):
        body = {"model": GROQ_MODEL, "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}]}
        try:
            data = http("https://api.groq.com/openai/v1/chat/completions", body,
                        {"authorization": f"Bearer {key}"}, timeout=90)
            return data["choices"][0]["message"]["content"], GROQ_MODEL
        except urllib.error.HTTPError as e:
            print(f"groq: HTTP {e.code}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"groq: {type(e).__name__}", file=sys.stderr)
    for key in env_list("OPENROUTER_API_KEYS"):
        body = {"model": OPENROUTER_MODEL, "temperature": temperature,
                "messages": [{"role": "user", "content": prompt + "\nReturn only a JSON object."}]}
        try:
            data = http("https://openrouter.ai/api/v1/chat/completions", body,
                        {"authorization": f"Bearer {key}"}, timeout=120)
            return data["choices"][0]["message"]["content"], OPENROUTER_MODEL
        except urllib.error.HTTPError as e:
            print(f"openrouter: HTTP {e.code}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"openrouter: {type(e).__name__}", file=sys.stderr)
    return None, None


def llm_json(prompt, temperature=1.0):
    """Return (parsed_json, model_label); (None, None) on any failure."""
    raw, model = llm(prompt, temperature)
    if not raw:
        return None, None
    raw = raw.strip()
    if raw.startswith("```"):  # some free models wrap JSON in a code fence
        raw = raw.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(raw), model
    except ValueError:
        return None, None


# ---------- Telegram ----------
def _tg_ready():
    return os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")


def tg_text(text, buttons=None):
    """buttons: list of rows, each row a list of (label, callback_data)."""
    if not _tg_ready():
        print("[telegram not configured]\n" + text)
        return False
    body = {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text[:4000]}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
    try:
        http(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage", body)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"telegram text failed: {type(e).__name__}", file=sys.stderr)
        return False


def tg_file(file_path, caption, kind="video", buttons=None):
    if not _tg_ready():
        print(f"[telegram not configured] would send {file_path}")
        return False
    field, method = ("video", "sendVideo") if kind == "video" else ("document", "sendDocument")
    fields = [("chat_id", os.environ["TELEGRAM_CHAT_ID"]), ("caption", caption[:1000])]
    if kind == "video":
        fields.append(("supports_streaming", "true"))
    if buttons:
        fields.append(("reply_markup", json.dumps({"inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in row] for row in buttons]})))
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode()
             for n, v in fields]
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
                  f'filename="{os.path.basename(file_path)}"\r\n'
                  "Content-Type: application/octet-stream\r\n\r\n").encode())
    with open(file_path, "rb") as f:
        parts.append(f.read())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{method}",
        data=b"".join(parts),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=300).read()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"telegram file failed: {type(e).__name__}", file=sys.stderr)
        return False
