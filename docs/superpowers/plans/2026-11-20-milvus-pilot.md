# Five-page Milvus pilot implementation plan

**Goal:** Import only the five completed OCR pages, per user approval.
**Architecture:** File-backed parent records and reproducible question/evidence chunks; independent Milvus test collection with Chinese BM25 and external dense vectors.
**Tech Stack:** Python, OpenAI-compatible Bailian, pymilvus.
**Spec:** docs/PRD.md section 13; approved five-page scope in chat.

- [ ] Test and implement cross-page parsing, option/answer boundaries, image and final-page quarantine.
- [ ] Persist parents/chunks; validate embedding dimensions, finite values and response mapping.
- [ ] Create isolated collection, test analyzer, insert and verify count and sparse/dense queries.
- [ ] Run repository tests and record actual results and limitations.

Constraints: never modify original OCR or existing collections; no production alias; no automatic approval of OCR content. Preserve raw records in files. Use API-reported token usage, reject oversized input (conservative byte guard), never truncate. Exact local model tokenizer remains a prerequisite for scaling to full-document long chunks.
