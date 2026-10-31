"""Answering: the question classifier/router, answer writing, and the auto-judge."""
import re

from . import config, llm

QUESTION_TYPES = {
    "single_fact": "Single fact",
    "multi_hop": "Multi-hop",
    "hidden_link": "Hidden link",
    "comparison": "Comparison",
    "list": "Complete list",
    "big_picture": "Big picture",
    "vague": "Vague topic",
    "unanswerable": "Unanswerable",
}

ROUTE_SYSTEM = """You route questions for a retrieval system that has two search methods:
- vector: finds passages whose wording/meaning resembles the question. Best for one specific fact (dates, numbers, quotes) and vague or topical questions that name no specific entity.
- graph: a knowledge graph of named entities and their relationships, plus summaries of clusters. Best for chaining relationships (A's B's C), complete lists of everything connected to something, and big-picture/theme questions about the whole collection.
- both: run both and merge, when the question names entities but may also need exact details, or when unsure.

Return JSON only: {"type": one of "single_fact","multi_hop","comparison","list","big_picture","vague","other",
"route": "vector" | "graph" | "both", "reason": "one plain-English sentence a beginner would understand"}"""


def rule_route(question, has_seeds):
    q = question.lower()
    if re.search(r"\b(main|overall|themes?|biggest|summar\w*|big picture|what'?s going on|across)\b", q):
        return {"type": "big_picture", "route": "graph",
                "reason": "It asks for the big picture, so it goes to the graph's community summaries."}
    if not has_seeds:
        return {"type": "vague", "route": "vector",
                "reason": "It names nothing the graph knows about, so only vector search can help."}
    if re.search(r"\b(when|what time|how much|how many|date|year)\b|\d", q):
        return {"type": "single_fact", "route": "vector",
                "reason": "It asks for an exact detail (a date, number or year), which graph extraction tends to drop."}
    if re.search(r"\b(list|everyone|every|all|who else|connected)\b", q):
        return {"type": "list", "route": "graph",
                "reason": "It asks for a complete list, and vector search stops at a fixed number of passages."}
    return {"type": "other", "route": "both",
            "reason": "It names entities but could also need exact wording, so it runs both searches and merges the evidence."}


def route(question, has_seeds, use_llm=True, meter=None):
    if use_llm and config.has_key():
        try:
            r = llm.complete_json(ROUTE_SYSTEM, f"Question: {question}\nNamed entities found in the graph: {'yes' if has_seeds else 'none'}",
                                  task="route", max_tokens=200, meter=meter)
            if r.get("route") in ("vector", "graph", "both"):
                r["by"] = "llm"
                return r
        except Exception:
            pass
    r = rule_route(question, has_seeds)
    r["by"] = "rules"
    return r


ANSWER_SYSTEM = """You answer questions using ONLY the evidence provided, which came from a search over a document collection.
- If the evidence doesn't contain the answer, say so plainly. Don't guess or use outside knowledge.
- If the evidence only partly answers it, give what it supports and say what's missing.
- Be concise: 1 to 4 sentences, or a short list if the question asks for one."""


def answer(question, evidence_label, context, meter=None):
    if not context.strip():
        return "The search found no evidence, so I can't answer this."
    user = f"Question: {question}\n\nEvidence ({evidence_label}):\n{context}"
    return llm.complete(ANSWER_SYSTEM, user, model=config.ANSWER_MODEL, task="answer", max_tokens=500, meter=meter).strip()


JUDGE_SYSTEM = """You grade an answer against a reference answer.
Return JSON only: {"grade": "correct" | "partial" | "wrong", "why": "one short sentence"}.
- correct: states the key facts of the reference without contradicting it. Extra true detail is fine.
- partial: some key facts right, others missing.
- wrong: contradicts the reference, answers something else, or claims there's no answer when there is one.
If the reference says the answer isn't in the documents, a correct answer must also say it can't be found."""


def judge(question, reference, candidate, meter=None):
    try:
        r = llm.complete_json(JUDGE_SYSTEM, f"Question: {question}\nReference answer: {reference}\nAnswer to grade: {candidate}",
                              task="judge", max_tokens=200, meter=meter)
        if r.get("grade") in ("correct", "partial", "wrong"):
            return r
    except Exception:
        pass
    return {"grade": "unknown", "why": "The judge couldn't grade this one."}
