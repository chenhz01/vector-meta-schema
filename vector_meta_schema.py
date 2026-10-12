#!/usr/bin/env python3
"""vector-meta-schema: metadata schema + validator + cross-store migration mapping for vector stores.

Pure stdlib. Exit codes: 0 = pass, 1 = violations found, 2 = input/usage error.
"""
import argparse
import fnmatch
import json
import sys

SPEC_VERSION = "1.0.0"

# Key-name profiles for popular vector stores (structural mapping of public
# documentation; not affiliated with any vendor).
PROFILES = {
    "generic":   {"id_key": "id", "vector_key": "vector", "text_key": "text", "metadata_key": "metadata"},
    "qdrant":    {"id_key": "id", "vector_key": "vector", "text_key": "text", "metadata_key": "payload"},
    "pinecone":  {"id_key": "id", "vector_key": "values", "text_key": "text", "metadata_key": "metadata"},
    "weaviate":  {"id_key": "id", "vector_key": "vector", "text_key": "content", "metadata_key": "properties"},
    "chroma":    {"id_key": "id", "vector_key": "embedding", "text_key": "document", "metadata_key": "metadata"},
}

TYPE_CHECKS = {
    "str": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "float_list": lambda v: isinstance(v, list) and len(v) > 0
                         and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v),
    "str_list": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    "dict": lambda v: isinstance(v, dict),
    "bool": lambda v: isinstance(v, bool),
}

DEFAULT_SCHEMA = {
    "required": {"id": "str", "vector": "float_list", "text": "str"},
    "optional": {
        "source": "str", "created_at": "str", "tags": "str_list",
        "score": "number", "tenant": "str", "metadata": "dict",
    },
}


def load_schema(path):
    """Load a user schema from JSON, or return DEFAULT_SCHEMA when path is None."""
    if path is None:
        return json.loads(json.dumps(DEFAULT_SCHEMA))
    with open(path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    if not isinstance(schema, dict) or "required" not in schema:
        raise ValueError("schema must be an object with a 'required' mapping")
    return schema


def _is_list_of_lists_of_numbers(v):
    return isinstance(v, list) and len(v) > 0 and all(TYPE_CHECKS["float_list"](row) for row in v)


def validate_record(record, schema, expected_dim=None, strict=False):
    """Validate one record. Returns a list of error dicts: {field, code, detail}."""
    errs = []
    if not isinstance(record, dict):
        return [{"field": "", "code": "not_object", "detail": "record must be a JSON object"}]

    known = dict(schema.get("required", {}))
    known.update(schema.get("optional", {}))

    for field, typ in schema.get("required", {}).items():
        if field not in record:
            errs.append({"field": field, "code": "missing_required", "detail": "required field absent"})
        else:
            errs.extend(_check_type(record[field], field, typ, expected_dim))

    for field, typ in schema.get("optional", {}).items():
        if field in record:
            errs.extend(_check_type(record[field], field, typ, expected_dim))

    for field in record:
        if field not in known:
            if strict:
                errs.append({"field": field, "code": "unknown_field_strict",
                             "detail": "field not in schema (strict mode)"})
    return errs


def _check_type(value, field, typ, expected_dim):
    errs = []
    if typ == "vector" or typ == "float_list":
        ok = TYPE_CHECKS["float_list"](value) or _is_list_of_lists_of_numbers(value)
        if not ok:
            errs.append({"field": field, "code": "bad_type",
                         "detail": "expected non-empty list of numbers (or matrix)"})
            return errs
        rows = value if _is_list_of_lists_of_numbers(value) else [value]
        for row in rows:
            if expected_dim is not None and len(row) != expected_dim:
                errs.append({"field": field, "code": "dim_mismatch",
                             "detail": "vector dim %d != expected %d" % (len(row), expected_dim)})
                break
        return errs
    checker = TYPE_CHECKS.get(typ)
    if checker is None:
        errs.append({"field": field, "code": "bad_schema_type", "detail": "unknown schema type %r" % typ})
    elif not checker(value):
        errs.append({"field": field, "code": "bad_type", "detail": "expected %s" % typ})
    return errs


def map_record(record, src, dst):
    """Rename top-level keys when moving a record from store profile src to dst.

    Unknown non-profile keys are preserved verbatim inside the destination
    metadata container when both stores use a metadata container, otherwise
    they are kept at top level.
    """
    if src not in PROFILES:
        raise KeyError("unknown source profile: %s" % src)
    if dst not in PROFILES:
        raise KeyError("unknown destination profile: %s" % dst)
    sp, dp = PROFILES[src], PROFILES[dst]
    out = {}
    known_src = {}
    for role in ("id_key", "vector_key", "text_key", "metadata_key"):
        known_src[sp[role]] = role
    role_values = {}
    passthrough = {}
    for k, v in record.items():
        role = known_src.get(k)
        if role:
            role_values[role] = v
        else:
            passthrough[k] = v
    for role in ("id_key", "vector_key", "text_key", "metadata_key"):
        if role in role_values:
            out[dp[role]] = role_values[role]
    if passthrough:
        # Documented v0.1.0 semantics: unknown top-level fields are preserved
        # inside the destination metadata container.
        meta = out.get(dp["metadata_key"])
        if not isinstance(meta, dict):
            meta = {}
        else:
            meta = dict(meta)
        meta.update(passthrough)
        out[dp["metadata_key"]] = meta
    return out


def load_records(path):
    """Load JSONL records. Raises ValueError with line number on corrupt input."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError("line %d: invalid JSON (%s)" % (lineno, exc.msg))
    return records


def find_duplicate_ids(records):
    """v0.1.1: return sorted list of ids appearing on more than one record."""
    seen, dups = set(), set()
    for rec in records:
        rid = rec.get("id") if isinstance(rec, dict) else None
        if isinstance(rid, str):
            if rid in seen:
                dups.add(rid)
            seen.add(rid)
    return sorted(dups)


def validate_file(path, schema_path=None, expected_dim=None, strict=False, unique_ids=False):
    records = load_records(path)
    schema = load_schema(schema_path)
    report = {"file": path, "total": len(records), "invalid": 0, "errors": []}
    for i, rec in enumerate(records):
        errs = validate_record(rec, schema, expected_dim=expected_dim, strict=strict)
        if errs:
            report["invalid"] += 1
            report["errors"].append({"index": i, "record_errors": errs})
    if unique_ids:
        for rid in find_duplicate_ids(records):
            report["invalid"] += 1
            report["errors"].append({"index": None, "record_errors": [
                {"field": "id", "code": "duplicate_id", "detail": "id %r appears more than once" % rid}]})
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vector-meta-schema",
                                 description="Vector-store metadata schema validator + migration mapper")
    sub = ap.add_subparsers(dest="cmd")
    pv = sub.add_parser("validate", help="validate a JSONL file of records")
    pv.add_argument("--in", dest="inp", required=True)
    pv.add_argument("--schema", default=None)
    pv.add_argument("--dim", type=int, default=None)
    pv.add_argument("--strict", action="store_true", help="unknown fields become errors")
    pv.add_argument("--unique-id", action="store_true", help="v0.1.1: duplicate ids become errors")
    pm = sub.add_parser("migrate", help="map records between store profiles")
    pm.add_argument("--in", dest="inp", required=True)
    pm.add_argument("--from", dest="src", required=True)
    pm.add_argument("--to", dest="dst", required=True)
    pm.add_argument("--out", required=True)
    sub.add_parser("profiles", help="list known store profiles")

    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help(sys.stderr)
        return 2
    try:
        if args.cmd == "profiles":
            for name, p in sorted(PROFILES.items()):
                print("%s: id=%s vector=%s text=%s metadata=%s"
                      % (name, p["id_key"], p["vector_key"], p["text_key"], p["metadata_key"]))
            return 0
        if args.cmd == "validate":
            report = validate_file(args.inp, args.schema, args.dim, args.strict, args.unique_id)
            print(json.dumps({k: v for k, v in report.items() if k != "errors"}))
            for e in report["errors"][:20]:
                print("ERR", json.dumps(e, ensure_ascii=False))
            return 1 if report["invalid"] else 0
        if args.cmd == "migrate":
            records = load_records(args.inp)
            with open(args.out, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(map_record(rec, args.src, args.dst), ensure_ascii=False) + "\n")
            print("migrated %d records %s -> %s" % (len(records), args.src, args.dst))
            return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
