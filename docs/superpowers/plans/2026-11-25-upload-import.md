# Two-stage PDF import

User authorizes two API endpoints and real first-ten-page OCR test. Do not modify pdf_ocr, main.py, dependency files or other-chat changes. New modules and this chat's rag_service may be changed.

- Upload endpoint streams PDF to unique output workspace with size/type validation, invokes pdf_ocr.async_converter.convert_pdf_async and AsyncOCRClient unchanged, returns output directory, markdown paths and partial failures.
- Index endpoint accepts output-contained OCR directory or its markdown path, reads MD as text authority with manifest/page/image provenance, validates complete selected page range, constructs parent/chunks/assets, stages durable job, indexes only that job, returns actual status/count. Reject traversal and incomplete data rather than silently import.
- Use async clients, bounded concurrency and worker-thread file operations, cancellation and explicit deadlines. No cache. Preserve existing data and never overwrite same-name upload.
- Tests first for upload/MD parsing/path scope/partial failure/job isolation. Real OCR first10pages only, then indexing and retrieval/image checks. Existing parser unsupported formats/long text must fail clearly.

Decision: direct awaited two-step endpoints for initial local service; no misleading in-process durable queue. Long requests require client timeout; future task API separate work. Uploaded output includes manifest/layout/page images, not arbitrary unrelated standalone Markdown.
