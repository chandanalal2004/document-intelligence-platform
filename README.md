cd D:\AIENGINEER
@'
# Document Intelligence Platform

AI-powered extraction, validation and API platform for invoices, balance
sheets, P&L statements and cash flow statements. Built for the AI
Engineer Internship technical case study.

## 1. Solution overview & architecture

    Upload (dashboard or API)
            |
            v
    [1] Document validation      -> file type / empty / corrupt / page-count checks
            |  (fails fast, returns FAILED + error code)
            v
    [2] Text extraction / OCR    -> pdftotext for native PDFs
            |                        Tesseract OCR (word-level bounding boxes,
            |                        reconstructed into rows by vertical
            |                        position) for scanned PDFs and JPG/PNG
            v
    [3] AI field & table extraction -> LLM call (Groq, OpenAI-compatible) with a
            |                           document-type-aware prompt. Returns every
            |                           meaningful field + line items, each with
            |                           page_number + literal source-text evidence.
            |                           Missing values are null, never invented.
            v
    [4] Financial validation      -> per-document-type formula checks
            |                          (see "Financial validation rules" below)
            v
    [5] Persistence                -> PostgreSQL (processed_documents table)
            v
    [6] Structured JSON response + Dashboard (server-rendered HTML/CSS/JS)

Each stage above is a separate service module (app/services/*), called in
order by document_service.py, which is the only file that knows the
pipeline order. This keeps validation, OCR, extraction, financial checks,
and persistence independently testable and replaceable.

A notable fix during development: OCR row reconstruction originally used
pytesseract.image_to_string(), which relies on Tesseract's own layout
analysis -- on multi-column comparative financial tables (e.g. a cash flow
statement with two years side by side), this let Tesseract scramble label
and number row order. It was rewritten to use pytesseract.image_to_data()
(word-level bounding boxes) and reconstruct each row purely from vertical
(y-axis) position, which fixed the misalignment. See
app/services/ocr_service.py.

## 2. Technology stack

| Layer | Choice | Why |
|---|---|---|
| API framework | FastAPI | async, automatic OpenAPI/Swagger docs, strong typing via Pydantic |
| Server-rendered frontend | Jinja2 + vanilla HTML/CSS/JS | single deployable service, no separate frontend build/host needed |
| Database | PostgreSQL (Render free tier) via SQLAlchemy | persistent across redeploys -- Render's free web-service filesystem is ephemeral, so SQLite would silently lose data on every redeploy; SQLAlchemy makes the swap a one-line DATABASE_URL change with zero code changes |
| Native PDF text | pdftotext (poppler-utils) | fast, exact, no OCR error on digitally-authored PDFs |
| OCR | Tesseract (pytesseract) + pdftoppm rasterization | free, local, no external OCR service dependency/rate limits |
| AI field extraction | Groq API (OpenAI-compatible /chat/completions), model openai/gpt-oss-20b | fast inference, generous free tier, structured JSON mode |
| Deployment | Render (Docker) | free tier, single web service serves both API and frontend; Dockerfile installs tesseract-ocr + poppler-utils via apt at build time |

## 3. Local setup

Prerequisites: Python 3.11+ (tested on 3.12.10), poppler-utils and
tesseract-ocr installed on the system.

Windows:

    winget install --id UB-Mannheim.TesseractOCR
    winget install --id oschwartz10612.Poppler

Add both installs' bin folders to your system PATH, then reopen your
terminal.

Linux/Debian:

    sudo apt-get install -y poppler-utils tesseract-ocr

Then, from the backend folder:

    cd backend
    python -m venv venv
    venv\Scripts\Activate.ps1
    pip install -r requirements.txt

    copy ..\.env.example .env
    # then edit .env and set LLM_API_KEY to your Groq key (console.groq.com/keys)

    python -m uvicorn app.main:app --reload

Open:
- Dashboard: http://localhost:8000
- Swagger/OpenAPI docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

## 4. Environment variables (.env.example)

| Variable | Purpose | Default |
|---|---|---|
| LLM_API_KEY | API key for the LLM used in field extraction | (required) |
| LLM_BASE_URL | OpenAI-compatible base URL | https://api.groq.com/openai/v1 |
| LLM_MODEL | Model name | openai/gpt-oss-20b |
| DATABASE_URL | SQLAlchemy connection string | SQLite locally by default; set to a Postgres URL in production (see section 9) |
| UPLOAD_DIR | Temp storage for in-flight uploads | ./storage/uploads |
| MAX_PAGE_COUNT | Reject documents over this page count | 3 |
| MAX_FILE_SIZE_MB | Reject uploads over this size | 15 |
| NATIVE_TEXT_MIN_CHARS_PER_PAGE | Threshold below which a PDF is treated as scanned and OCR'd | 40 |
| CORS_ORIGINS | Allowed CORS origins | * |

No real secrets are committed; .env is gitignored. In production, all
of these are set directly in Render's dashboard environment variables,
not in the repo.

## 5. API reference

### POST /api/v1/documents/process

    Content-Type: multipart/form-data
    file: <document.pdf|.jpg|.png>
    document_type: invoice | balance_sheet | profit_and_loss | cash_flow_statement

Example:

    curl -X POST https://document-intelligence-platform-1eak.onrender.com/api/v1/documents/process -F "file=@sample_invoice.pdf" -F "document_type=invoice"

Returns the full structured JSON (see sample_outputs/) or, on failure, an
HTTP 4xx/5xx with {"error": {"code": "...", "message": "..."}}. Verified
live: an unsupported file type (e.g. .txt) correctly returns 422 with
{"error": {"code": "UNSUPPORTED_FILE_TYPE", ...}} rather than a crash.

### GET /api/v1/documents/{document_name}

Returns the latest stored processing result for that file name.

    curl https://document-intelligence-platform-1eak.onrender.com/api/v1/documents/sample_invoice.pdf

### GET /api/v1/documents

Returns the list backing the dashboard (name, type, status, validation
status, processed_at).

### GET /api/v1/health

Liveness/readiness check, also verifies DB connectivity. Returns
{"status": "ok", "database": "ok"} when both the app and the database
connection are healthy.

## 6. OCR / LLM services used

- OCR: local, free, open-source -- pdftotext (poppler) for native PDFs,
  Tesseract for scanned PDFs and images. No external OCR API, no rate
  limits, no cost. Row reconstruction uses word-level bounding boxes
  (image_to_data) rather than Tesseract's default block layout, to
  correctly handle multi-column comparative financial tables.
- LLM: Groq, model openai/gpt-oss-20b, via its OpenAI-compatible
  Chat Completions endpoint. This is a reasoning model -- it spends part
  of its token budget on hidden reasoning before writing the output JSON,
  which can truncate the response if max_tokens is too low. This project
  uses max_tokens=8000 and extra_body={"reasoning_effort": "low"}
  (note: reasoning_effort must be passed via extra_body -- it is not a
  native parameter of the openai Python SDK's .create() signature).
  The extraction service is provider-agnostic -- set LLM_BASE_URL /
  LLM_API_KEY / LLM_MODEL to point it at any other OpenAI-compatible
  provider without code changes.

## 7. Confidence scoring

Not implemented (explicitly optional per the case study). Every extracted
field instead carries page_number + literal evidence.source_text so
values can be manually traced back to the source document, which we judged
more reliable than an LLM-generated confidence number.

## 8. Financial validation rules & tolerance

Implemented in app/services/financial_validation_service.py. A check only
runs if every field it needs is present and numeric; otherwise its status
is NOT_APPLICABLE (never assumed). Tolerance for "approximately equal" is
max(1.0, 0.5% of the reported value) to absorb OCR/rounding noise.

| Document | Checks |
|---|---|
| Invoice | subtotal + tax_amount - discount = total_amount; quantity x unit_price = line amount per line item; sum(line amounts) = subtotal; cash_paid - total_amount = change |
| Balance sheet | total_liabilities + total_equity = total_assets |
| Profit & loss | revenue - cost_of_sales = gross_profit; gross_profit - operating_expenses = operating_profit; operating_profit - tax = net_profit. A banking-specific variant (total_income - total_expenditure = net_profit) is also checked when those fields are present, since bank P&L statements use different line-item conventions than retail/commercial ones. |
| Cash flow | operating + investing + financing + fx = net_change_in_cash; opening_cash + net_change_in_cash = closing_cash |

Verified against real documents from the provided dataset -- see
sample_outputs/ for actual passing and one intentionally-failing
(balance sheet, missing total_equity) example.

## 9. Database / persistence

PostgreSQL (Render's free-tier managed Postgres), connected via
SQLAlchemy. One processed_documents table storing the full structured
result as JSON plus indexed columns (document_name, document_type,
processing_status, overall_validation_status, created_at) for the
dashboard/list query and GET-by-name lookup. Re-processing the same file
name inserts a new row; GET-by-name returns the most recent one.

This project originally used SQLite by default. That was changed to
Postgres after identifying a real deployment risk: Render's free web
service tier has no persistent disk, so a SQLite file on that filesystem
is wiped on every redeploy/restart -- which would make the "processed
documents" dashboard appear empty to anyone evaluating the deployed app
after any redeploy happened in between. Because all database access goes
through SQLAlchemy and DATABASE_URL is read from environment, the
switch required no application code changes -- only adding the
psycopg2-binary driver to requirements.txt and setting the new
connection string as an env var on Render. Verified by processing
multiple real documents against the live deployment and confirming they
persist correctly across separate requests via GET /api/v1/documents.

## 10. Testing

    cd backend
    pytest tests/ -v

13/13 tests passing. Covers: file-validation edge cases (empty/corrupt/
unsupported files), financial-check math (pass/fail/not-applicable), and
the core API flow (health, unsupported-file rejection, 404 on unknown
document, list endpoint). These run against a local SQLite test database
and don't require a live LLM key, since they exercise the paths that
don't require a live model call. Live-deployment behavior (real OCR + LLM
extraction against real documents, and Postgres persistence) was verified
separately against the deployed Render URL -- see sample_outputs/.

## 11. Known limitations

- Multi-period (comparative-year) validation is single-period. Balance
  sheet / P&L checks currently validate only the most recent period; the
  schema captures a periods list from the LLM but per-period looping
  through comparative years is not yet implemented.
- Line-item validation assumes tax-exclusive unit prices. On invoices
  where the amount column is VAT/tax-inclusive ("Gross worth") while
  unit_price is pre-tax ("Net price"), quantity x unit_price can
  legitimately differ from the reported line amount. This has not caused
  a false failure in testing so far (all sample invoices passed), but the
  check does not yet detect or adjust for a tax markup, so it's not
  guaranteed to generalize to every invoice template.
- Deterministic label-matching regex for receipt totals/discounts can
  misfire on very noisy OCR. On at least one low-quality receipt photo,
  a discount-label regex briefly misattributed an unrelated purchased
  line item as a discount before the fix; the broader class of this
  problem (regex overlap between similarly-worded labels under heavy OCR
  noise) is mitigated but not eliminated.
- Large phone-camera photos are slow to OCR -- full native resolution
  images have taken several minutes end-to-end. A fix (capping the image's
  long edge to ~2500px before OCR) has been identified but not yet applied.
- Severely low-quality photos (skew, shadow, cluttered background) can
  return an all-null extraction with no error. This was confirmed as a
  genuine image-quality ceiling, not a code defect -- the pipeline
  correctly reports PASS/FAILED based on what could be extracted
  rather than silently fabricating values, but very poor input images may
  legitimately yield little to no usable data.
- gpt-oss-20b is a reasoning model that spends part of its token
  budget on hidden reasoning before writing output JSON. Insufficient
  max_tokens can truncate the response before any content is written
  (empty response / finish_reason: length). Mitigated with
  max_tokens=8000 and reasoning_effort: "low", but a more complex
  document than any tested so far could still hit this ceiling.
- Confidence scoring is not implemented (explicitly optional in scope).
- Uploaded files are deleted immediately after processing (only the
  structured result is persisted) to keep storage bounded on free-tier
  hosting.

## 12. What I'd change for production

- Move OCR + LLM extraction to an async task queue (Celery/RQ) instead of
  synchronous request handling, with webhook/polling for results -- most
  OCR calls currently take 1-2 minutes synchronously, which is workable
  for a demo but not for real throughput.
- Add per-period validation loops for multi-year comparative statements.
- Add a tax-aware / configurable line-item validation mode so gross- and
  net-priced invoice templates are both handled correctly.
- Apply the drafted image-downscaling fix for large phone-camera photos.
- Add authentication/API keys for the upload endpoint.
- Add connection pooling tuning for Postgres under real concurrent load.
- Add structured request tracing (request ID propagated through logs).
- Add a proper confidence mechanism (e.g. cross-checking OCR text against
  extracted values) rather than leaving it optional.

## 13. AI coding assistants used

Claude (Anthropic) and ChatGPT (OpenAI) were used throughout this
project as implementation and debugging partners -- generating initial
code for the FastAPI services/routes/models, the financial validation
formulas, the OCR pipeline, and the frontend dashboard, then iterating
on that code through a live debug-test-fix loop against real documents
from the provided dataset.

Every fix in this project was verified against real output before being
accepted, not merely proposed. Concretely, this project's debugging
process:

- Diagnosed and fixed an OCR row-misalignment bug on multi-column
  comparative financial tables (cash flow statements) by rewriting text
  reconstruction to use word-level bounding boxes instead of Tesseract's
  default block-layout grouping -- verified against a real HDFC Bank
  cash-flow statement, where the original bug produced an incorrect
  operating cash flow figure and the fix corrected it.
- Diagnosed a discount-field misattribution on a low-quality receipt
  photo, traced it to an overly loose label-matching regex, and
  generalized the fix rather than hardcoding the one receipt's values.
- Identified and worked around a reasoning-model-specific failure mode
  (hidden reasoning tokens truncating JSON output before any content was
  written) after two prior model choices were deprecated mid-project by
  the LLM provider.
- Migrated persistence from SQLite to Postgres after independently
  identifying a real deployment risk (Render's free-tier ephemeral
  filesystem would silently wipe the database on redeploy), then
  verified the fix by processing live documents and confirming they
  persisted correctly through the API.
- Tested all 4 supported document types, an unsupported-file rejection
  path, and a genuine validation-failure case against the live
  deployment -- not just locally -- before considering any of it done.

The engineering decisions (what to fix, in what order, what "done" means
for each fix, and what to accept as a documented limitation vs. chase
further) were made by the author; the AI assistants were used to
accelerate implementation and debugging, not to replace judgment about
correctness.

## 14. Deployed URLs

- Live app / dashboard: https://document-intelligence-platform-1eak.onrender.com
- Backend API base: https://document-intelligence-platform-1eak.onrender.com/api/v1
- Swagger/OpenAPI docs: https://document-intelligence-platform-1eak.onrender.com/docs
- GitHub repo: https://github.com/chandanalal2004/document-intelligence-platform
