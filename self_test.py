#!/usr/bin/env python3
"""self_test for vector-meta-schema. Tiers: [A] functional, [B] exception/CLI, [C] extreme edges."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vector_meta_schema as vms  # noqa: E402

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))


def write_jsonl(path, records_or_lines):
    with open(path, "w", encoding="utf-8") as f:
        for x in records_or_lines:
            f.write(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False))
            f.write("\n")
    return path


def run_cli(args):
    return subprocess.run([sys.executable, os.path.join(HERE, "vector_meta_schema.py")] + args,
                          capture_output=True, text=True)


def raises(exc_type, fn, *args, **kw):
    try:
        fn(*args, **kw)
        return False
    except exc_type:
        return True


def deep_meta(levels):
    node = {"leaf": 1}
    for _ in range(levels):
        node = {"n": node}
    return node


TMP = tempfile.mkdtemp(prefix="vms_selftest_")


def p(name):
    return os.path.join(TMP, name)


GOOD = {"id": "r1", "vector": [0.1, 0.2, 0.3], "text": "hello", "tags": ["a"], "score": 1.5}

# ---------------- [A] functional ----------------
check("A01 good record passes", vms.validate_record(dict(GOOD), vms.DEFAULT_SCHEMA) == [])
check("A02 missing id detected", any(e["code"] == "missing_required" and e["field"] == "id"
                                     for e in vms.validate_record({"vector": [1.0], "text": "x"}, vms.DEFAULT_SCHEMA)))
check("A03 missing vector detected", any(e["field"] == "vector" for e in vms.validate_record(
    {"id": "x", "text": "x"}, vms.DEFAULT_SCHEMA)))
check("A04 missing text detected", any(e["field"] == "text" for e in vms.validate_record(
    {"id": "x", "vector": [1.0]}, vms.DEFAULT_SCHEMA)))
check("A05 vector of strings rejected", any(e["code"] == "bad_type" for e in vms.validate_record(
    {"id": "x", "vector": ["a"], "text": "t"}, vms.DEFAULT_SCHEMA)))
check("A06 numeric id rejected", any(e["code"] == "bad_type" for e in vms.validate_record(
    {"id": 5, "vector": [1.0], "text": "t"}, vms.DEFAULT_SCHEMA)))
check("A07 bool in vector rejected", any(e["code"] == "bad_type" for e in vms.validate_record(
    {"id": "x", "vector": [True], "text": "t"}, vms.DEFAULT_SCHEMA)))
check("A08 bool score rejected (number excludes bool)", any(e["code"] == "bad_type" for e in vms.validate_record(
    {"id": "x", "vector": [1.0], "text": "t", "score": True}, vms.DEFAULT_SCHEMA)))
check("A09 optional tags list ok", vms.validate_record(dict(GOOD, tags=["x", "y"]), vms.DEFAULT_SCHEMA) == [])
check("A10 optional tags wrong type", any(e["field"] == "tags" for e in vms.validate_record(
    dict(GOOD, tags="notalist"), vms.DEFAULT_SCHEMA)))
check("A11 unknown field allowed non-strict", vms.validate_record(dict(GOOD, extra=1), vms.DEFAULT_SCHEMA) == [])
check("A12 unknown field errors in strict", any(e["code"] == "unknown_field_strict" for e in vms.validate_record(
    dict(GOOD, extra=1), vms.DEFAULT_SCHEMA, strict=True)))
check("A13 dim match ok", vms.validate_record(GOOD, vms.DEFAULT_SCHEMA, expected_dim=3) == [])
check("A14 dim mismatch detected", any(e["code"] == "dim_mismatch" for e in vms.validate_record(
    GOOD, vms.DEFAULT_SCHEMA, expected_dim=768)))
check("A15 map generic->pinecone renames vector key",
      "values" in vms.map_record(GOOD, "generic", "pinecone"))
check("A16 map generic->qdrant renames metadata key",
      "payload" in vms.map_record(dict(GOOD, metadata={"a": 1}), "generic", "qdrant"))
check("A17 migrate roundtrip keeps vector",
      vms.map_record(vms.map_record(GOOD, "generic", "chroma"), "chroma", "generic")["vector"] == GOOD["vector"])
check("A18 weaviate text key is content",
      vms.PROFILES["weaviate"]["text_key"] == "content" and
      "content" in vms.map_record(GOOD, "generic", "weaviate"))
check("A19 all profiles have 4 roles", all(set(v.keys()) == {"id_key", "vector_key", "text_key", "metadata_key"}
                                           for v in vms.PROFILES.values()))
check("A20 file validate clean", vms.validate_file(
    write_jsonl(p("ok.jsonl"), [GOOD, dict(GOOD, id="r2")]))["invalid"] == 0)

# ---------------- [B] exception / CLI paths ----------------
def _exc(exc_type, fn, *args):
    try:
        fn(*args)
    except exc_type as exc:
        return exc
    return None


def corrupt_file():
    path = p("corrupt.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(GOOD) + "\n{not json\n")
    return path


check("B01 corrupt jsonl raises with line number",
      raises(ValueError, vms.load_records, corrupt_file()) and
      "line 2" in str(_exc(ValueError, vms.load_records, corrupt_file())))


check("B02 missing file raises OSError", raises(OSError, vms.load_records, p("nope.jsonl")))
check("B03 unknown src profile raises", raises(KeyError, vms.map_record, {}, "bogus", "generic"))
check("B04 unknown dst profile raises", raises(KeyError, vms.map_record, {}, "generic", "bogus"))
_badschema = p("badschema.json")
with open(_badschema, "w", encoding="utf-8") as _f:
    _f.write("[1,2,3]")
check("B05 bad schema file rejected", raises(ValueError, vms.load_schema, _badschema))
check("B06 CLI validate clean returns 0", run_cli(["validate", "--in", p("ok.jsonl")]).returncode == 0)
check("B07 CLI validate bad record returns 1",
      run_cli(["validate", "--in", write_jsonl(p("bad.jsonl"), [{"id": "x"}])]).returncode == 1)
check("B08 CLI validate missing file returns 2",
      run_cli(["validate", "--in", p("missing.jsonl")]).returncode == 2)
check("B09 CLI migrate writes output file", run_cli(
    ["migrate", "--in", p("ok.jsonl"), "--from", "generic", "--to", "pinecone", "--out", p("out.jsonl")]
).returncode == 0 and os.path.exists(p("out.jsonl")))
check("B10 CLI migrate unknown profile returns 2", run_cli(
    ["migrate", "--in", p("ok.jsonl"), "--from", "generic", "--to", "nope", "--out", p("o2.jsonl")]
).returncode == 2)
check("B11 CLI no subcommand returns 2", run_cli([]).returncode == 2)
check("B12 CLI profiles lists 5 stores",
      sum(1 for ln in run_cli(["profiles"]).stdout.splitlines() if ln.strip()) == 5)

# ---------------- [C] extreme edges ----------------
check("C01 empty object record -> 3 required errors",
      len(vms.validate_record({}, vms.DEFAULT_SCHEMA)) == 3)
check("C02 non-object record flagged", any(e["code"] == "not_object" for e in vms.validate_record(
    [1, 2, 3], vms.DEFAULT_SCHEMA)))
check("C03 empty file yields zero invalid", vms.validate_file(
    write_jsonl(p("empty.jsonl"), []))["invalid"] == 0)
LONG = "x" * 200000
check("C04 200k-char text ok", vms.validate_record(dict(GOOD, text=LONG), vms.DEFAULT_SCHEMA) == [])
check("C05 unicode text + tags ok", vms.validate_record(
    dict(GOOD, text="向量数据库→メタデータ", tags=["中文", "ελληνικά"]), vms.DEFAULT_SCHEMA) == [])
check("C06 deep nested metadata (300 levels) ok",
      vms.validate_record(dict(GOOD, metadata=deep_meta(300)), vms.DEFAULT_SCHEMA) == [])
check("C07 10k-dim vector ok", vms.validate_record(
    dict(GOOD, vector=[0.5] * 10000), vms.DEFAULT_SCHEMA, expected_dim=10000) == [])
check("C08 10k-dim vector mismatch caught", any(e["code"] == "dim_mismatch" for e in vms.validate_record(
    dict(GOOD, vector=[0.5] * 10000), vms.DEFAULT_SCHEMA, expected_dim=3)))
check("C09 vector as matrix accepted", vms.validate_record(
    dict(GOOD, vector=[[0.1, 0.2], [0.3, 0.4]]), vms.DEFAULT_SCHEMA) == [])
check("C10 blank lines in jsonl skipped",
      len(vms.load_records(write_jsonl(p("blank.jsonl"),
          [json.dumps(GOOD), "", json.dumps(dict(GOOD, id="r3"))]))) == 2)
check("C11 1000 unknown fields non-strict ok",
      vms.validate_record(dict(GOOD, **{"f%d" % i: i for i in range(1000)}), vms.DEFAULT_SCHEMA) == [])
check("C12 1000 unknown fields strict all flagged",
      len([e for e in vms.validate_record(dict(GOOD, **{"f%d" % i: i for i in range(1000)}),
                                          vms.DEFAULT_SCHEMA, strict=True)
           if e["code"] == "unknown_field_strict"]) == 1000)
check("C13 null vector rejected", any(e["code"] == "bad_type" for e in vms.validate_record(
    {"id": "x", "vector": None, "text": "t"}, vms.DEFAULT_SCHEMA)))
check("C14 empty vector list rejected", any(e["code"] == "bad_type" for e in vms.validate_record(
    {"id": "x", "vector": [], "text": "t"}, vms.DEFAULT_SCHEMA)))
check("C15 duplicate ids pass structural validation",
      vms.validate_file(write_jsonl(p("dup.jsonl"), [GOOD, dict(GOOD)]))["invalid"] == 0)
check("C16 unicode roundtrip through migrate",
      vms.map_record(dict(GOOD, text="检索→保存"), "generic", "chroma")["document"] == "检索→保存")
check("C17 over-nested vector rejected",
      any(e["code"] == "bad_type" for e in vms.validate_record(
          {"id": "x", "vector": [[[1.0]]], "text": "t"}, vms.DEFAULT_SCHEMA)))
check("C18 migrate preserves unknown fields into metadata",
      vms.map_record(dict(GOOD, custom_field="keep"), "generic", "qdrant")["payload"]["custom_field"] == "keep")
check("C19 CLI handles unicode record exit 0", run_cli(
    ["validate", "--in", write_jsonl(p("uni.jsonl"), [{"id": "u", "vector": [1.0], "text": "段落→分句"}])]
).returncode == 0)
check("C20 huge scalar score accepted", vms.validate_record(
    dict(GOOD, score=1e308), vms.DEFAULT_SCHEMA) == [])

# ---------------- [R2] round-2 block (v0.1.1: duplicate-id gate + custom schema) ----------------
check("R01 duplicate ids detected", vms.find_duplicate_ids(
    [GOOD, dict(GOOD), dict(GOOD, id="z")]) == ["r1"])
check("R02 no duplicates returns empty", vms.find_duplicate_ids([GOOD, dict(GOOD, id="z")]) == [])
check("R03 duplicate detection ignores non-dict records",
      vms.find_duplicate_ids([GOOD, [1], "x", dict(GOOD)]) == ["r1"])
check("R04 duplicate detection ignores non-string ids",
      vms.find_duplicate_ids([{"id": 1}, {"id": 1}]) == [])
check("R05 validate_file unique_ids flags file", vms.validate_file(
    write_jsonl(p("dup2.jsonl"), [GOOD, dict(GOOD)]), unique_ids=True)["invalid"] == 1)
check("R06 unique-id clean file stays clean", vms.validate_file(
    write_jsonl(p("uniq.jsonl"), [GOOD, dict(GOOD, id="z")]), unique_ids=True)["invalid"] == 0)
check("R07 CLI --unique-id exit 1 on duplicates", run_cli(
    ["validate", "--in", p("dup2.jsonl"), "--unique-id"]).returncode == 1)
check("R08 CLI --unique-id exit 0 clean", run_cli(
    ["validate", "--in", p("uniq.jsonl"), "--unique-id"]).returncode == 0)
_custom = p("custom.json")
with open(_custom, "w", encoding="utf-8") as _f:
    json.dump({"required": {"id": "str", "vector": "float_list"},
               "optional": {"lang": "str"}}, _f)
check("R09 custom schema loads and validates", vms.validate_file(
    write_jsonl(p("csr.jsonl"), [{"id": "a", "vector": [1.0], "lang": "en"}]),
    schema_path=_custom)["invalid"] == 0)
check("R10 custom schema flags missing vector", vms.validate_file(
    write_jsonl(p("csb.jsonl"), [{"id": "a", "text": "extra"}]), schema_path=_custom)["invalid"] == 1)
check("R11 unknown schema type name is reported", any(
    e["code"] == "bad_schema_type" for e in vms.validate_record(
        {"id": "x"}, {"required": {"id": "float128"}})))


def main():
    passed = sum(1 for _, ok in RESULTS if ok)
    total = len(RESULTS)
    for n, ok in RESULTS:
        if not ok:
            print("FAIL:", n)
    print("SUMMARY: PASS %d/%d" % (passed, total))
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
