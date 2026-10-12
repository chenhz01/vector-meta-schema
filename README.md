# vector-meta-schema

A metadata schema, validator, and cross-store migration mapper for vector-database records. Teams ingesting documents into more than one vector store — or migrating between stores — need one place that says which metadata fields are required, which are optional, and how field names map across stores. If your records already validate cleanly and you never switch stores, you do not need this. Confidence: [High ≥80%] that structural validation + key mapping catches the dominant migration failures (missing/ill-typed fields, key-name drift); [Medium] that the bundled profiles match your store's exact SDK. As of 2026-10-11.

<p align="center"><img src="docs/demo.gif" alt="demo" width="720"></p>

## Problem

Vector stores disagree about everything except the idea of a record. One store calls the text field `text`, another `content`, a third `document`. The vector sits in `vector`, `values`, or `embedding`; the payload in `metadata`, `payload`, or `properties`. When a pipeline is ported between stores, records fail silently: text lands in the wrong key, vectors arrive as the wrong dimension, and required fields vanish. The failure is discovered downstream — at retrieval time, weeks later.

## How it works

1. **Schema** — a required/optional field map with types (`str`, `number`, `float_list`, `str_list`, `dict`, `bool`). `vector` fields accept a flat list of numbers or a matrix; per-record dimension can be pinned with `--dim`.
2. **Validator** — every JSONL record is checked: missing required fields, wrong types, booleans masquerading as numbers, dimension mismatch. `--strict` promotes unknown fields to errors; `--unique-id` (v0.1.1) reports duplicate ids.
3. **Migration mapper** — a profile table (generic, qdrant, pinecone, weaviate, chroma) renames the four role keys (id/vector/text/metadata-container) per store. Fields unknown to both profiles are preserved inside the destination metadata container, so nothing is dropped on the floor.

Exit codes follow CI discipline: `0` clean, `1` violations found, `2` input or usage error.

## Quickstart (~1 min total)

```bash
# 1. Validate records (≈1 s)
python vector_meta_schema.py validate --in records.jsonl --dim 384 --strict --unique-id

# 2. Migrate records generic -> pinecone (≈1 s)
python vector_meta_schema.py migrate --in records.jsonl --from generic --to pinecone --out out.jsonl

# 3. List store profiles (instant)
python vector_meta_schema.py profiles
```

Run the full self-test suite: `python self_test.py` — 63 cases, ~10 s [Measured, repro: `python self_test.py`].

## How this differs

No direct equivalent found as of 2026-10-11 (precheck across 58 domains x 2 queries found no open repo combining a metadata schema + validator + cross-store migration mapping for vector records). Nearest adjacent tools:

| Alternative | What it does | How this differs |
|---|---|---|
| Vector-store SDK validators (e.g. qdrant-client, pinecone client) | Validate *one* store's wire format at client level | Store-specific and partial; no required-field schema across stores, no migration mapping |
| `jsonschema` (general JSON Schema validator) | Generic structural validation of any JSON | Knows nothing about vector semantics: dimensions, vector-vs-matrix, store key profiles |
| etl/ORM mapping layers (e.g. langchain Document converters) | Convert document objects per framework | Binds you to a framework's object model; no standalone validator or exit-code discipline for CI |

## Minimal Fallback (PLAN B)

No Python? Two grep-level sanity gates give ~70% of the value:

```bash
# every line must have the id and vector keys
grep -cv '"id"' records.jsonl            # must print 0
grep -cv '"vector"' records.jsonl        # must print 0
```

Any non-zero count is a record missing a required key. This cannot check types or dimensions — it only proves presence.

## Design Trade-offs

Priority order when rules conflict: **data preservation > structural correctness > determinism > vendor fidelity**. Concretely: (1) migration never drops unknown fields — they are funneled into the destination metadata container, even if that means a slightly wider payload; (2) validation is structural only — no embedding-model calls, no semantic checks; (3) mapping is a pure function of the profile table, so the same input always yields the same output; (4) profiles describe documented key conventions structurally, and we do not claim SDK-exact fidelity for every store version.

## Limits & Second-order Effects

- Profiles cover 4 key roles; stores with nested or per-collection key config (e.g. named vectors) are out of scope.
- Structural validation cannot catch a *semantically* wrong vector (right shape, wrong model's output).
- Second-order: a green validation report can create **gate complacency** — teams may skip end-to-end retrieval smoke tests; the mapper's metadata-container funnel can **hide field-name debt** instead of forcing cleanup; and a stable schema can ossify into an **accidental contract**, making later field additions politically expensive.

## FAQ

**Why JSONL and not JSON arrays?** Streaming-friendly and line-recoverable: one corrupt line is reported by line number instead of failing the whole file.

**Is `--strict` the default?** No. Unknown fields are legal by default because real pipelines attach extras; strict mode is an opt-in gate for contract enforcement.

**Does migrate rewrite vector values?** Never. It renames keys only; values pass through untouched.

**When NOT to use this tool?**
1. You use exactly one store, forever, with SDK-level validation already in place.
2. You need semantic validation (is this chunk relevant?) — this is structural only.
3. Your store uses named/multi vectors or collection-scoped schemas beyond the 4-role model.
4. You want automatic schema *inference* from data — this validates against a declared schema, it does not discover one.

## Core Assumptions

1. **Container-shaped stores.** Every profiled store exposes the four roles as top-level keys of a record object. [Medium]
2. **Presence beats inference.** Teams want declared required fields, not statistically inferred schemas; hence no inference mode. [High ≥80%]
3. **Key-name drift is the dominant migration failure**, ahead of type drift; hence the mapper exists at all. [Medium]
4. **JSONL is the exchange format** for bulk record movement between stores. [Medium]

## Contact

Issues and feedback: hcac4735@agent.qq.com

---

Part of the [zhengming-toolbox](https://github.com/chenhz01/zhengming-toolbox) — 55 purpose-built AI-engineering tools across neglected niches.

Related tools: [llm-gateway-spec](https://github.com/chenhz01/llm-gateway-spec) · [system-prompt-audit](https://github.com/chenhz01/system-prompt-audit) · [rag-chunk-bench](https://github.com/chenhz01/rag-chunk-bench)
