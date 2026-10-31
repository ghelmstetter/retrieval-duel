"""Vector RAG: embed passages, find the nearest ones to a question."""
import json

import numpy as np

from . import config
from .embed import load_embedder, make_embedder
from .textutil import approx_tokens, tokens


def build(chunks, folder, progress=lambda *a: None, backend=None):
    emb = make_embedder(backend)
    texts = [c["text"] for c in chunks]
    emb.fit(texts)
    vecs = []
    step = 32
    for i in range(0, len(texts), step):
        vecs.append(emb.embed(texts[i:i + step]))
        progress("embed", min(len(texts), i + step), len(texts))
    mat = np.vstack(vecs) if vecs else np.zeros((0, 1), dtype=np.float32)
    np.save(folder / "vectors.npy", mat)
    (folder / "embedder.json").write_text(json.dumps(emb.state()), encoding="utf-8")

    # 2D map for display: PCA for starting positions, plus each passage's nearest neighbors.
    coords = _pca2(mat)
    sims = mat @ mat.T if len(mat) else np.zeros((0, 0))
    seen, links = set(), []
    for i in range(len(mat)):
        order = [j for j in np.argsort(-sims[i]) if j != i][:3]
        for j in order:
            key = (min(i, int(j)), max(i, int(j)))
            if key not in seen:
                seen.add(key)
                links.append([key[0], key[1], round(float(sims[i, j]), 3)])
    # passages from the same document stay together
    for a in range(len(chunks) - 1):
        if chunks[a]["doc"] == chunks[a + 1]["doc"] and (a, a + 1) not in seen:
            links.append([a, a + 1, 0.5])
    viz = {"coords": coords.tolist(), "links": links, "embedder": emb.kind, "semantic": emb.semantic}
    (folder / "vector_viz.json").write_text(json.dumps(viz), encoding="utf-8")
    return viz


def _pca2(mat):
    if len(mat) < 3:
        return np.zeros((len(mat), 2))
    x = mat - mat.mean(axis=0)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    return x @ vt[:2].T


class VectorIndex:
    def __init__(self, folder, chunks):
        self.chunks = chunks
        self.mat = np.load(folder / "vectors.npy")
        self.emb = load_embedder(json.loads((folder / "embedder.json").read_text(encoding="utf-8")))

    def search(self, question, k=None):
        k = k or config.TOP_K
        q = self.emb.embed([question])[0]
        scores = self.mat @ q
        order = np.argsort(-scores)[:k]
        qt = set(tokens(question))
        hits = []
        for i in order:
            if scores[i] <= 0:
                continue
            c = self.chunks[int(i)]
            hits.append({"chunk": c["id"], "index": int(i), "score": round(float(scores[i]), 3),
                         "text": c["text"], "title": c["title"], "date": c.get("date", ""),
                         "shared": sorted(qt & set(tokens(c["text"])))})
        context = "\n\n".join(f"[{h['title']}] {h['text']}" for h in hits)
        return {"hits": hits, "context": context, "context_tokens": approx_tokens(context),
                "query_terms": sorted(qt)}
