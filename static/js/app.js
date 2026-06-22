/* LyricSync Pro — Frontend JS */

const $ = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

// ── State ──────────────────────────────────────────────────────────────────
let allFiles = [];
let sortCol = "";
let sortDir = 1;
let sessionStart = null;
let timerInterval = null;

// ── Nav ────────────────────────────────────────────────────────────────────
$$(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    $$(".nav-btn").forEach(b => b.classList.remove("active"));
    $$(".panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    $("panel-" + btn.dataset.panel).classList.add("active");
    if (btn.dataset.panel === "results") refreshResultsTable();
  });
});

// ── Scan ───────────────────────────────────────────────────────────────────
$("btn-browse").addEventListener("click", async () => {
  $("btn-browse").disabled = true;
  showToast("Opening folder browser...", "info");
  try {
    const res = await api("POST", "/browse");
    if (res.folder) {
      $("folder-input").value = res.folder;
      showToast("Folder selected successfully.", "success");
    } else if (res.cancelled) {
      showToast("Folder selection cancelled.", "");
    }
  } catch (e) {
    showToast("Error opening folder browser.", "error");
  } finally {
    $("btn-browse").disabled = false;
  }
});

$("btn-scan").addEventListener("click", async () => {
  const folder = $("folder-input").value.trim();
  if (!folder) { showToast("Enter a folder path first or browse.", "error"); return; }

  setBadge("scanning");
  $("btn-scan").disabled = true;
  $("btn-browse").disabled = true;
  $("card-summary").style.display = "none";
  $("card-progress").style.display = "none";
  $("card-log").style.display = "none";

  try {
    const res = await api("POST", "/scan", { folder });
    if (res.error) { showToast(res.error, "error"); setBadge("idle"); $("btn-scan").disabled = false; $("btn-browse").disabled = false; }
  } catch (e) {
    showToast("Could not reach server.", "error");
    setBadge("idle");
    $("btn-scan").disabled = false;
    $("btn-browse").disabled = false;
  }
});

// ── Process controls ───────────────────────────────────────────────────────
$("btn-start").addEventListener("click", async () => {
  sessionStart = Date.now();
  startTimer();
  await api("POST", "/process/start");
});

$("btn-pause").addEventListener("click", async () => {
  await api("POST", "/process/pause");
});

$("btn-resume").addEventListener("click", async () => {
  await api("POST", "/process/resume");
});

$("btn-cancel").addEventListener("click", async () => {
  if (!confirm("Cancel processing? Completed files will keep their embedded lyrics.")) return;
  await api("POST", "/process/cancel");
});

$("btn-export").addEventListener("click", () => {
  window.location.href = "/results/export";
});

$("btn-clear-log").addEventListener("click", () => {
  $("log-list").innerHTML = "";
});

// ── Settings ───────────────────────────────────────────────────────────────
async function loadSettings() {
  const s = await api("GET", "/settings");
  $("set-delay").value = s.delay_ms;
  $("set-fallback").checked = s.embed_unsynced_fallback;
  $("set-generate-lrc").checked = s.generate_lrc_files;
  $("set-report-folder").value = s.report_folder || "";
}

$("btn-save-settings").addEventListener("click", async () => {
  await api("POST", "/settings", {
    delay_ms: parseInt($("set-delay").value),
    embed_unsynced_fallback: $("set-fallback").checked,
    generate_lrc_files: $("set-generate-lrc").checked,
    report_folder: $("set-report-folder").value.trim()
  });
  showToast("Settings saved.", "success");
});

// ── SSE stream ─────────────────────────────────────────────────────────────
function connectSSE() {
  const es = new EventSource("/process/stream");
  es.onmessage = e => {
    const msg = JSON.parse(e.data);
    handleEvent(msg.type, msg.data);
  };
  es.onerror = () => {
    setTimeout(connectSSE, 3000);
    es.close();
  };
}

function handleEvent(type, data) {
  if (type === "status") {
    setBadge(data.status);
    updateButtons(data.status);
  }

  if (type === "scan_done") {
    $("btn-scan").disabled = false;
    $("btn-browse").disabled = false;
    setBadge("ready");
    updateButtons("ready");
    showScanSummary(data);
    allFiles = [];  // reset; will load from /results
  }

  if (type === "progress") {
    updateProgress(data);
    updateSidebarStats(data.counts);
    $("card-progress").style.display = "";
    $("card-log").style.display = "";
    $("np-track").textContent = data.title || data.current_file;
    $("np-artist").textContent = data.artist || "—";
  }

  if (type === "file_done") {
    addLogEntry(data.filename, data.outcome);
    updateSidebarStats(data.counts);
  }

  if (type === "done") {
    setBadge(data.status === "cancelled" ? "cancelled" : "done");
    updateButtons(data.status);
    stopTimer();
    $("np-track").textContent = "Processing complete";
    $("np-artist").textContent = "";
    updateSidebarStats(data.counts);
    showToast(data.status === "cancelled" ? "Processing cancelled." : "Done! All files processed.", "success");
    refreshResultsTable();
  }
}

// ── UI helpers ─────────────────────────────────────────────────────────────
function setBadge(status) {
  const badge = $("status-badge");
  badge.className = "badge " + status;
  const labels = {
    idle: "Idle", scanning: "Scanning…", ready: "Ready",
    processing: "Processing…", paused: "Paused",
    done: "Done", cancelled: "Cancelled"
  };
  badge.textContent = labels[status] || status;
}

function updateButtons(status) {
  const show = (id, visible) => $(id).style.display = visible ? "" : "none";
  show("btn-start",  status === "ready");
  show("btn-pause",  status === "processing");
  show("btn-resume", status === "paused");
  show("btn-cancel", status === "processing" || status === "paused");
}

function showScanSummary(data) {
  $("sum-total").textContent     = data.total.toLocaleString();
  $("sum-eligible").textContent  = data.eligible.toLocaleString();
  $("sum-skipped").textContent   = data.skipped.toLocaleString();
  const delay = parseInt($("set-delay").value) || 350;
  const estSec = Math.round(data.eligible * (delay / 1000 + 0.8));
  $("sum-est").textContent = fmtTime(estSec);
  $("card-summary").style.display = "";
}

function updateProgress(data) {
  const pct = data.total > 0 ? Math.round(data.processed / data.total * 100) : 0;
  $("progress-fill").style.width = pct + "%";
  $("prog-count").textContent = `${data.processed.toLocaleString()} / ${data.total.toLocaleString()}`;
  $("prog-pct").textContent = pct + "%";
  $("prog-time").textContent = fmtTime(data.elapsed) + " elapsed";
}

function updateSidebarStats(counts) {
  $("sidebar-stats").style.display = "";
  $("stat-synced").textContent   = (counts.synced_embedded  || 0).toLocaleString();
  $("stat-unsynced").textContent = (counts.unsynced_embedded || 0).toLocaleString();
  $("stat-notfound").textContent = (counts.not_found        || 0).toLocaleString();
  $("stat-failed").textContent   = (counts.failed           || 0).toLocaleString();
  $("stat-skipped").textContent  = (counts.skipped          || 0).toLocaleString();
}

let logCount = 0;
function addLogEntry(filename, outcome) {
  const list = $("log-list");
  const entry = document.createElement("div");
  entry.className = "log-entry";
  const now = new Date();
  const t = now.toTimeString().slice(0, 8);
  const labelMap = {
    SYNCED_EMBEDDED: "✓ Synced",
    UNSYNCED_EMBEDDED: "✓ Unsynced",
    NOT_FOUND: "— Not Found",
    FAILED: "✗ Failed",
    SKIPPED: "◌ Skipped"
  };
  entry.innerHTML = `
    <span class="log-time">${t}</span>
    <span class="log-file">${escHtml(filename)}</span>
    <span class="log-outcome ${outcome}">${labelMap[outcome] || outcome}</span>
  `;
  list.appendChild(entry);
  logCount++;
  // Auto-scroll
  const container = $("log-container");
  container.scrollTop = container.scrollHeight;
  // Cap at 500 entries
  if (logCount > 500) {
    list.removeChild(list.firstChild);
    logCount--;
  }
}

// ── Results table ──────────────────────────────────────────────────────────
async function refreshResultsTable() {
  const res = await api("GET", "/results");
  allFiles = res.files || [];
  renderTable();
}

function renderTable() {
  const search = ($("results-search").value || "").toLowerCase();
  const filter = $("results-filter").value;

  let rows = allFiles.filter(f => {
    if (filter && f.outcome !== filter && f.state !== filter) return false;
    if (search) {
      const hay = `${f.filename} ${f.artist} ${f.title}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  if (sortCol) {
    rows.sort((a, b) => {
      const av = (a[sortCol] || "").toLowerCase();
      const bv = (b[sortCol] || "").toLowerCase();
      return av < bv ? -sortDir : av > bv ? sortDir : 0;
    });
  }

  const tbody = $("results-body");
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No results match your filter.</td></tr>`;
    $("table-footer").textContent = "0 files";
    return;
  }

  tbody.innerHTML = rows.map(f => `
    <tr>
      <td title="${escHtml(f.filename)}">${escHtml(f.filename)}</td>
      <td title="${escHtml(f.artist)}">${escHtml(f.artist || "—")}</td>
      <td title="${escHtml(f.title)}">${escHtml(f.title || "—")}</td>
      <td><span class="chip ${f.state}">${f.state || "—"}</span></td>
      <td>${f.outcome ? `<span class="chip ${f.outcome}">${fmt_outcome(f.outcome)}</span>` : "<span class='chip EMPTY'>Pending</span>"}</td>
    </tr>
  `).join("");

  $("table-footer").textContent = `${rows.length.toLocaleString()} of ${allFiles.length.toLocaleString()} files`;
}

function fmt_outcome(o) {
  return {
    SYNCED_EMBEDDED: "Synced ✓",
    UNSYNCED_EMBEDDED: "Unsynced ✓",
    NOT_FOUND: "Not Found",
    FAILED: "Failed",
    SKIPPED: "Skipped"
  }[o] || o;
}

// Sort
$$("thead th[data-sort]").forEach(th => {
  th.addEventListener("click", () => {
    const col = th.dataset.sort;
    if (sortCol === col) sortDir = -sortDir;
    else { sortCol = col; sortDir = 1; }
    $$("thead th").forEach(t => t.classList.remove("sort-asc", "sort-desc"));
    th.classList.add(sortDir === 1 ? "sort-asc" : "sort-desc");
    renderTable();
  });
});

// Search + filter
$("results-search").addEventListener("input", renderTable);
$("results-filter").addEventListener("change", renderTable);

// ── Timer ──────────────────────────────────────────────────────────────────
function startTimer() {
  stopTimer();
  timerInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - sessionStart) / 1000);
    $("prog-time").textContent = fmtTime(elapsed) + " elapsed";
  }, 1000);
}
function stopTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
}

function fmtTime(s) {
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  const sec = s % 60;
  if (m < 60) return `${m}m ${sec}s`;
  return `${Math.floor(m/60)}h ${m%60}m`;
}

// ── Toast ──────────────────────────────────────────────────────────────────
let toastTimer;
function showToast(msg, type = "") {
  let toast = $("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.className = "show " + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.className = type; }, 3000);
}

// ── Utilities ──────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  return res.json();
}

function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Init ───────────────────────────────────────────────────────────────────
connectSSE();
loadSettings();
