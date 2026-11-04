"""Thin Gemini wrapper: JSON output against a Pydantic schema, rate limit, retries and
an on-disk cache so re-runs cost nothing.

Needs GEMINI_API_KEY. Model from GEMINI_MODEL (default below).
"""
import hashlib
import json
import os
import time
from pathlib import Path

DEFAULT_MODEL = "gemini-3.5-flash"  # 3.7/3.8-flash returned 503 "high demand" on 4 Nov 2026
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_env():
    """Read KEY=value lines from the project .env (never commit that file)."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


class GeminiLLM:
    def __init__(self, model=None, rpm=10, cache_dir=None):
        from google import genai
        load_env()
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise SystemExit("Set GEMINI_API_KEY (get one at https://aistudio.google.com/apikey)")
        self.client = genai.Client(api_key=key)
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self.min_gap = 60.0 / rpm
        self.last = 0.0
        self.cache_dir = Path(cache_dir) if cache_dir else None

    def generate_json(self, system, prompt, schema):
        """Return (text, usage dict). usage has in/out tokens and whether it was cached."""
        key = hashlib.sha256(f"{self.model}\n{system}\n{prompt}".encode()).hexdigest()
        cached = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if cached and cached.exists():
            rec = json.loads(cached.read_text(encoding="utf-8"))
            return rec["text"], {**rec["usage"], "cached": True}

        import httpx
        from google.genai import errors, types
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=0,
            response_mime_type="application/json", response_schema=schema,
            thinking_config=(None if self.model.startswith("gemma")
                             else types.ThinkingConfig(thinking_level="low")))
        for attempt in range(6):
            wait = self.min_gap - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt, config=config)
                break
            except errors.APIError as e:
                if e.code in (429, 500, 503) and attempt < 5:
                    time.sleep(min(120, 10 * 2 ** attempt))
                    continue
                raise
            except (httpx.TransportError, OSError):  # network dropped: wait and retry
                if attempt < 5:
                    time.sleep(min(120, 15 * 2 ** attempt))
                    continue
                raise
        u = resp.usage_metadata
        usage = {"in_tokens": u.prompt_token_count or 0,
                 "out_tokens": u.candidates_token_count or 0,
                 "seconds": round(time.time() - self.last, 2)}
        text = resp.text or '{"claims": []}'
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps({"text": text, "usage": usage}), encoding="utf-8")
        return text, {**usage, "cached": False}
