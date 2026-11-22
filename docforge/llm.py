"""Deploy.com (OpenAI-compatible) client with JSON parsing + retries."""
import json
import os
import re
import time
from pathlib import Path

from openai import OpenAI


class LLM:
    def __init__(self, cfg, log=print):
        c = cfg["llm"]
        key = (os.environ.get("DEPLOY_API_KEY") or "").strip().removeprefix("Bearer ").strip()
        if not key:
            raise RuntimeError("DEPLOY_API_KEY .env mein nahi mili")
        self.client = OpenAI(base_url=c["base_url"], api_key=key, timeout=c["timeout_s"])
        self.c = c
        self.log = log
        self.usage = {"prompt": 0, "completion": 0}
        import threading
        self._lock = threading.Lock()

    def _call(self, model, effort, system, user, temperature, images=()):
        content = user
        if images:  # multimodal (Hive DeepSeek v4.1 accepts image_url parts)
            import base64
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(Path(p).read_bytes()).decode()}}
                for p in images]
        if "thehive.ai" not in self.c["base_url"]:  # Deploy: plain JSON (proven path)
            r = self.client.chat.completions.create(
                model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
                temperature=temperature,
                extra_body={"reasoning_effort": effort, "max_completion_tokens": self.c["max_completion_tokens"]})
            if r.usage:
                with self._lock:
                    self.usage["prompt"] += r.usage.prompt_tokens or 0
                    self.usage["completion"] += r.usage.completion_tokens or 0
                    det = getattr(r.usage, "prompt_tokens_details", None)
                    self.usage["cached"] = self.usage.get("cached", 0) + ((getattr(det, "cached_tokens", 0) or 0) if det else 0)
            return r.choices[0].message.content or ""
        # Hive host: SSE stream
        stream = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            temperature=temperature, stream=True, stream_options={"include_usage": True},
            extra_body={"reasoning_effort": effort, "max_completion_tokens": self.c["max_completion_tokens"]},
        )
        parts, usage = [], None
        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            for ch in chunk.choices or []:
                d = getattr(ch.delta, "content", None)
                if d:
                    parts.append(d)
        if usage:
            with self._lock:
                self.usage["prompt"] += usage.prompt_tokens or 0
                self.usage["completion"] += usage.completion_tokens or 0
                det = getattr(usage, "prompt_tokens_details", None)
                self.usage["cached"] = self.usage.get("cached", 0) + ((getattr(det, "cached_tokens", 0) or 0) if det else 0)
        return "".join(parts)

    def json(self, role, system, user, temperature=None, images=(), effort=None):
        model = self.c["writer_model"] if role == "writer" else self.c["auditor_model"]
        effort = effort or (self.c["writer_reasoning"] if role == "writer" else self.c["auditor_reasoning"])
        temp = self.c["temperature"] if temperature is None else temperature
        last = None
        for attempt in range(self.c["retries"]):
            try:
                raw = self._call(model, effort, system, user, temp, images)
                return parse_json(raw)
            except Exception as e:  # network, 429, bad JSON
                last = e
                wait = 5 * (2 ** attempt)
                self.log(f"   LLM retry {attempt + 1} ({type(e).__name__}: {str(e)[:120]}) — {wait}s")
                time.sleep(wait)
                user = user + "\n\nREMINDER: respond with ONE valid JSON object only. No markdown fences."
        raise RuntimeError(f"LLM fail after retries: {last}")


def parse_json(raw):
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0:
        raise ValueError("no JSON object in response")
    body = raw[start:end + 1] if end > start else raw[start:]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # model ka JSON thoda toota (missing comma etc.) → repair karo, poori call dobara nahi
        from json_repair import loads as repair
        fixed = repair(body)
        if not isinstance(fixed, dict) or not fixed:
            raise
        return fixed


DEPLOY_BASES = ["https://api-cdn.thehive.ai/api/v3", "https://api-va1.thehive.ai/api/v3",
                "https://api.deploy.com/api/v1", "https://api-sf1.deploy.com/api/v1", "https://api-va1.deploy.com/api/v1"]


def diagnose_deploy(cfg):
    """Raw HTTP test of every Deploy base URL × both models. Returns (report_text, working_base or None)."""
    import requests
    key = (os.environ.get("DEPLOY_API_KEY") or "").strip().removeprefix("Bearer ").strip()
    if not key:
        return "✖ DEPLOY_API_KEY save nahi hai", None
    lines, working = [f"key: {key[:4]}…{key[-4:]} ({len(key)} chars)"], None
    bases = [cfg["llm"]["base_url"]] + [b for b in DEPLOY_BASES if b != cfg["llm"]["base_url"]]
    for base in bases:
        for model in (cfg["llm"]["writer_model"], cfg["llm"]["auditor_model"]):
            try:
                r = requests.post(f"{base}/chat/completions", timeout=60,
                                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                  json={"model": model, "messages": [{"role": "user", "content": "say ok"}], "stream": True,
                                        "max_completion_tokens": 20, "reasoning_effort": "low"}, stream=True)
                ok = r.status_code == 200
                r.close()
                hint = {401: "key galat — Hive portal ki V3 Service API **Secret Key** chahiye (V2 project key nahi)", 405: "account balance khatam (credits daalo)",
                        400: "request format / model naam", 429: "rate limit", 404: "URL ya model naam galat"}.get(r.status_code, "")
                lines.append(f"{'✔' if ok else '✖'} {r.status_code} {base} · {model}" + (f" — {hint}" if hint and not ok else "")
                             + ("" if ok else f"\n     {r.text[:160]}"))
                if ok and not working:
                    working = base
            except Exception as e:
                lines.append(f"✖ {base} · {model} — {type(e).__name__}: {str(e)[:120]}")
        if working:
            break
    return "\n".join(lines), working
