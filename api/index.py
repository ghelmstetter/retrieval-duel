"""Vercel entry point for the hosted demo.

Vercel runs this as a Python serverless function. It serves the JSON API in public-demo
mode: only the Larkspur Gazette, no uploads or indexing, and no calls to Claude.
The page itself (web/) is served as static files; see vercel.json.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("RDUEL_PUBLIC_DEMO", "1")
os.environ.setdefault("RDUEL_DATA_DIR", "/tmp/rduel")  # the only writable folder on Vercel

from rduel.server import app  # noqa: E402  (Vercel looks for a variable named `app`)
