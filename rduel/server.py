"""The web server: serves the page and a small JSON API."""
import json

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import config, pipeline
from .pipeline import Dataset

WEB = config.ROOT / "web"


def ok(data, status=200):
    return JSONResponse(data, status_code=status)


def fail(msg, status=400):
    return JSONResponse({"error": msg}, status_code=status)


def guarded(fn):
    async def wrapper(request):
        try:
            return await fn(request)
        except (ValueError, FileNotFoundError) as e:
            return fail(str(e))
        except PermissionError as e:
            return fail(str(e), 403)
        except Exception as e:  # show the real reason in the page
            import traceback
            traceback.print_exc()
            msg = str(e)
            if "authentication" in msg.lower() or "api key" in msg.lower() or "401" in msg:
                msg = "Claude rejected the API key. Check ANTHROPIC_API_KEY in your .env file."
            return fail(msg, 500)
    return wrapper


LOCAL_ONLY = ("The hosted demo only runs the Larkspur Gazette. To import public datasets or your own files, "
              "run Retrieval Duel on your computer: " + config.REPO_URL)


def _local_only():
    if config.PUBLIC_DEMO:
        raise PermissionError(LOCAL_ONLY)


def _ds(request):
    slug = request.path_params["slug"]
    ds = Dataset(slug)
    if not ds.meta:  # a fresh serverless copy may not have set up the demo yet
        pipeline.ensure_demo(force=True)
        ds = Dataset(slug)
    if not ds.meta:
        raise ValueError(f"No dataset called {slug}.")
    return ds


async def index(request):
    return FileResponse(WEB / "index.html")


@guarded
async def status(request):
    return ok({"has_key": config.has_key(), "fake": config.FAKE_LLM, "public": config.PUBLIC_DEMO, "repo": config.REPO_URL, "work_model": config.WORK_MODEL,
               "answer_model": config.ANSWER_MODEL, "top_k": config.TOP_K, "hops": config.GRAPH_HOPS})


@guarded
async def datasets(request):
    if request.method == "POST":
        _local_only()
        body = await request.json()
        out = await run_in_threadpool(pipeline.create_dataset, body.get("name", "My dataset"), body.get("description", ""),
                                      body.get("files", []), int(body.get("chunk_words", 120)))
        return ok(out)
    return ok(await run_in_threadpool(pipeline.list_datasets))


@guarded
async def catalog(request):
    if request.method == "POST":
        _local_only()
        b = await request.json()
        job = pipeline.start_import(b.get("id"), b.get("size"))
        return ok({k: v for k, v in job.items() if k != "events"})
    return ok(await run_in_threadpool(pipeline.catalog_list))


@guarded
async def dataset(request):
    ds = _ds(request)
    if request.method == "DELETE":
        _local_only()
        pipeline.delete_dataset(ds.slug)
        return ok({"deleted": ds.slug})
    return ok(ds.summary())


@guarded
async def estimate(request):
    return ok(await run_in_threadpool(pipeline.estimate, _ds(request).slug))


@guarded
async def start_index(request):
    _local_only()
    job = pipeline.start_index(_ds(request).slug)
    return ok({k: v for k, v in job.items() if k != "events"})


@guarded
async def job(request):
    j = pipeline.JOBS.get(request.path_params["job"])
    if not j:
        return fail("No such job.", 404)
    since = int(request.query_params.get("since", 0))
    out = {k: v for k, v in j.items() if k != "events"}
    out["events"] = j["events"][since:]
    out["event_count"] = len(j["events"])
    return ok(out)


@guarded
async def viz(request):
    ds = _ds(request)

    def build():
        if ds.meta.get("demo") and not (ds.folder / "vectors.npy").exists():
            pipeline.build_demo_indexes(ds)
        g = ds.graph
        vv = json.loads((ds.folder / "vector_viz.json").read_text(encoding="utf-8"))
        deg = {}
        for r in g["relations"]:
            deg[r["s"]] = deg.get(r["s"], 0) + 1
            deg[r["t"]] = deg.get(r["t"], 0) + 1
        return {
            "docs": [{"id": d["id"], "title": d.get("title", ""), "date": d.get("date", "")} for d in ds.docs],
            "chunks": [{"id": c["id"], "doc": c["doc"], "title": c["title"], "date": c.get("date", ""), "text": c["text"]} for c in ds.chunks],
            "vector": vv,
            "entities": [{"id": e["id"], "name": e["name"], "type": e["type"], "c": e.get("c", "misc"), "desc": e["desc"],
                          "docs": e["docs"], "deg": deg.get(e["id"], 0)} for e in g["entities"]],
            "relations": [{"s": r["s"], "t": r["t"], "rel": r["rel"], "doc": r["doc"]} for r in g["relations"]],
            "communities": [{k: c.get(k) for k in ("id", "title", "summary", "color", "members")} for c in g["communities"]],
            "stats": ds.meta.get("stats"), "meta": ds.summary(),
        }

    if ds.meta.get("status") not in ("ready",) and not ds.meta.get("demo"):
        return fail("This dataset hasn't been indexed yet.")
    return ok(await run_in_threadpool(build))


@guarded
async def documents(request):
    ds = _ds(request)
    return ok(ds.docs)


@guarded
async def question_list(request):
    ds = _ds(request)
    from .questions import TYPE_INFO
    return ok({"questions": ds.questions, "types": TYPE_INFO})


@guarded
async def ask(request):
    ds = _ds(request)
    body = await request.json()
    q = (body.get("question") or "").strip()
    if not q:
        return fail("Type a question first.")
    return ok(await run_in_threadpool(pipeline.ask, ds.slug, q, body.get("sample_id"), bool(body.get("fresh"))))


@guarded
async def results(request):
    return ok(pipeline.saved_results(_ds(request).slug))


@guarded
async def votes(request):
    ds = _ds(request)
    if config.PUBLIC_DEMO:  # votes stay in each visitor's browser
        return ok({})
    if request.method == "POST":
        b = await request.json()
        return ok(pipeline.record_vote(ds.slug, b.get("qid"), b.get("question", ""), b.get("vote"), b.get("grades")))
    if request.method == "DELETE":
        pipeline.clear_votes(ds.slug)
        return ok({})
    return ok(pipeline.get_votes(ds.slug))


routes = [
    Route("/", index),
    Route("/api/status", status),
    Route("/api/datasets", datasets, methods=["GET", "POST"]),
    Route("/api/catalog", catalog, methods=["GET", "POST"]),
    Route("/api/datasets/{slug}", dataset, methods=["GET", "DELETE"]),
    Route("/api/datasets/{slug}/estimate", estimate),
    Route("/api/datasets/{slug}/index", start_index, methods=["POST"]),
    Route("/api/datasets/{slug}/viz", viz),
    Route("/api/datasets/{slug}/documents", documents),
    Route("/api/datasets/{slug}/questions", question_list),
    Route("/api/datasets/{slug}/ask", ask, methods=["POST"]),
    Route("/api/datasets/{slug}/results", results),
    Route("/api/datasets/{slug}/votes", votes, methods=["GET", "POST", "DELETE"]),
    Route("/api/jobs/{job}", job),
    Mount("/static", StaticFiles(directory=WEB), name="static"),
]

app = Starlette(routes=routes)
pipeline.ensure_demo()  # set up the demo as soon as this copy of the app starts
