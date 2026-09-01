// =============================
// CONFIG
// =============================

const API_URL = "/api/logs";

let state = {
    page: 1,
    page_size: 25,
    search: "",
    level: "",
    task_id: "",
    date_from: "",
    date_to: ""
};

const LEVEL_STYLES = {
    DEBUG: "bg-secondary",
    INFO: "bg-info text-dark",
    WARNING: "bg-warning text-dark",
    ERROR: "bg-danger",
    CRITICAL: "bg-dark"
};


// =============================
// INIT
// =============================

document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadSummary();
    loadLogs();
});

function bindEvents() {

    document.getElementById("searchInput").addEventListener("input", debounce(e => {
        state.search = e.target.value;
        state.page = 1;
        loadLogs();
    }, 400));

    document.getElementById("filterLevel").addEventListener("change", e => {
        state.level = e.target.value;
        state.page = 1;
        loadLogs();
    });

    document.getElementById("filterTaskId").addEventListener("input", debounce(e => {
        state.task_id = e.target.value;
        state.page = 1;
        loadLogs();
    }, 400));

    document.getElementById("filterDateFrom").addEventListener("change", e => {
        state.date_from = e.target.value;
        state.page = 1;
        loadLogs();
    });

    document.getElementById("filterDateTo").addEventListener("change", e => {
        state.date_to = e.target.value;
        state.page = 1;
        loadLogs();
    });

    document.getElementById("pageSize").addEventListener("change", e => {
        state.page_size = parseInt(e.target.value);
        state.page = 1;
        loadLogs();
    });

    document.getElementById("reloadLogs").addEventListener("click", () => {
        loadSummary();
        loadLogs();
    });

    document.getElementById("resetFilters").addEventListener("click", resetFilters);

    document.getElementById("purgeLogsBtn").addEventListener("click", () => {
        document.getElementById("purgeError").classList.add("d-none");
        bootstrap.Modal.getOrCreateInstance(document.getElementById("purgeLogsModal")).show();
    });

    document.getElementById("confirmPurgeBtn").addEventListener("click", purgeLogs);
}


// =============================
// LOAD LOGS
// =============================

async function loadLogs() {

    showLoading(true);

    try {

        const params = new URLSearchParams({
            page: state.page,
            page_size: state.page_size,
            search: state.search,
            level: state.level,
            date_from: state.date_from,
            date_to: state.date_to
        });

        if (state.task_id) params.set("task_id", state.task_id);

        const res = await fetch(`${API_URL}?${params.toString()}`);
        const data = await res.json();

        renderTable(data.items || []);
        renderPagination(data.total_pages || 1);
        updateSummaryLine(data);

        document.getElementById("lastRefresh").textContent =
            "Actualizado: " + new Date().toLocaleTimeString();

    } catch (err) {
        console.error("Error cargando logs", err);
    } finally {
        showLoading(false);
    }
}

async function loadSummary() {

    try {
        const res = await fetch("/api/logs/summary");
        const data = await res.json();

        document.getElementById("summaryTotal").textContent = data.total ?? 0;
        document.getElementById("summaryError").textContent =
            (data.by_level && data.by_level.ERROR) || 0;
        document.getElementById("summaryWarning").textContent =
            (data.by_level && data.by_level.WARNING) || 0;
        document.getElementById("summary24h").textContent = data.last_24h ?? 0;

    } catch (err) {
        console.error("Error cargando el resumen de logs", err);
    }
}


// =============================
// RENDER
// =============================

function renderTable(logs) {

    const tbody = document.getElementById("logsTableBody");
    tbody.innerHTML = "";

    if (!logs.length) {
        document.getElementById("emptyState").style.display = "block";
        document.getElementById("tableContainer").style.display = "none";
        return;
    }

    document.getElementById("emptyState").style.display = "none";
    document.getElementById("tableContainer").style.display = "block";

    const template = document.getElementById("logRowTemplate");

    logs.forEach(log => {

        const row = template.content.cloneNode(true);

        row.querySelector(".log-id").textContent = `#${log.id}`;

        const levelBadge = row.querySelector(".log-level");
        levelBadge.textContent = log.level || "INFO";
        levelBadge.className = `badge log-level ${LEVEL_STYLES[log.level] || "bg-secondary"}`;

        row.querySelector(".log-message").textContent = log.message || "";

        const taskCell = row.querySelector(".log-task");
        if (log.task_id) {
            taskCell.innerHTML = `
                <div>#${log.task_id}</div>
                <small class="text-muted">${log.task_type || ""}${log.task_status ? " · " + log.task_status : ""}</small>
            `;
        } else {
            taskCell.innerHTML = '<span class="text-muted">—</span>';
        }

        row.querySelector(".log-created").textContent = log.created_at
            ? new Date(log.created_at).toLocaleString()
            : "—";

        row.querySelector(".btn-detail").addEventListener("click", () => openDetail(log));

        tbody.appendChild(row);
    });
}

function renderPagination(totalPages) {

    const el = document.getElementById("pagination");
    el.innerHTML = "";

    for (let i = 1; i <= totalPages; i++) {
        const li = document.createElement("li");
        li.className = `page-item ${i === state.page ? "active" : ""}`;
        li.innerHTML = `<a class="page-link" href="#">${i}</a>`;
        li.addEventListener("click", (e) => {
            e.preventDefault();
            state.page = i;
            loadLogs();
        });
        el.appendChild(li);
    }
}

function updateSummaryLine(data) {
    const shown = (data.items || []).length;
    document.getElementById("tableSummary").textContent =
        `Mostrando ${shown} de ${data.total ?? 0} logs`;
}


// =============================
// DETAIL MODAL
// =============================

function openDetail(log) {

    document.getElementById("detailMessage").textContent = log.message || "(sin mensaje)";

    const meta = log.meta_data && Object.keys(log.meta_data).length
        ? JSON.stringify(log.meta_data, null, 2)
        : "(sin metadata)";

    document.getElementById("detailMeta").textContent = meta;

    bootstrap.Modal.getOrCreateInstance(document.getElementById("logDetailModal")).show();
}


// =============================
// PURGE
// =============================

async function purgeLogs() {

    const days = parseInt(document.getElementById("purgeDays").value) || 30;

    try {
        const res = await fetch(`/api/logs/purge?days=${days}`, { method: "DELETE" });
        const data = await res.json();

        if (!res.ok) throw data;

        bootstrap.Modal.getInstance(document.getElementById("purgeLogsModal")).hide();
        loadSummary();
        loadLogs();

    } catch (err) {
        const el = document.getElementById("purgeError");
        el.textContent = err.error || "Error purgando los logs";
        el.classList.remove("d-none");
    }
}


// =============================
// FILTERS / HELPERS
// =============================

function resetFilters() {

    state = { page: 1, page_size: 25, search: "", level: "", task_id: "", date_from: "", date_to: "" };

    document.getElementById("searchInput").value = "";
    document.getElementById("filterLevel").value = "";
    document.getElementById("filterTaskId").value = "";
    document.getElementById("filterDateFrom").value = "";
    document.getElementById("filterDateTo").value = "";
    document.getElementById("pageSize").value = "25";

    loadLogs();
}

function showLoading(show) {
    document.getElementById("tableLoading").style.display = show ? "block" : "none";
    if (show) document.getElementById("tableContainer").style.display = "none";
}

function debounce(fn, delay) {
    let t;
    return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), delay);
    };
}