// =============================
// CONFIG
// =============================

const API_URL = "/api/tasks";

let state = {
    page: 1,
    page_size: 25,
    search: "",
    status_filter: "",
    task_type: "",
    analysis_id: "",
    user_id: ""
};

const STATUS_STYLES = {
    pending: "bg-secondary",
    queued: "bg-info text-dark",
    running: "bg-primary",
    paused: "bg-warning text-dark",
    completed: "bg-success",
    failed: "bg-danger",
    cancelled: "bg-dark",
    retrying: "bg-warning text-dark"
};


// =============================
// INIT
// =============================

document.addEventListener("DOMContentLoaded", () => {
    bindEvents();

    const params = new URLSearchParams(window.location.search);
    const analysisId = params.get("analysis_id");
    if (analysisId) {
        state.analysis_id = analysisId;
        document.getElementById("filterAnalysisId").value = analysisId;
    }

    loadWorkers();
    loadSummary();
    loadTasks();
});

function bindEvents() {

    document.getElementById("searchInput").addEventListener("input", debounce(e => {
        state.search = e.target.value;
        state.page = 1;
        loadTasks();
    }, 400));

    document.getElementById("filterStatus").addEventListener("change", e => {
        state.status_filter = e.target.value;
        state.page = 1;
        loadTasks();
    });

    document.getElementById("filterType").addEventListener("change", e => {
        state.task_type = e.target.value;
        state.page = 1;
        loadTasks();
    });

    document.getElementById("filterAnalysisId").addEventListener("input", debounce(e => {
        state.analysis_id = e.target.value;
        state.page = 1;
        loadTasks();
    }, 400));

    document.getElementById("filterUserId").addEventListener("input", debounce(e => {
        state.user_id = e.target.value;
        state.page = 1;
        loadTasks();
    }, 400));

    document.getElementById("reloadTasks").addEventListener("click", () => {
        loadSummary();
        loadTasks();
    });

    document.getElementById("refreshWorkers").addEventListener("click", loadWorkers);
}


// =============================
// WORKERS
// =============================

async function loadWorkers() {

    const container = document.getElementById("workersContainer");
    container.innerHTML = '<div class="col-12 text-muted">Comprobando workers...</div>';

    try {
        const res = await fetch("/api/workers");
        const data = await res.json();

        const workers = data.workers || [];

        if (!workers.length) {
            container.innerHTML = `
                <div class="col-12">
                    <div class="alert alert-warning mb-0">
                        <i class="bi bi-exclamation-triangle"></i>
                        No se detecta ningún worker de Celery activo.
                    </div>
                </div>`;
            return;
        }

        container.innerHTML = "";

        workers.forEach(w => {
            const col = document.createElement("div");
            col.className = "col-md-4";
            col.innerHTML = `
                <div class="border rounded-3 p-3 d-flex justify-content-between align-items-center">
                    <div>
                        <div class="fw-bold">${w.name}</div>
                        <div class="small text-muted">
                            ${w.active_tasks} activas · ${w.reserved_tasks} en cola
                            ${w.concurrency ? " · concurrencia " + w.concurrency : ""}
                        </div>
                    </div>
                    <span class="badge ${w.online ? "bg-success" : "bg-danger"}">
                        ${w.online ? "Online" : "Offline"}
                    </span>
                </div>`;
            container.appendChild(col);
        });

    } catch (err) {
        container.innerHTML = `
            <div class="col-12">
                <div class="alert alert-danger mb-0">
                    Error comprobando workers: ${err}
                </div>
            </div>`;
    }
}


// =============================
// SUMMARY
// =============================

async function loadSummary() {

    try {
        const res = await fetch("/api/tasks/summary");
        const data = await res.json();

        const container = document.getElementById("statusSummary");
        container.innerHTML = "";

        const byStatus = data.by_status || {};

        const total = document.createElement("div");
        total.className = "col";
        total.innerHTML = `
            <div class="p-2 rounded-3 bg-light">
                <div class="fs-4 fw-bold">${data.total ?? 0}</div>
                <div class="text-muted small">Total</div>
            </div>`;
        container.appendChild(total);

        Object.entries(byStatus).forEach(([status, count]) => {
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
        console.error("Error cargando resumen de tareas", err);
    }
}


// =============================
// LOAD TASKS
// =============================

async function loadTasks() {

    showLoading(true);

    try {

        const params = new URLSearchParams({
            page: state.page,
            page_size: state.page_size,
            search: state.search,
            status_filter: state.status_filter,
            task_type: state.task_type
        });

        if (state.analysis_id) params.set("analysis_id", state.analysis_id);
        if (state.user_id) params.set("user_id", state.user_id);

        const res = await fetch(`${API_URL}?${params.toString()}`);
        const data = await res.json();

        renderTable(data.items || []);
        renderPagination(data.total_pages || 1);

        document.getElementById("tableSummary").textContent =
            `Mostrando ${(data.items || []).length} de ${data.total ?? 0} tareas`;

        document.getElementById("lastRefresh").textContent =
            "Actualizado: " + new Date().toLocaleTimeString();

    } catch (err) {
        console.error("Error cargando tareas", err);
    } finally {
        showLoading(false);
    }
}


// =============================
// RENDER
// =============================

function renderTable(tasks) {

    const tbody = document.getElementById("tasksTableBody");
    tbody.innerHTML = "";

    if (!tasks.length) {
        document.getElementById("emptyState").style.display = "block";
        document.getElementById("tableContainer").style.display = "none";
        return;
    }

    document.getElementById("emptyState").style.display = "none";
    document.getElementById("tableContainer").style.display = "block";

    const template = document.getElementById("taskRowTemplate");

    tasks.forEach(task => {

        const row = template.content.cloneNode(true);

        row.querySelector(".task-id").textContent = `#${task.id}`;
        row.querySelector(".task-type").textContent = task.task_type || "—";

        const statusBadge = row.querySelector(".task-status");
        statusBadge.textContent = task.status || "—";
        statusBadge.className = `badge task-status ${STATUS_STYLES[task.status] || "bg-secondary"}`;

        const bar = row.querySelector(".task-progress-bar");
        bar.style.width = `${task.progress_percent || 0}%`;
        bar.textContent = `${task.progress_percent || 0}%`;
        if (task.status === "failed") bar.classList.add("bg-danger");

        row.querySelector(".task-owner").innerHTML = `
            ${task.analysis_name ? `<div>${task.analysis_name}</div>` : ""}
            ${task.username ? `<div class="text-muted">@${task.username}</div>` : ""}
            ${!task.analysis_name && !task.username ? "—" : ""}
        `;

        row.querySelector(".task-updated").textContent = task.finished_at
            ? new Date(task.finished_at).toLocaleString()
            : (task.started_at ? new Date(task.started_at).toLocaleString() : new Date(task.created_at).toLocaleString());

        row.querySelector(".btn-detail").addEventListener("click", () => openDetail(task.id));

        const retryBtn = row.querySelector(".btn-retry");
        const revokeBtn = row.querySelector(".btn-revoke");

        // reintentar solo tiene sentido si terminó mal
        retryBtn.disabled = !["failed", "cancelled"].includes(task.status);
        retryBtn.addEventListener("click", () => retryTask(task.id));

        // revocar solo tiene sentido si sigue en marcha
        revokeBtn.disabled = !["pending", "queued", "running", "retrying"].includes(task.status);
        revokeBtn.addEventListener("click", () => revokeTask(task.id));

        row.querySelector(".btn-delete").addEventListener("click", () => deleteTask(task.id));

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
            loadTasks();
        });
        el.appendChild(li);
    }
}


// =============================
// DETAIL
// =============================

async function openDetail(id) {

    const res = await fetch(`${API_URL}/${id}`);
    const task = await res.json();

    if (!res.ok) {
        alert(task.error || "No se pudo cargar el detalle de la tarea");
        return;
    }

    document.getElementById("detailTaskId").textContent = `#${task.id}`;
    document.getElementById("detailStatus").textContent = task.status;
    document.getElementById("detailType").textContent = task.task_type;
    document.getElementById("detailAnalysis").textContent =
        task.analysis_name ? `${task.analysis_name} (#${task.analysis_id})` : "—";
    document.getElementById("detailUser").textContent =
        task.username ? `@${task.username} (#${task.user_id})` : "—";
    document.getElementById("detailCeleryId").textContent = task.celery_task_id || "—";
    document.getElementById("detailStep").textContent = task.current_step || "—";

    const errorWrapper = document.getElementById("detailErrorWrapper");
    if (task.error_message) {
        errorWrapper.style.display = "block";
        document.getElementById("detailError").textContent = task.error_message;
    } else {
        errorWrapper.style.display = "none";
    }

    document.getElementById("detailInput").textContent =
        task.input_config && Object.keys(task.input_config).length
            ? JSON.stringify(task.input_config, null, 2) : "(vacío)";

    document.getElementById("detailOutput").textContent =
        task.output_summary && Object.keys(task.output_summary).length
            ? JSON.stringify(task.output_summary, null, 2) : "(vacío)";

    const logsEl = document.getElementById("detailLogs");
    logsEl.innerHTML = "";
    if (!task.logs || !task.logs.length) {
        logsEl.innerHTML = '<span class="text-muted">Sin logs para esta tarea.</span>';
    } else {
        task.logs.forEach(l => {
            const div = document.createElement("div");
            div.className = "mb-1 small";
            div.innerHTML = `
                <span class="badge ${STATUS_STYLES[l.level?.toLowerCase()] || "bg-secondary"}">${l.level}</span>
                <span class="text-muted">${new Date(l.created_at).toLocaleString()}</span>
                — ${l.message}`;
            logsEl.appendChild(div);
        });
    }

    bootstrap.Modal.getOrCreateInstance(document.getElementById("taskDetailModal")).show();
}


// =============================
// ACTIONS
// =============================

async function retryTask(id) {

    if (!confirm(`¿Reintentar la tarea #${id}? Se relanzará con los mismos datos de entrada.`)) return;

    const res = await fetch(`${API_URL}/${id}/retry`, { method: "POST" });
    const data = await res.json();

    if (!res.ok) {
        alert(data.error || "Error al reintentar la tarea");
        return;
    }

    loadSummary();
    loadTasks();
}

async function revokeTask(id) {

    if (!confirm(`¿Revocar/matar la tarea #${id}? Se intentará detener el proceso en el worker.`)) return;

    const res = await fetch(`${API_URL}/${id}/revoke`, { method: "POST" });
    const data = await res.json();

    if (!res.ok) {
        alert(data.error || "Error al revocar la tarea");
        return;
    }

    loadSummary();
    loadTasks();
}

async function deleteTask(id) {

    if (!confirm(`¿Eliminar el registro de la tarea #${id}? Esto NO detiene procesos activos, solo borra el registro.`)) return;

    const res = await fetch(`${API_URL}/${id}`, { method: "DELETE" });
    const data = await res.json();

    if (!res.ok) {
        alert(data.error || "Error al eliminar la tarea");
        return;
    }

    loadSummary();
    loadTasks();
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
