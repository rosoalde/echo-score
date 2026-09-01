// =============================
// CONFIG
// =============================

const API_URL = "/api/analyses";

let state = {
    page: 1,
    page_size: 25,
    search: "",
    status_filter: "",
    user_id: ""
};

let currentDetailId = null;

const STATUS_STYLES = {
    draft: "bg-secondary",
    active: "bg-primary",
    completed: "bg-success",
    archived: "bg-dark",
    error: "bg-danger",
    cancelled: "bg-warning text-dark"
};


// =============================
// INIT
// =============================

document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadSummary();
    loadAnalyses();
});

function bindEvents() {

    document.getElementById("searchInput").addEventListener("input", debounce(e => {
        state.search = e.target.value;
        state.page = 1;
        loadAnalyses();
    }, 400));

    document.getElementById("filterStatus").addEventListener("change", e => {
        state.status_filter = e.target.value;
        state.page = 1;
        loadAnalyses();
    });

    document.getElementById("filterUserId").addEventListener("input", debounce(e => {
        state.user_id = e.target.value;
        state.page = 1;
        loadAnalyses();
    }, 400));

    document.getElementById("reloadAnalyses").addEventListener("click", () => {
        loadSummary();
        loadAnalyses();
    });

    document.getElementById("saveStatusBtn").addEventListener("click", saveStatus);
}


// =============================
// SUMMARY
// =============================

async function loadSummary() {

    try {
        const res = await fetch("/api/analyses/summary");
        const data = await res.json();

        const container = document.getElementById("statusSummary");
        container.innerHTML = "";

        const total = document.createElement("div");
        total.className = "col";
        total.innerHTML = `
            <div class="p-2 rounded-3 bg-light">
                <div class="fs-4 fw-bold">${data.total ?? 0}</div>
                <div class="text-muted small">Total</div>
            </div>`;
        container.appendChild(total);

        Object.entries(data.by_status || {}).forEach(([status, count]) => {
            const col = document.createElement("div");
            col.className = "col";
            col.innerHTML = `
                <div class="p-2 rounded-3 bg-light">
                    <div class="fs-4 fw-bold">${count}</div>
                    <div class="text-muted small text-capitalize">${status}</div>
                </div>`;
            container.appendChild(col);
        });

    } catch (err) {
        console.error("Error cargando resumen de análisis", err);
    }
}


// =============================
// LOAD LIST
// =============================

async function loadAnalyses() {

    showLoading(true);

    try {

        const params = new URLSearchParams({
            page: state.page,
            page_size: state.page_size,
            search: state.search,
            status_filter: state.status_filter
        });

        if (state.user_id) params.set("user_id", state.user_id);

        const res = await fetch(`${API_URL}?${params.toString()}`);
        const data = await res.json();

        renderTable(data.items || []);
        renderPagination(data.total_pages || 1);

        document.getElementById("tableSummary").textContent =
            `Mostrando ${(data.items || []).length} de ${data.total ?? 0} análisis`;

        document.getElementById("lastRefresh").textContent =
            "Actualizado: " + new Date().toLocaleTimeString();

    } catch (err) {
        console.error("Error cargando análisis", err);
    } finally {
        showLoading(false);
    }
}


// =============================
// RENDER
// =============================

function renderTable(analyses) {

    const tbody = document.getElementById("analysesTableBody");
    tbody.innerHTML = "";

    if (!analyses.length) {
        document.getElementById("emptyState").style.display = "block";
        document.getElementById("tableContainer").style.display = "none";
        return;
    }

    document.getElementById("emptyState").style.display = "none";
    document.getElementById("tableContainer").style.display = "block";

    const template = document.getElementById("analysisRowTemplate");

    analyses.forEach(a => {

        const row = template.content.cloneNode(true);

        row.querySelector(".a-id").textContent = `#${a.id}`;
        row.querySelector(".a-name").textContent = a.project_name;
        row.querySelector(".a-slug").textContent = a.slug;
        row.querySelector(".a-user").textContent = a.username ? `@${a.username}` : "—";

        const statusBadge = row.querySelector(".a-status");
        statusBadge.textContent = a.status;
        statusBadge.className = `badge a-status ${STATUS_STYLES[a.status] || "bg-secondary"}`;

        const bar = row.querySelector(".a-progress-bar");
        bar.style.width = `${a.progress_percent || 0}%`;
        bar.textContent = `${a.progress_percent || 0}%`;

        const tasksLink = row.querySelector(".a-tasks-link");
        tasksLink.textContent = `${a.tasks_count} tareas`;
        tasksLink.href = `/tasks?analysis_id=${a.id}`;

        row.querySelector(".a-created").textContent = a.created_at
            ? new Date(a.created_at).toLocaleString() : "—";

        row.querySelector(".btn-detail").addEventListener("click", () => openDetail(a.id));

        const archiveBtn = row.querySelector(".btn-archive");
        const restoreBtn = row.querySelector(".btn-restore");

        archiveBtn.disabled = a.status === "archived";
        archiveBtn.addEventListener("click", () => changeStatus(a.id, "archived"));

        restoreBtn.disabled = a.status !== "archived";
        restoreBtn.addEventListener("click", () => changeStatus(a.id, "active"));

        row.querySelector(".btn-delete").addEventListener("click", () => deleteAnalysis(a.id));

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
            loadAnalyses();
        });
        el.appendChild(li);
    }
}


// =============================
// DETAIL
// =============================

async function openDetail(id) {

    const res = await fetch(`${API_URL}/${id}`);
    const a = await res.json();

    if (!res.ok) {
        alert(a.error || "No se pudo cargar el detalle del análisis");
        return;
    }

    currentDetailId = id;

    document.getElementById("detailName").textContent = a.project_name;
    document.getElementById("detailSlug").textContent = a.slug;
    document.getElementById("detailUser").textContent = a.username ? `@${a.username} (#${a.user_id})` : "—";
    document.getElementById("detailProgress").textContent = a.progress_percent || 0;
    document.getElementById("detailFolder").textContent = a.output_folder || "—";
    document.getElementById("detailCreated").textContent = a.created_at ? new Date(a.created_at).toLocaleString() : "—";
    document.getElementById("detailStatusSelect").value = a.status;

    document.getElementById("detailConfig").textContent =
        a.analysis_config && Object.keys(a.analysis_config).length
            ? JSON.stringify(a.analysis_config, null, 2) : "(vacío)";

    const tasksEl = document.getElementById("detailTasks");
    tasksEl.innerHTML = "";

    if (!a.tasks || !a.tasks.length) {
        tasksEl.innerHTML = '<span class="text-muted">Este análisis no tiene tareas asociadas.</span>';
    } else {
        a.tasks.forEach(t => {
            const div = document.createElement("div");
            div.className = "d-flex justify-content-between align-items-center border-bottom py-2 small";
            div.innerHTML = `
                <div>
                    <span class="badge ${STATUS_STYLES[t.status] || "bg-secondary"}">${t.status}</span>
                    #${t.id} · ${t.task_type}
                </div>
                <div class="text-muted">${t.progress_percent || 0}%</div>
            `;
            tasksEl.appendChild(div);
        });
    }

    bootstrap.Modal.getOrCreateInstance(document.getElementById("analysisDetailModal")).show();
}

async function saveStatus() {

    if (!currentDetailId) return;

    const newStatus = document.getElementById("detailStatusSelect").value;

    await changeStatus(currentDetailId, newStatus, /*fromModal*/ true);
}


// =============================
// ACTIONS
// =============================

async function changeStatus(id, newStatus, fromModal = false) {

    const res = await fetch(`${API_URL}/${id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus })
    });

    const data = await res.json();

    if (!res.ok) {
        alert(data.error || "Error cambiando el estado");
        return;
    }

    loadSummary();
    loadAnalyses();

    if (fromModal) {
        bootstrap.Modal.getInstance(document.getElementById("analysisDetailModal"))?.hide();
    }
}

async function deleteAnalysis(id) {

    if (!confirm(
        `¿Eliminar el registro del análisis #${id}?\n\n` +
        `Esto borra la fila en base de datos (y sus tareas/logs asociados), ` +
        `pero NO borra la carpeta en disco.`
    )) return;

    const res = await fetch(`${API_URL}/${id}`, { method: "DELETE" });
    const data = await res.json();

    if (!res.ok) {
        alert(data.error || "Error eliminando el análisis");
        return;
    }

    if (data.warning) console.warn(data.warning);

    loadSummary();
    loadAnalyses();
}


// =============================
// HELPERS
// =============================

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
