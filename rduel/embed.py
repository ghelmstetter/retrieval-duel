"""Embeddings: turn text into vectors.

By default this uses fastembed (a small, free embedding model that runs on your computer).
If fastembed isn't installed, it falls back to TF-IDF word matching, which needs nothing
extra but only matches shared words, not meanings.
"""
import json
import math
from collections import Counter

import numpy as np

from . import config
from .textutil import tokens


class FastEmbedder:
    kind = "fastembed"
    semantic = True

    def __init__(self, model_name=None):
        from fastembed import TextEmbedding
        self.model_name = model_name or config.EMBED_MODEL
        self.model = TextEmbedding(self.model_name)

    def fit(self, texts):
        return self

    def embed(self, texts):
        vecs = np.array(list(self.model.embed(list(texts))), dtype=np.float32)
        return _normalize(vecs)

    def state(self):
        return {"kind": self.kind, "model": self.model_name}


class TfidfEmbedder:
    kind = "tfidf"
    semantic = False

    def __init__(self, vocab=None, idf=None):
        self.vocab = vocab or {}
        self.idf = np.array(idf or [], dtype=np.float32)

    def fit(self, texts, max_vocab=8000):
        df = Counter()
        docs = [set(tokens(t)) for t in texts]
        for d in docs:
            df.update(d)
        words = [w for w, _ in df.most_common(max_vocab)]
        self.vocab = {w: i for i, w in enumerate(words)}
        n = len(texts)
        self.idf = np.array([math.log((n + 1) / (df[w] + 1)) + 1 for w in words], dtype=np.float32)
        return self

    def embed(self, texts):
        out = np.zeros((len(texts), max(1, len(self.vocab))), dtype=np.float32)
        for r, t in enumerate(texts):
            for w, c in Counter(tokens(t)).items():
                j = self.vocab.get(w)
                if j is not None:
                    out[r, j] = (1 + math.log(c)) * self.idf[j]
        return _normalize(out)

    def state(self):
        return {"kind": self.kind, "vocab": self.vocab, "idf": self.idf.tolist()}


def _normalize(m):
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1
    return m / n


def make_embedder(backend=None):
    want = backend or config.EMBED_BACKEND
    if want in ("auto", "fastembed"):
        try:
            return FastEmbedder()
        except Exception as e:  # not installed, or model download failed
            if want == "fastembed":
                raise
            print(f"[embed] fastembed unavailable ({e.__class__.__name__}); using TF-IDF word matching.")
    return TfidfEmbedder()


def load_embedder(state):
    if state["kind"] == "fastembed":
        return FastEmbedder(state.get("model"))
    return TfidfEmbedder(state["vocab"], state["idf"])


def save_state(path, emb):
    path.write_text(json.dumps(emb.state()), encoding="utf-8")
