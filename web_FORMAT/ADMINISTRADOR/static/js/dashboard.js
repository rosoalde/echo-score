// =============================
// INIT
// =============================

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("refreshHealth").addEventListener("click", loadHealth);
    loadStats();
    loadHealth();
});


// =============================
// STATS
// =============================

async function loadStats() {

    try {
        const res = await fetch("/api/dashboard/stats");
        const data = await res.json();

        if (!res.ok) throw data;

        renderStatCards(data);
        renderBreakdown("analysesBreakdown", data.analyses.by_status, "/analyses");
        renderBreakdown("tasksBreakdown", data.tasks.by_status, "/tasks");

    } catch (err) {
        console.error("Error cargando estadísticas del dashboard", err);
    }
}

function renderStatCards(data) {

    const cards = [
        {
            icon: "bi-people",
            color: "primary",
            value: data.users.total,
            label: "Usuarios totales",
            extra: `${data.users.active} activos · ${data.users.verified} verificados`,
            link: "/users"
        },
        {
            icon: "bi-bar-chart",
            color: "success",
            value: data.analyses.total,
            label: "Análisis totales",
            extra: `${data.analyses.active} activos ahora mismo`,
            link: "/analyses"
        },
        {
            icon: "bi-list-task",
            color: "info",
            value: data.tasks.total,
            label: "Tareas totales",
            extra: `${data.tasks.running} en marcha · ${data.tasks.failed} fallidas`,
            link: "/tasks"
        },
        {
            icon: "bi-exclamation-triangle",
            color: data.errors_24h > 0 ? "danger" : "secondary",
            value: data.errors_24h,
            label: "Errores (24h)",
            extra: "Nivel ERROR en los logs",
            link: "/logs"
        }
    ];

    const container = document.getElementById("statCards");
    container.innerHTML = "";

    cards.forEach(c => {
        const col = document.createElement("div");
        col.className = "col-md-6 col-xl-3";
        col.innerHTML = `
            <a href="${c.link}" class="text-decoration-none">
                <div class="card h-100 border-0 shadow-sm">
                    <div class="card-body d-flex align-items-center gap-3">
                        <div class="rounded-3 d-flex align-items-center justify-content-center bg-${c.color} bg-opacity-10"
                             style="width:56px;height:56px;">
                            <i class="bi ${c.icon} text-${c.color}" style="font-size:26px;"></i>
                        </div>
                        <div>
                            <div class="fs-3 fw-bold text-dark">${c.value}</div>
                            <div class="text-muted small">${c.label}</div>
                            <div class="text-muted small">${c.extra}</div>
                        </div>
                    </div>
                </div>
            </a>
        `;
        container.appendChild(col);
    });
}

function renderBreakdown(containerId, byStatus, link) {

    const el = document.getElementById(containerId);
    el.innerHTML = "";

    const entries = Object.entries(byStatus || {});

    if (!entries.length) {
        el.innerHTML = '<span class="text-muted">Sin datos todavía.</span>';
        return;
    }

    const total = entries.reduce((acc, [, c]) => acc + c, 0);

    entries.forEach(([status, count]) => {
        const pct = total ? Math.round((count / total) * 100) : 0;
        const row = document.createElement("div");
        row.className = "mb-2";
        row.innerHTML = `
            <div class="d-flex justify-content-between small mb-1">
                <span class="text-capitalize">${status}</span>
                <span>${count}</span>
            </div>
            <div class="progress" style="height:8px;">
                <div class="progress-bar" style="width:${pct}%"></div>
            </div>
        `;
        el.appendChild(row);
    });
}


// =============================
// HEALTH
// =============================

async function loadHealth() {

    const container = document.getElementById("healthContainer");
    container.innerHTML = '<div class="col-12 text-muted">Comprobando estado del sistema...</div>';

    try {
        const res = await fetch("/api/dashboard/health");
        const data = await res.json();

        const items = [
            {
                key: "db",
                icon: "bi-database",
                label: "Base de datos",
                info: data.db.ok
                    ? `${data.db.latency_ms} ms`
                    : (data.db.detail || "Sin conexión")
            },
            {
                key: "redis",
                icon: "bi-lightning-charge",
                label: "Redis",
                info: data.redis.ok
                    ? `${data.redis.latency_ms} ms`
                    : (data.redis.detail || "Sin conexión")
            },
            {
                key: "workers",
                icon: "bi-hdd-network",
                label: "Workers Celery",
                info: data.workers.ok
                    ? `${data.workers.workers_online} online · ${data.workers.active_tasks} tareas activas`
                    : "Sin workers activos"
            },
            {
                key: "llm",
                icon: "bi-cpu",
                label: "LLM (vLLM)",
                info: data.llm.ok
                    ? `${data.llm.latency_ms} ms`
                    : (data.llm.detail || "Sin conexión")
            }
        ];

        container.innerHTML = "";

        items.forEach(item => {
            const status = data[item.key];
            const col = document.createElement("div");
            col.className = "col-md-6 col-xl-3";
            col.innerHTML = `
                <div class="border rounded-3 p-3 d-flex justify-content-between align-items-center">
                    <div>
                        <div class="fw-bold"><i class="bi ${item.icon}"></i> ${item.label}</div>
                        <div class="small text-muted">${item.info}</div>
                    </div>
                    <span class="badge ${status.ok ? "bg-success" : "bg-danger"}">
                        ${status.ok ? "OK" : "Caído"}
                    </span>
                </div>
            `;
            container.appendChild(col);
        });

    } catch (err) {
        container.innerHTML = `<div class="col-12 text-danger">Error comprobando el estado: ${err}</div>`;
    }
}
