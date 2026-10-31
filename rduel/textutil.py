"""Text helpers: tokenizing, sentence splitting, chunking, and reading files."""
import base64
import io
import json
import re

STOP = set("""a an the and or of to in on at for from by with is are was were be been it its this that these those
as do does did which who whom what when where why how about into than then there their his her he she they them our
we you your i me my will would could should can may might not no if so up out over after before all any each more most
some such only own same very just also has have had during until since now every said say says here year years""".split())


def stem(w):
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w


def tokens(s):
    return [stem(w) for w in re.findall(r"[a-z0-9$]+", s.lower()) if w not in STOP and len(w) > 1]


def approx_tokens(s):
    return max(1, len(s) // 4)


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def sentences(text):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    # avoid splitting on common abbreviations
    protected = re.sub(r"\b(Dr|Mr|Mrs|Ms|St|Jr|Sr|Prof|vs|e\.g|i\.e)\.", lambda m: m.group(0).replace(".", "§"), text)
    return [s.replace("§", ".") for s in _SENT.split(protected) if s.strip()]


def chunk_document(doc, max_words=120, overlap_sentences=1):
    """Split a document into passages of up to `max_words`, on sentence boundaries."""
    sents = sentences(doc["text"])
    chunks, cur, cur_words = [], [], 0
    i = 0
    while i < len(sents):
        s = sents[i]
        w = len(s.split())
        if cur and cur_words + w > max_words:
            chunks.append(" ".join(cur))
            cur = cur[-overlap_sentences:] if overlap_sentences and len(cur) > overlap_sentences else []
            cur_words = sum(len(x.split()) for x in cur)
            if cur_words + w > max_words:
                cur, cur_words = [], 0
        cur.append(s)
        cur_words += w
        i += 1
    if cur:
        chunks.append(" ".join(cur))
    return [{"id": f"{doc['id']}.{k}", "doc": doc["id"], "title": doc.get("title", doc["id"]),
             "date": doc.get("date", ""), "text": c} for k, c in enumerate(chunks)]


def read_upload(name, content, encoding="text"):
    """Turn one uploaded file into a list of documents: [{'title', 'text'}]."""
    lower = name.lower()
    if encoding == "base64":
        raw = base64.b64decode(content)
    else:
        raw = content.encode("utf-8") if isinstance(content, str) else content
    if lower.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        return [{"title": name.rsplit(".", 1)[0], "text": text}]
    text = raw.decode("utf-8", errors="replace")
    if lower.endswith(".jsonl"):
        docs = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                docs.append(_record(json.loads(line), name, len(docs)))
        return docs
    if lower.endswith(".json"):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("documents") or data.get("data") or [data]
        return [_record(r, name, i) for i, r in enumerate(data)]
    return [{"title": name.rsplit(".", 1)[0], "text": text}]


def _record(r, name, i):
    if isinstance(r, str):
        return {"title": f"{name} #{i + 1}", "text": r}
    text = r.get("text") or r.get("body") or r.get("content") or r.get("context") or ""
    title = r.get("title") or r.get("subject") or f"{name} #{i + 1}"
    out = {"title": str(title), "text": str(text)}
    if r.get("date") or r.get("published_at"):
        out["date"] = str(r.get("date") or r.get("published_at"))
    return out
