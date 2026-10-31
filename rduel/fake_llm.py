"""A crude stand-in for Claude, used only by tests (RDUEL_FAKE_LLM=1).

It returns well-formed replies so the whole pipeline can run without a key or network.
The content is mechanical and not meant to be good.
"""
import json
import re

NAME = re.compile(r"\b([A-Z][a-z]+(?:\s+(?:of\s+the\s+|of\s+)?[A-Z][a-z]+)+|[A-Z][a-z]{3,})\b")
SKIP = {"The", "This", "That", "Records", "Several", "Work", "Entry", "Riders", "Lawyers", "If", "It", "He", "She", "Saturday"}


def fake_complete(task, system, user):
    if task == "extract":
        text = user.split("Text:", 1)[-1]
        names = []
        for m in NAME.finditer(text):
            n = m.group(1)
            if n.split()[0] in SKIP:
                n = " ".join(n.split()[1:])
            if n and n not in names and n not in SKIP:
                names.append(n)
        ents = [{"name": n, "type": "person" if len(n.split()) == 2 else "organization", "description": f"Mentioned in this text: {n}."} for n in names[:12]]
        rels = [{"source": names[i], "relation": "appears with", "target": names[i + 1]} for i in range(min(len(names) - 1, 10))]
        return json.dumps({"entities": ents, "relations": rels})
    if task == "summarize":
        names = re.findall(r"- ([^(]+) \(", user)[:4]
        return json.dumps({"title": (names[0].strip() if names else "Cluster") + " group",
                           "summary": "This cluster involves " + ", ".join(n.strip() for n in names) + "."})
    if task == "route":
        q = user.lower()
        if "main" in q or "theme" in q:
            return json.dumps({"type": "big_picture", "route": "graph", "reason": "Big-picture question."})
        return json.dumps({"type": "other", "route": "both", "reason": "Unsure, so both."})
    if task == "agent_plan":
        q = user.split("Question:", 1)[-1].split("\n", 1)[0].strip()
        return json.dumps({"rewritten": q + " (rewritten)", "why": "Stand-in plan.", "actions": [{"tool": "vector", "query": q + " council chair"}]})
    if task == "agent_check":
        if "read the topic summaries" in user:
            return json.dumps({"enough": True, "note": "Stand-in: enough now.", "next": None})
        return json.dumps({"enough": False, "note": "Stand-in: not enough yet.", "next": {"tool": "summaries"}})
    if task == "answer":
        ev = user.split("):", 1)[-1].strip().splitlines()
        ev = [l for l in ev if l.strip() and not l.endswith(":")]
        return "Based on the evidence: " + (ev[0][:200] if ev else "nothing found.")
    if task == "judge":
        return json.dumps({"grade": "partial", "why": "Stand-in judge."})
    if task.startswith("qgen:"):
        kind = task.split(":", 1)[1]
        mat = user.split("Material:", 1)[-1].strip().splitlines()
        first = mat[0][:80] if mat else "this"
        return json.dumps({"question": f"[{kind}] What about {first}?", "answer": f"Reference answer drawn from: {first}"})
    return "{}"
