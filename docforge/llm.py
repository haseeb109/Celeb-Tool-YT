"""Deploy.com (OpenAI-compatible) client with JSON parsing + retries."""
import json
import os
import re
import time

from openai import OpenAI


class LLM:
    def __init__(self, cfg, log=print):
        c = cfg["llm"]
        key = os.environ.get("DEPLOY_API_KEY")
        if not key:
            raise RuntimeError("DEPLOY_API_KEY .env mein nahi mili")
        self.client = OpenAI(base_url=c["base_url"], api_key=key, timeout=c["timeout_s"])
        self.c = c
        self.log = log
        self.usage = {"prompt": 0, "completion": 0}

    def _call(self, model, effort, system, user, temperature):
        r = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
            extra_body={
                "reasoning_effort": effort,
                "max_completion_tokens": self.c["max_completion_tokens"],
            },
        )
        if r.usage:
            self.usage["prompt"] += r.usage.prompt_tokens or 0
            self.usage["completion"] += r.usage.completion_tokens or 0
        return r.choices[0].message.content or ""

    def json(self, role, system, user, temperature=None):
        model = self.c["writer_model"] if role == "writer" else self.c["auditor_model"]
        effort = self.c["writer_reasoning"] if role == "writer" else self.c["auditor_reasoning"]
        temp = self.c["temperature"] if temperature is None else temperature
        last = None
        for attempt in range(self.c["retries"]):
            try:
                raw = self._call(model, effort, system, user, temp)
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
    if start < 0 or end < 0:
        raise ValueError("no JSON object in response")
    return json.loads(raw[start:end + 1])
