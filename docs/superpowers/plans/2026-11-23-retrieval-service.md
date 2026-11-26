# Retrieval service implementation plan

Spec: ../specs/2026-11-23-retrieval-service-design.md. User approved execution and supplied PostgreSQL localhost:5432/postgres, postgres user, POSTGRES_PASSWORD in .env.

Use superpowers subagent-driven-development; preserve current uncommitted work and legacy CLI. No cache or full PDF OCR.

- [ ] Implement rag_service configuration, async PostgreSQL repository, content-addressed image assets and ingestion CLI. Test provenance, idempotency, missing pages, image path safety and partial failure. Persist jobs and use short transactions without external I/O locks.
- [ ] Implement async embedding/Milvus adapters and retrieval service with bounded concurrency, timeout, cancellation, single-lane degradation, RRF and batch parent lookup. Test mapping and version/status filtering.
- [ ] Implement FastAPI lifespan, search/detail/assets/health APIs, local-only review mode, and docs. Test API errors, image roundtrip and no answer leakage in question view.
- [ ] Run full tests, lint, real five-page ingestion and searches including images. Review and fix findings. Record blockers honestly, do not publish or push.

Decisions: use existing checkout to preserve authorized prerequisite changes. No extra production infrastructure. Tokenizer identity must be verified; do not mislabel Qwen open weights tokenizer as exact Bailian tokenizer. Default published-only queries; explicit local development review mode needed for unreviewed sample.
