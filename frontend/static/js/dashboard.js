const API_BASE = "/api/v1";

const form = document.getElementById("upload-form");
const submitBtn = document.getElementById("submit-btn");
const statusBox = document.getElementById("upload-status");
const tableBody = document.getElementById("doc-table-body");
const refreshBtn = document.getElementById("refresh-btn");

function showStatus(kind, message) {
  statusBox.hidden = false;
  statusBox.className = `status-box ${kind}`;
  statusBox.textContent = message;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = document.getElementById("file");
  const docType = document.getElementById("document_type").value;
  if (!fileInput.files.length) return;

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("document_type", docType);

  submitBtn.disabled = true;
  showStatus("pending", "Processing document\u2026 this can take up to a minute for OCR + AI extraction.");

  try {
    const res = await fetch(`${API_BASE}/documents/process`, { method: "POST", body: formData });
    const data = await res.json();

    if (!res.ok) {
      const err = data.error || { code: "ERROR", message: "Processing failed." };
      showStatus("err", `${err.code}: ${err.message}`);
    } else {
      showStatus("ok", `Processed "${data.document_name}" \u2014 status: ${data.processing_status}`);
      form.reset();
      loadDocuments();
    }
  } catch (err) {
    showStatus("err", `Request failed: ${err.message}`);
  } finally {
    submitBtn.disabled = false;
  }
});

async function loadDocuments() {
  tableBody.innerHTML = `<tr><td colspan="5" class="empty-row">Loading\u2026</td></tr>`;
  try {
    const res = await fetch(`${API_BASE}/documents`);
    const docs = await res.json();

    if (!docs.length) {
      tableBody.innerHTML = `<tr><td colspan="5" class="empty-row">No documents processed yet. Upload one above.</td></tr>`;
      return;
    }

    tableBody.innerHTML = "";
    docs.forEach((doc) => {
      const tr = document.createElement("tr");
      tr.className = "clickable";
      tr.addEventListener("click", () => {
        window.location.href = `/documents/${encodeURIComponent(doc.document_name)}`;
      });
      const processedAt = doc.processed_at ? new Date(doc.processed_at).toLocaleString() : "\u2014";
      tr.innerHTML = `
        <td>${doc.document_name}</td>
        <td>${doc.document_type}</td>
        <td><span class="badge ${doc.processing_status}">${doc.processing_status}</span></td>
        <td><span class="badge ${doc.overall_validation_status || "na"}">${doc.overall_validation_status || "N/A"}</span></td>
        <td>${processedAt}</td>
      `;
      tableBody.appendChild(tr);
    });
  } catch (err) {
    tableBody.innerHTML = `<tr><td colspan="5" class="empty-row">Failed to load documents: ${err.message}</td></tr>`;
  }
}

refreshBtn.addEventListener("click", loadDocuments);
loadDocuments();