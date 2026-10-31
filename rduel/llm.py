"""A thin wrapper around the Claude API with a disk cache and token accounting.

Every call is cached on disk, keyed by its exact prompt, so re-running indexing on the
same documents costs nothing the second time.
"""
import hashlib
import json
import re
import threading
import time

from . import config


class NoKeyError(RuntimeError):
    pass


class Meter:
    """Counts tokens and dollars for one job (an indexing run or a question)."""

    def __init__(self, budget_dollars=None):
        self.lock = threading.Lock()
        self.calls = 0
        self.cached = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.dollars = 0.0
        self.budget = budget_dollars

    def add(self, model, tin, tout, cached=False):
        p_in, p_out = config.PRICES.get(model, (0.0, 0.0))
        with self.lock:
            self.calls += 1
            if cached:
                self.cached += 1
                return
            self.tokens_in += tin
            self.tokens_out += tout
            self.dollars += tin / 1e6 * p_in + tout / 1e6 * p_out

    def over_budget(self):
        return self.budget is not None and self.dollars > self.budget

    def as_dict(self):
        return {"calls": self.calls, "cached": self.cached, "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "dollars": round(self.dollars, 4)}


class BudgetExceeded(RuntimeError):
    pass


_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            if not config.ANTHROPIC_API_KEY:
                raise NoKeyError("No ANTHROPIC_API_KEY set. Add it to the .env file.")
            import anthropic
            _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=4)
        return _client


def _cache_path(key):
    d = config.CACHE_DIR / "llm" / key[:2]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def complete(system, user, *, model=None, max_tokens=1500, task="", meter=None):
    """Return the model's text reply. `task` names the kind of call (used by the test stand-in)."""
    model = model or config.WORK_MODEL
    key = hashlib.sha256(json.dumps([model, system, user, max_tokens]).encode()).hexdigest()
    path = _cache_path(key)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if meter:
            meter.add(model, data["in"], data["out"], cached=True)
        return data["text"]
    if meter and meter.over_budget():
        raise BudgetExceeded(f"Stopped: this run passed the ${meter.budget:.2f} budget.")

    if config.FAKE_LLM:
        from .fake_llm import fake_complete
        text = fake_complete(task, system, user)
        tin, tout = len(system + user) // 4, len(text) // 4
    else:
        client = _get_client()
        t0 = time.time()
        resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                      messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        tin, tout = resp.usage.input_tokens, resp.usage.output_tokens

    path.write_text(json.dumps({"text": text, "in": tin, "out": tout, "model": model}), encoding="utf-8")
    if meter:
        meter.add(model, tin, tout)
    return text


def complete_json(system, user, **kw):
    """Like complete(), but parses a JSON object or list out of the reply."""
    text = complete(system, user, **kw)
    return parse_json(text)


def parse_json(text):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            chunk = text[start:end + 1]
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                # common repair: trailing commas
                try:
                    return json.loads(re.sub(r",\s*([}\]])", r"\1", chunk))
                except json.JSONDecodeError:
                    continue
    raise ValueError("Could not parse JSON from model reply: " + text[:200])


def estimate_dollars(model, tin, tout):
    p_in, p_out = config.PRICES.get(model, (0.0, 0.0))
    return tin / 1e6 * p_in + tout / 1e6 * p_out
