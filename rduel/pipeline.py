"""Datasets, the indexing job, and asking a question of all three contestants."""
import json
import re
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import config, graph_index, llm, qa, questions, vector_index
from .embed import load_embedder
from .textutil import approx_tokens, chunk_document

JOBS = {}
_LOCK = threading.Lock()


def _read(p, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _write(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------- datasets ----------------
def ensure_demo():
    """Copy the bundled demo datasets into the data folder the first time the app runs."""
    config.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    if not config.DEMO_DIR.exists():
        return
    for src in config.DEMO_DIR.iterdir():
        if not src.is_dir():
            continue
        dst = config.DATASETS_DIR / src.name
        if not dst.exists():
            shutil.copytree(src, dst)
            continue
        # After an update (git pull), refresh the bundled files; rebuild derived indexes if the data changed.
        changed = False
        for f in src.iterdir():
            target = dst / f.name
            if f.name == "meta.json":  # keep the locally computed stats
                old = _read(target, {})
                new = {**_read(f), **({"stats": old["stats"]} if "stats" in old else {})}
                if new != old:
                    _write(target, new)
                continue
            if not target.exists() or target.read_bytes() != f.read_bytes():
                shutil.copy2(f, target)
                changed = changed or f.name in ("docs.json", "graph.json")
        if changed:
            for name in ("vectors.npy", "embedder.json", "vector_viz.json", "chunks.json", "entity_vectors.npy", "relation_vectors.npy"):
                (dst / name).unlink(missing_ok=True)


class Dataset:
    def __init__(self, slug):
        self.slug = slug
        self.folder = config.DATASETS_DIR / slug
        self.meta = _read(self.folder / "meta.json", {})
        self._v = self._g = None

    @property
    def docs(self):
        return _read(self.folder / "docs.json", [])

    @property
    def chunks(self):
        return _read(self.folder / "chunks.json", [])

    @property
    def graph(self):
        return _read(self.folder / "graph.json")

    @property
    def questions(self):
        return _read(self.folder / "questions.json", [])

    def save_meta(self):
        _write(self.folder / "meta.json", self.meta)

    def vindex(self):
        if self._v is None:
            self._v = vector_index.VectorIndex(self.folder, self.chunks)
        return self._v

    def gindex(self):
        if self._g is None:
            self._g = graph_index.GraphIndex(self.folder, self.meta.get("linking", "names+embeddings"))
        return self._g

    def summary(self):
        m = dict(self.meta)
        m["slug"] = self.slug
        return m


def list_datasets():
    ensure_demo()
    out = []
    for p in sorted(config.DATASETS_DIR.iterdir()):
        if (p / "meta.json").exists():
            out.append(Dataset(p.name).summary())
    out.sort(key=lambda m: (not m.get("demo"), m.get("created", 0)))
    return out


def create_dataset(name, description, files, chunk_words=120):
    from .textutil import read_upload
    docs = []
    for f in files:
        for d in read_upload(f["name"], f["content"], f.get("encoding", "text")):
            if d["text"].strip():
                d["id"] = f"d{len(docs) + 1}"
                docs.append(d)
    if not docs:
        raise ValueError("None of those files contained readable text.")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "dataset"
    base, n = slug, 2
    while (config.DATASETS_DIR / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    folder = config.DATASETS_DIR / slug
    folder.mkdir(parents=True)
    _write(folder / "docs.json", docs)
    ds = Dataset(slug)
    ds.meta = {"name": name, "description": description or f"{len(docs)} documents you uploaded.",
               "created": time.time(), "status": "new", "chunk_words": chunk_words,
               "linking": "names+embeddings", "demo": False, "doc_count": len(docs)}
    ds.save_meta()
    return ds.summary()


def catalog_list():
    from . import catalog
    imported = {}
    for p in config.DATASETS_DIR.iterdir():
        m = _read(p / "meta.json", {})
        if m.get("catalog"):
            imported[m["catalog"]] = p.name
    return [{**c, "imported": imported.get(c["id"])} for c in catalog.CATALOG]


def start_import(cat_id, size_id):
    from . import catalog
    if cat_id not in catalog.BY_ID:
        raise ValueError("Unknown dataset.")
    job_id = uuid.uuid4().hex[:10]
    job = {"id": job_id, "kind": "import", "dataset": None, "status": "running", "stage": "download", "done": 0, "total": 1,
           "message": "Contacting Hugging Face…", "entities": 0, "relations": 0, "communities": 0, "meter": {}, "error": None, "events": []}
    JOBS[job_id] = job

    def progress(stage, done, total, message=""):
        with _LOCK:
            job.update(stage=stage, done=done, total=total)
            if message:
                job["message"] = message

    def run():
        try:
            entry, size, docs, bench = catalog.run_import(cat_id, size_id, progress)
            for i, d in enumerate(docs):
                d["id"] = f"d{i + 1}"
            slug = cat_id
            n = 2
            while (config.DATASETS_DIR / slug).exists():
                slug, n = f"{cat_id}-{n}", n + 1
            folder = config.DATASETS_DIR / slug
            folder.mkdir(parents=True)
            _write(folder / "docs.json", docs)
            _write(folder / "benchmark.json", bench)
            ds = Dataset(slug)
            desc = f"{entry['description']} Sample: {size['label'].split(':')[-1].strip()}"
            if bench:
                desc += f", with {len(bench)} of the dataset's own questions."
            ds.meta = {"name": entry["name"], "description": desc, "created": time.time(), "status": "new",
                       "chunk_words": 150 if cat_id == "graphrag-bench" else 120, "linking": "names+embeddings",
                       "demo": False, "doc_count": len(docs), "catalog": cat_id, "size": size["id"], "source": entry["source"],
                       "license": entry["license"]}
            ds.save_meta()
            with _LOCK:
                job.update(status="done", stage="done", dataset=slug, message=f"Imported {len(docs)} documents.")
        except Exception as e:
            traceback.print_exc()
            with _LOCK:
                job.update(status="error", error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return job


def delete_dataset(slug):
    ds = Dataset(slug)
    if ds.meta.get("demo"):
        raise ValueError("The demo dataset can't be deleted.")
    shutil.rmtree(ds.folder)


def estimate(slug):
    ds = Dataset(slug)
    docs = ds.docs
    words = sum(len(d["text"].split()) for d in docs)
    units = graph_index.extraction_units(docs)
    unit_tokens = [approx_tokens(u["text"]) for u in units]
    ext_in = sum(t + 450 for t in unit_tokens)
    ext_out = sum(min(1800, int(t * 0.7) + 150) for t in unit_tokens)
    est_entities = max(4, int(sum(unit_tokens) / 60))
    est_comms = min(12, max(1, est_entities // 8))
    sum_in, sum_out = est_comms * 900, est_comms * 180
    q_in, q_out = 8 * 700 + 4 * 400, 8 * 200
    work_in, work_out = ext_in + sum_in + q_in, ext_out + sum_out + q_out
    dollars = llm.estimate_dollars(config.WORK_MODEL, work_in, work_out)
    est_chunks = max(len(docs), int(words / max(30, ds.meta.get("chunk_words", 120) * 0.85)))
    embed_tokens = int(words * 1.3)
    per_q = llm.estimate_dollars(config.ANSWER_MODEL, 3 * 1500, 3 * 180) + llm.estimate_dollars(config.WORK_MODEL, 4 * 400, 4 * 60)
    return {"docs": len(docs), "words": words, "chunks_est": est_chunks, "extraction_calls": len(units),
            "summary_calls_est": est_comms, "graph_tokens_est": work_in + work_out, "vector_tokens_est": embed_tokens,
            "dollars_est": round(dollars, 3), "dollars_per_question_est": round(per_q, 4),
            "budget": config.MAX_INDEX_DOLLARS, "has_key": config.has_key(),
            "work_model": config.WORK_MODEL, "answer_model": config.ANSWER_MODEL}


# ---------------- indexing ----------------
def start_index(slug):
    ds = Dataset(slug)
    if not config.has_key():
        raise ValueError("Building a knowledge graph needs Claude. Add ANTHROPIC_API_KEY to your .env file and restart.")
    job_id = uuid.uuid4().hex[:10]
    job = {"id": job_id, "dataset": slug, "status": "running", "stage": "chunk", "done": 0, "total": 0,
           "message": "Starting…", "entities": 0, "relations": 0, "communities": 0, "meter": {}, "error": None,
           "events": []}
    JOBS[job_id] = job
    threading.Thread(target=_run_index, args=(ds, job), daemon=True).start()
    return job


def _run_index(ds, job):
    meter = llm.Meter(budget_dollars=config.MAX_INDEX_DOLLARS)

    def progress(stage, done, total, message=""):
        with _LOCK:
            job.update(stage=stage, done=done, total=total, meter=meter.as_dict())
            if message:
                job["message"] = message

    try:
        ds.meta["status"] = "indexing"; ds.save_meta()
        docs = ds.docs
        # 1. chunk
        progress("chunk", 0, len(docs), "Cutting documents into passages…")
        chunks = []
        for d in docs:
            chunks += chunk_document(d, ds.meta.get("chunk_words", 120), ds.meta.get("overlap", 1))
        _write(ds.folder / "chunks.json", chunks)
        progress("chunk", len(docs), len(docs), f"{len(chunks)} passages.")

        # 2. vector index
        vector_index.build(chunks, ds.folder, lambda s, d, t: progress("embed", d, t, "Embedding passages…"),
                           backend=ds.meta.get("embed"))

        # 3. graph extraction, a few documents at a time
        units = graph_index.extraction_units(docs)
        results = [None] * len(units)
        done = [0]

        def work(i):
            if meter.over_budget():
                raise llm.BudgetExceeded(f"Stopped: indexing passed the ${config.MAX_INDEX_DOLLARS:.2f} budget set in .env.")
            results[i] = graph_index.extract_unit(units[i], meter)
            with _LOCK:
                done[0] += 1
                job["entities"] += len(results[i]["entities"])
                job["relations"] += len(results[i]["relations"])
                job["events"].append({"doc": units[i]["doc"], "title": units[i]["title"],
                                      "entities": len(results[i]["entities"]), "relations": len(results[i]["relations"])})
            progress("extract", done[0], len(units), f"AI reading \"{units[i]['title'][:60]}\"")

        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(work, range(len(units))))

        # 4. merge duplicates, find communities, summarize them
        progress("resolve", 0, 1, "Merging duplicate names…")
        entities, relations = graph_index.resolve([(u["doc"], r) for u, r in zip(units, results)])
        with _LOCK:
            job["entities"], job["relations"] = len(entities), len(relations)
        comms = graph_index.detect_communities(entities, relations)
        ebyid = {e["id"]: e for e in entities}
        for k, c in enumerate(comms):
            c["color"] = "#8fa0bd" if c["id"] == "misc" else graph_index.COMMUNITY_COLORS[k % len(graph_index.COMMUNITY_COLORS)]
            for m in c["members"]:
                ebyid[m]["c"] = c["id"]
        to_sum = [c for c in comms if c["id"] != "misc"]
        sdone = [0]

        def summ(c):
            c["title"], c["summary"] = graph_index.summarize_community(c, ebyid, relations, meter)
            with _LOCK:
                sdone[0] += 1
                job["communities"] = sdone[0]
            progress("summarize", sdone[0], len(to_sum), f"Summarizing community \"{c['title']}\"")

        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(summ, to_sum))
        for c in comms:
            if c["id"] == "misc":
                c["title"], c["summary"] = "Loose ends", ""
        graph = {"entities": entities, "relations": relations, "communities": comms}
        _write(ds.folder / "graph.json", graph)
        _embed_graph(ds.folder, graph)

        # 5. test questions
        ds._v = ds._g = None
        qs = questions.generate(docs, chunks, graph, ds.vindex(), meter,
                                lambda s, d, t, m="": progress("questions", d, t, "Writing test questions: " + m))
        bench = questions.benchmark_entries(_read(ds.folder / "benchmark.json", []))
        _write(ds.folder / "questions.json", bench + qs)

        ds.meta.update(status="ready", indexed=time.time(), stats=_stats(ds), index_cost=meter.as_dict())
        ds.save_meta()
        with _LOCK:
            job.update(status="done", stage="done", message="Both indexes are ready.", meter=meter.as_dict())
    except Exception as e:  # report any failure to the page
        traceback.print_exc()
        ds.meta["status"] = "error"; ds.meta["error"] = str(e); ds.save_meta()
        with _LOCK:
            job.update(status="error", error=str(e), meter=meter.as_dict())


def _embed_graph(folder, graph):
    emb = load_embedder(_read(folder / "embedder.json"))
    byid = {e["id"]: e for e in graph["entities"]}
    ents = [f"{e['name']}: {e['desc']}" for e in graph["entities"]] or [""]
    rels = [f"{byid[r['s']]['name']} {r['rel']} {byid[r['t']]['name']}" for r in graph["relations"]] or [""]
    np.save(folder / "entity_vectors.npy", emb.embed(ents))
    np.save(folder / "relation_vectors.npy", emb.embed(rels))


def build_demo_indexes(ds):
    """The demo ships with its graph prebuilt; only the (free, local) vector side is built here."""
    chunks = []
    for d in ds.docs:
        chunks += chunk_document(d, ds.meta.get("chunk_words", 120), ds.meta.get("overlap", 1))
    _write(ds.folder / "chunks.json", chunks)
    vector_index.build(chunks, ds.folder, backend=ds.meta.get("embed"))
    _embed_graph(ds.folder, ds.graph)
    ds.meta["stats"] = _stats(ds)
    ds.save_meta()
    ds._v = ds._g = None


def _stats(ds):
    g, chunks, docs = ds.graph, ds.chunks, ds.docs
    ents, rels = g["entities"], g["relations"]
    multi = sum(1 for e in ents if len(e["docs"]) >= 2)
    nums = set()
    for c in chunks:
        nums |= set(re.findall(r"\b\d[\d,.:]*\b", c["text"]))
    graph_text = " ".join(e["name"] + " " + e["desc"] for e in ents) + " " + " ".join(r["rel"] for r in rels)
    kept = sum(1 for n in nums if re.search(r"\b" + re.escape(n) + r"\b", graph_text))
    return {"docs": len(docs), "chunks": len(chunks), "entities": len(ents), "relations": len(rels),
            "communities": len([c for c in g["communities"] if c["id"] != "misc"]),
            "pct_multi_doc": round(100 * multi / max(1, len(ents))), "avg_degree": round(2 * len(rels) / max(1, len(ents)), 1),
            "numbers": len(nums), "numbers_kept": kept,
            "vector_tokens": sum(approx_tokens(c["text"]) for c in chunks)}


# ---------------- asking ----------------
def ask(slug, question, sample_id=None):
    ds = Dataset(slug)
    if not (ds.folder / "vectors.npy").exists():
        if ds.meta.get("demo"):
            build_demo_indexes(ds)
        else:
            raise ValueError("This dataset hasn't been indexed yet.")
    meter = llm.Meter()
    sample = next((q for q in ds.questions if q["id"] == sample_id), None) if sample_id else None
    if sample is None:
        sample = next((q for q in ds.questions if q["q"].strip().lower() == question.strip().lower()), None)

    t0 = time.time()
    v = ds.vindex().search(question, ds.meta.get("top_k"))
    t_vec = time.time() - t0
    gi = ds.gindex()
    seeds = gi.link(question)
    live = config.has_key()
    rt = qa.route(question, bool(seeds), use_llm=live, meter=meter)
    t1 = time.time()
    g = gi.global_search(question) if rt.get("type") == "big_picture" else gi.local_search(question)
    t_graph = time.time() - t1

    if sample and sample.get("path") and g["mode"] == "local" and g.get("facts"):
        _apply_path(gi, g, sample["path"])
    merged = f"Passages:\n{v['context']}\n\n{g['context']}" if rt["route"] == "both" else (v["context"] if rt["route"] == "vector" else g["context"])
    hy_tokens = approx_tokens(merged) + 40

    result = {"question": question, "sample": sample, "route": rt, "live": live,
              "vector": {**v, "latency": None}, "graph": {**g, "latency": None},
              "hybrid": {"route": rt["route"], "context_tokens": hy_tokens, "latency": None}}

    if live:
        jobs = {
            "vector": lambda: qa.answer(question, "passages found by vector search", v["context"], meter),
            "graph": lambda: qa.answer(question, "community summaries" if g["mode"] == "global" else "facts from a knowledge graph", g["context"], meter),
            "hybrid": lambda: qa.answer(question, "merged search results", merged, meter),
        }
        times = {}

        def run(name):
            s = time.time()
            out = jobs[name]()
            times[name] = time.time() - s
            return name, out

        with ThreadPoolExecutor(max_workers=3) as ex:
            for name, out in ex.map(run, list(jobs)):
                result[name]["answer"] = out
        result["vector"]["latency"] = round(t_vec + times["vector"], 2)
        result["graph"]["latency"] = round(t_graph + times["graph"], 2)
        result["hybrid"]["latency"] = round(max(t_vec, t_graph) + times["hybrid"], 2)
        if sample and sample.get("answer"):
            with ThreadPoolExecutor(max_workers=3) as ex:
                grades = list(ex.map(lambda n: qa.judge(question, sample["answer"], result[n]["answer"], meter), ["vector", "graph", "hybrid"]))
            for n, gr in zip(["vector", "graph", "hybrid"], grades):
                result[n]["grade"] = gr
    elif sample and sample.get("canned"):
        c = sample["canned"]
        for n in ("vector", "graph", "hybrid"):
            result[n]["answer"] = c[n]
            result[n]["grade"] = {"grade": "correct" if c[n + "_ok"] else "wrong", "why": "Pre-graded for the demo."}
        result["canned"] = True
    else:
        for n in ("vector", "graph", "hybrid"):
            result[n]["answer"] = None
    if not live:  # typical values so the meters still show something
        result["vector"]["latency"] = round(0.4 + v["context_tokens"] / 2000, 1)
        result["graph"]["latency"] = round(3.2 if g["mode"] == "global" else (0.9 + g["context_tokens"] / 900 if g.get("seeds") else 0.3), 1)
        result["hybrid"]["latency"] = round(0.3 + max(result["vector"]["latency"], result["graph"]["latency"]), 1)
        result["estimated_latency"] = True
    result["meter"] = meter.as_dict()
    return result


def _apply_path(gi, g, path):
    """Highlight the facts along a known reasoning path (used by the hand-made demo questions)."""
    pairs = {frozenset(p) for p in zip(path, path[1:])}
    pairs |= {frozenset((path[0], x)) for x in path[1:]} if len(path) > 2 else set()
    key = [f["i"] for f in g["facts"] if frozenset((gi.relations[f["i"]]["s"], gi.relations[f["i"]]["t"])) in pairs]
    if key:
        g["key_facts"] = key
        g["facts"].sort(key=lambda f: f["i"] not in key)


def record_vote(slug, qid, question, vote, grades=None):
    ds = Dataset(slug)
    path = ds.folder / "votes.json"
    votes = _read(path, {})
    votes[qid or question] = {"q": question, "vote": vote, "grades": grades or {}, "t": time.time()}
    _write(path, votes)
    return votes


def get_votes(slug):
    return _read(Dataset(slug).folder / "votes.json", {})


def clear_votes(slug):
    p = Dataset(slug).folder / "votes.json"
    if p.exists():
        p.unlink()
