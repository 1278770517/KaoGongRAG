# Frontend workbench implementation plan

**Goal:** Implement the user-approved temporary Vue testing frontend in `font/`.
**Architecture:** One app shell with import, search and question views. Shared typed HTTP helpers and response panel. Direct connection to configurable API origin; use existing backend CORS.
**Tech stack:** Existing Vue 3, TypeScript, Vite, Tailwind; no additional runtime dependencies.
**Spec:** User-confirmed layout and `docs/frontend-api-contract.md`, with `docs/openapi.snapshot.json` for request parameters.

- [x] Implement and check HTTP errors, URL handling and explicit OCR/import success gates.
- [x] Build PDF upload/OCR and separate user-triggered indexing, with long request timeouts and no automatic POST retries.
- [x] Build search, review-mode detail, asset display and raw response inspection.
- [x] Apply white/light-gray/blue visual direction, responsive navigation and accessible form/status feedback.
- [x] Run type checking/build, focused request helper tests and browser checks where available.

Validation: seven helper tests pass; Vue type checking and Vite production build pass. Browser verified desktop navigation, 390px responsive width, invalid API-origin validation and failed health feedback. Live backend connection failed; no actual OCR or indexing write was triggered.

Review focus: partial OCR failure must block indexing; pending/running must not appear successful; review permission errors must be visible; question options must not duplicate the question text; backend changes must not apply stale results to a new connection. Never claim health of the live backend from mocked tests.
