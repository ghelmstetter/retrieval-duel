"""Tests for parsing JSON out of model replies, including cut-off replies.  Run: python -m tests.test_llm_json"""
import json
from rduel.llm import parse_json

full = {"entities": [{"name": f"Person {i}", "type": "person", "description": "A person, with \"quotes\" and [brackets]."} for i in range(20)],
        "relations": [{"source": "Person 1", "relation": "knows", "target": f"Person {i}"} for i in range(2, 20)]}
s = json.dumps(full, indent=1)

cases = {
    "plain": s,
    "fenced": "Here you go:\n```json\n" + s + "\n```",
    "trailing comma": s.replace('"knows",', '"knows",', 1).replace("\n]\n}", ",\n]\n}"),
    "cut mid-relations": s[: int(len(s) * 0.8)],
    "cut mid-string": s[: s.index("Person 7") + 4],
    "cut in entities": s[: int(len(s) * 0.3)],
    "fenced and cut": "```json\n" + s[: int(len(s) * 0.6)],
}
for name, text in cases.items():
    d = parse_json(text, dict)
    assert isinstance(d, dict) and d.get("entities"), name
    print(f"{name:20} ok: {len(d.get('entities', []))} entities, {len(d.get('relations', []))} relations")

assert isinstance(parse_json('[{"a":1},{"a":2}]', list), list)
try:
    parse_json("no json here", dict); raise SystemExit("should have failed")
except ValueError:
    pass
print("ALL JSON TESTS PASSED")
