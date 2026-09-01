document.addEventListener("DOMContentLoaded", () => {
    loadSummary();
    setInterval(loadSummary, 15000); // refresco automático cada 15s

    document.querySelectorAll(".range-btn").forEach(btn => {
        btn.addEventListener("click", () => loadHistory(btn.dataset.range));
    });
    loadHistory("24h");
});

function fmt(value, suffix = "", decimals = 1) {
    if (value === null || value === undefined || Number.isNaN(value)) return "—";
    return `${value.toFixed(decimals)}${suffix}`;
}

function fmtBytes(bytes) {
    if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let value = bytes;
    while (value >= 1024 && i < units.length - 1) {
        value /= 1024;
        i++;
    }
    return `${value.toFixed(1)} ${units[i]}`;
}

function renderTopUsers(items) {

    const tbody = document.getElementById("topUsersBody");

    if (!items.length) {
        tbody.innerHTML = '<tr><td class="text-muted">Sin datos todavía.</td></tr>';
        return;
    }

    tbody.innerHTML = "";

    items
        .sort((a, b) => b.bytes - a.bytes)
        .forEach(item => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${item.username}</td>
                <td class="text-end fw-medium">${fmtBytes(item.bytes)}</td>
            `;
            tbody.appendChild(tr);
        });
}

function barColor(pct) {
    if (pct === null) return "bg-secondary";
    if (pct >= 90) return "bg-danger";
    if (pct >= 70) return "bg-warning";
    return "bg-success";
}

async function loadSummary() {

    try {
        const res = await fetch("/api/monitoring/summary");
        const data = await res.json();

        document.getElementById("promDownAlert").classList.toggle("d-none", data.prometheus_reachable);

        const m = data.metrics || {};

        renderHostMetrics(m);

        document.getElementById("mContainers").textContent = m.containers_running !== null ? Math.round(m.containers_running) : "—";

        document.getElementById("mPgConn").textContent = m.pg_connections !== null ? Math.round(m.pg_connections) : "—";
        document.getElementById("mPgCache").textContent = `Cache hit: ${fmt(m.pg_cache_hit_pct, "%")}`;

        document.getElementById("mRedisMem").textContent = fmt(m.redis_memory_mb, "", 0);
        document.getElementById("mRedisHit").textContent = `Hit ratio: ${fmt(m.redis_hit_ratio_pct, "%")}`;

        document.getElementById("mHttpP95").textContent = fmt(m.http_p95_ms, "", 0);
        document.getElementById("mHttpErr").textContent = `Errores 5xx: ${fmt(m.http_error_rate, "%")}`;

        document.getElementById("mCeleryWorkers").textContent = m.celery_workers_online !== null ? Math.round(m.celery_workers_online) : "—";
        document.getElementById("mCeleryQueue").textContent = `Cola: ${m.celery_queue_length !== null ? Math.round(m.celery_queue_length) : "—"}`;
        document.getElementById("mCeleryTasks").textContent =
            `Éxito: ${m.celery_tasks_succeeded !== null ? Math.round(m.celery_tasks_succeeded) : "—"} · ` +
            `Fallidas: ${m.celery_tasks_failed !== null ? Math.round(m.celery_tasks_failed) : "—"} · ` +
            `Reintentos: ${m.celery_tasks_retried !== null ? Math.round(m.celery_tasks_retried) : "—"}`;

        document.getElementById("mDataTotal").textContent = fmtBytes(m.data_total_bytes);
        document.getElementById("mDataFreshness").textContent = m.data_last_refresh_seconds_ago !== null
            ? `Última actualización: hace ${Math.round(m.data_last_refresh_seconds_ago / 60)} min`
            : "Última actualización: —";

        renderTopUsers(data.top_users_by_data || []);

    } catch (err) {
        console.error("Error cargando resumen de monitorización", err);
        document.getElementById("promDownAlert").classList.remove("d-none");
    }
}

function renderHostMetrics(m) {

    const items = [
        { label: "CPU", value: m.cpu_pct, suffix: "%" },
        { label: "RAM", value: m.ram_pct, suffix: "%" },
        { label: "Swap", value: m.swap_pct, suffix: "%" },
        { label: "Disco (/)", value: m.disk_pct, suffix: "%" },
        { label: "Load average (1m)", value: m.load1, suffix: "", noBar: true },
    ];

    const container = document.getElementById("hostMetrics");
    container.innerHTML = "";

    items.forEach(item => {
        const col = document.createElement("div");
        col.className = "col-md-4 col-lg-2";

        const pctText = item.value !== null && item.value !== undefined
            ? fmt(item.value, item.suffix)
            : "—";

        let barHtml = "";
        if (!item.noBar) {
            const pct = item.value !== null ? Math.min(100, Math.max(0, item.value)) : 0;
            barHtml = `
                <div class="progress mt-2" style="height:8px;">
                    <div class="progress-bar ${barColor(item.value)}" style="width:${pct}%"></div>
                </div>`;
        }

        col.innerHTML = `
            <div class="text-muted small">${item.label}</div>
            <div class="fs-4 fw-bold">${pctText}</div>
            ${barHtml}
        `;
        container.appendChild(col);
    });
}


// =============================
// HISTÓRICO (Chart.js)
// =============================

const charts = {};

function formatLabel(ts, range) {
    const d = new Date(ts * 1000);
    if (range === "24h") {
        return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { day: "2-digit", month: "2-digit" }) +
        " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function renderLineChart(canvasId, labels, datasets, yTitle) {

    const ctx = document.getElementById(canvasId).getContext("2d");

    if (charts[canvasId]) {
        charts[canvasId].destroy();
    }

    charts[canvasId] = new Chart(ctx, {
        type: "line",
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            elements: { point: { radius: 0 } },
            interaction: { mode: "index", intersect: false },
            scales: {
                y: { title: { display: !!yTitle, text: yTitle }, beginAtZero: true },
                x: { ticks: { maxTicksLimit: 6 } }
            },
            plugins: {
                legend: { display: datasets.length > 1, position: "bottom", labels: { boxWidth: 12 } }
            }
        }
    });
}

async function loadHistory(range) {

    document.querySelectorAll(".range-btn").forEach(b => b.classList.toggle("active", b.dataset.range === range));

    try {
        const res = await fetch(`/api/monitoring/history?range=${range}`);
        const data = await res.json();
        const s = data.series || {};

        // etiquetas de referencia: node-exporter es el target más estable,
        // se usa como reloj común para todas las gráficas de este rango
        const labels = (s.cpu_pct || []).map(p => formatLabel(p[0], range));
        const vals = (arr) => (arr || []).map(p => p[1]);

        renderLineChart("chartServer", labels, [
            { label: "CPU %", data: vals(s.cpu_pct), borderColor: "#0d6efd", borderWidth: 2 },
            { label: "RAM %", data: vals(s.ram_pct), borderColor: "#198754", borderWidth: 2 },
            { label: "Disco %", data: vals(s.disk_pct), borderColor: "#dc3545", borderWidth: 2 },
        ], "%");

        renderLineChart("chartRequests", labels, [
            { label: "Peticiones/s", data: vals(s.http_requests_rate), borderColor: "#0dcaf0", borderWidth: 2 },
        ]);

        renderLineChart("chartLatency", labels, [
            { label: "p95 (ms)", data: vals(s.http_p95_ms), borderColor: "#6f42c1", borderWidth: 2 },
        ], "ms");

        renderLineChart("chartErrors", labels, [
            { label: "Errores 5xx (%)", data: vals(s.http_error_rate), borderColor: "#dc3545", borderWidth: 2 },
        ], "%");

        renderLineChart("chartCelery", labels, [
            { label: "Éxito/s", data: vals(s.celery_success_rate), borderColor: "#198754", borderWidth: 2 },
            { label: "Fallidas/s", data: vals(s.celery_failed_rate), borderColor: "#dc3545", borderWidth: 2 },
        ]);

        renderLineChart("chartData", labels, [
            {
                label: "Datos (GB)",
                data: (s.data_total_bytes || []).map(p => p[1] / 1024 / 1024 / 1024),
                borderColor: "#fd7e14",
                borderWidth: 2,
            },
        ], "GB");

    } catch (err) {
        console.error("Error cargando histórico", err);
    }
}