const API_BASE = "/api/v1";
const root = document.getElementById("result-root");
const documentName = document.body.dataset.documentName;

// Fields that get their own dedicated section instead of the generic grid.
const EXCLUDED_FROM_GRID = new Set(["line_items", "periods"]);

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatValue(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "object") {
    // Defensive: a field value should normally be a primitive, but if the
    // backend ever returns a nested object/array here, show it as JSON
    // instead of leaking "[object Object]" onto the page.
    return JSON.stringify(value);
  }
  return String(value);
}

// Evidence may arrive as an object ({ source_text, page_number }), a plain
// string, or be absent entirely. Handle all three without assuming shape.
function evidenceHtml(entry) {
  if (!entry) return "";

  let sourceText = null;
  let pageNumber = entry.page_number ?? null;

  if (entry.evidence && typeof entry.evidence === "object") {
    sourceText = entry.evidence.source_text ?? null;
    pageNumber = entry.evidence.page_number ?? pageNumber;
  } else if (typeof entry.evidence === "string" && entry.evidence.trim()) {
    sourceText = entry.evidence;
  }

  if (!sourceText) return "";

  const pageSuffix = pageNumber ? ` — p.${escapeHtml(pageNumber)}` : "";
  return `<div class="field-evidence">\u201C${escapeHtml(sourceText)}\u201D${pageSuffix}</div>`;
}

function fieldCard(name, entry) {
  const rawValue = entry && typeof entry === "object" && "value" in entry ? entry.value : entry;
  const displayValue = formatValue(rawValue);
  const hasValue = displayValue !== null && displayValue !== "";
  const evidence = entry && typeof entry === "object" ? evidenceHtml(entry) : "";

  return `
    <div class="field-card ${hasValue ? "" : "missing"}">
      <div class="field-name">${escapeHtml(name.replace(/_/g, " "))}</div>
      <div class="field-value ${hasValue ? "" : "null"}">${hasValue ? escapeHtml(displayValue) : "not found"}</div>
      ${evidence}
    </div>`;
}

function checkRow(check) {
  const status = check.status ?? "NOT_APPLICABLE";
  return `
    <tr>
      <td>${escapeHtml(check.name ?? "—")}</td>
      <td class="formula">${escapeHtml(check.formula ?? "—")}</td>
      <td>${check.calculated_value ?? "—"}</td>
      <td>${check.reported_value ?? "—"}</td>
      <td>${check.variance ?? "—"}</td>
      <td><span class="badge ${escapeHtml(status)}">${escapeHtml(status)}</span></td>
    </tr>`;
}

function lineItemRow(item) {
  return `
    <tr>
      <td>${escapeHtml(item.description ?? "—")}</td>
      <td>${item.quantity ?? "—"}</td>
      <td>${item.unit_price ?? "—"}</td>
      <td>${item.amount ?? "—"}</td>
    </tr>`;
}

function periodsHtml(periods) {
  if (!Array.isArray(periods) || !periods.length) return "";
  const chips = periods
    .map((p) => `<span class="period-chip">${escapeHtml(typeof p === "object" ? JSON.stringify(p) : p)}</span>`)
    .join("");
  return `
    <div class="section-title">Reporting periods</div>
    <div class="periods-row">${chips}</div>`;
}

async function loadResult() {
  try {
    const res = await fetch(`${API_BASE}/documents/${encodeURIComponent(documentName)}`);
    if (!res.ok) {
      let message = res.statusText;
      try {
        const err = await res.json();
        message = err.error ? err.error.message : message;
      } catch {
        // response wasn't JSON; fall back to statusText
      }
      root.innerHTML = `<p class="subtle">Could not load result: ${escapeHtml(message)}</p>`;
      return;
    }
    const data = await res.json();
    render(data);
  } catch (err) {
    root.innerHTML = `<p class="subtle">Failed to load result: ${escapeHtml(err.message)}</p>`;
  }
}

function render(data) {
  const extracted = data.extracted_data || {};
  const fields = Object.entries(extracted).filter(([k]) => !EXCLUDED_FROM_GRID.has(k));
  const lineItems = extracted.line_items || [];
  const periods = extracted.periods || [];
  const checks = (data.validation || {}).checks || [];
  const issues = (data.validation || {}).issues || [];

  root.innerHTML = `
    <div class="result-header">
      <div>
        <h1 class="result-title">${escapeHtml(data.document_name ?? "Untitled document")}</h1>
        <div class="result-meta">
          ${escapeHtml(data.document_type ?? "—")} · OCR used: ${data.processing_metadata?.ocr_used ? "yes" : "no"} ·
          ${data.processing_metadata?.processing_time_ms ?? "—"} ms
        </div>
      </div>
      <div>
        <span class="badge ${escapeHtml(data.processing_status ?? "na")}">${escapeHtml(data.processing_status ?? "N/A")}</span>
        <span class="badge ${escapeHtml(data.validation?.overall_status || "na")}">${escapeHtml(data.validation?.overall_status || "N/A")}</span>
      </div>
    </div>

    ${periodsHtml(periods)}

    <div class="section-title">Extracted fields</div>
    <div class="field-grid">
      ${fields.length ? fields.map(([name, entry]) => fieldCard(name, entry)).join("") : `<p class="subtle">No fields were extracted for this document.</p>`}
    </div>

    ${lineItems.length ? `
    <div class="section-title">Line items</div>
    <table class="line-items-table">
      <thead><tr><th>Description</th><th>Qty</th><th>Unit price</th><th>Amount</th></tr></thead>
      <tbody>${lineItems.map(lineItemRow).join("")}</tbody>
    </table>` : ""}

    <div class="section-title">Financial validation</div>
    ${checks.length ? `
    <table class="check-table">
      <thead><tr><th>Check</th><th>Formula</th><th>Calculated</th><th>Reported</th><th>Variance</th><th>Status</th></tr></thead>
      <tbody>${checks.map(checkRow).join("")}</tbody>
    </table>` : `<p class="subtle">No applicable financial checks could be run for this document.</p>`}

    ${issues.length ? `<ul class="issues-list">${issues.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>` : ""}

    <details class="json-toggle">
      <summary>View raw JSON</summary>
      <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
    </details>
  `;
}

loadResult();