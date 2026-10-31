"""Generate test questions that probe each method's strengths and blind spots.

Each question type picks its raw material from the indexes (a passage with a number, a
two-step path in the graph, a well-connected entity, the community summaries...), then
Claude writes a natural question and its reference answer from that material only.
"""
import random
import re
from collections import Counter

from . import llm

TYPE_INFO = {
    "single_fact": {"label": "Single fact", "expect": "vector", "tests": "Can it find one exact detail?",
        "rule": "Looking up one specific fact? Use vector RAG.",
        "lesson": "Exact details like dates and numbers live in the original sentences. Graph extraction keeps who connects to whom and often drops the specifics."},
    "multi_hop": {"label": "Multi-hop", "expect": "graph", "tests": "Can it chain two relationships from different documents?",
        "rule": "Chained questions (A's B's C) are more reliable with GraphRAG.",
        "lesson": "The answer needs two facts from two different documents. The graph can walk from one to the other; vector search only succeeds if both passages happen to rank in its top results."},
    "hidden_link": {"label": "Hidden link", "expect": "graph", "tests": "Can it reach a document that shares no words with the question?",
        "rule": "When the answer sits in a document that shares no words with the question, use GraphRAG.",
        "lesson": "We checked: vector search did not retrieve the document holding the second fact for this question. The graph can still reach it by following a connection."},
    "comparison": {"label": "Comparison", "expect": "tie", "tests": "Can it hold two viewpoints side by side?",
        "rule": "If each side lives in its own passage, vector RAG is cheaper and keeps more nuance.",
        "lesson": "Both sides are usually findable either way. Compare how much context each method used, and which answer kept the reasons and details."},
    "list": {"label": "Complete list", "expect": "graph", "tests": "Does it return all matches or only the top few?",
        "rule": "\"List every…\" questions favor GraphRAG.",
        "lesson": "Vector search returns a fixed number of passages, so a list question gets cut off. The graph gathers every neighbor, however many documents they came from."},
    "big_picture": {"label": "Big picture", "expect": "graph", "tests": "Can it summarize the whole collection?",
        "rule": "Themes, summaries and \"what's going on\" questions need GraphRAG's global search.",
        "lesson": "No single passage answers this. GraphRAG answers from its community summaries, written once at index time; vector search sees only a handful of passages."},
    "vague": {"label": "Vague topic", "expect": "vector", "tests": "Does it work when the question names nobody?",
        "rule": "Vague or topical questions with no names favor vector RAG.",
        "lesson": "GraphRAG starts from named things in the question. With no names to latch onto it has little to work with, while vector search matches on wording and meaning."},
    "temporal": {"label": "Temporal", "expect": "tie", "tests": "Can it reason about when things were reported?",
        "rule": "Questions about dates and sources need metadata filters, which neither basic method has.",
        "lesson": "This question hinges on publication dates or which outlet said what. Neither plain vector search nor a basic graph handles that well; production systems add date and source filters on top of retrieval."},
    "unanswerable": {"label": "Unanswerable", "expect": "tie", "tests": "Does it admit what it doesn't know?",
        "rule": "Always test with questions the corpus can't answer.",
        "lesson": "The documents don't contain this answer. The right response is to say so. Watch for a confident answer built from nearby facts; graph extraction often drops the qualifiers (years, conditions) that would reveal the mismatch."},
}

QGEN_SYSTEM = """You write test questions for comparing search methods over a document collection.
Write ONE natural question a curious reader might ask, plus its reference answer, using ONLY the material given.
Never mention "the documents", "the text", "the passage" or "the graph" in the question.
Return JSON only: {"question": "...", "answer": "..."}"""

INSTRUCTIONS = {
    "single_fact": "Ask for the specific date, number or amount stated in this passage. Name the subject clearly so the question stands alone.",
    "multi_hop": "Write a question that names ONLY the first entity of the chain and whose answer is the LAST entity, so answering needs both facts. Do not name the middle entity.",
    "comparison": "Ask how the two named entities differ in their relationship to the third. The answer states each one's position.",
    "list": "Ask for everyone and everything connected to the named entity. The answer lists all the connected names with a few words on each.",
    "big_picture": "Ask a broad question about the main themes, conflicts or developments across the whole collection. The answer synthesizes the summaries in 3 to 5 sentences.",
    "vague": "Ask a vague, topical question about what this passage describes, WITHOUT naming any specific person, place, organization or event.",
    "unanswerable": "Ask a question that sounds answerable from this passage but asks for a detail the passage does NOT contain (for example, a different year, or a figure it never gives). The answer must say the information isn't available.",
}


def _write(qtype, material, meter):
    user = f"Question type: {qtype}\nInstruction: {INSTRUCTIONS[qtype]}\n\nMaterial:\n{material}"
    try:
        r = llm.complete_json(QGEN_SYSTEM, user, task="qgen:" + qtype, max_tokens=500, meter=meter)
        q, a = str(r.get("question", "")).strip(), str(r.get("answer", "")).strip()
        return (q, a) if q and a else None
    except Exception:
        return None


def generate(docs, chunks, graph, vindex, meter, progress=lambda *a: None, seed=7):
    rnd = random.Random(seed)
    ents, rels = graph["entities"], graph["relations"]
    byid = {e["id"]: e for e in ents}
    rtext = lambda r: f"{byid[r['s']]['name']} {r['rel']} {byid[r['t']]['name']}"
    out = []

    def add(qtype, q, a, sources, note=""):
        info = TYPE_INFO[qtype]
        out.append({"id": f"g{len(out) + 1}", "type": qtype, "label": info["label"], "q": q, "answer": a,
                    "expect": info["expect"], "sources": sources, "note": note})

    plan = 8
    step = 0

    def tick(msg):
        nonlocal step
        step += 1
        progress("questions", step, plan, msg)

    # 1. single fact: a passage with a number or date in it
    num_chunks = [c for c in chunks if re.search(r"\d", c["text"]) and len(c["text"].split()) >= 8]
    if num_chunks:
        c = rnd.choice(num_chunks)
        r = _write("single_fact", c["text"], meter)
        if r:
            add("single_fact", *r, [c["doc"]])
    tick("single fact")

    # 2-3. multi-hop paths a -r1- b -r2- c, facts from different documents
    adj = {}
    for i, r in enumerate(rels):
        adj.setdefault(r["s"], []).append(i)
        adj.setdefault(r["t"], []).append(i)
    together = set()
    for e in ents:
        for d in e["docs"]:
            together.add((e["id"], d))
    paths = []
    for b, idx in adj.items():
        for i in idx:
            for j in idx:
                if i >= j:
                    continue
                r1, r2 = rels[i], rels[j]
                if r1["doc"] == r2["doc"]:
                    continue
                a = r1["t"] if r1["s"] == b else r1["s"]
                c = r2["t"] if r2["s"] == b else r2["s"]
                if a == c or set(byid[a]["docs"]) & set(byid[c]["docs"]):
                    continue
                paths.append((a, b, c, i, j))
    rnd.shuffle(paths)
    tried = 0
    for a, b, c, i, j in paths[:6]:
        if tried >= 3:
            break
        material = (f"Chain: {byid[a]['name']} -> {byid[b]['name']} -> {byid[c]['name']}\n"
                    f"Fact 1: {rtext(rels[i])}\nFact 2: {rtext(rels[j])}\n"
                    f"{byid[a]['name']}: {byid[a]['desc']}\n{byid[c]['name']}: {byid[c]['desc']}")
        r = _write("multi_hop", material, meter)
        tried += 1
        if not r:
            continue
        # Did vector search find the document holding the far fact?
        far_doc = rels[j]["doc"] if c in (rels[j]["s"], rels[j]["t"]) else rels[i]["doc"]
        found = {h["chunk"].rsplit(".", 1)[0] for h in vindex.search(r[0])["hits"]}
        qtype = "multi_hop" if far_doc in found else "hidden_link"
        if any(x["type"] == qtype for x in out):
            qtype = "multi_hop"
        add(qtype, *r, [rels[i]["doc"], rels[j]["doc"]],
            note=("Vector search's top results included the second document." if qtype == "multi_hop"
                  else "Vector search's top results missed the second document."))
    tick("multi-hop")
    tick("hidden link")

    # 4. comparison: two same-type entities linked to a common third, from different documents
    for b, idx in sorted(adj.items(), key=lambda kv: -len(kv[1])):
        pairs = []
        for i in idx:
            for j in idx:
                if i < j and rels[i]["doc"] != rels[j]["doc"]:
                    x = rels[i]["t"] if rels[i]["s"] == b else rels[i]["s"]
                    y = rels[j]["t"] if rels[j]["s"] == b else rels[j]["s"]
                    if x != y and byid[x]["type"] == byid[y]["type"] and byid[x]["type"] in ("person", "organization"):
                        pairs.append((i, j))
        if pairs:
            i, j = pairs[0]
            r = _write("comparison", f"Third entity: {byid[b]['name']}\nFact A: {rtext(rels[i])}\nFact B: {rtext(rels[j])}", meter)
            if r:
                add("comparison", *r, [rels[i]["doc"], rels[j]["doc"]])
            break
    tick("comparison")

    # 5. complete list: a hub entity whose connections span several documents
    hubs = sorted(ents, key=lambda e: (-len({rels[i]["doc"] for i in adj.get(e["id"], [])}), -len(adj.get(e["id"], []))))
    if hubs and adj.get(hubs[0]["id"]):
        h = hubs[0]
        facts = "\n".join(rtext(rels[i]) for i in adj[h["id"]][:25])
        r = _write("list", f"Entity: {h['name']}\nAll its connections:\n{facts}", meter)
        if r:
            add("list", *r, sorted({rels[i]["doc"] for i in adj[h["id"]]}))
    tick("complete list")

    # 6. big picture: from community summaries
    summaries = "\n".join(f"[{c['title']}] {c['summary']}" for c in graph["communities"] if c.get("summary"))
    if summaries:
        r = _write("big_picture", summaries, meter)
        if r:
            add("big_picture", *r, [])
    tick("big picture")

    # 7. vague: a passage that names none of the graph's entities
    names = [a for e in ents for a in e["aliases"] if len(a) >= 4]
    unnamed = [c for c in chunks if len(c["text"].split()) >= 8 and not any(n in c["text"].lower() for n in names)]
    pool = unnamed or sorted(chunks, key=lambda c: sum(n in c["text"].lower() for n in names))[:5]
    if pool:
        c = rnd.choice(pool)
        r = _write("vague", c["text"], meter)
        if r:
            add("vague", *r, [c["doc"]])
    tick("vague topic")

    # 8. unanswerable: looks answerable, but the detail isn't there
    if num_chunks:
        c = rnd.choice(num_chunks)
        r = _write("unanswerable", c["text"], meter)
        if r:
            add("unanswerable", *r, [])
    tick("unanswerable")
    return out


def benchmark_entries(bench, start=1):
    """Turn a dataset's own benchmark questions into question cards."""
    out = []
    for k, b in enumerate(bench):
        info = TYPE_INFO.get(b["type"], TYPE_INFO["multi_hop"])
        out.append({"id": f"b{start + k}", "type": b["type"], "label": info["label"] + " · benchmark", "q": b["q"],
                    "answer": b["answer"], "expect": info["expect"], "sources": [], "benchmark": True,
                    "note": "This question and its reference answer come from the dataset's authors."})
    return out
