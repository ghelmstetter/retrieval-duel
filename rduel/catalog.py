"""Built-in public datasets that can be imported with one click.

Each importer downloads a small, cost-friendly sample from Hugging Face on your computer,
turns it into documents, and (where the dataset has them) keeps its own benchmark
questions with reference answers.

Hugging Face file layouts change from time to time, so the importers look up the
dataset's file list first and accept a few common field-name variants.
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

HF = "https://huggingface.co"
ROWS_API = "https://datasets-server.huggingface.co"

CATALOG = [
    {"id": "multihop-rag", "name": "MultiHop-RAG", "source": "Hugging Face · yixuantt/MultiHopRAG", "license": "ODC-By",
     "description": "News articles from late 2023, with multi-hop questions and ground-truth answers. The questions come with the dataset.",
     "why": "Its questions need facts from two to four different articles, and it includes unanswerable ones. Published after many models' training data was collected, so less is known from memory (but newer models may have seen it).",
     "sizes": [{"id": "s", "label": "Small: 30 articles", "docs": 30, "questions": 6},
               {"id": "m", "label": "Medium: 60 articles", "docs": 60, "questions": 10},
               {"id": "l", "label": "Large: 120 articles", "docs": 120, "questions": 16}],
     "default": "m"},
    {"id": "graphrag-bench", "name": "GraphRAG-Bench (novel)", "source": "Hugging Face · GraphRAG-Bench", "license": "see dataset card",
     "description": "One novel from the GraphRAG-Bench study of when graphs actually help, split into sections, with the study's own questions.",
     "why": "Long narrative with many characters and relationships, where GraphRAG should shine on summary questions. The novels are public-domain classics, so the model may know some of the story already.",
     "sizes": [{"id": "s", "label": "Small: about 15,000 words", "words": 15000, "questions": 8},
               {"id": "m", "label": "Medium: about 30,000 words", "words": 30000, "questions": 10},
               {"id": "l", "label": "Large: about 60,000 words", "words": 60000, "questions": 14}],
     "default": "s"},
    {"id": "enron", "name": "Enron emails", "source": "Hugging Face · Enron email corpus", "license": "public record",
     "description": "A run of real emails from the Enron corpus, released during the 2001 investigation. Who wrote to whom, about which deal.",
     "why": "Naturally graph-shaped: people, deals and meetings spread across many short messages. Expect messy text. These are real people's emails; the corpus is public, but treat it with care.",
     "sizes": [{"id": "s", "label": "Small: 75 emails", "docs": 75},
               {"id": "m", "label": "Medium: 150 emails", "docs": 150},
               {"id": "l", "label": "Large: 300 emails", "docs": 300}],
     "default": "m"},
]
BY_ID = {c["id"]: c for c in CATALOG}


class ImportError_(RuntimeError):
    pass


# ---------------- networking ----------------
def _get(url, timeout=60):
    headers = {"User-Agent": "retrieval-duel/0.1"}
    tok = os.getenv("HF_TOKEN", "").strip()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _get_json(url, **kw):
    return json.loads(_get(url, **kw).decode("utf-8"))


def _hf_files(repo):
    data = _get_json(f"{HF}/api/datasets/{repo}/tree/main?recursive=true")
    return [f for f in data if f.get("type") == "file"]


def _hf_download(repo, path, progress, label):
    progress("download", 0, 1, f"Downloading {label} from Hugging Face…")
    raw = _get(f"{HF}/datasets/{repo}/resolve/main/{urllib.parse.quote(path)}", timeout=300)
    progress("download", 1, 1, f"Downloaded {label} ({len(raw) / 1e6:.1f} MB).")
    return raw


def _load_records(raw):
    """Parse JSON or JSONL into a list of dicts (unwrapping common wrapper keys)."""
    text = raw.decode("utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(l) for l in text.splitlines() if l.strip()]
    if isinstance(data, dict):
        for k in ("data", "documents", "corpus", "records", "questions", "items", "rows"):
            if isinstance(data.get(k), list):
                return data[k]
        if all(isinstance(v, dict) for v in data.values()):  # {id: record}
            return [{"_key": k, **v} for k, v in data.items()]
        return [data]
    return data


def _pick(rec, *names, default=""):
    low = {k.lower(): k for k in rec}
    for n in names:
        if n in low and rec[low[n]] not in (None, ""):
            return rec[low[n]]
    return default


def _text_field(rec):
    v = _pick(rec, "body", "text", "content", "context", "article", "document", "email_body", "message", "passage")
    if not v:  # fall back to the longest string field
        strs = [x for x in rec.values() if isinstance(x, str)]
        v = max(strs, key=len) if strs else ""
    return str(v)


# ---------------- MultiHop-RAG ----------------
MH_TYPES = {"inference_query": "multi_hop", "comparison_query": "comparison", "temporal_query": "temporal",
            "null_query": "unanswerable"}


def import_multihop(size, progress, seed=11):
    repo = "yixuantt/MultiHopRAG"
    files = [f["path"] for f in _hf_files(repo)]
    corpus_path = next((p for p in files if re.search(r"corpus.*\.jsonl?$", p, re.I)), None)
    q_path = next((p for p in files if re.search(r"multihop.*\.jsonl?$", p, re.I) and p != corpus_path), None)
    if not corpus_path or not q_path:
        raise ImportError_(f"Couldn't find the corpus and question files in {repo}. Files seen: {', '.join(files[:10])}")
    corpus = _load_records(_hf_download(repo, corpus_path, progress, "articles"))
    qs = _load_records(_hf_download(repo, q_path, progress, "questions"))
    progress("sample", 0, 1, "Choosing a sample…")
    return sample_multihop(corpus, qs, size, seed)


def sample_multihop(corpus, qs, size, seed=11):
    rnd = random.Random(seed)
    arts = []
    for r in corpus:
        body = _text_field(r)
        if len(body.split()) < 40:
            continue
        title = str(_pick(r, "title", default="Untitled"))
        src = str(_pick(r, "source", "publisher", default=""))
        date = str(_pick(r, "published_at", "date", "published", default=""))[:10]
        arts.append({"title": title, "source": src, "date": date, "url": _pick(r, "url", default=""), "body": body})
    by_title = {a["title"].strip().lower(): a for a in arts}
    by_url = {a["url"]: a for a in arts if a["url"]}

    def evidence_articles(q):
        out = []
        for ev in _pick(q, "evidence_list", "evidence", default=[]) or []:
            if not isinstance(ev, dict):
                continue
            a = by_url.get(ev.get("url")) or by_title.get(str(ev.get("title", "")).strip().lower())
            if a and a not in out:
                out.append(a)
        return out

    # stratified pick of questions whose evidence fits in the sample
    groups = {}
    for q in qs:
        t = str(_pick(q, "question_type", "type", default="other"))
        groups.setdefault(t, []).append(q)
    for g in groups.values():
        rnd.shuffle(g)
    chosen, docs = [], []
    want_q, want_docs = size["questions"], size["docs"]
    order = sorted(groups, key=lambda t: t != "null_query")  # make sure an unanswerable one gets in
    while len(chosen) < want_q and any(groups.values()):
        for t in order:
            if not groups[t] or len(chosen) >= want_q:
                continue
            q = groups[t].pop()
            ev = evidence_articles(q)
            if t != "null_query" and not ev:
                continue
            new = [a for a in ev if a not in docs]
            if len(docs) + len(new) > want_docs * 0.7:
                continue
            docs += new
            chosen.append((t, q))
    # fill the rest with random articles as distractors
    pool = [a for a in arts if a not in docs]
    rnd.shuffle(pool)
    docs += pool[:max(0, want_docs - len(docs))]
    rnd.shuffle(docs)

    out_docs = [{"title": f"{a['source']}: {a['title']}" if a["source"] else a["title"], "date": a["date"],
                 "text": (f"Source: {a['source']}. Published: {a['date']}.\n\n" if a["source"] or a["date"] else "") + a["body"]}
                for a in docs]
    bench = []
    for t, q in chosen:
        qtype = MH_TYPES.get(t, "multi_hop")
        bench.append({"type": qtype, "q": str(_pick(q, "query", "question")), "answer": str(_pick(q, "answer")),
                      "benchmark": True, "source_type": t})
    return out_docs, bench


# ---------------- GraphRAG-Bench ----------------
GB_REPOS = ["GraphRAG-Bench/GraphRAG-Bench", "wuchuanjie/GraphRAG-Bench", "suki4060/GraphRAG-Benchmark"]
GB_TYPES = {"fact retrieval": "single_fact", "complex reasoning": "multi_hop", "contextual summarize": "big_picture",
            "contextual summarization": "big_picture", "summarization": "big_picture"}


def import_graphrag_bench(size, progress, seed=5):
    errors = []
    for repo in GB_REPOS:
        try:
            files = [f["path"] for f in _hf_files(repo)]
        except Exception as e:
            errors.append(f"{repo}: {e}")
            continue
        corpus_path = next((p for p in files if re.search(r"corpus", p, re.I) and re.search(r"novel.*\.jsonl?$", p, re.I)), None)
        q_path = next((p for p in files if re.search(r"question", p, re.I) and re.search(r"novel.*\.jsonl?$", p, re.I)), None)
        if not corpus_path:
            errors.append(f"{repo}: no novel corpus file")
            continue
        corpus = _load_records(_hf_download(repo, corpus_path, progress, "novels"))
        qs = _load_records(_hf_download(repo, q_path, progress, "questions")) if q_path else []
        progress("sample", 0, 1, "Choosing a novel…")
        return sample_graphrag_bench(corpus, qs, size, seed)
    raise ImportError_("Couldn't find GraphRAG-Bench on Hugging Face. " + "; ".join(errors))


def _sections(text, target_words=1200):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) < 3:
        paras = re.split(r"(?<=[.!?])\s+", text)
    out, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > target_words:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        out.append("\n\n".join(cur))
    return out


def sample_graphrag_bench(corpus, qs, size, seed=5):
    novels = []
    for r in corpus:
        text = _text_field(r)
        name = str(_pick(r, "corpus_name", "name", "title", "source", "id", "_key", default="Novel"))
        if len(text.split()) > 3000:
            novels.append((name, text))
    if not novels:
        raise ImportError_("The GraphRAG-Bench corpus didn't contain any novel-length texts.")
    qsrc = lambda q: str(_pick(q, "source", "corpus_name", "novel", default=""))
    counts = {}
    for q in qs:
        counts[qsrc(q)] = counts.get(qsrc(q), 0) + 1
    # prefer the novel with the most questions, then the shortest
    novels.sort(key=lambda nt: (-counts.get(nt[0], 0), len(nt[1])))
    name, text = novels[0]
    words = text.split()
    slice_text = text
    if len(words) > size["words"]:
        cut = len(" ".join(words[:size["words"]]))
        slice_text = text[:cut]
        nl = slice_text.rfind("\n\n")
        if nl > cut * 0.8:
            slice_text = slice_text[:nl]
    secs = _sections(slice_text)
    docs = [{"title": f"{name}, section {i + 1}", "date": "", "text": s} for i, s in enumerate(secs)]

    norm = lambda s: re.sub(r"\s+", " ", s.lower()).strip()
    hay = norm(slice_text)
    whole = len(words) <= size["words"]
    bench = []
    for q in qs:
        if qsrc(q) != name:
            continue
        t = str(_pick(q, "question_type", "type", default="")).lower()
        qtype = GB_TYPES.get(t)
        if not qtype:
            continue
        ev = _pick(q, "evidence", "evidences", "context", default="")
        ev_list = ev if isinstance(ev, list) else [ev]
        ev_list = [str(e) for e in ev_list if e]
        if not whole:
            if not ev_list:
                continue
            # keep the question only if its evidence is inside the slice we kept
            if not all(norm(e)[:80] in hay for e in ev_list if len(e) > 20):
                continue
        bench.append({"type": qtype, "q": str(_pick(q, "question", "query")), "answer": str(_pick(q, "answer", "gold_answer")),
                      "benchmark": True, "source_type": t})
    rnd = random.Random(seed)
    by = {}
    for b in bench:
        by.setdefault(b["type"], []).append(b)
    picked = []
    while len(picked) < size["questions"] and any(by.values()):
        for t in list(by):
            if by[t] and len(picked) < size["questions"]:
                picked.append(by[t].pop(rnd.randrange(len(by[t]))))
    return docs, picked


# ---------------- Enron ----------------
ENRON_SOURCES = ["corbt/enron-emails", "LLM-PBE/enron-email", "Yale-LILY/aeslc"]


def _rows(dataset, n, progress, seed):
    splits = _get_json(f"{ROWS_API}/splits?dataset={urllib.parse.quote(dataset)}")["splits"]
    sp = next((s for s in splits if s["split"] == "train"), splits[0])
    info = _get_json(f"{ROWS_API}/size?dataset={urllib.parse.quote(dataset)}")
    total = 0
    for s in info.get("size", {}).get("splits", []):
        if s.get("split") == sp["split"] and s.get("config") == sp["config"]:
            total = s.get("num_rows", 0)
    start = random.Random(seed).randrange(max(1, total - n)) if total > n else 0
    rows = []
    while len(rows) < n:
        length = min(100, n - len(rows))
        url = (f"{ROWS_API}/rows?dataset={urllib.parse.quote(dataset)}&config={urllib.parse.quote(sp['config'])}"
               f"&split={urllib.parse.quote(sp['split'])}&offset={start + len(rows)}&length={length}")
        batch = _get_json(url).get("rows", [])
        if not batch:
            break
        rows += [b["row"] for b in batch]
        progress("download", len(rows), n, f"Downloading emails from {dataset}…")
    return rows


def import_enron(size, progress, seed=3):
    errors = []
    for ds in ENRON_SOURCES:
        try:
            rows = _rows(ds, int(size["docs"] * 1.5), progress, seed)
            docs = emails_to_docs(rows, size["docs"])
            if len(docs) >= min(20, size["docs"]):
                return docs, []
            errors.append(f"{ds}: too few usable emails")
        except Exception as e:
            errors.append(f"{ds}: {e}")
    raise ImportError_("Couldn't download Enron emails. " + "; ".join(errors))


_HDR = re.compile(r"^(message-id|date|from|to|cc|bcc|subject|mime-version|content-type|content-transfer-encoding|x-[\w-]+):.*$", re.I | re.M)


def emails_to_docs(rows, n):
    docs, seen = [], set()
    for r in rows:
        body = _text_field(r)
        subject = str(_pick(r, "subject", "subject_line", default=""))
        sender = _pick(r, "from", "sender", "from_address", default="")
        to = _pick(r, "to", "recipients", "to_addresses", default="")
        cc = _pick(r, "cc", default="")
        date = str(_pick(r, "date", "sent_at", "timestamp", default=""))
        if isinstance(to, list):
            to = ", ".join(map(str, to[:8]))
        if isinstance(cc, list):
            cc = ", ".join(map(str, cc[:8]))
        if not sender:  # raw messages: pull headers out of the text
            m = re.search(r"^from:\s*(.+)$", body, re.I | re.M)
            sender = m.group(1).strip() if m else ""
            m = re.search(r"^to:\s*(.+)$", body, re.I | re.M)
            to = to or (m.group(1).strip() if m else "")
            m = re.search(r"^subject:\s*(.+)$", body, re.I | re.M)
            subject = subject or (m.group(1).strip() if m else "")
            m = re.search(r"^date:\s*(.+)$", body, re.I | re.M)
            date = date or (m.group(1).strip() if m else "")
        clean = _HDR.sub("", body)
        clean = re.split(r"\n-{3,}\s*Original Message|\n-{3,}\s*Forwarded by", clean)[0]
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        if len(clean.split()) < 15:
            continue
        key = clean[:200]
        if key in seen:
            continue
        seen.add(key)
        head = "\n".join(x for x in [f"From: {sender}" if sender else "", f"To: {to}" if to else "",
                                     f"Cc: {cc}" if cc else "", f"Subject: {subject}" if subject else ""] if x)
        words = clean.split()
        if len(words) > 700:
            clean = " ".join(words[:700]) + " …"
        docs.append({"title": subject or f"Email {len(docs) + 1}", "date": date[:25], "text": (head + "\n\n" if head else "") + clean})
        if len(docs) >= n:
            break
    return docs


IMPORTERS = {"multihop-rag": import_multihop, "graphrag-bench": import_graphrag_bench, "enron": import_enron}


def run_import(cat_id, size_id, progress):
    entry = BY_ID[cat_id]
    size = next((s for s in entry["sizes"] if s["id"] == size_id), None) or next(s for s in entry["sizes"] if s["id"] == entry["default"])
    try:
        docs, bench = IMPORTERS[cat_id](size, progress)
    except ImportError_:
        raise
    except urllib.error.HTTPError as e:
        raise ImportError_(f"Hugging Face returned an error ({e.code}). If it says 401 or 403, the dataset may need you to accept its terms on huggingface.co and set HF_TOKEN in .env.")
    except urllib.error.URLError as e:
        raise ImportError_(f"Couldn't reach Hugging Face ({e.reason}). Check your internet connection.")
    if not docs:
        raise ImportError_("The download worked, but no usable documents came out of it.")
    return entry, size, docs, bench
