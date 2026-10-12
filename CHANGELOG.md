# Changelog — vector-meta-schema

All notable changes. Format based on Keep a Changelog; versioning: SemVer.

## [0.1.1] - 2026-10-11

### Added
- `--unique-id` flag and `find_duplicate_ids()`: duplicate record ids are now reported as validation errors (round-2 review finding: duplicate ids were silently accepted, causing silent upsert-merge semantics downstream).
- Custom schema files (`--schema`) are exercised by the self-test suite.

### Changed
- Self-test suite expanded 52 → 63 cases (+21%, round-2 ≥20% improvement gate): [R2] block adds 11 cases covering duplicate-id detection, CLI wiring, and custom-schema loading.
- Round-2 self-review fix: unknown top-level fields are now *always* funneled into the destination metadata container during migration (previously kept top-level when no metadata existed), making preservation deterministic across all profile pairs. Re-run: `SUMMARY: PASS 63/63`.

## [0.1.0] - 2026-10-11

### Added
- Metadata schema (required/optional typed fields) with `validate` command: missing-field, bad-type, bool-as-number, dimension-mismatch, strict-unknown-field checks.
- Cross-store migration mapping (`migrate`) across generic/qdrant/pinecone/weaviate/chroma profiles with unknown-field preservation.
- `profiles` introspection command.
- CLI with CI exit-code discipline (0 clean / 1 violations / 2 input-error).
- Self-test suite: 52 cases across functional, exception/CLI, and extreme-edge tiers (empty/200k-char/unicode/300-deep-nesting/10k-dim).
- MIT LICENSE, README with fallback plan and assumption register.
