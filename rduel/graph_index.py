"""GraphRAG: build a knowledge graph with Claude, detect communities, search by walking the graph."""
import json
import re
from collections import Counter, defaultdict

import networkx as nx
import numpy as np

from . import config, llm
from .embed import load_embedder
from .textutil import approx_tokens, tokens

ENTITY_TYPES = ["person", "organization", "place", "event", "project", "document", "product", "concept"]

EXTRACT_SYSTEM = """You build knowledge graphs from documents.
Read the text and list the important named things in it, and how they relate.

Return JSON only, in this shape:
{"entities": [{"name": "...", "type": "...", "description": "..."}],
 "relations": [{"source": "...", "relation": "...", "target": "..."}]}

Rules:
- type is one of: person, organization, place, event, project, document, product, concept.
- Use each entity's fullest name as it appears (e.g. "Felix Arden", not "Arden").
- description: one short sentence about the entity, based only on this text.
- relation: a short verb phrase, like "chairs", "funds", "is sister of", "would be built at".
- source and target must be names from your entities list.
- Only include what the text states. At most 25 entities and 30 relations."""


def _windows(text, max_words=900):
    words = text.split()
    if len(words) <= max_words:
        return [text]
    out = []
    for i in range(0, len(words), max_words - 100):
        out.append(" ".join(words[i:i + max_words]))
    return out


def extraction_units(docs):
    units = []
    for d in docs:
        for k, w in enumerate(_windows(d["text"])):
            units.append({"doc": d["id"], "title": d.get("title", ""), "text": w, "part": k})
    return units


def extract_unit(unit, meter):
    user = f"Title: {unit['title']}\n\nText:\n{unit['text']}"
    try:
        data = llm.complete_json(EXTRACT_SYSTEM, user, task="extract", max_tokens=8000, meter=meter)
    except ValueError:
        return {"entities": [], "relations": [], "warning": "unreadable reply"}
    ents = [e for e in data.get("entities") or [] if isinstance(e, dict) and e.get("name")]
    rels = [r for r in data.get("relations") or [] if isinstance(r, dict) and r.get("source") and r.get("target")]
    return {"entities": ents, "relations": rels}


# ---------------- entity resolution ----------------
_TITLES = re.compile(r"^(dr|mr|mrs|ms|prof|sir|the|councilor|keeper|librarian|chair)\s+")


def norm(name):
    n = re.sub(r"[^a-z0-9 ]+", " ", name.lower()).strip()
    n = re.sub(r"\s+", " ", n)
    prev = None
    while prev != n:
        prev, n = n, _TITLES.sub("", n)
    return n


def resolve(raw):
    """Merge entities that are the same thing under slightly different names.

    raw: list of (doc_id, extraction) pairs. Returns entities, relations.
    """
    groups = defaultdict(lambda: {"names": Counter(), "types": Counter(), "descs": [], "docs": set()})
    for doc, ex in raw:
        for e in ex["entities"]:
            key = norm(e["name"])
            if not key:
                continue
            g = groups[key]
            g["names"][e["name"].strip()] += 1
            g["types"][str(e.get("type", "concept")).lower()] += 1
            if e.get("description"):
                g["descs"].append(e["description"].strip())
            g["docs"].add(doc)

    # Merge one-word names ("Arden") into a unique longer name containing that word ("Felix Arden").
    keys = list(groups)
    alias_of = {}
    for k in keys:
        if " " in k:
            continue
        cands = [o for o in keys if o != k and " " in o and k in o.split()
                 and groups[o]["types"].most_common(1)[0][0] == groups[k]["types"].most_common(1)[0][0]]
        if len(cands) == 1:
            alias_of[k] = cands[0]
    for k, target in alias_of.items():
        g, t = groups[k], groups[target]
        t["names"].update(g["names"]); t["types"].update(g["types"]); t["descs"] += g["descs"]; t["docs"] |= g["docs"]
        del groups[k]

    entities, key_to_id = [], {}
    for i, (k, g) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]["docs"]))):
        name = max(g["names"], key=lambda n: (g["names"][n], len(n)))
        descs = list(dict.fromkeys(g["descs"]))
        desc = " ".join(descs[:2])[:320]
        eid = f"e{i}"
        key_to_id[k] = eid
        aliases = sorted({norm(n) for n in g["names"]} | {k})
        entities.append({"id": eid, "name": name, "type": g["types"].most_common(1)[0][0], "desc": desc,
                         "aliases": aliases, "docs": sorted(g["docs"])})
    for k, target in alias_of.items():
        key_to_id[k] = key_to_id[target]

    relations, seen = [], set()
    for doc, ex in raw:
        for r in ex["relations"]:
            s, t = key_to_id.get(norm(r["source"])), key_to_id.get(norm(r["target"]))
            rel = str(r.get("relation", "relates to")).strip()[:60] or "relates to"
            if not s or not t or s == t:
                continue
            sig = (s, rel.lower(), t)
            if sig in seen:
                continue
            seen.add(sig)
            relations.append({"s": s, "rel": rel, "t": t, "doc": doc})
    return entities, relations


# ---------------- communities ----------------
SUMMARY_SYSTEM = """You summarize one cluster of a knowledge graph for a reader who hasn't seen the documents.
Return JSON only: {"title": "2 to 4 word name for this cluster", "summary": "2 to 4 sentences: who and what is involved, and what is going on between them"}.
Use only the facts given."""

COMMUNITY_COLORS = ["#ff8a5c", "#5ce1c6", "#b49cff", "#ffd166", "#7ee081", "#ff7eb6", "#6cb8ff", "#f5a3ff",
                    "#c2e86a", "#ffb38a", "#8fe3ff", "#d6b98a"]


def detect_communities(entities, relations, max_communities=12):
    g = nx.Graph()
    g.add_nodes_from(e["id"] for e in entities)
    for r in relations:
        w = g.get_edge_data(r["s"], r["t"], {}).get("weight", 0)
        g.add_edge(r["s"], r["t"], weight=w + 1)
    if g.number_of_edges() == 0:
        return [{"id": "c0", "members": [e["id"] for e in entities]}]
    comms = nx.community.louvain_communities(g, weight="weight", seed=42)
    comms = sorted(comms, key=len, reverse=True)
    out, misc = [], []
    for c in comms:
        if len(c) >= 2 and len(out) < max_communities:
            out.append({"id": f"c{len(out)}", "members": sorted(c)})
        else:
            misc.extend(c)
    if misc:
        out.append({"id": "misc", "members": sorted(misc)})
    return out


def summarize_community(comm, ebyid, relations, meter):
    members = set(comm["members"])
    lines = [f"- {ebyid[m]['name']} ({ebyid[m]['type']}): {ebyid[m]['desc']}" for m in comm["members"][:40]]
    facts = [f"- {ebyid[r['s']]['name']} {r['rel']} {ebyid[r['t']]['name']}" for r in relations
             if r["s"] in members and r["t"] in members][:60]
    user = "Entities:\n" + "\n".join(lines) + "\n\nRelationships:\n" + ("\n".join(facts) or "- (none)")
    try:
        data = llm.complete_json(SUMMARY_SYSTEM, user, task="summarize", max_tokens=800, meter=meter)
        return str(data.get("title", "Cluster"))[:40], str(data.get("summary", ""))
    except (ValueError, AttributeError, llm.EmptyReply):
        return "Cluster", ""


# ---------------- search ----------------
class GraphIndex:
    def __init__(self, folder, linking="names+embeddings"):
        g = json.loads((folder / "graph.json").read_text(encoding="utf-8"))
        self.entities, self.relations, self.communities = g["entities"], g["relations"], g["communities"]
        self.byid = {e["id"]: e for e in self.entities}
        self.linking = linking
        self.ent_vecs = self.rel_vecs = None
        emb_path = folder / "embedder.json"
        if (folder / "entity_vectors.npy").exists() and emb_path.exists():
            self.ent_vecs = np.load(folder / "entity_vectors.npy")
            self.rel_vecs = np.load(folder / "relation_vectors.npy")
            self.emb = load_embedder(json.loads(emb_path.read_text(encoding="utf-8")))
        self.adj = defaultdict(list)
        for i, r in enumerate(self.relations):
            self.adj[r["s"]].append(i)
            self.adj[r["t"]].append(i)

    def rel_text(self, r):
        return f"{self.byid[r['s']]['name']} {r['rel']} {self.byid[r['t']]['name']}"

    def link(self, question):
        ql = " " + norm(question) + " "
        qt = set(tokens(question))
        seeds = {}
        for e in self.entities:
            for a in e["aliases"]:
                if len(a) >= 3 and f" {a} " in ql:
                    seeds[e["id"]] = "named"
                    break
        if self.linking == "names":
            # description overlap: the question describes the entity without naming it
            for e in self.entities:
                if e["id"] not in seeds and len(qt & set(tokens(e["name"] + " " + e["desc"]))) >= 3:
                    seeds[e["id"]] = "described"
        elif self.ent_vecs is not None and len(self.ent_vecs):
            q = self.emb.embed([question])[0]
            sims = self.ent_vecs @ q
            thresh = 0.62 if getattr(self.emb, "semantic", False) else 0.3
            for i in np.argsort(-sims)[:3]:
                eid = self.entities[int(i)]["id"]
                if sims[i] >= thresh and eid not in seeds:
                    seeds[eid] = "similar"
        return [{"id": k, "how": v, "name": self.byid[k]["name"]} for k, v in seeds.items()]

    def find_entities(self, names):
        """Match names the agent chose (e.g. "Harbor Council") to graph entities."""
        out = []
        for name in names or []:
            n = norm(str(name))
            if not n:
                continue
            hit = next((e for e in self.entities if n in e["aliases"] or n == norm(e["name"])), None)
            if not hit:
                hit = next((e for e in self.entities if len(n) >= 4 and (n in norm(e["name"]) or norm(e["name"]) in n)), None)
            if hit and hit["id"] not in [o["id"] for o in out]:
                out.append({"id": hit["id"], "how": "chosen", "name": hit["name"]})
        return out

    def local_search(self, question, seeds=None):
        seeds = self.link(question) if seeds is None else seeds
        if not seeds:
            return {"mode": "local", "seeds": [], "hops": [], "nodes": [], "facts": [], "key_facts": [],
                    "context": "", "context_tokens": 0}
        dist = {s["id"]: 0 for s in seeds}
        frontier = list(dist)
        used = {}
        for h in range(1, config.GRAPH_HOPS + 1):
            nxt = []
            for n in frontier:
                for ri in self.adj[n]:
                    r = self.relations[ri]
                    other = r["t"] if r["s"] == n else r["s"]
                    used.setdefault(ri, h)
                    if other not in dist:
                        dist[other] = h
                        nxt.append(other)
            frontier = nxt
            if not frontier:
                break
        # rank facts by relevance to the question, keep the best
        ids = list(used)
        if self.rel_vecs is not None and len(ids) and self.linking != "names":
            q = self.emb.embed([question])[0]
            rel = self.rel_vecs[ids] @ q
        else:
            qt = set(tokens(question))
            rel = np.array([len(qt & set(tokens(self.rel_text(self.relations[i])))) / 5 for i in ids])
        seed_ids = {s["id"] for s in seeds}
        score = {ri: float(rel[k]) + (0.15 if (self.relations[ri]["s"] in seed_ids or self.relations[ri]["t"] in seed_ids) else 0)
                 - 0.05 * (used[ri] - 1) for k, ri in enumerate(ids)}
        kept = sorted(ids, key=lambda ri: -score[ri])[:config.GRAPH_MAX_FACTS]
        nodes = set(seed_ids)
        for ri in kept:
            nodes.add(self.relations[ri]["s"]); nodes.add(self.relations[ri]["t"])
        hops = []
        for h in range(1, config.GRAPH_HOPS + 1):
            hops.append({"edges": [ri for ri in kept if used[ri] == h],
                         "nodes": [n for n in nodes if dist.get(n) == h]})
        facts = [{"i": ri, "text": self.rel_text(self.relations[ri]), "doc": self.relations[ri]["doc"],
                  "hop": used[ri], "score": round(score[ri], 3)} for ri in kept]
        key = [f["i"] for f in facts[:3]]
        ent_lines = [f"{self.byid[n]['name']}: {self.byid[n]['desc']}" for n in sorted(nodes, key=lambda n: dist.get(n, 9))][:40]
        context = "Entities:\n" + "\n".join(ent_lines) + "\n\nFacts:\n" + "\n".join(f["text"] for f in facts)
        return {"mode": "local", "seeds": seeds, "hops": hops, "nodes": sorted(nodes), "facts": facts,
                "key_facts": key, "context": context, "context_tokens": approx_tokens(context)}

    def global_search(self, question):
        comms = [c for c in self.communities if c.get("summary")]
        context = "\n\n".join(f"[{c['title']}] {c['summary']}" for c in comms)
        return {"mode": "global", "seeds": [], "communities": [c["id"] for c in comms],
                "summaries": [{"id": c["id"], "title": c["title"], "summary": c["summary"], "color": c["color"]} for c in comms],
                "context": context, "context_tokens": approx_tokens(context)}
