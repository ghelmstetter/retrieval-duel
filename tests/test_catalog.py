"""Offline tests for the dataset importers, using small fixtures in each dataset's published format.

Run:  python -m tests.test_catalog
"""
import json
import random
import urllib.parse

from rduel import catalog

R = random.Random(1)
WORDS = "harbor council budget vote storm report market energy trading contract pipeline meeting".split()


def para(n=80):
    return " ".join(R.choice(WORDS) for _ in range(n)) + "."


# ---- MultiHop-RAG-shaped fixtures ----
MH_CORPUS = [{"title": f"Story {i}", "author": "A", "source": ["TechCrunch", "BBC", "Fortune"][i % 3],
              "published_at": f"2023-10-{i % 28 + 1:02d}T10:00:00+00:00", "category": "tech", "url": f"https://x/{i}",
              "body": para(200)} for i in range(200)]
MH_QS = []
for i in range(80):
    t = ["inference_query", "comparison_query", "temporal_query", "null_query"][i % 4]
    ev = [] if t == "null_query" else [{"title": f"Story {(i * 7) % 200}", "url": f"https://x/{(i * 7) % 200}", "fact": "f"},
                                        {"title": f"Story {(i * 7 + 3) % 200}", "url": f"https://x/{(i * 7 + 3) % 200}", "fact": "g"}]
    MH_QS.append({"query": f"Question {i}?", "answer": "Insufficient information." if t == "null_query" else f"Answer {i}",
                  "question_type": t, "evidence_list": ev})

# ---- GraphRAG-Bench-shaped fixtures ----
NOVEL_A = "\n\n".join(f"Chapter {k}. " + para(150) for k in range(400))  # ~60k words
NOVEL_B = "\n\n".join(para(150) for _ in range(60))
GB_CORPUS = [{"corpus_name": "Novel-1", "context": NOVEL_B}, {"corpus_name": "Novel-2", "context": NOVEL_A}]
paras_a = NOVEL_A.split("\n\n")
GB_QS = []
for k in range(40):
    t = ["Fact Retrieval", "Complex Reasoning", "Contextual Summarize", "Creative Generation"][k % 4]
    GB_QS.append({"id": f"Novel-2-{k}", "source": "Novel-2", "question": f"Q{k}?", "answer": f"A{k}", "question_type": t,
                  "evidence": [paras_a[k * 9][:200]]})

# ---- Enron-shaped rows ----
ENRON_ROWS = [{"message_id": f"<{i}@enron>", "subject": f"Re: deal {i % 7}", "from": f"person{i % 5}@enron.com",
               "to": [f"person{(i + 1) % 5}@enron.com", "x@enron.com"], "date": "2001-05-04",
               "body": para(60) + "\n\n-----Original Message-----\nFrom: someone\n" + para(40)} for i in range(500)]

FILES = {
    "https://huggingface.co/api/datasets/yixuantt/MultiHopRAG/tree/main?recursive=true":
        [{"type": "file", "path": "corpus.json"}, {"type": "file", "path": "MultiHopRAG.json"}, {"type": "file", "path": "README.md"}],
    "https://huggingface.co/datasets/yixuantt/MultiHopRAG/resolve/main/corpus.json": MH_CORPUS,
    "https://huggingface.co/datasets/yixuantt/MultiHopRAG/resolve/main/MultiHopRAG.json": MH_QS,
    "https://huggingface.co/api/datasets/GraphRAG-Bench/GraphRAG-Bench/tree/main?recursive=true":
        [{"type": "file", "path": "Datasets/Corpus/novel.json"}, {"type": "file", "path": "Datasets/Questions/novel_questions.json"},
         {"type": "file", "path": "Datasets/Corpus/medical.json"}],
    "https://huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench/resolve/main/Datasets/Corpus/novel.json": GB_CORPUS,
    "https://huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench/resolve/main/Datasets/Questions/novel_questions.json": GB_QS,
}


def fake_get(url, timeout=60):
    if url in FILES:
        return json.dumps(FILES[url]).encode()
    if "datasets-server" in url:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if "corbt" not in q["dataset"][0]:
            raise AssertionError("should use the first Enron source")
        if "/splits" in url:
            return json.dumps({"splits": [{"dataset": "corbt/enron-emails", "config": "default", "split": "train"}]}).encode()
        if "/size" in url:
            return json.dumps({"size": {"splits": [{"config": "default", "split": "train", "num_rows": len(ENRON_ROWS)}]}}).encode()
        off, n = int(q["offset"][0]), int(q["length"][0])
        return json.dumps({"rows": [{"row": r} for r in ENRON_ROWS[off:off + n]]}).encode()
    raise AssertionError("unexpected URL " + url)


def main():
    catalog._get = fake_get
    log = []
    prog = lambda *a: log.append(a)

    for size_id in ("s", "m", "l"):
        entry, size, docs, bench = catalog.run_import("multihop-rag", size_id, prog)
        types = {b["type"] for b in bench}
        assert len(docs) == size["docs"], (len(docs), size)
        assert len(bench) == size["questions"], len(bench)
        assert "unanswerable" in types and "multi_hop" in types, types
        titles = {d["title"] for d in docs}
        assert docs[0]["text"].startswith("Source:"), docs[0]["text"][:40]
        print(f"multihop {size_id}: {len(docs)} docs, {len(bench)} questions, types={sorted(types)}")

    for size_id in ("s", "l"):
        entry, size, docs, bench = catalog.run_import("graphrag-bench", size_id, prog)
        words = sum(len(d["text"].split()) for d in docs)
        assert words <= size["words"] * 1.05, words
        assert docs[0]["title"].startswith("Novel-2"), docs[0]["title"]
        assert all(b["type"] in ("single_fact", "multi_hop", "big_picture") for b in bench)
        print(f"graphrag-bench {size_id}: {len(docs)} sections, {words} words, {len(bench)} questions in the slice")

    entry, size, docs, bench = catalog.run_import("enron", "m", prog)
    assert len(docs) == 150, len(docs)
    assert docs[0]["text"].startswith("From: person"), docs[0]["text"][:60]
    assert "Original Message" not in docs[0]["text"]
    print(f"enron m: {len(docs)} emails; first:\n  " + docs[0]["text"][:160].replace("\n", " | "))

    # raw-message variant (headers inside the text, as in some Enron copies)
    raw = [{"text": f"Message-ID: <{i}>\nDate: Mon, 14 May 2001\nFrom: a{i}@enron.com\nTo: b@enron.com\nSubject: Gas {i}\n\n" + para(40)} for i in range(30)]
    d = catalog.emails_to_docs(raw, 10)
    assert d[0]["text"].startswith("From: a0@enron.com") and d[0]["title"] == "Gas 0" and "Message-ID" not in d[0]["text"], d[0]
    print("enron raw-format parsing ok")

    # wrapper and JSONL variants
    assert len(catalog._load_records(json.dumps({"data": [{"a": 1}]}).encode())) == 1
    assert len(catalog._load_records(b'{"a":1}\n{"a":2}\n')) == 2
    print("ALL CATALOG TESTS PASSED")


if __name__ == "__main__":
    main()
