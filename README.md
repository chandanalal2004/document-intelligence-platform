# Document Intelligence Platform

AI-powered extraction, validation and API platform for invoices, balance
sheets, P&L statements and cash flow statements. Built for the AI Engineer
Internship technical case study.

## 1. Solution overview & architecture

```
Upload (dashboard or API)
        │
        ▼
[1] Document validation      -> file type / empty / corrupt / page-count checks
        │  (fails fast, returns FAILED + error code)
        ▼
[2] Text extraction / OCR    -> pdftotext for native PDFs
        │                        Tesseract OCR (via pdftoppm rasterization)
        │                        for scanned PDFs and JPG/PNG
        ▼
[3] AI field & table extraction -> LLM call (Groq, OpenAI-compatible) with a
        │                           document-type-aware prompt. Returns every
        │                           meaningful field + line items, each with
        │                           page_number + literal source-text evidence.
        │                           Missing values are null, never invented.
        ▼
[4] Financial validation      -> per-document-type formula checks
        │                          (see "Financial validation rules" below)
        ▼
[5] Persistence                -> stored in SQLite (processed_documents table)
        ▼
[6] Structured JSON response + Dashboard (server-rendered HTML/CSS/JS)
```

Each stage above is a separate service module (`app/services/*`), called in
order by `document_service.py`, which is the only file that knows the
pipeline order. This keeps validation, OCR, extraction, financial checks,
and persistence independently testable and replaceable.

## 2. Technology stack

| Layer | Choice | Why |
|---|---|---|
| API framework | FastAPI | async, automatic OpenAPI/Swagger docs, strong typing via Pydantic |
| Server-rendered frontend | Jinja2 + vanilla HTML/CSS/JS | single deployable service, no separate frontend build/host needed, satisfies "HTML/CSS + JS where required" |
| Database | SQLite via SQLAlchemy | zero-config for a 3-day assessment; SQLAlchemy makes swapping to Postgres a one-line `DATABASE_URL` change |
| Native PDF text | `pdftotext` (poppler-utils) | fast, exact, no OCR error on digitally-authored PDFs |
| OCR | Tesseract (`pytesseract`) + `pdftoppm` rasterization | free, local, no external OCR service dependency/rate limits |
| AI field extraction | Groq API (OpenAI-compatible `/chat/completions`) | fast inference, generous free tier, structured JSON mode |
| Deployment | Render / Railway | free tier, single `web` service serves both API and frontend |

## 3. Local setup

Prerequisites: Python 3.11+, `poppler-utils` and `tesseract-ocr` installed
on the system (Debian/Ubuntu: `sudo apt-get install poppler-utils
tesseract-ocr`).

```bash
git clone <your-repo-url>
cd <repo>/backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp ../.env.example .env
# edit .env and set LLM_API_KEY to your Groq key (console.groq.com/keys)

uvicorn app.main:app --reload
```

Open:
- Dashboard: http://localhost:8000
- Swagger/OpenAPI docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

## 4. Environment variables (`.env.example`)

| Variable | Purpose | Default |
|---|---|---|
| `LLM_API_KEY` | API key for the LLM used in field extraction | *(required)* |
| `LLM_BASE_URL` | OpenAI-compatible base URL | `https://api.groq.com/openai/v1` |
| `LLM_MODEL` | Model name | `llama-3.3-70b-versatile` |
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///./storage/app.db` |
| `UPLOAD_DIR` | Temp storage for in-flight uploads | `./storage/uploads` |
| `MAX_PAGE_COUNT` | Reject documents over this page count | `3` |
| `MAX_FILE_SIZE_MB` | Reject uploads over this size | `15` |
| `NATIVE_TEXT_MIN_CHARS_PER_PAGE` | Threshold below which a PDF is treated as scanned and OCR'd | `40` |
| `CORS_ORIGINS` | Allowed CORS origins | `*` |

No real secrets are committed; `.env` is gitignored.

## 5. API reference

### `POST /api/v1/documents/process`
```
Content-Type: multipart/form-data
file: <document.pdf|.jpg|.png>
document_type: invoice | balance_sheet | profit_and_loss | cash_flow_statement
```
```bash
curl -X POST http://localhost:8000/api/v1/documents/process \
  -F "file=@sample_invoice.pdf" \
  -F "document_type=invoice"
```
Returns the full structured JSON (see `sample_outputs/`) or, on failure, an
HTTP 4xx/5xx with `{"error": {"code": "...", "message": "..."}}`.

### `GET /api/v1/documents/{document_name}`
Returns the latest stored processing result for that file name.
```bash
curl http://localhost:8000/api/v1/documents/sample_invoice.pdf
```

### `GET /api/v1/documents`
Returns the list backing the dashboard (name, type, status, validation
status, processed_at).

### `GET /api/v1/health`
Liveness/readiness check, also verifies DB connectivity.

## 6. OCR / LLM services used

- **OCR**: local, free, open-source — `pdftotext` (poppler) for native PDFs,
  Tesseract for scanned PDFs and images. No external OCR API, no rate
  limits, no cost.
- **LLM**: Groq (`llama-3.3-70b-versatile` by default) via its
  OpenAI-compatible Chat Completions endpoint. The extraction service is
  provider-agnostic — set `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` to
  point it at any other OpenAI-compatible provider (OpenAI, xAI Grok,
  etc.) without code changes.

## 7. Confidence scoring

Not implemented (explicitly optional per the case study). Every extracted
field instead carries `page_number` + literal `evidence.source_text` so
values can be manually traced back to the source document, which we judged
more reliable than an LLM-generated confidence number.

## 8. Financial validation rules & tolerance

Implemented in `app/services/financial_validation_service.py`. A check only
runs if every field it needs is present and numeric; otherwise its status
is `NOT_APPLICABLE` (never assumed). Tolerance for "approximately equal" is
`max(1.0, 0.5% of the reported value)` to absorb OCR/rounding noise.

| Document | Checks |
|---|---|
| Invoice | `subtotal + tax_amount - discount ≈ total_amount`; `quantity × unit_price ≈ line amount` per line item; `sum(line amounts) ≈ subtotal`; `cash_paid - total_amount ≈ change` |
| Balance sheet | `total_liabilities + total_equity ≈ total_assets` |
| Profit & loss | `revenue - cost_of_sales ≈ gross_profit`; `gross_profit - operating_expenses ≈ operating_profit`; `operating_profit - tax ≈ net_profit` |
| Cash flow | `operating + investing + financing + fx ≈ net_change_in_cash`; `opening_cash + net_change_in_cash ≈ closing_cash` |

## 9. Database / persistence

SQLite (`storage/app.db`), one `processed_documents` table storing the full
structured result as JSON plus indexed columns (`document_name`,
`document_type`, `processing_status`, `overall_validation_status`,
`created_at`) for the dashboard/list query and GET-by-name lookup. Re-
processing the same file name inserts a new row; GET-by-name returns the
most recent one (prior versions are retained, not deleted). Swapping to
Postgres/MySQL is a one-line `DATABASE_URL` change — no code changes,
since access goes through SQLAlchemy.

## 10. Testing

```bash
cd backend
pytest tests/ -v
```
Covers: file-validation edge cases (empty/corrupt/unsupported files),
financial-check math (pass/fail/not-applicable), and the core API flow
(health, unsupported-file rejection, 404 on unknown document, list
endpoint). These run without any LLM key since they exercise the paths
that don't require a live model call.

## 11. Known limitations

- Multi-period (comparative-year) balance sheet / P&L validation is
  currently single-period; the schema supports a `periods` list from the
  LLM but per-period looping is a follow-up (flagged as a TODO in
  `financial_validation_service.py`).
- Confidence scoring is not implemented (explicitly optional in scope).
- OCR accuracy on low-quality scans depends on Tesseract; no
  post-OCR spell-correction pass is applied.
- Uploaded files are deleted immediately after processing (only the
  structured result is persisted) to keep storage bounded on free-tier
  hosting.

## 12. What I'd change for production

- Move OCR + LLM extraction to an async task queue (Celery/RQ) instead of
  synchronous request handling, with webhook/polling for results.
- Add per-period validation loops for multi-year statements.
- Add authentication/API keys for the upload endpoint.
- Swap SQLite for Postgres and add connection pooling.
- Add structured request tracing (request ID propagated through logs).
- Add a proper confidence mechanism (e.g. cross-checking OCR text against
  extracted values) rather than leaving it optional.

## 13. AI coding assistants used

Claude (Anthropic) was used throughout — architecture design, backend
code (FastAPI services/routes/models), frontend (HTML/CSS/JS dashboard),
financial validation formulas, and this README.

## 14. Deployed URLs

_Fill in after deployment:_
- Frontend: `<your-render-url>`
- Backend API base: `<same-url>/api/v1` (single service serves both)
- Swagger/OpenAPI: `<your-render-url>/docs`
- GitHub repo: `<your-repo-url>`
