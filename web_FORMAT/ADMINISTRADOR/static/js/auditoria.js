// =============================
// CONFIG
// =============================

const API_URL = "/api/audit";

let state = {
    page: 1,
    page_size: 25,
    search: "",
    event_type: "",
    category: "",
    result_filter: "",
    actor_type: "",
    actor_username: "",
    date_from: "",
    date_to: ""
};

const RESULT_STYLES = {
    success: "bg-success",
    failure: "bg-danger",
    warning: "bg-warning text-dark"
};

const CATEGORY_LABELS = {
    auth: "auth",
    user: "user",
    project: "project",
    permissions: "permissions",
    security: "security",
    system: "system",
    keywords: "keywords",
    aceptacion: "aceptacion"
};

const CATEGORY_STYLES = {
    auth: "bg-primary",
    user: "bg-info text-dark",
    project: "bg-success",
    permissions: "bg-warning text-dark",
    security: "bg-danger",
    system: "bg-secondary",
    keywords: "bg-dark",
    aceptacion: "bg-aceptacion"
};

const ACTOR_STYLES = {
    user: "bg-primary",
    admin: "bg-dark",
    system: "bg-secondary"
};


// =============================
// INIT
// =============================

document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadSummary();
    loadAudit();
});

function bindEvents() {

    document.getElementById("searchInput").addEventListener("input", debounce(e => {
        state.search = e.target.value;
        state.page = 1;
        loadAudit();
    }, 400));

    document.getElementById("filterCategory").addEventListener("change", e => {
        state.category = e.target.value;
        state.page = 1;
        loadAudit();
    });

    document.getElementById("filterResult").addEventListener("change", e => {
        state.result_filter = e.target.value;
        state.page = 1;
        loadAudit();
    });

    document.getElementById("filterActorType").addEventListener("change", e => {
        state.actor_type = e.target.value;
        state.page = 1;
        loadAudit();
    });

    document.getElementById("filterActorUsername").addEventListener("input", debounce(e => {
        state.actor_username = e.target.value;
        state.page = 1;
        loadAudit();
    }, 400));

    document.getElementById("filterEventType").addEventListener("change", e => {
        state.event_type = e.target.value;
        state.page = 1;
        loadAudit();
    });

    document.getElementById("filterDateFrom").addEventListener("change", e => {
        state.date_from = e.target.value;
        state.page = 1;
        loadAudit();
    });

    document.getElementById("filterDateTo").addEventListener("change", e => {
        state.date_to = e.target.value;
        state.page = 1;
        loadAudit();
    });

    document.getElementById("pageSize").addEventListener("change", e => {
        state.page_size = parseInt(e.target.value);
        state.page = 1;
        loadAudit();
    });

    document.getElementById("reloadAudit").addEventListener("click", () => {
        loadSummary();
        loadAudit();
    });

    document.getElementById("resetFilters").addEventListener("click", resetFilters);

    document.getElementById("purgeBlobsBtn").addEventListener("click", () => {
        document.getElementById("purgeError").classList.add("d-none");
        bootstrap.Modal.getOrCreateInstance(document.getElementById("purgeBlobsModal")).show();
    });

    document.getElementById("confirmPurgeBtn").addEventListener("click", purgeBlobs);
}


// =============================
// LOAD
// =============================

async function loadAudit() {

    showLoading(true);

    try {

        const params = new URLSearchParams({
            page: state.page,
            page_size: state.page_size,
            search: state.search,
            event_type: state.event_type,
            category: state.category,
            result_filter: state.result_filter,
            actor_type: state.actor_type,
            actor_username: state.actor_username,
            date_from: state.date_from,
            date_to: state.date_to
        });

        const res = await fetch(`${API_URL}?${params.toString()}`);
        const data = await res.json();

        renderTable(data.items || []);
        renderPagination(data.total_pages || 1);
        updateSummaryLine(data);

        document.getElementById("lastRefresh").textContent =
            "Actualizado: " + new Date().toLocaleTimeString();

    } catch (err) {
        console.error("Error cargando auditoría", err);
    } finally {
        showLoading(false);
    }
}

async function loadSummary() {

    try {
        const res = await fetch("/api/audit/summary");
        const data = await res.json();

        document.getElementById("summaryTotal").textContent = data.total ?? 0;
        document.getElementById("summaryFailure").textContent =
            (data.by_result && data.by_result.failure) || 0;
        document.getElementById("summarySecurity").textContent = data.security_events ?? 0;
        document.getElementById("summary24h").textContent = data.last_24h ?? 0;

    } catch (err) {
        console.error("Error cargando el resumen de auditoría", err);
    }
}


// =============================
// RENDER
// =============================

function renderTable(items) {

    const tbody = document.getElementById("auditTableBody");
    tbody.innerHTML = "";

    if (!items.length) {
        document.getElementById("emptyState").style.display = "block";
        document.getElementById("tableContainer").style.display = "none";
        return;
    }

    document.getElementById("emptyState").style.display = "none";
    document.getElementById("tableContainer").style.display = "block";

    const template = document.getElementById("auditRowTemplate");

    items.forEach(item => {

        const row = template.content.cloneNode(true);

        row.querySelector(".a-id").textContent = `#${item.id}`;
        row.querySelector(".a-event").textContent = item.event_type;

        const resultBadge = row.querySelector(".a-result");
        resultBadge.textContent = item.result;
        resultBadge.className = `badge a-result ${RESULT_STYLES[item.result] || "bg-secondary"}`;

        const categoryBadge = row.querySelector(".a-category");
        categoryBadge.textContent = item.category;
        categoryBadge.className = `badge a-category ${CATEGORY_STYLES[item.category] || "bg-light text-dark border"}`;

        const actorBadge = row.querySelector(".a-actor-type");
        actorBadge.textContent = item.actor_type;
        actorBadge.className = `badge a-actor-type ${ACTOR_STYLES[item.actor_type] || "bg-secondary"}`;

        row.querySelector(".a-actor-name").textContent =
            item.actor_username ? `@${item.actor_username}` : (item.actor_id ? `#${item.actor_id}` : "—");

        const short_message = item.message && item.message.length > 120
            ? item.message.substring(0, 50) + "..."
            : (item.message || "");
        
        row.querySelector(".a-message").textContent = short_message;

        row.querySelector(".a-target").textContent = item.target_type
            ? `${item.target_type}${item.target_label ? ": " + item.target_label : ""}${item.target_id ? " (#" + item.target_id + ")" : ""}`
            : "—";

        row.querySelector(".a-ip").textContent = item.ip_address
            ? `${item.ip_address}${item.port_address ? ":" + item.port_address : ""}`
            : "—";

        row.querySelector(".a-created").textContent = item.created_at
            ? new Date(item.created_at).toLocaleString()
            : "—";

        row.querySelector(".btn-detail").addEventListener("click", () => openDetail(item.id));

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
            loadAudit();
        });
        el.appendChild(li);
    }
}

function updateSummaryLine(data) {
    const shown = (data.items || []).length;
    document.getElementById("tableSummary").textContent =
        `Mostrando ${shown} de ${data.total ?? 0} eventos`;
}


// =============================
// DETAIL MODAL
// =============================

async function openDetail(id) {

    const res = await fetch(`${API_URL}/${id}`);
    const item = await res.json();

    if (!res.ok) {
        alert(item.error || "No se pudo cargar el detalle del evento");
        return;
    }

    document.getElementById("detailId").textContent = `#${item.id}`;
    document.getElementById("detailEvent").textContent = `${item.event_type} (${item.category})`;
    document.getElementById("detailResult").textContent = item.result;
    document.getElementById("detailActor").textContent =
        `${item.actor_type}${item.actor_username ? " · @" + item.actor_username : ""}${item.actor_id ? " (#" + item.actor_id + ")" : ""}`;
    document.getElementById("detailTarget").textContent = item.target_type
        ? `${item.target_type}${item.target_label ? ": " + item.target_label : ""}${item.target_id ? " (#" + item.target_id + ")" : ""}`
        : "—";
    document.getElementById("detailIp").textContent = item.ip_address || "—";
    document.getElementById("detailPort").textContent = item.port_address ?? "—";
    document.getElementById("detailUA").textContent = item.user_agent || "—";
    document.getElementById("detailSession").textContent = item.session_id || "—";
    document.getElementById("detailRequestId").textContent = item.request_id || "—";
    document.getElementById("detailMessage").textContent = item.message || "(sin mensaje)";

    document.getElementById("detailAttachmentBadge").style.display = item.has_attachment ? "inline-block" : "none";

    const details = item.details && Object.keys(item.details).length
        ? JSON.stringify(item.details, null, 2)
        : "(sin detalles adicionales)";

    document.getElementById("detailMeta").textContent = details;

    bootstrap.Modal.getOrCreateInstance(document.getElementById("auditDetailModal")).show();
}


// =============================
// PURGE (solo ficheros pesados, nunca filas)
// =============================

async function purgeBlobs() {

    const days = parseInt(document.getElementById("purgeDays").value) || 180;

    try {
        const res = await fetch(`/api/audit/purge-blobs?days=${days}`, { method: "DELETE" });
        const data = await res.json();

        if (!res.ok) throw data;

        bootstrap.Modal.getInstance(document.getElementById("purgeBlobsModal")).hide();
        loadSummary();
        loadAudit();

    } catch (err) {
        const el = document.getElementById("purgeError");
        el.textContent = err.error || "Error purgando los ficheros";
        el.classList.remove("d-none");
    }
}


// =============================
// FILTERS / HELPERS
// =============================

function resetFilters() {

    state = {
        page: 1, page_size: 25, search: "", event_type: "", category: "",
        result_filter: "", actor_type: "", actor_username: "", date_from: "", date_to: ""
    };

    document.getElementById("searchInput").value = "";
    document.getElementById("filterCategory").value = "";
    document.getElementById("filterResult").value = "";
    document.getElementById("filterActorType").value = "";
    document.getElementById("filterActorUsername").value = "";
    document.getElementById("filterEventType").value = "";
    document.getElementById("filterDateFrom").value = "";
    document.getElementById("filterDateTo").value = "";
    document.getElementById("pageSize").value = "25";

    loadAudit();
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