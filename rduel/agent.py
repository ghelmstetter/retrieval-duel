"""The Agentic contestant: plan, search, check, search again, answer.

Unlike the simple Hybrid (one routing decision, one search), the agent:
  1. rewrites the question into better search terms and picks starting searches,
  2. runs them (vector search, a graph walk from entities it names, or the community summaries),
  3. checks whether the evidence answers the question, and if not, picks a follow-up search,
  4. answers from everything it gathered.

Its "brain" (the planner) is Claude when a key is available. The hosted demo can't call
Claude, so it uses a pre-written plan for each demo question (the searches still run
live), or simple rules for questions people type.
"""
import time

from . import config, llm, qa
from .textutil import approx_tokens

MAX_SEARCHES = 3

PLAN_SYSTEM = """You plan searches over a document collection to answer a question. Three search tools exist:
- "vector": finds passages whose wording resembles a query. Good for specific facts, dates, numbers, quotes, and vague topics.
- "graph": walks a knowledge graph outward from named entities. Good for relationships, chains (A's B's C) and everything connected to something. Only works with entity names from the list below.
- "summaries": reads short summaries of every topic cluster. Good for big-picture or "what's going on" questions.

Questions often use different words than the documents ("in charge of the town" vs "council chair"), so rewrite the
question using words the documents are likely to contain, including synonyms and related roles.

Return JSON only:
{"rewritten": "the question rephrased with likely document vocabulary",
 "why": "one plain sentence a beginner would understand",
 "actions": [{"tool": "vector", "query": "..."} | {"tool": "graph", "entities": ["exact names from the list"]} | {"tool": "summaries"}]}
Use one or two actions. Use the collection description to understand the setting (for example, the name of
the place the documents are about). Never invent names, places or facts that aren't in the description or the entity list."""

CHECK_SYSTEM = """You are checking whether gathered evidence is enough to answer a question well.
Return JSON only:
{"enough": true or false,
 "note": "one plain sentence: what the evidence shows, and what (if anything) is missing",
 "next": null, or ONE follow-up action: {"tool": "vector", "query": "..."} | {"tool": "graph", "entities": ["exact names from the list"]} | {"tool": "summaries"}}
If the evidence points to a related entity that might hold the answer, a graph search from it is often a good next step.
Only say enough=false if a follow-up search is likely to help. Never repeat a search that was already done."""

ANSWER_SYSTEM = qa.ANSWER_SYSTEM + """
- If the question assumes something the evidence doesn't support (for example, a role that doesn't exist), say so, then give the closest thing the evidence does support."""


# ---------------- planners ----------------
class ClaudePlanner:
    kind = "claude"

    def __init__(self, gi, meter, about=""):
        self.gi, self.meter = gi, meter
        ents = sorted(gi.entities, key=lambda e: -len(gi.adj.get(e["id"], [])))[:200]
        self.names = ", ".join(e["name"] for e in ents)
        # What the collection is about: its description plus the topic summaries, so the planner knows the setting.
        topics = "\n".join(f"- {c['title']}: {c['summary']}" for c in gi.communities if c.get("summary"))[:3000]
        self.context = f"About this document collection: {about}\nTopics in it:\n{topics}" if (about or topics) else ""

    def plan(self, question):
        user = f"Question: {question}\n\n{self.context}\n\nEntity names in the graph:\n{self.names}"
        try:
            r = llm.complete_json(PLAN_SYSTEM, user, task="agent_plan", max_tokens=2000, meter=self.meter)
            acts = [a for a in r.get("actions") or [] if isinstance(a, dict) and a.get("tool") in ("vector", "graph", "summaries")][:2]
            return {"rewritten": str(r.get("rewritten") or question), "why": str(r.get("why") or ""),
                    "actions": acts or [{"tool": "vector", "query": question}]}
        except Exception:
            return RulesPlanner(self.gi).plan(question)

    def check(self, question, evidence_text, done):
        user = (f"Question: {question}\n\n{self.context}\n\nSearches already done:\n" + "\n".join(f"- {d}" for d in done) +
                f"\n\nEntity names in the graph:\n{self.names}\n\nEvidence so far:\n{evidence_text[:12000]}")
        try:
            r = llm.complete_json(CHECK_SYSTEM, user, task="agent_check", max_tokens=2000, meter=self.meter)
            nxt = r.get("next") if isinstance(r.get("next"), dict) and r["next"].get("tool") in ("vector", "graph", "summaries") else None
            return {"enough": bool(r.get("enough")) or nxt is None, "note": str(r.get("note") or ""), "next": nxt}
        except Exception:
            return {"enough": True, "note": "Couldn't run the check, so it answers with what it has.", "next": None}


class RulesPlanner:
    """No-key fallback: vector search on the question, plus the graph if it names something,
    otherwise the community summaries. Better than giving up, but it can't rewrite the question."""
    kind = "rules"

    def __init__(self, gi):
        self.gi = gi

    def plan(self, question):
        seeds = self.gi.link(question)
        acts = [{"tool": "vector", "query": question}]
        if seeds:
            acts.append({"tool": "graph", "entities": [s["name"] for s in seeds]})
        else:
            acts.append({"tool": "summaries"})
        return {"rewritten": question, "actions": acts,
                "why": "Without an API key the agent can't rewrite the question, so it uses simple rules: search the passages, then "
                       + ("walk the graph from the names it recognized." if seeds else "read the topic summaries, since the question names nothing in the graph.")}

    def check(self, question, evidence_text, done):
        return {"enough": True, "note": "Rules mode doesn't judge the evidence; with a key, Claude would decide whether to search again.", "next": None}


class ScriptedPlanner:
    """Pre-written plan for a demo question: the decisions are canned, the searches run live."""
    kind = "scripted"

    def __init__(self, script):
        self.script = script
        self.checks = list(script.get("checks", []))

    def plan(self, question):
        return {"rewritten": self.script.get("rewritten", question), "why": self.script.get("why", ""),
                "actions": self.script["actions"]}

    def check(self, question, evidence_text, done):
        if self.checks:
            return self.checks.pop(0)
        return {"enough": True, "note": "", "next": None}


# ---------------- the loop ----------------
def _clean(action):
    """Normalize a planned action: entities as a list of names, query as text."""
    if not isinstance(action, dict):
        return None
    tool = action.get("tool")
    if tool not in ("vector", "graph", "summaries"):
        return None
    out = {"tool": tool}
    if tool == "vector":
        q = action.get("query")
        out["query"] = q if isinstance(q, str) else " ".join(map(str, q)) if isinstance(q, list) else ""
    if tool == "graph":
        ents = action.get("entities") or action.get("entity") or []
        out["entities"] = [ents] if isinstance(ents, str) else [str(e) for e in ents if e]
    return out



def _describe(action):
    if action["tool"] == "vector":
        return f'vector search for "{action.get("query", "")}"'
    if action["tool"] == "graph":
        return "graph walk from " + ", ".join(action.get("entities") or ["(nothing)"])
    return "read the topic summaries"


def run(question, vindex, gi, *, planner, top_k=None, answer=True, meter=None):
    meter = meter or llm.Meter()
    t0 = time.time()
    steps, done = [], []
    passages, facts, summaries = {}, {}, None

    def mark():
        return (meter.tokens_in + meter.tokens_out, meter.dollars, meter.calls)

    def step(kind, text, before, extra=None):
        tok, dol, calls = mark()
        s = {"kind": kind, "text": text, "tokens": tok - before[0], "dollars": round(dol - before[1], 5), "calls": calls - before[2]}
        if extra:
            s.update(extra)
        steps.append(s)

    def evidence_text():
        parts = []
        if passages:
            parts.append("Passages:\n" + "\n".join(f"[{h['title']}] {h['text']}" for h in passages.values()))
        if facts:
            parts.append("Facts from the knowledge graph:\n" + "\n".join(f["text"] for f in facts.values()))
        if summaries:
            parts.append("Topic summaries:\n" + summaries)
        return "\n\n".join(parts)

    def do(action):
        before = mark()
        tool = action["tool"]
        if tool == "vector":
            r = vindex.search(action.get("query") or question, top_k)
            new = [h for h in r["hits"] if h["chunk"] not in passages]
            for h in r["hits"]:
                passages.setdefault(h["chunk"], h)
            best = r["hits"][0]["text"] if r["hits"] else ""
            found = f"{len(new)} new passage(s)" + (f'; best match: "{best[:110]}{"…" if len(best) > 110 else ""}"' if best else "")
            step("search", _describe(action), before, {"tool": tool, "found": found, "hits": [h["chunk"] for h in r["hits"]]})
        elif tool == "graph":
            seeds = gi.find_entities(action.get("entities"))
            if not seeds:
                step("search", _describe(action), before, {"tool": tool, "found": "None of those names are in the graph."})
            else:
                r = gi.local_search(question, seeds=seeds)
                new = [f for f in r["facts"] if f["i"] not in facts]
                for f in r["facts"]:
                    facts.setdefault(f["i"], f)
                top = "; ".join(f["text"] for f in r["facts"][:2])
                step("search", _describe({"tool": "graph", "entities": [s["name"] for s in seeds]}), before,
                     {"tool": tool, "found": f"{len(new)} new fact(s)" + (f"; e.g. {top}" if top else ""), "seeds": [s["id"] for s in seeds]})
        else:
            r = gi.global_search(question)
            nonlocal summaries
            summaries = r["context"]
            step("search", _describe(action), before, {"tool": tool, "found": f"{len(r['summaries'])} topic summaries"})
        done.append(_describe(action))

    before = mark()
    plan = planner.plan(question)
    rewritten = str(plan.get("rewritten") or question)
    step("plan", plan.get("why") or "Planned the searches.", before,
         {"rewritten": rewritten if rewritten.strip().lower() != question.strip().lower() else None,
          "planned": [_describe(a) for a in map(_clean, plan["actions"]) if a]})

    for a in [c for c in map(_clean, plan["actions"]) if c][:MAX_SEARCHES]:
        do(a)
    while len(done) < MAX_SEARCHES:
        before = mark()
        c = planner.check(question, evidence_text(), done)
        nxt = _clean(c.get("next"))
        if nxt and _describe(nxt) in done:
            nxt = None
        step("check", c.get("note") or ("Enough to answer." if c.get("enough") or not nxt else "Not enough yet."), before,
             {"enough": not nxt, "next": _describe(nxt) if nxt else None})
        if not nxt:
            break
        do(nxt)

    ctx = evidence_text()
    out = {"steps": steps, "context": ctx, "context_tokens": approx_tokens(ctx), "planner": planner.kind,
           "searches": len(done), "passages": list(passages), "facts": list(facts), "used_summaries": bool(summaries)}
    if answer:
        before = mark()
        if ctx.strip():
            text = llm.complete(ANSWER_SYSTEM, f"Question: {question}\n\nEvidence gathered by several searches:\n{ctx}",
                                model=config.ANSWER_MODEL, task="answer", max_tokens=3000, meter=meter).strip()
        else:
            text = "None of the searches found relevant evidence, so I can't answer this."
        step("answer", "Wrote the answer from all the evidence gathered.", before)
        out["answer"] = text
    out["latency"] = round(time.time() - t0, 2)
    out["meter"] = {"calls": meter.calls, "tokens": meter.tokens_in + meter.tokens_out, "dollars": round(meter.dollars, 5)}
    return out
