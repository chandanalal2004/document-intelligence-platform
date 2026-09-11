import json
import re
from typing import Any, Dict

from openai import OpenAI

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

client = OpenAI(
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_BASE_URL,
)


REQUIRED_FIELDS = {
    "invoice": [
        "invoice_number",
        "invoice_date",
        "vendor_name",
        "vendor_address",
        "vendor_phone",
        "vendor_fax",
        "customer_name",
        "currency",
        "subtotal",
        "tax_amount",
        "discount",
        "total_amount",
        "rounding_adjustment",
        "final_amount",
        "payment_amount",
        "change",
        "line_items",
    ],
    "balance_sheet": [
        "statement_date",
        "currency",
        "total_assets",
        "total_liabilities",
        "total_equity",
    ],
    "profit_and_loss": [
        "period",
        "currency",
        "total_income",
        "total_expenditure",
        "net_profit",
    ],
    "cash_flow_statement": [
        "period",
        "currency",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "fx_adjustment",
        "opening_cash",
        "net_change_in_cash",
        "closing_cash",
    ],
}


_SYSTEM_PROMPT = """
You are a financial document field extraction system.

Extract structured information ONLY from the supplied OCR/document text.

Rules:
1. Never invent information.
2. If a field is not present, return null.
3. Preserve the meaning and values found in the document.
4. Every non-null field must include evidence as a short literal
   substring copied from the supplied document.
5. Do not perform arithmetic unless the requested field is explicitly
   reported or can be directly identified from the document.
6. For monetary values, return numeric values without currency symbols.
7. Return ONLY valid JSON.
8. Do not use markdown.
9. Do not wrap the JSON in ``` fences.
10. Keep the JSON compact.
"""


def _build_user_prompt(
    document_type: str,
    text: str,
    page_number: int = 1,
) -> str:

    if document_type == "invoice":
        task_instructions = """
Extract every meaningful invoice or receipt field.

IMPORTANT DATE RULE:
- Extract the invoice/receipt transaction date whenever explicitly present.
- The date does NOT need a printed label such as "DATE".
- Retail receipts may show a timestamp such as:
  "19/10/2018 20:49:59 #01"
- In that situation:
  invoice_date = "19/10/2018"
- Recognize DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY,
  YYYY/MM/DD and YYYY-MM-DD.
- Never infer a date from the filename or current date.
- Evidence must be copied literally from the supplied text.

IMPORTANT RECEIPT TOTAL RULE:
- Distinguish:
  * subtotal
  * tax
  * discount
  * total amount before rounding
  * rounding adjustment
  * final amount payable
  * payment/cash received
  * change
- Do not confuse CASH with TOTAL AMT.
- Do not confuse CHANGE with the final amount.
- Do not invent values that are not supported by the supplied text.

If a receipt contains:
@DISC 10.00% -5.59
TOTAL AMT RM 60.31
ROUNDING ADJ -0.01
RM 60.30
CASH RM 70.30
CHANGE RM 10.00

extract:
discount = 5.59
total_amount = 60.31
rounding_adjustment = -0.01
final_amount = 60.30
payment_amount = 70.30
change = 10.00

OCR may contain small recognition errors in labels.
"""

    elif document_type == "balance_sheet":
        task_instructions = """
Extract:
- statement date
- currency/unit
- total assets
- total liabilities
- total equity

Preserve the reporting date and currency/unit exactly as represented.
"""

    elif document_type == "profit_and_loss":
        task_instructions = """
Extract:
- reporting period
- currency/unit
- total income
- total expenditure
- net profit
"""

    elif document_type == "cash_flow_statement":
        task_instructions = """
Extract:
- period
- currency
- operating cash flow
- investing cash flow
- financing cash flow
- FX adjustment
- opening cash
- net change in cash
- closing cash

Distinguish cash-flow components from opening and closing cash balances.
"""

    else:
        task_instructions = """
Extract the requested fields from the supplied document.
"""

    fields = REQUIRED_FIELDS[document_type]

    return f"""
Document type: {document_type}

Required fields:
{json.dumps(fields)}

{task_instructions}

Return ONLY this JSON structure:

{{
  "fields": {{
    "field_name": {{
      "value": null,
      "page_number": null,
      "evidence": null
    }}
  }},
  "line_items": []
}}

For every non-null field:
- value = extracted value
- page_number = page number
- evidence = short literal text copied from the OCR

For a missing field:
"value": null,
"page_number": null,
"evidence": null

For line_items, return objects containing:
- description
- quantity
- unit_price
- amount

OCR/document text:
--------------------
{text}
--------------------
"""


def _strip_code_fences(value: str) -> str:
    value = value.strip()

    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)

        if value.endswith("```"):
            value = value[:-3]

    return value.strip()


def _normalise_receipt_number(value: Any) -> Any:

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        cleaned = value.strip()

        cleaned = cleaned.replace("RM", "")
        cleaned = cleaned.replace("$", "")
        cleaned = cleaned.replace("€", "")
        cleaned = cleaned.replace("£", "")
        cleaned = cleaned.replace(",", ".")

        cleaned = re.sub(r"[^\d.\-]", "", cleaned)

        if cleaned in {"", "-", ".", "-."}:
            return None

        try:
            return float(cleaned)
        except ValueError:
            return value

    return value


def _make_field(
    value: Any,
    page_number: int,
    source_text: Any = None,
) -> Dict[str, Any]:

    if value is None:
        return {
            "value": None,
            "page_number": None,
            "evidence": None,
        }

    if source_text is None:
        source_text = ""

    return {
        "value": value,
        "page_number": page_number,
        "evidence": source_text,
    }


def _find_labelled_amount(
    text: str,
    patterns,
) -> tuple[Any, str | None]:

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        if not match:
            continue

        source = match.group(0)

        numbers = re.findall(
            r"[-+]?\d+(?:[.,]\d+)?",
            source,
        )

        if not numbers:
            continue

        number = numbers[-1]

        value = _normalise_receipt_number(number)

        if value is not None:
            return value, source

    return None, None


# ---------------------------------------------------------------------
# Generic date fallback (NOT specific to any single receipt/document).
#
# The LLM is instructed to extract unlabeled receipt timestamps, but on
# noisy OCR it sometimes omits `invoice_date` entirely rather than risk
# guessing (per the "never invent" rule). This mirrors the existing
# regex-based safety net already used for discount/total/rounding/etc.:
# it only fills the field in when the model left it null, and it matches
# on generic date shapes rather than any literal value.
# ---------------------------------------------------------------------

_DATE_WITH_TIME_PATTERN = re.compile(
    r"\b(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})\s+\d{1,2}:\d{2}(?::\d{2})?\b"
)

_BARE_DATE_PATTERNS = [
    re.compile(r"\b\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}\b"),
    re.compile(r"\b\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}\b"),
]


def _find_invoice_date(text: str) -> tuple[Any, str | None]:
    """
    Look for a date, preferring one immediately followed by a clock time
    (the common retail-receipt timestamp shape), then falling back to any
    bare date pattern in the document.
    """

    match = _DATE_WITH_TIME_PATTERN.search(text)
    if match:
        return match.group(1), match.group(0)

    for pattern in _BARE_DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0), match.group(0)

    return None, None


def _ensure_all_required_fields(
    fields: Dict[str, Any],
    document_type: str,
) -> Dict[str, Any]:
    """
    Guarantee every field the schema promises is present in the response,
    even if the LLM silently dropped a key. Missing keys become explicit
    nulls, matching the shape the LLM would have produced for a field it
    genuinely couldn't find -- so downstream code never has to special-case
    "missing key" vs. "present but null".
    """

    for field_name in REQUIRED_FIELDS.get(document_type, []):
        if field_name == "line_items":
            continue

        existing = fields.get(field_name)
        if not isinstance(existing, dict):
            fields[field_name] = _make_field(None, None, None)

    return fields


def _apply_invoice_label_overrides(
    extracted: Dict[str, Any],
    text: str,
    page_number: int,
) -> Dict[str, Any]:

    fields = extracted.setdefault("fields", {})

    # ---------------------------------------------------------
    # Invoice / receipt date
    # ---------------------------------------------------------

    existing_date_field = fields.get("invoice_date")
    existing_date_value = (
        existing_date_field.get("value")
        if isinstance(existing_date_field, dict)
        else None
    )

    if existing_date_value in (None, ""):
        date_value, date_source = _find_invoice_date(text)

        if date_value is not None:
            fields["invoice_date"] = _make_field(
                date_value,
                page_number,
                date_source,
            )

    # ---------------------------------------------------------
    # Discount
    # ---------------------------------------------------------

    discount_patterns = [
        r"@\s*DISC\b.{0,80}?[-~]?\s*\d+[.,]\d{2}\b",
        r"@\s*ISC\b.{0,80}?[-~]?\s*\d+[.,]\d{2}\b",
        r"DISC\b.{0,80}?[-~]?\s*\d+[.,]\d{2}\b",
        r"ISC\b.{0,80}?[-~]?\s*\d+[.,]\d{2}\b",
    ]

    discount_value, discount_source = _find_labelled_amount(
        text,
        discount_patterns,
    )

    if discount_value is not None:
        fields["discount"] = _make_field(
            abs(float(discount_value)),
            page_number,
            discount_source,
        )

    # ---------------------------------------------------------
    # Total amount before rounding
    # ---------------------------------------------------------

    total_patterns = [
        r"\bTOTAL\s*AMT\b.{0,100}?\bRM\b\s*[-~]?\s*\d+[.,]\d{2}",
        r"\bTOTAL\s*A[MN]?T\b.{0,100}?\bRM\b\s*[-~]?\s*\d+[.,]\d{2}",
        r"\bTOTAL\s*AMOUNT\b.{0,100}?\bRM\b\s*[-~]?\s*\d+[.,]\d{2}",
        r"\bINVOICE\s*TOTAL\b.{0,100}?\bRM\b\s*[-~]?\s*\d+[.,]\d{2}",
        r"\bTOTAL\b.{0,100}?\bRM\b\s*[-~]?\s*\d+[.,]\d{2}",
    ]

    total_value, total_source = _find_labelled_amount(
        text,
        total_patterns,
    )

    if total_value is not None:
        fields["total_amount"] = _make_field(
            total_value,
            page_number,
            total_source,
        )

    # ---------------------------------------------------------
    # Rounding adjustment
    # ---------------------------------------------------------

    rounding_patterns = [
        r"\bROUNDING\s*ADJ\b.{0,100}?[-~]?\s*\d+[.,]\d{2}",
        r"\bROUNDING\s*ADI\b.{0,100}?[-~]?\s*\d+[.,]\d{2}",
        r"\bROUNDING\b.{0,100}?[-~]?\s*\d+[.,]\d{2}",
    ]

    rounding_value, rounding_source = _find_labelled_amount(
        text,
        rounding_patterns,
    )

    if rounding_value is not None and abs(float(rounding_value)) <= 1:
        fields["rounding_adjustment"] = _make_field(
            float(rounding_value),
            page_number,
            rounding_source,
        )

    # ---------------------------------------------------------
    # Final amount
    # ---------------------------------------------------------

    total_field = fields.get("total_amount", {})
    rounding_field = fields.get("rounding_adjustment", {})

    total_number = total_field.get("value")
    rounding_number = rounding_field.get("value")

    if (
        isinstance(total_number, (int, float))
        and isinstance(rounding_number, (int, float))
    ):
        final_value = round(
            float(total_number) + float(rounding_number),
            2,
        )

        total_evidence = total_field.get("evidence") or ""
        rounding_evidence = rounding_field.get("evidence") or ""

        fields["final_amount"] = _make_field(
            final_value,
            page_number,
            f"{total_evidence} {rounding_evidence}".strip(),
        )

    # ---------------------------------------------------------
    # Payment amount / CASH
    # ---------------------------------------------------------

    payment_patterns = [
        r"\bCASH\b.{0,100}?\b(?:RM|RE|RS)?\s*[-~]?\s*\d+[.,]\d{2}",
        r"\bCAGHS\b.{0,100}?\b(?:RM|RE|RS)?\s*[-~]?\s*\d+[.,]\d{2}",
    ]

    payment_value, payment_source = _find_labelled_amount(
        text,
        payment_patterns,
    )

    if payment_value is not None:
        fields["payment_amount"] = _make_field(
            payment_value,
            page_number,
            payment_source,
        )

    # ---------------------------------------------------------
    # Change
    # ---------------------------------------------------------

    change_patterns = [
        r"\bCHANGE\b.{0,100}?\b(?:RM|RE|RS)?\s*[-~]?\s*\d+[.,]\d{2}",
    ]

    change_value, change_source = _find_labelled_amount(
        text,
        change_patterns,
    )

    if change_value is not None:
        fields["change"] = _make_field(
            change_value,
            page_number,
            change_source,
        )

    # ---------------------------------------------------------
    # Correct payment from final amount + change
    # ---------------------------------------------------------

    final_field = fields.get("final_amount", {})
    change_field = fields.get("change", {})

    final_number = final_field.get("value")
    change_number = change_field.get("value")

    if (
        isinstance(final_number, (int, float))
        and isinstance(change_number, (int, float))
    ):
        corrected_payment = round(
            float(final_number) + float(change_number),
            2,
        )

        final_evidence = final_field.get("evidence") or ""
        change_evidence = change_field.get("evidence") or ""

        fields["payment_amount"] = _make_field(
            corrected_payment,
            page_number,
            f"{final_evidence} {change_evidence}".strip(),
        )

    return extracted


def extract_fields(
    document_type: str,
    text: str,
    page_number: int = 1,
) -> Dict[str, Any]:

    if document_type not in REQUIRED_FIELDS:
        raise ValueError(
            f"Unsupported document type: {document_type}"
        )

    prompt = _build_user_prompt(
        document_type=document_type,
        text=text,
        page_number=page_number,
    )

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        temperature=0,
        # gpt-oss models on Groq spend part of their output budget on a
        # hidden reasoning phase before writing the final answer, and that
        # usage isn't perfectly deterministic between runs even at
        # temperature=0. max_tokens=8000 mirrors the value already proven
        # to work for this project's larger (cash-flow) schema.
        max_tokens=8000,
        # reasoning_effort is a Groq-specific extension, not part of the
        # official OpenAI API, so the SDK's typed method signature doesn't
        # accept it directly -- extra_body passes it straight through to
        # the underlying HTTP request instead.
        extra_body={
            # Structured field extraction doesn't need heavy step-by-step
            # reasoning -- lowering effort reduces hidden reasoning-token
            # usage, directly reducing truncation risk.
            "reasoning_effort": "low",
        },
        messages=[
            {
                "role": "system",
                "content": _SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    content = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason

    logger.debug(
        "LLM extraction response: finish_reason=%s message=%s",
        finish_reason,
        response.choices[0].message.model_dump(),
    )

    if not content:
        reasoning = getattr(response.choices[0].message, "reasoning", None)
        raise ValueError(
            "AI returned an empty response "
            f"(finish_reason={finish_reason!r}, "
            f"reasoning_present={bool(reasoning)}). "
            "If finish_reason is 'length', the model likely ran out of "
            "tokens during its reasoning phase -- consider raising "
            "max_tokens further or lowering reasoning effort."
        )

    content = _strip_code_fences(content)

    try:
        extracted = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"AI returned invalid JSON: {content}"
        ) from exc

    if not isinstance(extracted, dict):
        raise ValueError(
            "AI extraction result must be a JSON object."
        )

    if "fields" not in extracted:
        extracted = {
            "fields": extracted,
            "line_items": [],
        }

    if "line_items" not in extracted:
        extracted["line_items"] = []

    if not isinstance(extracted.get("fields"), dict):
        raise ValueError(
            "AI extraction result contains an invalid 'fields' object."
        )

    extracted["fields"] = _ensure_all_required_fields(
        extracted["fields"],
        document_type,
    )

    if document_type == "invoice":
        extracted = _apply_invoice_label_overrides(
            extracted=extracted,
            text=text,
            page_number=page_number,
        )

    return extracted