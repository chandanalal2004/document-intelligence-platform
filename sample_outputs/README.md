# Sample outputs

This folder is where processed JSON results go for your submission
(section 12/§11 of the case study requires real sample outputs from the
provided dataset).

They are not included yet because generating them requires a live call to
the LLM (Groq), and the development sandbox this codebase was built in has
no network access to api.groq.com to run one.

**To generate real ones once you have your app running locally:**

```bash
curl -X POST http://localhost:8000/api/v1/documents/process \
  -F "file=@/path/to/New Dataset/Invoices/X51005361895.jpg" \
  -F "document_type=invoice" \
  -o sample_outputs/invoice_X51005361895.json

curl -X POST http://localhost:8000/api/v1/documents/process \
  -F "file=@/path/to/New Dataset/Balance Sheet/Consolidated Balance Sheet 2024.pdf" \
  -F "document_type=balance_sheet" \
  -o sample_outputs/balance_sheet_2024.json
```

Do this for at least:
- one invoice
- one balance sheet
- one profit & loss
- one cash flow statement
- one scanned/image-based document (several invoices in the dataset are
  JPGs, and the balance sheet PDFs are scans — `processing_metadata.ocr_used`
  should read `true` for these)
- one failure/validation-mismatch case (you can intentionally test an
  unsupported file, e.g. a `.txt`, to capture the error-response shape too)

Save each response as a `.json` file in this folder before you submit.
