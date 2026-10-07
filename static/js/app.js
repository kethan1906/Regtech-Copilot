"use strict";

const PAGE_SIZE = 50;
const state = { offset: 0, total: 0 };

const $ = (id) => document.getElementById(id);

function showNotice(message, isError) {
  const el = $("notice");
  el.textContent = message;
  el.className = "notice" + (isError ? " error" : "");
  el.hidden = !message;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    let detail = "";
    try { detail = (await response.json()).error || ""; } catch (_) { /* ignore */ }
    throw new Error(detail || "Request failed (" + response.status + ")");
  }
  return response.json();
}

function cell(row, text, className) {
  const td = document.createElement("td");
  td.textContent = text;           // textContent: data is never interpreted as HTML
  if (className) td.className = className;
  row.appendChild(td);
  return td;
}

function renderTransactions(transactions) {
  const table = $("transactionTable");
  table.replaceChildren();
  if (transactions.length === 0) {
    const tr = document.createElement("tr");
    const td = cell(tr, "No transactions match the current filters.");
    td.colSpan = 9;
    table.appendChild(tr);
    return;
  }
  transactions.forEach((t) => {
    const tr = document.createElement("tr");
    if (t.flagged) tr.className = "flagged";
    cell(tr, t.id);
    cell(tr, t.step);
    cell(tr, t.type);
    cell(tr, t.amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }), "num");
    cell(tr, t.origin);
    cell(tr, t.destination);
    const risk = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = "badge " + t.risk_level;
    badge.textContent = t.risk_level;
    risk.appendChild(badge);
    tr.appendChild(risk);
    cell(tr, t.flagged ? "FLAGGED" : "NORMAL");
    cell(tr, t.reasons.join(", "), "reason");
    table.appendChild(tr);
  });
}

function renderPager() {
  const from = state.total === 0 ? 0 : state.offset + 1;
  const to = Math.min(state.offset + PAGE_SIZE, state.total);
  $("pageInfo").textContent = from + "-" + to + " of " + state.total;
  $("prevPage").disabled = state.offset === 0;
  $("nextPage").disabled = state.offset + PAGE_SIZE >= state.total;
}

async function loadTransactions() {
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: state.offset });
  const risk = $("riskFilter").value;
  if (risk) params.set("risk_level", risk);
  if ($("flaggedOnly").checked) params.set("flagged_only", "true");
  try {
    const data = await getJson("/api/transactions?" + params);
    state.total = data.total;
    renderTransactions(data.transactions);
    renderPager();
  } catch (error) {
    console.error(error);
    const table = $("transactionTable");
    table.replaceChildren();
    const tr = document.createElement("tr");
    const td = cell(tr, "Unable to load transaction data: " + error.message);
    td.colSpan = 9;
    table.appendChild(tr);
  }
}

function listBlock(title, items) {
  const div = document.createElement("div");
  const h = document.createElement("h3");
  h.textContent = title;
  const ul = document.createElement("ul");
  items.forEach((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    ul.appendChild(li);
  });
  div.append(h, ul);
  return div;
}

async function loadSummary() {
  try {
    const s = await getJson("/api/reports/summary");
    $("totalTransactions").textContent = s.total_transactions.toLocaleString();
    $("flaggedTransactions").textContent = s.flagged_transactions.toLocaleString();
    $("highCount").textContent = s.by_risk_level.HIGH.toLocaleString();
    $("mediumCount").textContent = s.by_risk_level.MEDIUM.toLocaleString();

    const body = $("reportBody");
    body.replaceChildren();
    body.appendChild(listBlock("Alerts by rule",
      Object.entries(s.by_rule).map(([code, n]) => s.rule_descriptions[code] + ": " + n)));
    body.appendChild(listBlock("Top origin accounts by alerts",
      s.top_origin_accounts.length
        ? s.top_origin_accounts.map((a) => a.account + " (" + a.alerts + ")")
        : ["None"]));
    const run = s.last_monitoring_run;
    body.appendChild(listBlock("Last monitoring run",
      run ? [
        "Run at: " + run.run_at + " (UTC)",
        "Scanned: " + run.transactions_scanned.toLocaleString(),
        "Alerts: " + run.alerts_created.toLocaleString(),
        "Flagged amount total: " + s.flagged_amount_total.toLocaleString(undefined, { maximumFractionDigits: 2 }),
      ] : ["Monitoring has not been run yet."]));

    if (!run && s.total_transactions > 0) {
      showNotice("Transactions are loaded but monitoring has not run. Run: python -m scripts.run_monitoring", false);
    } else if (s.unmonitored_transactions > 0 && run) {
      showNotice(s.unmonitored_transactions + " transactions were added after the last monitoring run and are not yet evaluated. Run: python -m scripts.run_monitoring", false);
    } else if (s.total_transactions === 0) {
      showNotice("The database is empty. Run: python -m scripts.setup_demo", false);
    } else {
      showNotice("", false);
    }
  } catch (error) {
    console.error(error);
    showNotice("Unable to load the report: " + error.message, true);
  }
}

async function uploadCsv(event) {
  event.preventDefault();
  const file = $("csvFile").files[0];
  if (!file) {
    showNotice("Please choose a CSV file first.", true);
    return;
  }

  const button = $("uploadButton");
  const result = $("uploadResult");
  const formData = new FormData();
  formData.append("file", file);
  if ($("replaceData").checked) formData.append("replace", "true");

  button.disabled = true;
  button.textContent = "Uploading…";
  result.hidden = true;
  try {
    const response = await fetch("/api/import", { method: "POST", body: formData });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Upload failed");

    result.textContent = "Imported " + body.imported_transactions.toLocaleString() +
      " transactions and created " + body.monitoring.alerts_created.toLocaleString() + " alerts.";
    result.className = "upload-result success";
    result.hidden = false;
    state.offset = 0;
    await Promise.all([loadSummary(), loadTransactions()]);
  } catch (error) {
    result.textContent = error.message;
    result.className = "upload-result error";
    result.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "Upload & Run Monitoring";
  }
}

function bindControls() {
  $("uploadForm").addEventListener("submit", uploadCsv);
  const reload = () => { state.offset = 0; loadTransactions(); };
  $("riskFilter").addEventListener("change", reload);
  $("flaggedOnly").addEventListener("change", reload);
  $("prevPage").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE_SIZE); loadTransactions(); });
  $("nextPage").addEventListener("click", () => { state.offset += PAGE_SIZE; loadTransactions(); });
}

document.addEventListener("DOMContentLoaded", () => {
  bindControls();
  loadSummary();
  loadTransactions();
});
