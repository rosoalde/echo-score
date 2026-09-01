document.addEventListener("DOMContentLoaded", () => {
    console.log("🚀 JS de Analizar Datasets cargado (v10 - textos restaurados).");

    const projectSelect = document.getElementById("projectSelect");
    const resultsPlaceholder = document.getElementById("resultsPlaceholder");
    const chartsContainer = document.getElementById("chartsContainer");

    const DEFINICIONES_PILARES = {
        "legitimacion": "Mide si la ciudadanía percibe la medida como válida, legal y socialmente aceptable.",
        "efectividad": "Evalúa si el público cree que la medida realmente cumple sus objetivos y resuelve el problema.",
        "justicia_equidad": "Analiza si la política se percibe como justa e igualitaria para todos los sectores sociales.",
        "confianza_institucional": "Refleja el nivel de credibilidad y confianza en los organismos que implementan la medida."
    };

    let rawDataset = [];
    let charts = {};
    let zoomPluginLoaded = false;
    let tagifyInstance = null;
    let aceptacionModalInstance = null;
    let currentGeoTerms = [];
    let currentCustomTopic = "";
    let currentGeoTermsAceptacion = [];
    let _allTopics = [];

    const COLORS = ["#FF4500", "#01A5FF", "#FF0000", "#0088CC", "#ab54f0", "#e8c302", "#999999"];

    const PLATFORM_COLORS = {
        reddit: "#FF4500",
        bluesky: "#01A5FF",
        youtube: "#FF0000",
        telegram: "#0088CC",
    };

    function getPlatformColor(platformName, index) {
        index = index || 0;
        var key = (platformName || "").toLowerCase().trim();
        for (var name in PLATFORM_COLORS) {
            if (key.indexOf(name) !== -1) return PLATFORM_COLORS[name];
        }
        return COLORS[index % COLORS.length];
    }

    // ── ScoreOP v3: escala 0-100, neutro en 50 ──────────────────────────────
    const SCOREOP_COLORS = {
        muy_positivo: "#0a7c4a",
        positivo: "#0eb26c",
        neutro: "#adb5bd",
        negativo: "#f28c8c",
        muy_negativo: "#d8535f"
    };

    function scoreopCategoria(pct) {
        if (pct > 80) return { label: "Repercusión muy positiva", color: SCOREOP_COLORS.muy_positivo, textColor: "#fff" };
        if (pct >= 60) return { label: "Repercusión positiva", color: SCOREOP_COLORS.positivo, textColor: "#fff" };
        if (pct >= 40) return { label: "Repercusión equilibrada / polarizada", color: SCOREOP_COLORS.neutro, textColor: "#333" };
        if (pct >= 20) return { label: "Repercusión negativa", color: SCOREOP_COLORS.negativo, textColor: "#6b1e1e" };
        return { label: "Repercusión muy negativa", color: SCOREOP_COLORS.muy_negativo, textColor: "#fff" };
    }

    function scoreopBadgeStyle(pct) {
        var c = scoreopCategoria(pct);
        return "background:" + c.color + ";color:" + c.textColor + ";";
    }

    function extractPlatformData(porPlataforma) {
        if (!porPlataforma || typeof porPlataforma !== "object") {
            return { platforms: [], counts: [], means: [], medians: [], comments: [] };
        }
        var platformSet = new Set();
        Object.values(porPlataforma).forEach(function (v) {
            if (v && typeof v === "object") Object.keys(v).forEach(function (k) { platformSet.add(k); });
        });
        var platforms = Array.from(platformSet);
        var allKeys = Object.keys(porPlataforma);
        var countKey = allKeys.find(function (k) { return k.toLowerCase().indexOf("count") !== -1; });
        var meanKey = allKeys.find(function (k) { return k.toLowerCase() === "scoreop_pct_mean"; })
            || allKeys.find(function (k) { return k.toLowerCase().indexOf("pct_mean") !== -1; });
        var medianKey = allKeys.find(function (k) { return k.toLowerCase() === "scoreop_pct_median"; })
            || allKeys.find(function (k) { return k.toLowerCase().indexOf("pct_median") !== -1; });
        var commentKey = allKeys.find(function (k) { return k.toLowerCase().indexOf("sum") !== -1; });
        return {
            platforms,
            counts: countKey ? platforms.map(function (p) { return porPlataforma[countKey][p] || 0; }) : [],
            means: meanKey ? platforms.map(function (p) { return porPlataforma[meanKey][p] || 0; }) : [],
            medians: medianKey ? platforms.map(function (p) { return porPlataforma[medianKey][p] || 0; }) : [],
            comments: commentKey ? platforms.map(function (p) { return porPlataforma[commentKey][p] || 0; }) : []
        };
    }

    // ════════════════════════════════════════════════════════
    // LOAD CHARTJS ZOOM PLUGIN DYNAMICALLY
    // ════════════════════════════════════════════════════════
    function loadZoomPlugin(callback) {
        if (zoomPluginLoaded) { callback(); return; }
        var hammer = document.createElement("script");
        hammer.src = "https://cdnjs.cloudflare.com/ajax/libs/hammer.js/2.0.8/hammer.min.js";
        hammer.onload = function () {
            var zoom = document.createElement("script");
            zoom.src = "https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js";
            zoom.onload = function () {
                zoomPluginLoaded = true;
                callback();
            };
            document.head.appendChild(zoom);
        };
        document.head.appendChild(hammer);
    }

    // ════════════════════════════════════════════════════════
    // 1. CARGA DE DATOS
    // ════════════════════════════════════════════════════════
    async function cargarDashboard(analysisId, retryCount) {
        retryCount = retryCount || 0;
        if (!analysisId) return;

        if (retryCount === 0) {
            resultsPlaceholder.classList.remove("d-none");
            resultsPlaceholder.innerHTML = `
                <div class="py-5 text-center">
                    <div class="spinner-border text-primary" style="width:3rem;height:3rem;"></div>
                    <p class="mt-3 fw-bold">Sincronizando resultados del análisis...</p>
                    <small class="text-muted">Preparando visualización, un momento por favor.</small>
                </div>`;
            chartsContainer.classList.add("d-none");
        }

        try {
            const response = await fetch("/analisis/" + analysisId + "/dashboard");
            const data = await response.json();

            if (response.status === 202 && data.procesando) {
                const faseTexto = data.fase === "llm"
                    ? "🧠 Analizando contenido con IA…"
                    : "📊 Calculando…";

                chartsContainer.classList.add("d-none");
                resultsPlaceholder.classList.remove("d-none");
                resultsPlaceholder.innerHTML = `
                    <div class="py-5 text-center">
                        <div class="spinner-border text-primary" style="width:3rem;height:3rem;"></div>
                        <h5 class="mt-4 fw-bold">${faseTexto}</h5>
                        <p class="text-muted">El análisis se está completando automáticamente.</p>
                        <p class="text-muted small">La página se actualizará sola cuando esté listo.</p>
                        <div class="progress mt-3 mx-auto" style="max-width:300px;height:6px;">
                            <div class="progress-bar progress-bar-striped progress-bar-animated bg-primary"
                                style="width:100%"></div>
                        </div>
                    </div>`;

                setTimeout(function () { cargarDashboard(analysisId, 0); }, 15000);
                return;
            }

            if (!response.ok || !data || data.error) throw new Error(data.error || "Datos incompletos");

            document.getElementById("displayProjectName").innerText = data.project_name || "--";
            document.getElementById("displayTemaName").innerText = data.tema || "--";
            document.getElementById("displayThemeDescription").innerText = data.desc_tema || "";

            resultsPlaceholder.classList.add("d-none");
            chartsContainer.classList.remove("d-none");
            renderDashboard(data);

        } catch (error) {
            console.warn("⚠️ Reintentando (" + (retryCount + 1) + "/5): " + error.message);
            if (retryCount < 5) {
                setTimeout(function () { cargarDashboard(analysisId, retryCount + 1); }, 3000);
            } else {
                resultsPlaceholder.innerHTML = `
                    <div class="alert alert-warning shadow-sm text-center p-4">
                        <i class="bi bi-exclamation-triangle display-4 d-block mb-3"></i>
                        <h5 class="fw-bold">Los datos están tardando en generarse</h5>
                        <button class="btn btn-warning fw-bold mt-2" onclick="location.reload()">
                            <i class="bi bi-arrow-clockwise"></i> REINTENTAR AHORA
                        </button>
                    </div>`;
            }
        }
    }

    // ════════════════════════════════════════════════════════
    // 2. RENDERIZADO PRINCIPAL
    // ════════════════════════════════════════════════════════
    function renderDashboard(data) {
        if (!data || !data.kpis) {
            resultsPlaceholder.innerHTML = `<div class="alert alert-warning">El análisis terminó pero los datos aún se están procesando.</div>`;
            return;
        }

        const scoreop = data.scoreop || { disponible: false };

        const headerDiv = document.getElementById("projectHeader");
        if (headerDiv) {
            headerDiv.classList.remove("d-none");
            document.getElementById("displayProjectName").innerText = data.project_name || "Proyecto sin nombre";
            document.getElementById("displayTemaName").innerText = data.tema || "No hay un tema definido.";
            document.getElementById("displayThemeDescription").innerText = data.desc_tema || "No hay descripción disponible.";
        }

        _allTopics = (data.topics || []).slice().sort(function (a, b) { return b.volumen - a.volumen; });
        rawDataset = data.raw_data || rawDataset;
        window._lastDashboardData = data;  // ← añadir esta línea
        // ── TAB 1: PUBLICACIONES ──────────────────────────────
        try {
            const total = scoreop.disponible ? (scoreop.total_posts || 0) : (data.kpis.total || 0);
            document.getElementById("kpiTotal").innerText = total.toLocaleString("es-ES");
        } catch (e) { console.error(e); }

        // ── DONUT ─────────────────────────────────────────────
        try {
            var volLabels, volValues;
            if (scoreop.disponible && scoreop.por_plataforma) {
                const pd = extractPlatformData(scoreop.por_plataforma);
                volLabels = pd.platforms;
                volValues = pd.counts;
            } else {
                const vol = data.volumen_por_red || {};
                volLabels = Object.keys(vol);
                volValues = Object.values(vol);
            }
            const totalVol = volValues.reduce(function (a, b) { return a + b; }, 0) || 1;
            renderChart("volumenRedChart", "doughnut", {
                labels: volLabels,
                datasets: [{
                    data: volValues,
                    backgroundColor: volLabels.map(function (p, i) { return getPlatformColor(p, i); }),
                    borderWidth: 0
                }]
            }, {
                cutout: "60%",
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                var pct = ((ctx.parsed / totalVol) * 100).toFixed(1);
                                return " " + ctx.label + ": " + pct + "%";
                            }
                        }
                    }
                }
            });
        } catch (e) { console.error(e); }

        // ── TENDENCIA TEMPORAL con zoom ───────────────────────
        try {
            const trend = data.tendencia_global || {};
            const trendRed = data.tendencia_por_red || {};

            const fechasSet = new Set();
            Object.keys(trend).forEach(f => fechasSet.add(f));
            Object.keys(trendRed).forEach(red => {
                Object.keys(trendRed[red].total || {}).forEach(f => fechasSet.add(f));
            });
            const fechas = Array.from(fechasSet).sort();
            const redes = Object.keys(trendRed).filter(red =>
                Object.keys(trendRed[red].total || {}).length > 0
            );

            const container = document.getElementById("evolucionPorRedContainer");
            if (container) {
                container.classList.remove("d-none");
                container.innerHTML = `
                    <div class="mb-3">
                        <small class="fw-bold text-uppercase text-muted">Comparar plataformas</small>
                        <div id="togglesRedes" class="d-flex flex-wrap gap-2 mt-2"></div>
                    </div>`;
            }

            const datasets = [{
                label: "Actividad total",
                data: fechas.map(f => trend[f] || 0),
                borderColor: "#6c757d",
                backgroundColor: "rgba(108,117,125,0.10)",
                fill: true, tension: 0.3, borderWidth: 3, pointRadius: 0, hidden: false
            }];
            redes.forEach((red, i) => {
                datasets.push({
                    label: red,
                    data: fechas.map(f => trendRed[red].total[f] || 0),
                    borderColor: getPlatformColor(red, i),
                    backgroundColor: getPlatformColor(red, i) + "22",
                    fill: false, hidden: true, tension: 0.3, borderWidth: 2, pointRadius: 0
                });
            });

            loadZoomPlugin(function () {
                renderChart("tendenciaGlobalVolChart", "line", {
                    labels: fechas,
                    datasets: datasets
                }, {
                    interaction: { mode: "index", intersect: false },
                    plugins: {
                        legend: { position: "bottom" },
                        zoom: {
                            zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "x" },
                            pan: { enabled: true, mode: "x" }
                        }
                    },
                    scales: { y: { beginAtZero: true }, x: {} }
                });

                var resetBtn = document.getElementById("btnResetZoomVol");
                if (!resetBtn) {
                    var btn = document.createElement("button");
                    btn.id = "btnResetZoomVol";
                    btn.className = "btn btn-outline-secondary btn-sm mt-1";
                    btn.innerHTML = '<i class="bi bi-zoom-out me-1"></i>Restablecer zoom';
                    btn.onclick = function () { if (charts["tendenciaGlobalVolChart"]) charts["tendenciaGlobalVolChart"].resetZoom(); };
                    var canvasParent = document.getElementById("tendenciaGlobalVolChart").parentNode;
                    canvasParent.parentNode.insertBefore(btn, canvasParent.nextSibling);
                }
            });

            const toggleWrap = document.getElementById("togglesRedes");
            if (toggleWrap) {
                toggleWrap.innerHTML = `
                    <div class="form-check form-switch">
                        <input class="form-check-input red-toggle" type="checkbox" value="0" id="toggle_global" checked>
                        <label class="form-check-label small fw-bold text-secondary" for="toggle_global">Global</label>
                    </div>`;
                redes.forEach((red, i) => {
                    const color = getPlatformColor(red, i);
                    toggleWrap.innerHTML += `
                        <div class="form-check form-switch">
                            <input class="form-check-input red-toggle" type="checkbox" value="${i + 1}" id="toggle_${i}">
                            <label class="form-check-label small fw-bold" for="toggle_${i}" style="color:${color}">${red}</label>
                        </div>`;
                });
                toggleWrap.querySelectorAll(".red-toggle").forEach(el => {
                    el.addEventListener("change", function () {
                        const chart = charts["tendenciaGlobalVolChart"];
                        const idx = parseInt(this.value);
                        if (chart) { chart.data.datasets[idx].hidden = !this.checked; chart.update(); }
                    });
                });
            }
        } catch (e) { console.error(e); }

        // ── BARRAS publicaciones + comentarios por plataforma ──
        try {
            if (scoreop.disponible && scoreop.por_plataforma) {
                const pd = extractPlatformData(scoreop.por_plataforma);
                renderChart("tendenciaRedVolChart", "bar", {
                    labels: pd.platforms,
                    datasets: [
                        { label: "Publicaciones", data: pd.counts, backgroundColor: pd.platforms.map(function (p, i) { return getPlatformColor(p, i) + "BB"; }), borderColor: pd.platforms.map(function (p, i) { return getPlatformColor(p, i); }), borderWidth: 2, borderRadius: 6, yAxisID: "y" },
                        { label: "Comentarios", data: pd.comments, backgroundColor: "rgba(200,200,200,0.4)", borderColor: "#888", borderWidth: 1.5, borderRadius: 6, yAxisID: "y1" }
                    ]
                }, { scales: { y: { type: "linear", position: "left", beginAtZero: true }, y1: { type: "linear", position: "right", beginAtZero: true, grid: { drawOnChartArea: false } } } });
            }
        } catch (e) { console.error(e); }

        // ── TAB 2: SCOREOP ────────────────────────────────────
        try {
            if (scoreop.disponible) { renderScoreOP(scoreop); }
            else { renderScoreOPNoDisponible(); }
        } catch (e) { console.error(e); }

        // ── TAB 3: TOPICS Y NUBES ─────────────────────────────
        try {
            const topics = data.topics || [];
            _allTopics = topics.slice().sort(function (a, b) { return b.volumen - a.volumen; });
            populateTopicDropdown(_allTopics);

            const topTopics = topics.slice().sort(function (a, b) { return b.volumen - a.volumen; }).slice(0, 10);
            renderChart("topicsPieChart", "pie", {
                labels: topTopics.map(function (t) { return t.TOPIC || t.TOPIC_CLEAN || "?"; }),
                datasets: [{ data: topTopics.map(function (t) { return t.volumen; }), backgroundColor: COLORS.concat(COLORS), borderWidth: 1 }]
            }, {
                plugins: {
                    legend: {
                        position: "right",
                        labels: {
                            boxWidth: 12,
                            font: { size: 10 },
                            generateLabels: function (chart) {
                                var data = chart.data;
                                return data.labels.map(function (label, i) {
                                    var truncated = label.length > 22 ? label.substring(0, 22) + "…" : label;
                                    return { text: truncated, fillStyle: data.datasets[0].backgroundColor[i], index: i };
                                });
                            }
                        }
                    }
                },
                layout: { padding: { right: 10 } }
            });
            renderTopicsDetail(topics, data.kpis.total);
        } catch (e) { console.error(e); }

        // ── NUBES ──────────────────────────────────────────────
        try {
            const cloudContainer = document.getElementById("cloudContainer");
            const cloudTitle = document.getElementById("cloudTitle");
            if (cloudContainer && data.nubes) {
                cloudContainer.innerHTML = "";
                const entries = Object.entries(data.nubes);
                if (entries.length === 0) {
                    cloudContainer.innerHTML = '<div class="col-12"><p class="text-muted small fst-italic text-center">No hay nubes disponibles.</p></div>';
                } else {
                    if (cloudTitle) cloudTitle.innerText = "Términos más frecuentes por plataforma";

                    // Agrupar por plataforma: bluesky_posts + bluesky_comentarios juntas
                    const plataformas = {};
                    entries.forEach(function ([nombre, b64Str]) {
                        // Detectar si es formato nuevo (con _posts/_comentarios) o antiguo
                        var plat, tipo;
                        if (nombre.endsWith("_posts")) {
                            plat = nombre.replace("nube_", "").replace("_posts", "");
                            tipo = "posts";
                        } else if (nombre.endsWith("_comentarios")) {
                            plat = nombre.replace("nube_", "").replace("_comentarios", "");
                            tipo = "comentarios";
                        } else {
                            plat = nombre.replace("nube_", "");
                            tipo = "posts";  // formato antiguo, tratar como posts
                        }
                        if (!plataformas[plat]) plataformas[plat] = {};
                        plataformas[plat][tipo] = b64Str;
                    });

                    Object.entries(plataformas).forEach(function ([plat, nubes]) {
                        var colDiv = document.createElement("div");
                        colDiv.className = "col-12 mb-4";

                        var platLabel = plat.toUpperCase();
                        var platColor = getPlatformColor(plat);

                        var innerHtml = '<div class="border rounded-3 p-3 bg-white shadow-sm">';
                        innerHtml += '<div class="d-flex align-items-center gap-2 mb-3">';
                        innerHtml += '<span class="badge rounded-pill" style="background:' + platColor + ';font-size:.7rem;">' + platLabel + '</span>';
                        innerHtml += '</div>';
                        innerHtml += '<div class="row g-3">';

                        if (nubes.posts) {
                            innerHtml += '<div class="col-md-6">';
                            innerHtml += '<p class="text-muted small fw-bold text-uppercase mb-1" style="font-size:.65rem;letter-spacing:1px;">📝 Vocabulario de los posts (autores)</p>';
                            innerHtml += '<img src="data:image/png;base64,' + nubes.posts + '" class="img-fluid rounded" style="cursor:zoom-in;" title="Haz clic para ampliar">';
                            innerHtml += '</div>';
                        }
                        if (nubes.comentarios) {
                            innerHtml += '<div class="col-md-6">';
                            innerHtml += '<p class="text-muted small fw-bold text-uppercase mb-1" style="font-size:.65rem;letter-spacing:1px;">💬 Vocabulario de los comentarios (comunidad)</p>';
                            innerHtml += '<img src="data:image/png;base64,' + nubes.comentarios + '" class="img-fluid rounded" style="cursor:zoom-in;" title="Haz clic para ampliar">';
                            innerHtml += '</div>';
                        }
                        if (!nubes.comentarios && nubes.posts) {
                            // Solo una nube (posts), centrarla
                            // (ya se renderizó arriba)
                        }

                        innerHtml += '</div></div>';
                        colDiv.innerHTML = innerHtml;
                        cloudContainer.appendChild(colDiv);
                    });
                }
            }
        } catch (e) { console.error(e); }
    }

    // ════════════════════════════════════════════════════════
    // 2b. TOPIC DROPDOWN
    // ════════════════════════════════════════════════════════
    function populateTopicDropdown(topics) {
        var select = document.getElementById("topicDropdownSelect");
        var input = document.getElementById("topicFilterInput");
        if (!select) return;

        // Dropdown tiene TODOS los topics
        select.innerHTML = '<option value="">— Selecciona un subtema —</option>';
        topics.slice()
            .sort(function (a, b) { return b.volumen - a.volumen; })
            .forEach(function (t) {
                var label = t.TOPIC || t.TOPIC_CLEAN || "?";
                var opt = document.createElement("option");
                opt.value = label;
                opt.textContent = label + " (" + (t.volumen || 0) + " menciones)";
                select.appendChild(opt);
            });

        // Selección del dropdown → filtro EXACTO, sin semántica, sin llamada al servidor
        select.onchange = function () {
            var selected = this.value;
            if (!selected) {
                // Limpiar: volver a mostrar todos
                if (input) input.value = "";
                renderTopicsDetail(_allTopics, rawDataset.length || 1);
                return;
            }
            if (input) input.value = "";   // no contaminar el campo de texto

            // Buscar el topic en _allTopics y mostrarlo solo él
            var topicObj = _allTopics.find(function (t) {
                return (t.TOPIC || t.TOPIC_CLEAN || "").toLowerCase().trim()
                    === selected.toLowerCase().trim();
            });
            if (topicObj) {
                renderTopicsDetail([topicObj], rawDataset.length || 1);
                // Abrir automáticamente el modal de posts
                _mostrarPostsTopic(selected);
            }
        };
    }

    // ════════════════════════════════════════════════════════
    // 3. SCOREOP — RENDERIZADO COMPLETO v10
    // ════════════════════════════════════════════════════════
    function renderScoreOP(scoreop) {
        var stats = scoreop.stats || {};
        var distPorPlat = scoreop.dist_por_plataforma || {};

        // ── KPIs globales ─────────────────────────────────────
        var setKpi = function (id, val) {
            var el = document.getElementById(id);
            if (el) el.innerText = (val !== undefined && val !== null) ? val.toFixed(1) + "%" : "--";
        };
        var pctMedia = stats.pct_media !== undefined ? stats.pct_media : stats.media;
        var pctMediana = stats.pct_mediana !== undefined ? stats.pct_mediana : stats.mediana;
        var pctMax = stats.pct_max !== undefined ? stats.pct_max : stats.max;
        var pctMin = stats.pct_min !== undefined ? stats.pct_min : stats.min;

        setKpi("kpiScoreopMedia", pctMedia);
        setKpi("kpiScoreopMediana", pctMediana);
        setKpi("kpiScoreopMax", pctMax);
        setKpi("kpiScoreopMin", pctMin);

        _colorKpi("kpiScoreopMedia", pctMedia);
        _colorKpi("kpiScoreopMax", pctMax);
        _colorKpi("kpiScoreopMin", pctMin);

        // KPI posición global ponderada
        var globalPct = scoreop.scoreop_pct_global;
        var kpiGlobal = document.getElementById("kpiScoreopGlobal");
        if (kpiGlobal && globalPct !== undefined) {
            kpiGlobal.innerText = globalPct.toFixed(1) + "%";
            var catGlobal = scoreopCategoria(globalPct);
            kpiGlobal.style.color = catGlobal.color;
        }

        // ── Texto interpretativo global (RESTAURADO) ──────────
        _renderInterpretacionGlobal(globalPct, scoreop);

        var plataformas = Object.keys(distPorPlat);
        var hayMultiPlat = plataformas.length > 1;

        var contentEl = document.getElementById("scoreop-content");
        if (!contentEl) return;

        var platsConDatos = scoreop.tendencia_red ? Object.keys(scoreop.tendencia_red) : [];

        // ── Sección trayectorias ──────────────────────────────
        // TEXTOS ACLARADOS: se explica qué mide cada serie del gráfico
        var htmlTrayectoria = `
        <div class="bg-light p-3 rounded-3 mb-3 border-start border-4 border-info shadow-sm">
            <h6 class="text-dark fw-bold small text-uppercase mb-1">
                <i class="bi bi-activity me-2 text-info"></i>Dinámica de polaridad y balance neto del debate por plataforma
            </h6>
            <p class="text-muted mb-2 mt-1" style="font-size:.75rem;">
                Esta gráfica monitoriza el  <strong>promedio diario de los ECHO score de las publicaciones</strong>.
                Un valor de <strong>50 %</strong> indica un día de debate equilibrado o mayoritariamente neutro;
                los valores superiores indican una jornada con predominancia favorable y los inferiores una jornada de predominancia crítica.
            </p>
            <div class="d-flex flex-wrap gap-3 small" style="font-size:.72rem;">
                <span><span class="d-inline-block rounded me-1" style="width:12px;height:12px;background:rgba(14,178,108,0.45);"></span><strong>Zona verde</strong>: días con promedio por encima del umbral neutro (50 %)</span>
                <span><span class="d-inline-block rounded me-1" style="width:12px;height:12px;background:rgba(216,83,95,0.45);"></span><strong>Zona roja</strong>: días con promedio por debajo del umbral neutro (50 %)</span>
                <span><span class="d-inline-block rounded me-1" style="width:12px;height:12px;background:#666;"></span><strong>Línea</strong>: promedio ECHO score del día</span>
                <span><span class="d-inline-block rounded me-1" style="width:12px;height:12px;background:#7c3aed;"></span><strong>Balance neto (opcional)</strong>: sumatorio progresivo de las desviaciones diarias respecto al 50%. No mide la opinión de un día, sino la acumulación de capital social o malestar crónico a lo largo de todo el periodo</span>
            </div>
            <p class="text-muted mt-2 mb-0" style="font-size:.7rem;">
                <i class="bi bi-mouse me-1 text-info"></i>Zoom con la rueda del ratón · Arrastra para desplazarte · Botón Reset para restaurar la vista.
            </p>
        </div>
        <div class="row g-4 mb-4" id="scoreopPlatTimeCharts">`;

        platsConDatos.forEach(function (red) {
            var safeId = red.replace(/[^a-z0-9]/gi, "_");
            var color = getPlatformColor(red);
            htmlTrayectoria += `
            <div class="col-12">
                <div class="card border-0 shadow-sm rounded-4 p-3 h-100">
                    <div class="d-flex align-items-center gap-2 mb-2">
                        <span class="badge rounded-pill" style="background:${color};font-size:.65rem;">${red}</span>
                        <small class="text-muted fw-bold text-uppercase ms-1" style="font-size:.6rem;">ECHO score promedio diario · Umbral neutro = 50 %</small>
                        <div class="ms-auto d-flex gap-2 align-items-center">
                            <button class="btn btn-outline-secondary btn-sm py-0" style="font-size:.65rem;"
                                onclick="(function(){ var c=window._charts && window._charts['platChart_${safeId}']; if(c) c.resetZoom(); })()">
                                <i class="bi bi-zoom-out"></i> Reset zoom
                            </button>
                            <div class="form-check form-switch mb-0" style="font-size:.7rem;">
                                <input class="form-check-input" type="checkbox" id="toggleAcum_${safeId}" style="cursor:pointer;">
                                <label class="form-check-label text-muted" for="toggleAcum_${safeId}">Ver balance neto acumulado</label>
                            </div>
                        </div>
                    </div>
                    <div style="height:200px;"><canvas id="platChart_${safeId}"></canvas></div>
                </div>
            </div>`;
        });
        htmlTrayectoria += '</div>';

        // ── Tarjetas de plataforma (CON TEXTO EXPLICATIVO RESTAURADO) ────
        var htmlCards = "";
        if (hayMultiPlat) {
            htmlCards = `
            <div class="bg-light p-3 rounded-3 mb-3 border-start border-4 border-primary shadow-sm">
                <h6 class="text-dark fw-bold small text-uppercase mb-1">
                    <i class="bi bi-bar-chart me-2"></i>ECHO score por plataforma
                </h6>
                <p class="text-muted mb-0 mt-1" style="font-size:.75rem;">
                    Para cada plataforma se muestra el <strong>ECHO score Red</strong>
                    y la distribución de posts en <em>motores positivos</em> (&gt;60 %), <em>anclajes neutros</em> (40–60 %)
                    y <em>motores negativos</em> (&lt;40 %).
                    Un post con ECHO score &gt;60 % concentra tracción positiva; uno con &lt;40 % concentra tracción negativa.
                </p>
            </div>
            <div class="row g-3 mb-4" id="scoreopPlatCards"></div>`;
        }

        // ── Posts: motores positivos / motores negativos (CON TEXTO RESTAURADO) ──
        var htmlPosts = `
        <div class="bg-light p-3 rounded-3 mb-4 border-start border-4 border-success shadow-sm">
            <h6 class="text-dark fw-bold small text-uppercase mb-1">
                <i class="bi bi-list-stars me-2"></i>Publicaciones según ECHO score
            </h6>
            <p class="text-muted mb-0 mt-1" style="font-size:.75rem;">
                <strong>Motor positivo</strong>: posts con ECHO score &gt;60 % — que consolidan los argumentos positivos. 
                <strong>Motor negativo</strong>: posts con ECHO score &lt;40 % — que consolidan los argumentos negativos. 
                Dentro de cada grupo, los posts se ordenan primero ECHO score y, en caso de empate, por su <strong>energía de la agenda</strong>: este indicador revela la capacidad de tracción e influencia estructural de cada mensaje (alcance + interacción), independientemente de su signo. La etiqueta <em>Agenda X</em> identifica a las publicaciones que realmente dominan la conversación.
            </p>
        </div>
        <div class="row g-4">
            <div class="col-md-6">
                <div class="card border-0 shadow-sm rounded-4 p-4 h-100">
                    <h6 class="fw-bold small text-uppercase mb-3" style="color:#0a7c4a;">
                        <i class="bi bi-arrow-up-circle-fill me-2"></i>Motores positivos
                        <span class="badge ms-1 fw-normal" style="background:#0a7c4a;font-size:.65rem;">ECHO score &gt; 60 %</span>
                    </h6>
                    <div id="topPostsContainer" style="max-height:420px;overflow-y:auto;"></div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card border-0 shadow-sm rounded-4 p-4 h-100">
                    <h6 class="fw-bold small text-uppercase mb-3" style="color:#d8535f;">
                        <i class="bi bi-arrow-down-circle-fill me-2"></i>Motores negativos
                        <span class="badge ms-1 fw-normal" style="background:#d8535f;font-size:.65rem;">ECHO score &lt; 40 %</span>
                    </h6>
                    <div id="bottomPostsContainer" style="max-height:420px;overflow-y:auto;"></div>
                </div>
            </div>
        </div>`;

        contentEl.innerHTML = htmlTrayectoria + htmlCards + htmlPosts;

        window._charts = charts;

        setTimeout(function () {
            loadZoomPlugin(function () {
                // ── Gráficas de trayectoria por plataforma ──────────────
                platsConDatos.forEach(function (red, idx) {
                    var safeId = red.replace(/[^a-z0-9]/gi, "_");
                    var chartId = "platChart_" + safeId;
                    var toggleId = "toggleAcum_" + safeId;

                    var tendMedia = scoreop.tendencia_red[red] || {};
                    var tendPos = (scoreop.tendencia_red_pos || {})[red] || {};
                    var tendNeg = (scoreop.tendencia_red_neg || {})[red] || {};

                    var fechasSet = new Set(
                        Object.keys(tendMedia).concat(Object.keys(tendPos)).concat(Object.keys(tendNeg))
                    );
                    var fechas = Array.from(fechasSet).sort();

                    var mediaArr = fechas.map(function (f) { return tendMedia[f] != null ? tendMedia[f] : null; });

                    // Tendencia acumulada: desviación respecto al neutro (50)
                    var s = 0;
                    var acumArr = mediaArr.map(function (v) { s += (v != null ? v - 50 : 0); return parseFloat(s.toFixed(2)); });
                    var platColor = getPlatformColor(red, idx);

                    function buildDatasets(showAcum) {
                        return [
                            {
                                // Sombreado inteligente: verde si valor > 50, rojo si < 50
                                label: "_fill_area",
                                data: mediaArr,
                                borderColor: "transparent",
                                backgroundColor: "transparent",
                                fill: {
                                    target: { value: 50 },
                                    above: "rgba(14, 178, 108, 0.15)",
                                    below: "rgba(216, 83, 95, 0.15)"
                                },
                                tension: 0.4, pointRadius: 0, order: 4
                            },
                            {
                                label: "ECHO score promedio diario",
                                data: mediaArr,
                                borderColor: platColor,
                                borderWidth: 3,
                                tension: 0.4,
                                pointRadius: 2,
                                spanGaps: true,
                                order: 1
                            },
                            {
                                label: "Balance neto acumulado",
                                data: showAcum ? acumArr : fechas.map(function () { return null; }),
                                borderColor: "#7c3aed",
                                backgroundColor: "rgba(124,58,237,0.07)",
                                borderWidth: 2, borderDash: [3, 2],
                                tension: 0.35, pointRadius: 0,
                                fill: true, spanGaps: true, order: 2,
                                yAxisID: showAcum ? "y2" : "y"
                            }
                        ];
                    }

                    function buildOptions(showAcum) {
                        var scales = {
                            y: {
                                min: 0, max: 100,
                                title: { display: true, text: "ECHO score promedio (%)", font: { size: 9 } },
                                ticks: { callback: function (v) { return v + "%"; }, font: { size: 9 } },
                                grid: {
                                    color: function (ctx) {
                                        return ctx.tick.value === 50 ? "rgba(0,0,0,0.25)" : "rgba(0,0,0,0.04)";
                                    }
                                }
                            },
                            x: { title: { display: true, text: "Fecha", font: { size: 9 } } }
                        };
                        if (showAcum) {
                            scales.y2 = {
                                position: "right",
                                title: { display: true, text: ["Balance neto acumulado", "(Inercia del debate)"], font: { size: 9 } },
                                grid: { drawOnChartArea: false }
                            };
                        }
                        return {
                            plugins: {
                                legend: {
                                    position: "bottom",
                                    labels: {
                                        boxWidth: 10, font: { size: 9 },
                                        filter: function (item) { return !item.text.startsWith("_"); }
                                    }
                                },
                                tooltip: {
                                    filter: function (item) { return !item.dataset.label.startsWith("_"); },
                                    callbacks: {
                                        label: function (ctx) {
                                            var v = ctx.parsed.y;
                                            if (v == null) return "";
                                            if (ctx.dataset.label === "ECHO score promedio diario") {
                                                var cat = scoreopCategoria(v);
                                                return " " + v.toFixed(1) + "% — " + cat.label;
                                            }
                                            if (ctx.dataset.label.startsWith("Balance neto acumulado")) {
                                                return " ∑ desviación: " + (v >= 0 ? "+" : "") + v.toFixed(1) + " pts";
                                            }
                                            return " " + (v >= 0 ? "+" : "") + v.toFixed(1);
                                        }
                                    }
                                },
                                zoom: {
                                    zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "x" },
                                    pan: { enabled: true, mode: "x" }
                                }
                            },
                            scales: scales
                        };
                    }

                    if (charts[chartId]) charts[chartId].destroy();
                    var canvas = document.getElementById(chartId);
                    if (!canvas) return;
                    charts[chartId] = new Chart(canvas, {
                        type: "line",
                        data: { labels: fechas, datasets: buildDatasets(false) },
                        options: Object.assign({ responsive: true, maintainAspectRatio: false }, buildOptions(false))
                    });
                    window._charts[chartId] = charts[chartId];

                    var toggle = document.getElementById(toggleId);
                    if (toggle) {
                        toggle.addEventListener("change", function () {
                            var show = toggle.checked;
                            if (charts[chartId]) charts[chartId].destroy();
                            var cv = document.getElementById(chartId);
                            if (!cv) return;
                            charts[chartId] = new Chart(cv, {
                                type: "line",
                                data: { labels: fechas, datasets: buildDatasets(show) },
                                options: Object.assign({ responsive: true, maintainAspectRatio: false }, buildOptions(show))
                            });
                            window._charts[chartId] = charts[chartId];
                        });
                    }
                });
            });

            // ── Tarjetas por plataforma (v10) ─────────────────────────
            if (hayMultiPlat) {
                var cardsEl = document.getElementById("scoreopPlatCards");
                if (cardsEl) {
                    var todosLosPostsPct = (scoreop.top_posts || []).concat(scoreop.bottom_posts || []);

                    cardsEl.innerHTML = plataformas.map(function (p, i) {
                        var color = getPlatformColor(p, i);
                        var pctMedio = (scoreop.scoreop_pct_por_red || {})[p] || 0;
                        var catPlat = scoreopCategoria(pctMedio);

                        var d = distPorPlat[p] || {};
                        var total = d.total || 0;

                        var nPos = (d.muy_positivo || 0) + (d.positivo || 0);
                        var nNeu = d.neutro || 0;
                        var nNeg = (d.negativo || 0) + (d.muy_negativo || 0);

                        if (total === 0 && todosLosPostsPct.length > 0) {
                            var postsDePlat = todosLosPostsPct.filter(function (pp) {
                                return (pp.plataforma || "").toLowerCase() === p.toLowerCase();
                            });
                            total = postsDePlat.length;
                            postsDePlat.forEach(function (pp) {
                                var pct = pp.ScoreOP_pct != null ? pp.ScoreOP_pct : 50;
                                if (pct > 60) nPos++;
                                else if (pct >= 40) nNeu++;
                                else nNeg++;
                            });
                        }

                        var totalDist = nPos + nNeu + nNeg || 1;
                        var pPosBar = ((nPos / totalDist) * 100).toFixed(0);
                        var pNeuBar = ((nNeu / totalDist) * 100).toFixed(0);
                        var pNegBar = ((nNeg / totalDist) * 100).toFixed(0);

                        return `
                        <div class="col-lg-4">
                            <div class="card border-0 shadow-sm rounded-4 p-3 h-100" style="border-top: 3px solid ${color} !important;">
                                <div class="d-flex justify-content-between align-items-center mb-3">
                                    <span class="badge rounded-pill" style="background:${color}">${p}</span>
                                    <small class="text-muted">${total} posts</small>
                                </div>
                                
                                <div class="text-center py-2">
                                    <div class="text-muted extra-small text-uppercase fw-bold" style="font-size:.65rem;">ECHO score Red</div>
                                    <div class="h2 fw-bold" style="color:${catPlat.color}">${pctMedio.toFixed(1)}%</div>
                                    <div class="badge" style="${scoreopBadgeStyle(pctMedio)}">${catPlat.label}</div>
                                </div>

                                <div class="mt-3 pt-2 border-top">
                                    <div class="d-flex justify-content-between extra-small mb-1" style="font-size:.65rem;">
                                        <span class="text-success fw-bold">Motores positivos (&gt;60%): ${nPos}</span>
                                        <span class="text-danger fw-bold">Motores negativos (&lt;40%): ${nNeg}</span>
                                    </div>
                                    <div class="progress rounded-pill" style="height:8px; background:#f0f0f0;">
                                        <div class="progress-bar bg-success" style="width:${pPosBar}%"></div>
                                        <div class="progress-bar bg-secondary" style="width:${pNeuBar}%"></div>
                                        <div class="progress-bar bg-danger" style="width:${pNegBar}%"></div>
                                    </div>
                                    <div class="d-flex justify-content-between extra-small mt-1" style="font-size:.6rem;color:#888;">
                                        <span>▲ ${pPosBar}% Masa positiva</span>
                                        <span>● ${pNeuBar}% Masa en equilibrio</span>
                                        <span>▼ ${pNegBar}% Masa negativa</span>
                                    </div>
                                </div>
                            </div>
                        </div>`;
                    }).join("");
                }
            }

            // ── Motores positivos y negativos ────────────────────────
            var topFiltered = (scoreop.top_posts || []).filter(function (p) {
                var pct = p.ScoreOP_pct;
                return pct !== undefined ? pct > 60 : (p.ScoreOP || 0) > 0;
            });
            var bottomFiltered = (scoreop.bottom_posts || []).filter(function (p) {
                var pct = p.ScoreOP_pct;
                return pct !== undefined ? pct < 40 : (p.ScoreOP || 0) < 0;
            });
            // REEMPLAZAR POR
            function _safeNum(v) { return (v != null && !isNaN(parseFloat(v))) ? parseFloat(v) : 0; }

            topFiltered.sort(function (a, b) {
                var dPct = _safeNum(b.ScoreOP_pct) - _safeNum(a.ScoreOP_pct);
                if (Math.abs(dPct) > 0.001) return dPct;
                return _safeNum(b.ScoreOP_sup) - _safeNum(a.ScoreOP_sup);
            });

            bottomFiltered.sort(function (a, b) {
                var dPct = _safeNum(a.ScoreOP_pct) - _safeNum(b.ScoreOP_pct);
                if (Math.abs(dPct) > 0.001) return dPct;
                return _safeNum(b.ScoreOP_sup) - _safeNum(a.ScoreOP_sup);
            });

            renderPostsList("topPostsContainer", topFiltered, "top");
            renderPostsList("bottomPostsContainer", bottomFiltered, "bottom");

        }, 0);
    }

    // ════════════════════════════════════════════════════════
    // 3b. TEXTO INTERPRETATIVO KPI GLOBAL (RESTAURADO DE v9)  
    // ════════════════════════════════════════════════════════
    function _renderInterpretacionGlobal(globalPct, scoreop) {
        var el = document.getElementById("scoreopInterpretacion");
        if (!el || globalPct === undefined) return;
        var cat = scoreopCategoria(globalPct);
        var nRedes = scoreop.scoreop_pct_por_red ? Object.keys(scoreop.scoreop_pct_por_red).length : 0;
        el.innerHTML =
            '<span class="badge px-2 me-1 fw-bold" style="' + scoreopBadgeStyle(globalPct) + '">' + cat.label + '</span><br>' +
            '<div class="text-muted" style="font-size:.82rem; line-height:1.5;">' +
            'La polaridad ponderada global es <strong>' + globalPct.toFixed(1) + '%</strong>' +
            (nRedes > 1 ? ' (promedio ponderado de ' + nRedes + ' plataformas)' : '') +
            '. ' + _textoInterpretativo(globalPct) +
            '</div>';
    }

    function _textoInterpretativo(pct) {
        if (pct > 80) return "Existe una alta convergencia argumental favorable.";
        if (pct > 60) return "La energía discursiva muestra una predominancia favorable; los argumentos positivos logran capitalizar la mayor parte de la interacción.";
        if (pct > 50) return "Equilibrio con sesgo positivo: existe polarización, pero los argumentos favorables mantienen una ligera ventaja en tracción social.";
        if (pct === 50) return "Estado de equilibrio absoluto: las fuerzas discursivas favorables y críticas se neutralizan o la conversación es puramente neutra.";
        if (pct >= 40) return "Equilibrio con sesgo crítico: la energía de los argumentos negativos empieza a desplazar el centro de gravedad del debate.";
        if (pct >= 20) return "La energía discursiva muestra una predominancia crítica; los argumentos de rechazo lideran la narrativa con alta tracción social.";
        return "Existe una alta convergencia argumental crítica; el discurso está dominado por una negatividad estructural con máxima intensidad social.";
    }

    function _colorKpi(id, pct) {
        var el = document.getElementById(id);
        if (!el || pct === undefined) return;
        el.style.color = scoreopCategoria(pct).color;
    }

    function renderScoreOPNoDisponible() {
        var contentEl = document.getElementById("scoreop-content");
        if (contentEl) {
            contentEl.innerHTML = '<div class="alert alert-info shadow-sm d-flex align-items-start gap-3 p-4 rounded-4"><i class="bi bi-info-circle-fill fs-3 text-info flex-shrink-0 mt-1"></i><div><h6 class="fw-bold mb-1">ScoreOP no disponible</h6><p class="mb-0 text-muted small">El archivo <code>scoreop_consolidado.csv</code> no ha sido encontrado.</p></div></div>';
        }
        ["kpiScoreopMedia", "kpiScoreopMediana", "kpiScoreopMax", "kpiScoreopMin", "kpiScoreopGlobal"].forEach(function (id) {
            var el = document.getElementById(id); if (el) el.innerText = "--";
        });
    }

    // ════════════════════════════════════════════════════════
    // 4. LISTA DE POSTS (v10)
    // ════════════════════════════════════════════════════════
    function renderPostsList(containerId, posts, type) {
        var container = document.getElementById(containerId);
        if (!container) return;
        if (!posts || posts.length === 0) {
            container.innerHTML = '<p class="text-muted small fst-italic">No hay publicaciones en esta categoría.</p>';
            return;
        }
        container.innerHTML = posts.map(function (post) {
            var pct = post.ScoreOP_pct != null ? post.ScoreOP_pct : null;
            var content = post.contenido_post || "Sin contenido";
            var stance = post.stance_post || "--";
            var topic = post.topic || "";
            var nComent = post.num_comentarios != null ? post.num_comentarios : 0;
            var platColor = getPlatformColor(post.plataforma || "");

            var cat = pct !== null ? scoreopCategoria(pct) : scoreopCategoria(type === "top" ? 70 : 30);
            var badgeStyle = "background:" + cat.color + ";color:" + cat.textColor + ";";

            var stanceIcon = stance === 1 || stance === "1" ? "bi-hand-thumbs-up text-success"
                : stance === -1 || stance === "-1" ? "bi-hand-thumbs-down text-danger"
                    : "bi-dash-circle text-muted";

            var sup = post.ScoreOP_sup != null ? parseFloat(post.ScoreOP_sup) : null;
            var supFmt = sup != null ? sup.toFixed(1) : null;
            return '<div class="post-card p-3 mb-2 border rounded-3 bg-white shadow-sm">' +
                '<div class="d-flex justify-content-between align-items-start mb-2">' +
                '<div class="d-flex align-items-center gap-2 flex-wrap">' +
                '<span class="badge rounded-pill" style="background:' + platColor + ';color:#fff;font-size:0.65rem;">' + (post.plataforma || "--") + '</span>' +
                (topic ? '<small class="text-muted fw-bold text-uppercase" style="font-size:0.65rem;">' + topic + '</small>' : "") +
                '</div>' +
                '<div class="d-flex align-items-center gap-1">' +
                '<span class="badge rounded-pill px-2 fw-bold" style="' + badgeStyle + ';font-size:.65rem;">' + cat.label + '</span>' +
                (supFmt != null
                    ? '<span class="badge rounded-pill px-2 fw-normal" style="background:rgba(108,117,125,0.12);color:var(--bs-secondary);font-size:.6rem;" title="Energía de Agenda: Mide la capacidad de tracción del hilo (alcance + interacción) que soporta la polaridad del tópico."><i class="bi bi-megaphone me-1"></i>Agenda ' + supFmt + '</span>'
                    : '') +
                '</div>' +
                '</div>' +
                '<div style="max-height:100px;overflow-y:auto;padding-right:4px;" class="mb-2">' +
                '<p class="mb-0 small text-dark" style="line-height:1.45;white-space:pre-wrap;word-break:break-word;">' + content + '</p>' +
                '</div>' +
                '<div class="d-flex gap-3 mt-1 flex-wrap align-items-center">' +
                '<small class="text-muted"><i class="bi bi-chat-dots me-1"></i>' + nComent.toLocaleString("es-ES") + ' comentarios</small>' +
                '<small class="text-muted"><i class="bi ' + stanceIcon + ' me-1"></i>Tono: ' + _stanceLabel(stance) + '</small>' +
                (pct !== null ? '<small class="ms-auto fw-bold" style="font-size:.65rem;color:' + cat.color + ';" title="ScoreOP_pct: % del potencial positivo obtenido">' + pct.toFixed(1) + '%</small>' : "") +
                '</div></div>';
        }).join("");
    }

    function _stanceLabel(stance) {
        if (stance === 1 || stance === "1") return "Positivo";
        if (stance === -1 || stance === "-1") return "Negativo";
        if (stance === 0 || stance === "0") return "Neutro";
        return stance || "--";
    }

    // ════════════════════════════════════════════════════════
    // 5. CHART.JS GENÉRICO
    // ════════════════════════════════════════════════════════
    function renderChart(id, type, data, options) {
        options = options || {};
        var ctx = document.getElementById(id);
        if (!ctx) return;
        if (charts[id]) charts[id].destroy();
        charts[id] = new Chart(ctx, {
            type: type,
            data: data,
            options: Object.assign({ responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } }, options)
        });
    }

    // ════════════════════════════════════════════════════════
    // 6. TOPICS DETAIL
    // ════════════════════════════════════════════════════════
    function renderTopicsDetail(topics, totalGlobal) {
        var container = document.getElementById("topicsDetailContainer");
        if (!container) return;
        container.innerHTML = "";

        var sorted = topics.slice().sort(function (a, b) { return b.volumen - a.volumen; });
        var top10 = sorted.slice(0, 10);
        var rest = sorted.slice(10);

        // Agregar fila OTROS si hay más de 10
        if (rest.length > 0) {
            var otrosVol = rest.reduce(function (s, t) { return s + (t.volumen || 0); }, 0);
            var otrosPos = rest.reduce(function (s, t) { return s + (t.pos || 0); }, 0);
            var otrosNeu = rest.reduce(function (s, t) { return s + (t.neu || 0); }, 0);
            var otrosNeg = rest.reduce(function (s, t) { return s + (t.neg || 0); }, 0);
            top10.push({
                TOPIC: "Otros (" + rest.length + " subtemas)",
                volumen: otrosVol, pos: otrosPos, neu: otrosNeu, neg: otrosNeg,
                pct_medio: null, _isOtros: true
            });
        }

        top10.forEach(function (topic) {
            var vol = topic.volumen || 1;
            var label = topic.TOPIC || topic.TOPIC_CLEAN || "?";
            var pPos = ((topic.pos || 0) / vol) * 100;
            var pNeu = ((topic.neu || 0) / vol) * 100;
            var pNeg = ((topic.neg || 0) / vol) * 100;
            var pGlobal = (vol / (totalGlobal || 1)) * 100;

            var pctMedio = (topic.pct_medio != null) ? parseFloat(topic.pct_medio) : null;
            var catBadge = pctMedio !== null ? scoreopCategoria(pctMedio) : null;
            var badgeHtml = catBadge
                ? '<span class="badge ms-2 fw-normal px-2" style="' + scoreopBadgeStyle(pctMedio)
                + ';font-size:.62rem;">' + catBadge.label + ' · ' + pctMedio.toFixed(1) + '%</span>'
                : '';

            var row = document.createElement("div");
            row.className = "mb-4";
            row.innerHTML =
                '<div class="d-flex justify-content-between align-items-center mb-1 flex-wrap gap-1">' +
                '<div class="d-flex align-items-center flex-wrap gap-1">' +
                '<span class="fw-bold text-dark text-uppercase" style="font-size:0.72rem;">' + label + '</span>' +
                badgeHtml +
                '<span class="badge bg-light text-dark border ms-1" style="font-size:0.62rem;">'
                + topic.volumen + ' publicaciones</span>' +
                '</div>' +
                '<div class="d-flex align-items-center gap-2">' +
                '<small class="text-muted fw-bold" style="font-size:0.68rem;">'
                + pGlobal.toFixed(1) + '% del total</small>' +
                (!topic._isOtros
                    ? '<button class="btn btn-outline-secondary btn-sm py-0 px-2 ver-posts-btn"'
                    + ' style="font-size:.6rem;" data-topic="' + label + '">'
                    + '<i class="bi bi-list-stars me-1"></i>Ver posts</button>'
                    : '') +
                '</div>' +
                '</div>' +
                '<div class="progress rounded-pill" style="height:10px;background-color:#f0f0f0;">' +
                '<div class="progress-bar bg-success" style="width:' + pPos.toFixed(1) + '%"'
                + ' title="Favorable (>60%): ' + (topic.pos || 0) + ' posts"></div>' +
                '<div class="progress-bar bg-secondary" style="width:' + pNeu.toFixed(1) + '%;opacity:0.6;"'
                + ' title="Neutro (40-60%): ' + (topic.neu || 0) + ' posts"></div>' +
                '<div class="progress-bar bg-danger" style="width:' + pNeg.toFixed(1) + '%"'
                + ' title="En contra (<40%): ' + (topic.neg || 0) + ' posts"></div>' +
                '</div>' +
                '<div class="d-flex justify-content-between mt-1" style="font-size:0.68rem;">' +
                '<span class="text-success fw-bold">▲ ' + pPos.toFixed(1) + '% favorables ('
                + (topic.pos || 0) + ')</span>' +
                // ← FIX: añadir count de neutro
                '<span class="text-muted fw-bold">● ' + pNeu.toFixed(1) + '% neutro ('
                + (topic.neu || 0) + ')</span>' +
                '<span class="text-danger fw-bold">▼ ' + pNeg.toFixed(1) + '% en contra ('
                + (topic.neg || 0) + ')</span>' +
                '</div>';

            container.appendChild(row);
        });

        container.querySelectorAll(".ver-posts-btn").forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                e.stopPropagation();
                _mostrarPostsTopic(btn.getAttribute("data-topic"));
            });
        });
    }
    function _mostrarPostsTopic(topicLabel) {
        var topicLower = topicLabel.toLowerCase().trim();
        var posts = (rawDataset || []).filter(function (p) {
            return (p.topic || p.TOPIC || "").toLowerCase().trim() === topicLower;
        });

        if (posts.length === 0) {
            var msg = document.createElement("div");
            msg.className = "alert alert-info position-fixed bottom-0 end-0 m-3 shadow";
            msg.style.zIndex = 9999;
            msg.innerHTML = '<i class="bi bi-info-circle me-2"></i>No hay posts detallados. '
                + 'Aplica un filtro geográfico para activarlos.';
            document.body.appendChild(msg);
            setTimeout(function () { msg.remove(); }, 4000);
            return;
        }

        // Separar por posición real (no por mitades arbitrarias)
        var positivosPosts = posts.filter(function (p) {
            return (p.ScoreOP_pct !== undefined ? p.ScoreOP_pct : 50) > 60;
        }).sort(function (a, b) { return b.ScoreOP_pct - a.ScoreOP_pct; }).slice(0, 5);

        var neutrosPosts = posts.filter(function (p) {
            var pct = p.ScoreOP_pct !== undefined ? p.ScoreOP_pct : 50;
            return pct >= 40 && pct <= 60;
        }).slice(0, 3);

        var negativosPosts = posts.filter(function (p) {
            return (p.ScoreOP_pct !== undefined ? p.ScoreOP_pct : 50) < 40;
        }).sort(function (a, b) { return a.ScoreOP_pct - b.ScoreOP_pct; }).slice(0, 5);

        var nMotPos = positivosPosts.length;
        var nMotNeg = negativosPosts.length;
        var pctMedTopic = posts.reduce(function (s, p) {
            return s + (p.ScoreOP_pct !== undefined ? p.ScoreOP_pct : 50);
        }, 0) / posts.length;
        var catTopic = scoreopCategoria(pctMedTopic);

        function _postCard(post) {
            var pct = post.ScoreOP_pct !== undefined ? post.ScoreOP_pct : null;
            var cat = pct !== null ? scoreopCategoria(pct) : null;
            var platColor = getPlatformColor(post.plataforma || "");
            return '<div class="border rounded-3 p-2 mb-2 bg-white shadow-sm">' +
                '<div class="d-flex justify-content-between align-items-center mb-1">' +
                '<span class="badge rounded-pill" style="background:' + platColor + ';font-size:.58rem;">'
                + (post.plataforma || "--") + '</span>' +
                (cat ? '<span class="badge px-2" style="' + scoreopBadgeStyle(pct)
                    + ';font-size:.58rem;">' + pct.toFixed(1) + '% · ' + cat.label + '</span>' : '') +
                '</div>' +
                '<p class="mb-1" style="max-height:80px;overflow-y:auto;font-size:.73rem;'
                + 'white-space:pre-wrap;word-break:break-word;">'
                + (post.contenido_post || "Sin contenido") + '</p>' +
                '<small style="font-size:.6rem;color:#888;">'
                + '<i class="bi bi-chat-dots me-1"></i>' + (post.num_comentarios || 0)
                + ' comentarios</small>' +
                '</div>';
        }

        // Construir columnas SOLO si tienen posts
        function _buildCol(sectionPosts, colorClass, icon, title, subtitleBadge) {
            if (sectionPosts.length === 0) return "";
            return '<div class="col-md-' + (negativosPosts.length === 0 || positivosPosts.length === 0 ? "6" : "4") + '">' +
                '<h6 class="fw-bold small text-uppercase mb-2" style="color:' + colorClass + ';">' +
                '<i class="bi ' + icon + ' me-1"></i>' + title + '</h6>' +
                sectionPosts.map(_postCard).join("") +
                '</div>';
        }

        var colsHtml =
            _buildCol(positivosPosts, "#0a7c4a", "bi-arrow-up-circle-fill", "Voces favorables", "> 60%") +
            _buildCol(neutrosPosts, "#6c757d", "bi-dash-circle", "Voces neutras", "40-60%") +
            _buildCol(negativosPosts, "#d8535f", "bi-arrow-down-circle-fill", "Voces críticas", "< 40%");

        var existente = document.getElementById("topicPostsModal");
        if (existente) existente.remove();

        var html = '<div class="modal fade" id="topicPostsModal" tabindex="-1">' +
            '<div class="modal-dialog modal-xl modal-dialog-scrollable">' +
            '<div class="modal-content">' +
            '<div class="modal-header py-2">' +
            '<h6 class="modal-title fw-bold" style="font-size:.82rem;">' +
            '<i class="bi bi-tags me-2 text-primary"></i>' + topicLabel + '</h6>' +
            '<button type="button" class="btn-close btn-sm" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body">' +

            // Resumen
            '<div class="d-flex flex-wrap gap-3 align-items-center mb-3 p-2 rounded-3 bg-light border">' +
            '<div class="text-center px-2">' +
            '<div class="h4 fw-bold mb-0" style="color:' + catTopic.color + ';">'
            + pctMedTopic.toFixed(1) + '%</div>' +
            '<small class="text-muted" style="font-size:.65rem;">ScoreOP_pct medio</small></div>' +
            '<div class="vr"></div>' +
            '<div><small class="d-block text-success fw-bold">' + nMotPos + ' voces favorables (&gt;60%)</small>' +
            '<small class="d-block text-danger fw-bold">' + nMotNeg + ' voces críticas (&lt;40%)</small>' +
            '<small class="d-block text-muted">' + posts.length + ' publicaciones totales</small></div>' +
            '<div class="ms-auto"><span class="badge px-3 py-2" style="' + scoreopBadgeStyle(pctMedTopic)
            + ';font-size:.72rem;">' + catTopic.label + '</span></div>' +
            '</div>' +

            // Columnas de posts (solo las que tienen contenido)
            '<div class="row g-3">' + colsHtml + '</div>' +

            '</div>' +
            '<div class="modal-footer py-2">' +
            '<small class="text-muted me-auto" style="font-size:.65rem;">'
            + '0% = rechazo máximo · 50% = neutro · 100% = apoyo máximo</small>' +
            '<button class="btn btn-sm btn-secondary" data-bs-dismiss="modal">Cerrar</button>' +
            '</div></div></div></div>';

        document.body.insertAdjacentHTML("beforeend", html);
        var mi = new bootstrap.Modal(document.getElementById("topicPostsModal"));
        mi.show();

        document.getElementById("topicPostsModal").addEventListener("hidden.bs.modal", function () {
            document.querySelectorAll(".modal-backdrop").forEach(function (el) { el.remove(); });
            document.body.classList.remove("modal-open");
            document.body.style.overflow = "auto";
            document.body.style.paddingRight = "0";
            document.getElementById("topicPostsModal")?.remove();
        });
    }

    // ════════════════════════════════════════════════════════
    // 7. FILTROS GEO + TOPIC
    // ════════════════════════════════════════════════════════
    function initFilters() {
        var geoInput = document.getElementById("geoFilterInput");
        var btnApplyGeo = document.getElementById("btnApplyFilter");
        var btnClearGeo = document.getElementById("btnClearFilter");
        // Alias en otras pestañas (apuntan a los mismos inputs de filtro)
        var geoInputs = [
            document.getElementById("geoFilterInput"),
            document.getElementById("geoFilterInput2"),
            document.getElementById("geoFilterInput3"),
            document.getElementById("geoFilterInput4"),
            document.getElementById("geoFilterInput5"),
        ].filter(Boolean);
        var btnApplyGeos = [
            document.getElementById("btnApplyFilter"),
            document.getElementById("btnApplyFilter2"),
            document.getElementById("btnApplyFilter3"),
            document.getElementById("btnApplyFilter4"),
            document.getElementById("btnApplyFilter5"),
        ].filter(Boolean);
        var btnClearGeos = [
            document.getElementById("btnClearFilter"),
            document.getElementById("btnClearFilter2"),
            document.getElementById("btnClearFilter3"),
            document.getElementById("btnClearFilter4"),
            document.getElementById("btnClearFilter5"),
        ].filter(Boolean);
        var topicInput = document.getElementById("topicFilterInput");
        var btnApplyTopic = document.getElementById("btnApplyTopic");
        var btnClearTopic = document.getElementById("btnClearTopic");

        // Sincronizar valores entre los inputs geo de distintas pestañas
        function _syncGeoInputs(valor, origen) {
            geoInputs.forEach(function (inp) {
                if (inp !== origen) inp.value = valor;
            });
        }

        if (geoInput && typeof Tagify !== "undefined" && !tagifyInstance) {
            try {
                tagifyInstance = new Tagify(geoInput, { delimiters: ",", dropdown: { enabled: 0 } });
                tagifyInstance.on("remove", function () {
                    if (tagifyInstance.value.length === 0 && !currentCustomTopic) {
                        currentGeoTerms = [];
                        cargarDashboard(projectSelect.value);
                    }
                });
                tagifyInstance.on("change", function () {
                    var val = tagifyInstance.value.map(function (t) { return t.value; }).join(", ");
                    _syncGeoInputs(val, geoInput);
                });
            } catch (e) { console.warn(e); }
        }
        [
            document.getElementById("geoFilterInput2"),
            document.getElementById("geoFilterInput3"),
            document.getElementById("geoFilterInput4"),
            document.getElementById("geoFilterInput5"),
        ]
            .filter(Boolean)
            .forEach(function (inp) {
                inp.addEventListener("input", function () {
                    _syncGeoInputs(inp.value, inp);
                    // Actualizar tagify si existe
                    if (tagifyInstance) {
                        tagifyInstance.removeAllTags();
                        if (inp.value.trim()) {
                            inp.value.split(",").map(function (t) { return t.trim(); })
                                .filter(Boolean)
                                .forEach(function (t) { tagifyInstance.addTags([t]); });
                        }
                    }
                });
            });

        async function applyFilters() {
            var analysisId = projectSelect.value;
            if (!analysisId) { alert("Selecciona un proyecto."); return; }
            // Leer términos geo del input activo (cualquiera de los tres)
            if (tagifyInstance && tagifyInstance.value.length > 0) {
                currentGeoTerms = tagifyInstance.value.map(function (t) { return t.value; });
            } else {
                // Buscar el input con valor en cualquiera de las pestañas
                var geoVal = "";
                geoInputs.forEach(function (inp) { if (inp.value.trim()) geoVal = inp.value.trim(); });
                currentGeoTerms = geoVal ? geoVal.split(",").map(function (t) { return t.trim(); }).filter(Boolean) : [];
            }
            currentCustomTopic = topicInput ? topicInput.value.trim() : "";
            if (currentGeoTerms.length === 0 && currentCustomTopic === "") { alert("Ingresa un término geográfico o un topic para filtrar."); return; }
            var savedProjectName = document.getElementById("displayProjectName").innerText;
            var savedTema = document.getElementById("displayTemaName").innerText;
            var savedDescTema = document.getElementById("displayThemeDescription").innerText;

            resultsPlaceholder.classList.remove("d-none");
            chartsContainer.classList.add("d-none");
            resultsPlaceholder.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary" role="status"></div><p class="mt-2 fw-bold">Filtrando y recalculando…</p></div>';

            try {
                var response = await fetch("/analisis/" + analysisId + "/filter-geo", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ terms: currentGeoTerms, custom_topic: currentCustomTopic })
                });
                if (!response.ok) { var errData = await response.json().catch(function () { return {}; }); throw new Error(errData.detail || "Error del servidor (" + response.status + ")"); }
                var newData = await response.json();
                newData.project_name = savedProjectName;
                newData.tema = savedTema;
                newData.desc_tema = savedDescTema;
                // Guardar estado filtrado globalmente para que el grafo lo use
                // Guardar estado filtrado globalmente
                window._lastFilteredData = newData;
                window._lastFilterTerms = { geo: currentGeoTerms, topic: currentCustomTopic };

                resultsPlaceholder.classList.add("d-none");
                chartsContainer.classList.remove("d-none");
                rawDataset = newData.raw_data || [];
                _allTopics = (newData.topics || []).slice().sort(function (a, b) { return b.volumen - a.volumen; });
                renderDashboard(newData);

                // Sincronizar el dropdown del grafo con los nuevos topics
                if (window._syncGrafoTopicDrop) window._syncGrafoTopicDrop();

                // Recargar el grafo siempre (esté visible o no), para que al cambiar a la pestaña
                // ya tenga los datos filtrados listos
                if (window._grafoRecargar) {
                    // Marcar para recargar pero NO ejecutar si la pestaña no está activa
                    // (se hará al mostrarla via shown.bs.tab)
                    window._grafoPendingReload = true;
                    var grafoTabEl = document.getElementById("grafo-tab");
                    if (grafoTabEl && grafoTabEl.classList.contains("active")) {
                        window._grafoPendingReload = false;
                        window._grafoRecargar(analysisId);
                    }
                }
                if (window._lexicoV2) {
                    window._lexicoPendingReload = true;
                    var lexicoTabEl = document.getElementById("lexico-tab");
                    if (lexicoTabEl && lexicoTabEl.classList.contains("active")) {
                        window._lexicoPendingReload = false;
                        var platSel = document.getElementById("lexV2PlatFilter");
                        var plat = platSel ? platSel.value : "todas";
                        window._lexicoV2.recargar(analysisId, plat, currentGeoTerms.join(","));
                    }
                }
            } catch (error) {
                resultsPlaceholder.classList.remove("d-none");
                chartsContainer.classList.add("d-none");
                resultsPlaceholder.innerHTML = '<div class="alert alert-warning shadow-sm text-center p-4"><h6 class="fw-bold">' + error.message + '</h6><button class="btn btn-sm btn-outline-secondary mt-2" onclick="location.reload()">Ver datos completos</button></div>';
            }
        }

        function clearFilters() {
            if (tagifyInstance) tagifyInstance.removeAllTags();
            geoInputs.forEach(function (inp) { inp.value = ""; });
            currentGeoTerms = [];
            window._lastFilteredData = null;
            window._lastFilterTerms = null;
            window._grafoPendingReload = false;  // cancelar recarga pendiente
            // Forzar recarga del grafo con datos sin filtrar
            if (window._grafoRecargar) {
                var grafoTabEl = document.getElementById("grafo-tab");
                if (grafoTabEl && grafoTabEl.classList.contains("active")) {
                    window._grafoRecargar(projectSelect.value);
                } else {
                    window._grafoPendingReload = true; // recargar cuando se active
                }
            }
            if (window._lexicoV2) {
                window._lexicoPendingReload = true;
                var lexicoTabEl = document.getElementById("lexico-tab");
                if (lexicoTabEl && lexicoTabEl.classList.contains("active")) {
                    window._lexicoPendingReload = false;
                    var platSel = document.getElementById("lexV2PlatFilter");
                    var plat = platSel ? platSel.value : "todas";
                    window._lexicoV2.recargar(projectSelect.value, plat, "");
                }
            }
            if (currentCustomTopic) {
                applyFilters();
            } else {
                cargarDashboard(projectSelect.value);
            }
        }

        btnApplyGeos.forEach(function (btn) { btn.addEventListener("click", applyFilters); });
        btnClearGeos.forEach(function (btn) { btn.addEventListener("click", clearFilters); });

        if (btnApplyTopic) {
            btnApplyTopic.addEventListener("click", function () {
                var val = topicInput ? topicInput.value.trim() : "";
                if (!val) return;
                var exactMatch = _allTopics.find(function (t) {
                    return (t.TOPIC || t.TOPIC_CLEAN || "").toLowerCase().trim() === val.toLowerCase().trim();
                });
                if (exactMatch && currentGeoTerms.length === 0) {
                    renderTopicsDetail([exactMatch], rawDataset.length || 1);
                    _mostrarPostsTopic(val);
                } else {
                    applyFilters();
                }
            });
        }

        if (btnClearTopic) {
            btnClearTopic.addEventListener("click", function () {
                if (topicInput) topicInput.value = "";
                currentCustomTopic = "";
                if (currentGeoTerms.length) applyFilters(); else cargarDashboard(projectSelect.value);
            });
        }
    }

    initFilters();

    // ════════════════════════════════════════════════════════
    // 8. CARGA AUTOMÁTICA POR URL
    // ════════════════════════════════════════════════════════
    var urlParams = new URLSearchParams(window.location.search);
    var pid = urlParams.get("project_id");
    if (pid) {
        if (projectSelect) {
            var option = projectSelect.querySelector('option[value="' + pid + '"]');
            if (!option) { option = document.createElement("option"); option.value = pid; option.text = pid; projectSelect.appendChild(option); }
            projectSelect.value = pid;
        }
        cargarDashboard(pid);
    }
    projectSelect.addEventListener("change", function (e) { cargarDashboard(e.target.value); });

    // ════════════════════════════════════════════════════════
    // 9. INDICADOR DE ACEPTACIÓN — PillarOP
    // ════════════════════════════════════════════════════════
    async function aplicarFiltroAceptacion() {
        var analysisId = projectSelect.value;
        if (!analysisId) return;
        var geoInputModal = document.getElementById("geoInputModal");
        var rawValue = geoInputModal ? geoInputModal.value.trim() : "";
        var terms = rawValue.split(",").map(function (t) { return t.trim(); }).filter(function (t) { return t.length > 0; });
        currentGeoTermsAceptacion = terms;
        var aceptacionContainer = document.getElementById("aceptacionContainer");
        if (aceptacionContainer) {
            aceptacionContainer.innerHTML = '<div class="card border-0 shadow-sm p-3 text-center"><div class="spinner-border text-primary mb-2"></div><div class="fw-bold">Actualizando indicador</div></div>';
        }
        try {
            var response = await fetch("/analisis/" + analysisId + "/aceptacion/filter-geo", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ terms: currentGeoTermsAceptacion })
            });
            if (!response.ok) throw new Error("Error en el servidor");
            var data = await response.json();
            renderAceptacion(data);
        } catch (err) {
            if (aceptacionContainer) aceptacionContainer.innerHTML = '<div class="alert alert-danger">' + err.message + '</div>';
        }
    }

    var btnRunAcep = document.getElementById("btnRunAcep");
    var aceptacionContainer = document.getElementById("aceptacionContainer");

    if (btnRunAcep) {
        btnRunAcep.addEventListener("click", async function () {
            var analysisId = projectSelect.value;
            if (!analysisId) return;
            btnRunAcep.disabled = true;
            if (aceptacionContainer) aceptacionContainer.innerHTML = '<div class="card border-0 shadow-sm p-3 text-center"><div class="spinner-border text-primary mb-2"></div><div class="fw-bold">Calculando indicador de aceptación…</div></div>';
            try {
                var response = await fetch("/analisis/" + analysisId + "/aceptacion", { method: "POST", headers: { "Content-Type": "application/json" } });
                if (!response.ok) throw new Error((await response.text()) || "Error ejecutando indicador.");
                var data = await response.json();
                renderAceptacion(data);
            } catch (error) {
                if (aceptacionContainer) aceptacionContainer.innerHTML = '<div class="alert alert-danger mt-2">' + error.message + '</div>';
            } finally { btnRunAcep.disabled = false; }
        });
    }

    // ════════════════════════════════════════════════════════
    // 9b. RENDER ACEPTACIÓN — PillarOP v2
    // ════════════════════════════════════════════════════════
    function renderAceptacion(result) {
        if (!result || result.error) {
            if (aceptacionContainer) aceptacionContainer.innerHTML =
                '<div class="alert alert-warning">' + (result ? result.error : "Sin datos") + '</div>';
            return;
        }
        var globalData = result.global || {};
        var porRed = result.por_red || {};
        var interpretacion = result.interpretacion || "";
        var totalMenciones = globalData.total_menciones || 0;
        var pctMedio = globalData.PillarOP_pct_medio || 0;
        var sign = pctMedio >= 0 ? "+" : "";
        var PILARES = ["legitimacion", "efectividad", "justicia_equidad", "confianza_institucional"];
        var PILAR_LABEL = {
            legitimacion: "Legitimación",
            efectividad: "Efectividad",
            justicia_equidad: "Justicia y Equidad",
            confianza_institucional: "Confianza Institucional"
        };

        // ── Mini-card en la columna derecha ───────────────────────────────
        if (aceptacionContainer) {
            var resumenInterpretacion =
                'Resultado global construido a partir de los cuatro pilares de aceptación ' +
                '(legitimación, efectividad, justicia y confianza institucional) y del ' +
                'conjunto de plataformas sociales analizadas.';
            aceptacionContainer.innerHTML =
                '<div class="card border-0 shadow-sm p-3 bg-white rounded-4">' +

                '<div class="d-flex justify-content-between align-items-start mb-2">' +

                '<div>' +
                '<small class="text-muted text-uppercase fw-bold" style="font-size:.65rem;">' +
                'Síntesis global de aceptación social' +
                '</small>' +

                '<div class="text-muted mt-1" style="font-size:.72rem;line-height:1.25;">' +
                resumenInterpretacion +
                '</div>' +
                '</div>' +

                '<span class="badge fw-bold px-2" style="' +
                _pillarBadgeStyle(pctMedio) + '">' +
                sign + pctMedio.toFixed(1) + '%' +
                '</span>' +

                '</div>' +

                // 🔥 AQUÍ reutilizas tu interpretador existente
                '<div class="fw-bold mb-1" style="font-size:.95rem;">' +
                interpretacion +
                '</div>' +

                '<small class="text-muted fst-italic" style="font-size:.75rem;">' +
                totalMenciones + ' menciones analizadas en ' +
                (Object.keys(porRed).length || 1) +
                ' red(es) sociales.' +
                '</small>' +

                '<button class="btn btn-sm btn-outline-primary mt-3 w-100 fw-bold" ' +
                'onclick="new bootstrap.Modal(document.getElementById(\'aceptacionModal\')).show()">' +
                'Ver desglose por pilares y redes' +
                '</button>' +

                '</div>';
        }

        var redes = Object.keys(porRed);

        // ── Tabla por red y pilar ─────────────────────────────────────────
        var tableHtml = "";
        if (redes.length > 0) {
            var headerCols = redes.map(function (r) {
                return '<th class="text-center small text-capitalize">' + r + '</th>';
            }).join("");

            var bodyRows = PILARES.map(function (p) {
                var gPct = globalData["PillarOP_pct_" + p] || 0;
                var gSign = gPct >= 0 ? "+" : "";
                var gMen = globalData["menciones_" + p] || 0;
                var redCols = redes.map(function (r) {
                    var rd = porRed[r] || {};
                    var val = rd["PillarOP_pct_" + p] || 0;
                    var vs = val >= 0 ? "+" : "";
                    var col = val >= 60 ? "#0a7c4a" : val >= 40 ? "#888" : "#d8535f";
                    var men = rd["menciones_" + p] || 0;
                    return '<td class="text-center small">' +
                        '<span style="color:' + col + ';font-weight:600;">' + vs + val.toFixed(1) + '%</span><br>' +
                        '<span class="text-muted" style="font-size:.65rem;">(' + men + ' menciones)</span></td>';
                }).join("");
                var gCol = gPct >= 60 ? "#0a7c4a" : gPct >= 40 ? "#888" : "#d8535f";
                return `
                    <tr>
                        <td class="small">
                            <div class="fw-bold">
                                ${PILAR_LABEL[p]}
                            </div>
                            <div class="text-muted"
                                style="font-size:.68rem;line-height:1.2;">
                                ${DEFINICIONES_PILARES[p]}
                            </div>
                        </td>
                        ${redCols}
                        <td class="text-center">
                            <span style="font-weight:700;color:${gCol};">
                                ${gSign}${gPct.toFixed(1)}%
                            </span>
                            <br>
                            <span class="text-muted" style="font-size:.65rem;">
                                (${gMen} menciones)
                            </span>
                        </td>
                    </tr>`;
            }).join("");

            // Fila de totales por red
            var totalRedCols = redes.map(function (r) {
                var rdData = porRed[r] || {};
                var rdMedio = rdData["PillarOP_pct_medio"] || 0;
                var rdSign = rdMedio >= 0 ? "+" : "";
                var rdMen = rdData["total_menciones"] || 0;
                var rdCol = rdMedio >= 60 ? "#0a7c4a" : rdMedio >= 40 ? "#888" : "#d8535f";
                return '<td class="text-center" style="background:#f8f9fa;border-top:2px solid #dee2e6;">' +
                    '<span style="font-weight:800;font-size:.85rem;color:' + rdCol + ';">' + rdSign + rdMedio.toFixed(1) + '%</span><br>' +
                    '<span class="text-muted" style="font-size:.65rem;">(' + rdMen + ' menciones)</span></td>';
            }).join("");

            var globalMedio = pctMedio;
            var globalSign2 = globalMedio >= 0 ? "+" : "";
            var globalMedioCol = globalMedio >= 60 ? "#0a7c4a" : globalMedio >= 40 ? "#888" : "#d8535f";
            var totalGlobalCol =
                '<td class="text-center" style="background:#e8f0fe;border-top:2px solid #dee2e6;">' +
                '<span style="font-weight:800;font-size:.9rem;color:' + globalMedioCol + ';">' +
                globalSign2 + globalMedio.toFixed(1) + '%</span><br>' +
                '<span class="text-muted" style="font-size:.65rem;">(' + (globalData.total_menciones || 0) + ' menciones)</span></td>';

            tableHtml = `
            <div class="table-responsive mb-0">
                <table class="table table-sm table-hover align-middle mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Pilar</th>
                            ${headerCols}
                            <th class="text-center" style="background:#e8f0fe;">Resultado global</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${bodyRows}
                        <tr class="fw-bold">
                            <td class="small fw-bold text-uppercase"
                                style="background:#f8f9fa;border-top:2px solid #dee2e6;">
                                <i class="bi bi-calculator me-1 text-primary"></i>Aceptación total
                            </td>
                            ${totalRedCols}
                            ${totalGlobalCol}
                        </tr>
                    </tbody>
                </table>
            </div>`;
        }

        // ── Distribución por pilar (barras de stance) ─────────────────────
        var distHtml = '<div class="row g-2">';
        PILARES.forEach(function (p) {
            var pos = globalData["pos_" + p] || 0;
            var neu = globalData["neu_" + p] || 0;
            var neg = globalData["neg_" + p] || 0;
            var pct = globalData["PillarOP_pct_" + p] || 0;
            var total = pos + neu + neg || 1;
            var s = pct >= 0 ? "+" : "";
            distHtml +=
                '<div class="col-md-6"><div class="p-2 border rounded-3 bg-white shadow-sm h-100">' +
                '<div class="d-flex justify-content-between align-items-center mb-1">' +
                '<span class="fw-bold" style="font-size:.8rem;">' + PILAR_LABEL[p] + '</span>' +
                '<span class="fw-bold px-2 rounded" style="' + _pillarBadgeStyle(pct) + ';font-size:.75rem;">' + s + pct.toFixed(1) + '%</span></div>' +
                '<div class="progress rounded-pill mb-1" style="height:8px;background:#f0f0f0;">' +
                '<div class="progress-bar bg-success" style="width:' + (pos / total * 100).toFixed(0) + '%"></div>' +
                '<div class="progress-bar bg-secondary" style="width:' + (neu / total * 100).toFixed(0) + '%;opacity:.55;"></div>' +
                '<div class="progress-bar bg-danger" style="width:' + (neg / total * 100).toFixed(0) + '%"></div></div>' +
                '<div class="d-flex justify-content-between" style="font-size:.65rem;">' +
                '<span class="text-success fw-bold">▲ ' + pos + ' a favor (' + (pos / total * 100).toFixed(0) + '%)</span>' +
                '<span class="text-muted">● ' + neu + ' neutro</span>' +
                '<span class="text-danger fw-bold">▼ ' + neg + ' en contra (' + (neg / total * 100).toFixed(0) + '%)</span></div>' +
                '<p class="text-muted mb-0 mt-1" style="font-size:.65rem;line-height:1.2;">' +
                // (DEFINICIONES_PILARES[p] || "") + '</p>' +
                '</div></div>';
        });
        distHtml += "</div>";

        // ── Construir cuerpo del modal (SIN gráfica redundante) ───────────
        var bodyEl = document.getElementById("aceptacionModalBody");
        if (bodyEl) {
            bodyEl.innerHTML =
                // ── Explicación metodológica ──────────────────────────────
                `<div class="alert alert-info border-0 small mb-3 py-2 px-3" style="background:#e8f4fd;">
                    <div class="fw-bold mb-1"><i class="bi bi-info-circle-fill me-1"></i>¿Cómo se calcula la aceptación?</div>
                    <p class="mb-1">
                        El indicador de aceptación por pilar aplica la misma lógica que el ECHO score
                        a los cuatro pilares de aceptación de políticas.
                        Para cada hilo de conversación y cada pilar, el modelo combina la <strong>posición del autor</strong> 
                        con la <strong>posición de los comentarios</strong>, ponderando cada voz
                        según su esfuerzo social (likes, compartidos, respuestas) e influencia (seguidores, vistas).
                    </p>
                    <p class="mb-0">
                        La tabla desglosa los resultados por pilar y plataforma, mientras que la columna “Resultado global” muestra el promedio agregado de todas las redes para cada dimensión. La fila “Aceptación total” resume la valoración general de cada plataforma a partir del conjunto de pilares analizados.
                    </p>
                </div>` +

                // ── Tabla por red y pilar ─────────────────────────────────
                '<h6 class="fw-bold small text-uppercase mb-2 border-bottom pb-1">' +
                '<i class="bi bi-diagram-3 me-1 text-info"></i>Aceptación por red y por pilar</h6>' +
                '<p class="text-muted small mb-2" style="font-size:.72rem;line-height:1.35;">' +
                '<strong>Interpretación:</strong> cada fila representa un pilar de aceptación y cada columna una red social. ' +
                'La columna <strong>“Resultado global”</strong> resume el resultado agregado de todas las redes para ese pilar, ' +
                'mientras que la fila <strong>“Aceptación total”</strong> sintetiza la valoración global de cada plataforma ' +
                'a partir del conjunto de pilares analizados.' +
                '</p>' +
                '<div class="mb-4">' + (tableHtml || "<p class='text-muted small'>Sin datos por red disponibles.</p>") + '</div>' +

                // ── Comparativa de redes (solo si hay >1) ─────────────────
                (redes.length > 1
                    ? '<h6 class="fw-bold small text-uppercase mb-2 border-bottom pb-1">' +
                    '<i class="bi bi-layers me-1 text-success"></i>Comparativa de redes por pilar</h6>' +
                    '<div style="height:200px;margin-bottom:1.5rem;"><canvas id="pillaropRedChart"></canvas></div>'
                    : '') +

                // ── Distribución por pilar ────────────────────────────────
                '<h6 class="fw-bold small text-uppercase mb-2 border-bottom pb-1">' +
                '<i class="bi bi-pie-chart me-1 text-warning"></i>Distribución de posiciones por pilar</h6>' +
                '<p class="text-muted small mb-3" style="font-size:.75rem;">' +
                'Muestra cuántas menciones (posts y comentarios) tomaron posición a favor, neutra o en contra para cada pilar.' +
                '</p>' +
                distHtml;

            // ── Renderizar gráfica comparativa de redes ───────────────────
            setTimeout(function () {
                var ctx2 = document.getElementById("pillaropRedChart");
                if (ctx2 && redes.length > 1) {
                    if (charts["pillaropRedChart"]) charts["pillaropRedChart"].destroy();
                    var labels2 = PILARES.map(function (p) { return PILAR_LABEL[p]; });
                    var datasets2 = redes.map(function (red, i) {
                        return {
                            label: red,
                            data: PILARES.map(function (p) {
                                return (porRed[red] || {})["PillarOP_pct_" + p] || 0;
                            }),
                            backgroundColor: getPlatformColor(red, i) + "BB",
                            borderColor: getPlatformColor(red, i),
                            borderWidth: 1.5,
                            borderRadius: 4
                        };
                    });
                    charts["pillaropRedChart"] = new Chart(ctx2, {
                        type: "bar",
                        data: { labels: labels2, datasets: datasets2 },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 10 } } },
                                tooltip: {
                                    callbacks: {
                                        label: function (ctx) {
                                            return " " + ctx.dataset.label + ": " + ctx.parsed.y.toFixed(1) + "% (50% = neutro)";
                                        }
                                    }
                                }
                            },
                            scales: {
                                y: {
                                    min: 0, max: 100,
                                    ticks: { callback: function (v) { return v + "%"; }, font: { size: 10 } },
                                    grid: {
                                        color: function (ctx) {
                                            return ctx.tick.value === 50
                                                ? "rgba(0,0,0,0.3)"
                                                : "rgba(0,0,0,0.05)";
                                        }
                                    }
                                }
                            }
                        }
                    });
                }
            }, 80);
        }

        // ── Abrir modal ───────────────────────────────────────────────────
        var aceptacionModalEl = document.getElementById("aceptacionModal");
        aceptacionModalInstance = bootstrap.Modal.getOrCreateInstance(aceptacionModalEl);
        aceptacionModalInstance.show();

        // ── Botones dentro del modal ──────────────────────────────────────
        var btnApplyModal = document.getElementById("btnApplyGeoFromModal");
        if (btnApplyModal) {
            btnApplyModal.onclick = async function () {
                var geoInput = document.getElementById("geoInputModal").value.trim();
                if (!geoInput) { alert("Introduce al menos un término geográfico."); return; }
                currentGeoTermsAceptacion = geoInput.split(",").map(function (t) { return t.trim(); }).filter(Boolean);
                try {
                    btnApplyModal.disabled = true;
                    btnApplyModal.innerText = "Aplicando…";
                    await aplicarFiltroAceptacion();
                } catch (err) {
                    alert("Error: " + err.message);
                } finally {
                    btnApplyModal.disabled = false;
                    btnApplyModal.innerText = "Aplicar filtro geográfico";
                }
            };
        }
        var btnClearModal = document.getElementById("btnClearGeoFromModal");
        if (btnClearModal) {
            btnClearModal.onclick = async function () {
                var inp = document.getElementById("geoInputModal");
                if (inp) inp.value = "";
                await aplicarFiltroAceptacion();
            };
        }
        var btnDl = document.getElementById("btnDownloadAceptacion");
        if (btnDl) {
            btnDl.onclick = function () {
                var analysisId = projectSelect.value;
                if (!analysisId) { alert("No hay un proyecto seleccionado."); return; }
                window.location = "/analisis/" + analysisId + "/aceptacion/download-txt";
            };
        }
    }
    function _pillarBadgeStyle(pct) {
        if (pct >= 60) return "background:#0a7c4a;color:#fff;";
        if (pct >= 40) return "background:#f0ad4e;color:#212529;";
        return "background:#d8535f;color:#fff;";
    }
    function _pillarColor(pct) {
        if (pct >= 60) return "rgba(14,178,108,0.75)";
        if (pct >= 40) return "rgba(173,181,189,0.7)";
        return "rgba(216,83,95,0.75)";
    }

    // ════════════════════════════════════════════════════════
    // 10. LIMPIEZA MODAL BOOTSTRAP
    // ════════════════════════════════════════════════════════
    var modalEl = document.getElementById("aceptacionModal");
    if (modalEl) {
        // Limpiar cualquier backdrop colgado al cerrar
        modalEl.addEventListener("hidden.bs.modal", function () {
            document.querySelectorAll(".modal-backdrop").forEach(function (el) { el.remove(); });
            document.body.classList.remove("modal-open");
            document.body.style.overflow = "auto";
            document.body.style.paddingRight = "0px";
            // Destruir la instancia para forzar recreación limpia la próxima vez
            var inst = bootstrap.Modal.getInstance(modalEl);
            if (inst) inst.dispose();
            aceptacionModalInstance = null;
        });
        // Botón X y botón Cerrar: obtener instancia actual y llamar hide()
        modalEl.querySelectorAll('[data-bs-dismiss="modal"]').forEach(function (btn) {
            btn.addEventListener("click", function () {
                var inst = bootstrap.Modal.getInstance(modalEl);
                if (inst) inst.hide();
            });
        });
    }

    // ════════════════════════════════════════════════════════
    // 11. REDIMENSIONAR AL CAMBIAR PESTAÑA
    // ════════════════════════════════════════════════════════
    document.querySelectorAll("button[data-bs-toggle='tab']").forEach(function (tabEl) {
        tabEl.addEventListener("shown.bs.tab", function () {
            Object.values(charts).forEach(function (chart) { if (chart) chart.resize(); });
        });
    });

    // ════════════════════════════════════════════════════════
    // 12. ZOOM EN NUBES
    // ════════════════════════════════════════════════════════
    var cloudContainerEl = document.getElementById("cloudContainer");
    var cloudModal = new bootstrap.Modal(document.getElementById("vllmCloudModal"));
    var zoomImg = document.getElementById("vllmCloudZoomImg");
    if (cloudContainerEl) {
        cloudContainerEl.addEventListener("click", function (e) {
            if (e.target.tagName === "IMG") { zoomImg.src = e.target.src; cloudModal.show(); }
        });
    }

    // ════════════════════════════════════════════════════════════════════════════
    // 13. RED DE NARRATIVAS — grafo canvas + nube sincronizados
    //     Añadir al FINAL del DOMContentLoaded en analizar_datasets.js
    //     (justo antes del cierre  }); // fin DOMContentLoaded )
    // ════════════════════════════════════════════════════════════════════════════

    /**
     * lexico_semantico_v2.js
     * ======================
     * Pestaña "Léxico semántico" — DOS representaciones:
     *
     *  A) Nube unificada (palabras + bigramas, top-30)
     *     Sb  → tamaño  del texto
     *     Cb  → color   (verde=favorable, gris=neutro, rojo=rechazo)
     *     Ib  → opacidad (coherencia sent↔postura; solo bigramas visible)
     *
     *  B) Grafo bipartito G = (VT ∪ VU, E) — canvas con simulación de fuerzas
     *     Nodos tópico  (internos, círculos sólidos grandes):
     *       St   → radio
     *       Ct   → color
     *       Ib_t → opacidad
     *     Nodos usuario (hojas, círculos punteados pequeños):
     *       Su   → radio
     *       Cu   → color
     *     Aristas e_{u,t}:
     *       Wu_t_norm → grosor normalizado
     *       Cu_t      → color
     *       Ib_e      → opacidad
     *
     * El módulo se auto-inicializa al cargar el DOM.
     * Expone window._lexicoV2 = { recargar(id, plat, geo) } para uso externo.
     */

    (function () {
        "use strict";

        /* ─── Paleta de postura ─────────────────────────────────────── */
        function _posColor(c, alpha) {
            alpha = (alpha !== undefined) ? alpha : 1;
            if (c > 0.15) return "rgba(10,124,74," + alpha + ")";
            if (c < -0.15) return "rgba(216,83,95," + alpha + ")";
            return "rgba(108,117,125," + alpha + ")";
        }
        function _posColorHex(c) {
            if (c > 0.15) return "#0a7c4a";
            if (c < -0.15) return "#d8535f";
            return "#6c757d";
        }
        function _posLabel(c) {
            if (c > 0.15) return "Favorable";
            if (c < -0.15) return "Crítico";
            return "Neutro";
        }
        function _escalar(v, minV, maxV, minPx, maxPx) {
            if (maxV === minV) return (minPx + maxPx) / 2;
            return minPx + ((v - minV) / (maxV - minV)) * (maxPx - minPx);
        }

        var STOPWORDS_ES = new Set([
            "para", "como", "sobre", "desde", "entre", "hacia", "donde", "cuando", "porque",
            "también", "están", "esta", "este", "estos", "estas", "sus", "con",
            "los", "las", "del", "una", "unos", "unas", "más", "pero", "aunque", "sino",
            "todo", "todos", "toda", "todas", "cada", "otro", "otra", "otros", "otras",
            "puede", "pueden", "debe", "deben", "sido", "fueron", "será", "serán",
            "tiene", "tienen", "había", "hace", "hacen", "sólo", "solo", "muy", "tras",
            "ante", "bajo", "contra", "durante", "mediante", "según", "dentro", "fuera",
            "frente", "sigue", "mientras", "incluso", "además", "aunque"
        ]);

        /* ─── Estado del módulo ─────────────────────────────────────── */
        var _state = {
            data: null, analysisId: null,
            alpha: 0, tickRunning: false,
            nodes: [], edges: [], nodeMap: {},
            transform: { x: 0, y: 0, scale: 1 },
            hlNode: null,
            evBound: false, drag: null, tip: null,
            _maxSt: 1, _maxSu: 1,
            /* Modo: 'topic' muestra solo tópicos; 'usuario' muestra solo usuarios */
            grafoNivel: 'topic',
            /* Cuando se selecciona un nodo en modo topic, mostramos sus usuarios */
            expandedTopicId: null,
        };

        /* ═══════════ A. NUBE DE TÉRMINOS ═══════════════════════════ */
        function _renderNube(terminos) {
            var container = document.getElementById("lexV2NubeContainer");
            if (!container) return;
            container.innerHTML = "";
            if (!terminos || !terminos.length) {
                container.innerHTML = "<p style='color:#6c757d;font-size:13px;text-align:center;padding:2rem 0;'>Sin términos suficientes.</p>";
                return;
            }
            var sbArr = terminos.map(function (t) { return t.Sb; });
            var maxSb = Math.max.apply(null, sbArr);
            var minSb = Math.min.apply(null, sbArr);

            container.style.cssText = "min-height:280px;display:flex;flex-wrap:wrap;justify-content:center;align-items:center;align-content:center;gap:8px 18px;padding:20px;overflow:hidden;";

            var copy = terminos.slice().sort(function (a, b) { return b.Sb - a.Sb; });
            var ordered = [];
            while (copy.length) {
                ordered.push(copy.shift());
                if (copy.length) ordered.unshift(copy.shift());
            }

            ordered.forEach(function (b) {
                var fz = _escalar(b.Sb, minSb, maxSb, 0.9, 3.5).toFixed(2);
                var col = _posColorHex(b.Cb);
                var op = Math.max(0.25, b.Ib);
                var isBig = (b.tipo === "bigrama");
                var span = document.createElement("span");
                span.textContent = b.text;
                span.dataset.d = JSON.stringify(b);
                span.style.cssText = [
                    "font-size:" + fz + "rem",
                    "color:" + col,
                    "opacity:" + op.toFixed(2),
                    "cursor:pointer",
                    "display:inline-block",
                    "font-style:" + (isBig ? "italic" : "normal"),
                    "font-weight:" + (isBig ? "600" : "800"),
                    "letter-spacing:" + (isBig ? "-0.5px" : "-1.5px"),
                    "transition:all 0.3s cubic-bezier(0.175,0.885,0.32,1.275)",
                    "user-select:none", "line-height:1", "position:relative", "z-index:1"
                ].join(";");
                span.addEventListener("mouseenter", function (e) {
                    var d = JSON.parse(this.dataset.d);
                    _showTip(e,
                        "<strong>" + d.text + "</strong>" +
                        " <span style='margin-left:5px;background:" + _posColorHex(d.Cb) +
                        ";color:#fff;font-size:10px;padding:1px 6px;border-radius:4px;'>" +
                        (d.tipo === "bigrama" ? "Frase" : "Palabra") + "</span>" +
                        "<hr style='margin:5px 0;opacity:.2;'>" +
                        "<span style='color:#aaa;'>Relevancia:</span> <strong>" + d.Sb.toFixed(1) + "</strong><br>" +
                        "<span style='color:#aaa;'>Tono:</span> <strong>" + _posLabel(d.Cb) + "</strong><br>" +
                        "<span style='color:#aaa;'>Alineación:</span> <strong>" + Math.round(d.Ib * 100) + "%</strong><br>" +
                        "<span style='color:#aaa;'>Menciones:</span> " + d.Nb
                    );
                    this.style.opacity = "1";
                    this.style.transform = "scale(1.15) translateY(-3px)";
                    this.style.zIndex = "10";
                    this.style.textShadow = "0px 8px 15px rgba(0,0,0,0.2)";
                });
                span.addEventListener("mousemove", _moveTip);
                span.addEventListener("mouseleave", function () {
                    _hideTip();
                    this.style.opacity = op.toFixed(2);
                    this.style.transform = "scale(1) translateY(0)";
                    this.style.zIndex = "1";
                    this.style.textShadow = "none";
                });
                container.appendChild(span);
            });

            var leyenda = document.createElement("div");
            leyenda.style.cssText = "width:100%;margin-top:14px;font-size:11px;color:#6c757d;display:flex;gap:14px;flex-wrap:wrap;justify-content:center;border-top:0.5px solid #dee2e6;padding-top:12px;";
            leyenda.innerHTML = "<span><span style='color:#0a7c4a;'>■</span> Favorable</span><span><span style='color:#6c757d;'>■</span> Neutro</span><span><span style='color:#d8535f;'>■</span> Crítico</span><span style='font-style:italic;padding:0 5px;'>cursiva = bigrama</span><span>Opacidad = coherencia argumental</span>";
            container.appendChild(leyenda);
        }
        function _aplicarFiltroNube() {
            var pool = _state.nubePool || [];
            var selP = document.getElementById("lexV2NPalabras");
            var selB = document.getElementById("lexV2NBigramas");
            var nP = selP ? parseInt(selP.value, 10) : 20;
            var nB = selB ? parseInt(selB.value, 10) : 20;
            if (!nP || nP === 0) nP = 999;
            if (!nB || nB === 0) nB = 999;

            var palabras = pool.filter(function (t) { return t.tipo === "palabra"; })
                .sort(function (a, b) { return b.Sb - a.Sb; })
                .slice(0, nP);
            var bigramas = pool.filter(function (t) { return t.tipo === "bigrama"; })
                .sort(function (a, b) { return b.Sb - a.Sb; })
                .slice(0, nB);

            var combinado = palabras.concat(bigramas).sort(function (a, b) { return b.Sb - a.Sb; });
            _renderNube(combinado);
        }
        /* ═══════════ B. TEMAS DETECTADOS ══════════════════════════ */
        function _renderTemas(data) {
            var topics = (_state.data && _state.data._topics) || [];

            // ── Filtrar por plataforma activa ─────────────────────────────────
            var platSel = document.getElementById("lexV2PlatFilter");
            var platActiva = platSel ? platSel.value.toLowerCase() : "todas";

            var topicsFiltrados = topics;
            if (platActiva !== "todas" && rawDataset && rawDataset.length) {
                // Contar volumen de cada topic para la plataforma activa
                var volPorTopic = {};
                rawDataset.forEach(function (p) {
                    if (!p.topic && !p.TOPIC) return;
                    var t = (p.topic || p.TOPIC || "").toLowerCase().trim();
                    var plat = (p.plataforma || "").toLowerCase();
                    if (platActiva !== "todas" && plat !== platActiva) return;
                    volPorTopic[t] = (volPorTopic[t] || 0) + 1;
                });
                // Reconstruir topics con volumen filtrado
                topicsFiltrados = topics.map(function (t) {
                    var key = (t.TOPIC || t.TOPIC_CLEAN || "").toLowerCase().trim();
                    return Object.assign({}, t, { volumen: volPorTopic[key] || 0 });
                }).filter(function (t) { return t.volumen > 0; });
            }

            /* Poblar dropdown */
            var sel = document.getElementById("lexV2TopicDropdownSelect");
            if (sel) {
                sel.innerHTML = '<option value="">— Selecciona un subtema detectado —</option>';
                topicsFiltrados.slice().sort(function (a, b) { return b.volumen - a.volumen; })
                    .forEach(function (t) {
                        var lbl = t.TOPIC || t.TOPIC_CLEAN || "?";
                        var opt = document.createElement("option");
                        opt.value = lbl;
                        opt.textContent = lbl + " (" + (t.volumen || 0) + " menciones)";
                        sel.appendChild(opt);
                    });
                sel.onchange = function () {
                    if (!this.value) {
                        _renderTopicsDetail(topicsFiltrados, rawDataset.length || 1);
                        _clearTopicPostsPanel();
                        return;
                    }
                    var found = topicsFiltrados.find(function (t) {
                        return (t.TOPIC || t.TOPIC_CLEAN || "").toLowerCase().trim() ===
                            sel.value.toLowerCase().trim();
                    });
                    if (found) {
                        _renderTopicsDetail([found], rawDataset.length || 1);
                        _renderTopicPostsPanel(sel.value);
                    }
                };
            }

            /* Pie chart */
            var top10 = topicsFiltrados.slice().sort(function (a, b) { return b.volumen - a.volumen; }).slice(0, 10);
            var COLORS_PIE = ["#FF4500", "#0085FF", "#FF0000", "#ab54f0", "#e8c302", "#999999",
                "#0a7c4a", "#d8535f", "#4A7CC1", "#F5A623"];
            var pieCtx = document.getElementById("lexV2TopicsPieChart");
            if (pieCtx) {
                if (window._lexV2PieChart) window._lexV2PieChart.destroy();
                window._lexV2PieChart = new Chart(pieCtx, {
                    type: "pie",
                    data: {
                        labels: top10.map(function (t) { return t.TOPIC || t.TOPIC_CLEAN || "?"; }),
                        datasets: [{
                            data: top10.map(function (t) { return t.volumen; }),
                            backgroundColor: COLORS_PIE, borderWidth: 1
                        }]
                    },
                    options: {
                        responsive: true, maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: "right",
                                labels: {
                                    boxWidth: 12, font: { size: 10 },
                                    generateLabels: function (chart) {
                                        return chart.data.labels.map(function (label, i) {
                                            var truncated = label.length > 22 ? label.substring(0, 22) + "…" : label;
                                            return {
                                                text: truncated,
                                                fillStyle: chart.data.datasets[0].backgroundColor[i],
                                                index: i
                                            };
                                        });
                                    }
                                }
                            }
                        }
                    }
                });
            }

            _renderTopicsDetail(topicsFiltrados, rawDataset.length || 1);
            _clearTopicPostsPanel();
        }
        function _clearTopicPostsPanel() {
            var panel = document.getElementById("lexV2TopicPostsPanel");
            if (!panel) return;
            panel.innerHTML =
                '<div class="text-center text-muted py-5">' +
                '<i class="bi bi-hand-index-thumb display-4 d-block mb-3 opacity-25"></i>' +
                '<p class="small">Selecciona un tema del panel izquierdo para ver las publicaciones asociadas.</p>' +
                '</div>';
        }
        function _renderTopicPostsPanel(topicLabel) {
            var panel = document.getElementById("lexV2TopicPostsPanel");
            if (!panel) return;

            var topicLower = topicLabel.toLowerCase().trim();

            /* Filtrar por plataforma activa también */
            var platSel = document.getElementById("lexV2PlatFilter");
            var platActiva = platSel ? platSel.value.toLowerCase() : "todas";

            var posts = (rawDataset || []).filter(function (p) {
                var topicMatch = (p.topic || p.TOPIC || "").toLowerCase().trim() === topicLower;
                if (!topicMatch) return false;
                if (platActiva !== "todas") {
                    return (p.plataforma || "").toLowerCase() === platActiva;
                }
                return true;
            });

            if (posts.length === 0) {
                panel.innerHTML = '<div class="alert alert-info small">No hay publicaciones para este tema' +
                    (platActiva !== "todas" ? ' en ' + platActiva : '') + '.</div>';
                return;
            }

            /* Ordenar por impacto (ScoreOP_sup desc), luego por ScoreOP_pct */
            posts = posts.slice().sort(function (a, b) {
                var supB = parseFloat(b.ScoreOP_sup) || 0;
                var supA = parseFloat(a.ScoreOP_sup) || 0;
                if (Math.abs(supB - supA) > 0.001) return supB - supA;
                return (parseFloat(b.ScoreOP_pct) || 50) - (parseFloat(a.ScoreOP_pct) || 50);
            });

            var pctMed = posts.reduce(function (s, p) {
                return s + (p.ScoreOP_pct !== undefined ? p.ScoreOP_pct : 50);
            }, 0) / posts.length;
            var catTopic = scoreopCategoria(pctMed);

            /* Cabecera del panel */
            var html =
                '<div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">' +
                '<h6 class="fw-bold mb-0" style="color:#6f42c1;">' +
                '<i class="bi bi-tags me-2"></i>' + topicLabel + '</h6>' +
                '<div class="d-flex gap-2 align-items-center">' +
                '<span class="badge px-2 py-1" style="' + scoreopBadgeStyle(pctMed) + ';font-size:.65rem;">' +
                pctMed.toFixed(1) + '% · ' + catTopic.label + '</span>' +
                '<small class="text-muted">' + posts.length + ' publicaciones</small>' +
                '</div></div>' +
                '<p class="text-muted mb-3" style="font-size:.72rem;">' +
                'Ordenadas por energía de agenda (mayor impacto e interacción primero).' +
                '</p>';

            /* Nota de los posts con scroll */
            html += '<div style="max-height:520px;overflow-y:auto;padding-right:4px;">';
            posts.slice(0, 20).forEach(function (post) {
                var pct = post.ScoreOP_pct != null ? parseFloat(post.ScoreOP_pct) : null;
                var cat = pct !== null ? scoreopCategoria(pct) : null;
                var sup = post.ScoreOP_sup != null ? parseFloat(post.ScoreOP_sup) : null;
                var platColor = getPlatformColor(post.plataforma || "");
                var stance = post.stance_post;
                var stanceIcon = (stance === 1 || stance === "1") ? "bi-hand-thumbs-up text-success" :
                    (stance === -1 || stance === "-1") ? "bi-hand-thumbs-down text-danger" :
                        "bi-dash-circle text-muted";

                html +=
                    '<div class="border rounded-3 p-2 mb-2 bg-white shadow-sm">' +
                    '<div class="d-flex justify-content-between align-items-center mb-1 flex-wrap gap-1">' +
                    '<span class="badge rounded-pill" style="background:' + platColor + ';font-size:.58rem;">' +
                    (post.plataforma || "--") + '</span>' +
                    '<div class="d-flex gap-1 align-items-center">' +
                    (cat ? '<span class="badge px-1" style="' + scoreopBadgeStyle(pct) + ';font-size:.58rem;">' +
                        pct.toFixed(1) + '%</span>' : '') +
                    (sup != null ? '<span class="badge rounded-pill px-1 fw-normal" style="background:rgba(108,117,125,0.12);color:#555;font-size:.55rem;" title="Energía de la agenda">' +
                        '<i class="bi bi-megaphone me-1"></i>' + sup.toFixed(1) + '</span>' : '') +
                    '</div></div>' +
                    '<p class="mb-1 small text-dark" style="max-height:70px;overflow-y:auto;white-space:pre-wrap;word-break:break-word;font-size:.73rem;">' +
                    (post.contenido_post || "Sin contenido") + '</p>' +
                    '<div class="d-flex gap-3 mt-1" style="font-size:.6rem;color:#888;">' +
                    '<span><i class="bi bi-chat-dots me-1"></i>' + (post.num_comentarios || 0) + '</span>' +
                    '<span><i class="bi ' + stanceIcon + ' me-1"></i>' + _stanceLabel(stance) + '</span>' +
                    '</div></div>';
            });
            html += '</div>';

            panel.innerHTML = html;
        }
        /* Renderiza la lista detallada de tópicos */
        function _renderTopicsDetail(topics, totalGlobal) {
            var container = document.getElementById("lexV2TopicsDetailContainer");
            if (!container) return;
            container.innerHTML = "";
            var sorted = topics.slice().sort(function (a, b) { return b.volumen - a.volumen; });
            var top10 = sorted.slice(0, 10);
            var rest = sorted.slice(10);
            if (rest.length > 0) {
                var otrosVol = rest.reduce(function (s, t) { return s + (t.volumen || 0); }, 0);
                var otrosPos = rest.reduce(function (s, t) { return s + (t.pos || 0); }, 0);
                var otrosNeu = rest.reduce(function (s, t) { return s + (t.neu || 0); }, 0);
                var otrosNeg = rest.reduce(function (s, t) { return s + (t.neg || 0); }, 0);
                top10.push({ TOPIC: "Otros (" + rest.length + " subtemas)", volumen: otrosVol, pos: otrosPos, neu: otrosNeu, neg: otrosNeg, pct_medio: null, _isOtros: true });
            }
            top10.forEach(function (topic) {
                var vol = topic.volumen || 1;
                var label = topic.TOPIC || topic.TOPIC_CLEAN || "?";
                var pPos = ((topic.pos || 0) / vol) * 100;
                var pNeu = ((topic.neu || 0) / vol) * 100;
                var pNeg = ((topic.neg || 0) / vol) * 100;
                var pGlobal = (vol / (totalGlobal || 1)) * 100;
                var pctMedio = (topic.pct_medio != null) ? parseFloat(topic.pct_medio) : null;
                var catBadge = pctMedio !== null ? scoreopCategoria(pctMedio) : null;
                var badgeHtml = catBadge
                    ? '<span class="badge ms-2 fw-normal px-2" style="' + scoreopBadgeStyle(pctMedio) + ';font-size:.62rem;">' + catBadge.label + ' · ' + pctMedio.toFixed(1) + '%</span>'
                    : '';
                var row = document.createElement("div");
                row.className = "mb-4";
                row.innerHTML =
                    '<div class="d-flex justify-content-between align-items-center mb-1 flex-wrap gap-1">' +
                    '<div class="d-flex align-items-center flex-wrap gap-1">' +
                    '<span class="fw-bold text-dark text-uppercase" style="font-size:0.72rem;">' + label + '</span>' +
                    badgeHtml +
                    '<span class="badge bg-light text-dark border ms-1" style="font-size:0.62rem;">' + topic.volumen + ' publicaciones</span>' +
                    '</div>' +
                    '<div class="d-flex align-items-center gap-2">' +
                    '<small class="text-muted fw-bold" style="font-size:0.68rem;">' + pGlobal.toFixed(1) + '% del total</small>' +
                    (!topic._isOtros ? '<button class="btn btn-outline-secondary btn-sm py-0 px-2 lex-ver-posts-btn" style="font-size:.6rem;" data-topic="' + label + '"><i class="bi bi-list-stars me-1"></i>Ver posts</button>' : '') +
                    '</div></div>' +
                    '<div class="progress rounded-pill" style="height:10px;background-color:#f0f0f0;">' +
                    '<div class="progress-bar bg-success" style="width:' + pPos.toFixed(1) + '%"></div>' +
                    '<div class="progress-bar bg-secondary" style="width:' + pNeu.toFixed(1) + '%;opacity:0.6;"></div>' +
                    '<div class="progress-bar bg-danger" style="width:' + pNeg.toFixed(1) + '%"></div></div>' +
                    '<div class="d-flex justify-content-between mt-1" style="font-size:0.68rem;">' +
                    '<span class="text-success fw-bold">▲ ' + pPos.toFixed(1) + '% (' + (topic.pos || 0) + ')</span>' +
                    '<span class="text-muted fw-bold">● ' + pNeu.toFixed(1) + '% (' + (topic.neu || 0) + ')</span>' +
                    '<span class="text-danger fw-bold">▼ ' + pNeg.toFixed(1) + '% (' + (topic.neg || 0) + ')</span></div>';
                container.appendChild(row);
            });
            container.querySelectorAll(".lex-ver-posts-btn").forEach(function (btn) {
                btn.addEventListener("click", function (e) {
                    e.stopPropagation();
                    var tLabel = btn.getAttribute("data-topic");
                    _renderTopicPostsPanel(tLabel);
                    // Scroll al panel de posts
                    var pp = document.getElementById("lexV2TopicPostsPanel");
                    if (pp) pp.scrollIntoView({ behavior: "smooth", block: "start" });
                });
            });
        }

        /* ═══════════ C. GRAFO BIPARTITO con lógica topic/usuario ═══ */

        function _nodeR(n) {
            var raw = n.tipo === "topico" ? n.St : n.Su;
            var max = n.tipo === "topico" ? _state._maxSt : _state._maxSu;

            // 2. Aplicar RAÍZ CUADRADA para percepción de área (Ley de Stevens)
            var t = Math.sqrt(raw / (max || 1));

            // 3. Escalar al rango de píxeles deseado
            var minR = n.tipo === "topico" ? 16 : 6;
            var maxR = n.tipo === "topico" ? 48 : 18;

            return minR + t * (maxR - minR);
        }

        /* Calcula qué nodos/aristas son visibles según el nivel y selección */

        function _nodesVisibles() {
            var nivel = _state.grafoNivel;
            var allNodes = _state.nodes;
            var allEdges = _state.edges;

            if (nivel === 'topic') {
                var topicos = allNodes.filter(function (n) { return n.tipo === "topico"; });

                if (_state.expandedTopicId) {
                    var expandedId = _state.expandedTopicId;
                    var connectedIds = new Set();

                    // Buscar aristas donde el tópico aparece como source O target
                    var aristasDelTopico = allEdges.filter(function (e) {
                        return e.source === expandedId || e.target === expandedId;
                    });

                    aristasDelTopico.forEach(function (e) {
                        connectedIds.add(e.source);
                        connectedIds.add(e.target);
                    });
                    connectedIds.delete(expandedId); // quitar el propio tópico

                    var usuarios;
                    if (connectedIds.size > 0) {
                        usuarios = allNodes.filter(function (n) {
                            return n.tipo === "usuario" && connectedIds.has(n.id);
                        });
                    } else {
                        // Fallback: todos los usuarios con alguna arista
                        var uidsConArista = new Set();
                        allEdges.forEach(function (e) {
                            uidsConArista.add(e.source);
                            uidsConArista.add(e.target);
                        });
                        usuarios = allNodes.filter(function (n) {
                            return n.tipo === "usuario" && uidsConArista.has(n.id);
                        });
                        // Sin límite arbitrario de 15
                    }

                    return {
                        nodes: topicos.concat(usuarios),
                        edges: aristasDelTopico
                    };
                }

                return { nodes: topicos, edges: [] };
            }

            if (nivel === 'usuario') {
                var usuarios2 = allNodes.filter(function (n) { return n.tipo === "usuario"; });

                if (_state.expandedTopicId) {
                    var expandedUid = _state.expandedTopicId;

                    var aristasDelUsuario = allEdges.filter(function (e) {
                        return e.source === expandedUid || e.target === expandedUid;
                    });

                    var connectedTopicIds = new Set();
                    aristasDelUsuario.forEach(function (e) {
                        connectedTopicIds.add(e.source);
                        connectedTopicIds.add(e.target);
                    });
                    connectedTopicIds.delete(expandedUid);

                    var topicos2;
                    if (connectedTopicIds.size > 0) {
                        topicos2 = allNodes.filter(function (n) {
                            return n.tipo === "topico" && connectedTopicIds.has(n.id);
                        });
                    } else {
                        topicos2 = allNodes.filter(function (n) { return n.tipo === "topico"; });
                    }

                    return {
                        nodes: usuarios2.concat(topicos2),
                        edges: aristasDelUsuario
                    };
                }

                return { nodes: usuarios2, edges: [] };
            }

            return { nodes: allNodes, edges: allEdges };
        }

        function _renderGrafo(data) {
            _state._renderGen = (_state._renderGen || 0) + 1;
            var currentGen = _state._renderGen;  // capturar aquí

            var grafo = data.grafo_bipartito || {};
            var nodes = grafo.nodes || [];
            var edges = grafo.edges || [];
            var canvas = document.getElementById("lexV2GrafoCanvas");
            var loader = document.getElementById("lexV2GrafoLoader");
            if (!canvas) return;

            var ctx = canvas.getContext("2d");
            var rect = canvas.parentElement.getBoundingClientRect();
            var dpr = window.devicePixelRatio || 1;
            var W = rect.width || 640;
            var H = rect.height || 480;
            canvas.width = W * dpr; canvas.height = H * dpr;
            canvas.style.width = W + "px"; canvas.style.height = H + "px";
            ctx.scale(dpr, dpr);
            if (loader) loader.style.display = "none";

            _state.alpha = 1.0;
            _state.tickRunning = true;
            _tick(ctx, W, H, currentGen);  // pasar gen como argumento

            if (!nodes.length) {
                ctx.fillStyle = "rgba(108,117,125,0.65)";
                ctx.font = "13px system-ui"; ctx.textAlign = "center";
                ctx.fillText("Sin datos para el grafo bipartito.", W / 2, H / 2 - 10);
                ctx.font = "11px system-ui";
                ctx.fillText("Asegúrate de que los *_analizado.csv tienen columna 'topic'.", W / 2, H / 2 + 14);
                return;
            }

            var topicos = nodes.filter(function (n) { return n.tipo === "topico"; });
            var usuarios = nodes.filter(function (n) { return n.tipo === "usuario"; });
            _state._maxSt = Math.max.apply(null, topicos.map(function (n) { return n.St || 0; })) || 1;
            _state._maxSu = Math.max.apply(null, usuarios.map(function (n) { return n.Su || 0; })) || 1;

            // DESPUÉS — UNIVERSO + FILTRO CRUZADO
            /* ── Universo según selectores "Temas" / "Usuarios" ──────────────
               0 = "Todos" → 999 (límite práctico = "todo lo que haya").
               Filtro cruzado inteligente:
                 - Si se reducen los TEMAS, se eliminan usuarios que no
                   hablan de ninguno de esos temas.
                 - Si se reducen los USUARIOS, se eliminan temas de los
                   que ninguno de esos usuarios habla.
               Si ambos selectores están en "Todos", no se prunea nada
               (solo entra el cap de seguridad MAX_TOTAL_NODOS).         */

            var selTopics = document.getElementById("lexV2TopNTopics");
            var selUsers = document.getElementById("lexV2TopNUsers");
            var nTopicsSel = selTopics ? parseInt(selTopics.value, 10) : 10;
            var nUsersSel = selUsers ? parseInt(selUsers.value, 10) : 30;
            if (!nTopicsSel || nTopicsSel === 0) nTopicsSel = 999;
            if (!nUsersSel || nUsersSel === 0) nUsersSel = 999;

            // Cap de seguridad: evita que "Todos"/"Todos" congele la simulación
            var MAX_TOTAL_NODOS = 300;

            var topicosOrdenados = topicos.slice().sort(function (a, b) { return (b.St || 0) - (a.St || 0); });
            var usuariosOrdenados = usuarios.slice().sort(function (a, b) { return (b.Su || 0) - (a.Su || 0); });

            var topicosRestringido = nTopicsSel < topicosOrdenados.length;
            var usuariosRestringido = nUsersSel < usuariosOrdenados.length;

            var topTopicos = topicosOrdenados.slice(0, Math.min(nTopicsSel, topicosOrdenados.length));
            var topUsuarios = usuariosOrdenados.slice(0, Math.min(nUsersSel, usuariosOrdenados.length));

            function _parTopicoUsuario(e) {
                return String(e.target).indexOf("topico__") === 0
                    ? { topic: e.target, user: e.source }
                    : { topic: e.source, user: e.target };
            }

            if (topicosRestringido || usuariosRestringido) {
                var topicIds = new Set(topTopicos.map(function (n) { return n.id; }));
                var userIds = new Set(topUsuarios.map(function (n) { return n.id; }));

                // Hasta 3 rondas para que el filtro cruzado se estabilice
                for (var iter = 0; iter < 3; iter++) {
                    var conectTopics = new Set();
                    var conectUsers = new Set();
                    edges.forEach(function (e) {
                        var par = _parTopicoUsuario(e);
                        if (topicIds.has(par.topic) && userIds.has(par.user)) {
                            conectTopics.add(par.topic);
                            conectUsers.add(par.user);
                        }
                    });

                    var nuevoTopicIds = topicIds;
                    var nuevoUserIds = userIds;

                    // Usuarios reducidos → fuera los temas de los que no hablan
                    if (usuariosRestringido) {
                        nuevoTopicIds = new Set(Array.from(topicIds).filter(function (id) { return conectTopics.has(id); }));
                    }
                    // Temas reducidos → fuera los usuarios que no hablan de ellos
                    if (topicosRestringido) {
                        nuevoUserIds = new Set(Array.from(userIds).filter(function (id) { return conectUsers.has(id); }));
                    }

                    if (nuevoTopicIds.size === topicIds.size && nuevoUserIds.size === userIds.size) break;
                    topicIds = nuevoTopicIds;
                    userIds = nuevoUserIds;
                }

                topTopicos = topTopicos.filter(function (n) { return topicIds.has(n.id); });
                topUsuarios = topUsuarios.filter(function (n) { return userIds.has(n.id); });
            }

            // Cap final por rendimiento (solo recorta usuarios, mantiene los temas)
            if (topTopicos.length + topUsuarios.length > MAX_TOTAL_NODOS) {
                var maxUsuariosFinal = Math.max(MAX_TOTAL_NODOS - topTopicos.length, 10);
                topUsuarios = topUsuarios
                    .slice()
                    .sort(function (a, b) { return (b.Su || 0) - (a.Su || 0); })
                    .slice(0, maxUsuariosFinal);
            }

            var dn = topTopicos.concat(topUsuarios);
            var dnIds = new Set(dn.map(function (n) { return n.id; }));
            var de = edges.filter(function (e) { return dnIds.has(e.source) && dnIds.has(e.target); });

            /* Posiciones iniciales */
            var topicosDn = dn.filter(function (n) { return n.tipo === "topico"; });
            var usuariosDn = dn.filter(function (n) { return n.tipo === "usuario"; });
            var topicPos = {};

            // Eje global de polarización: verde→derecha, rojo→izquierda, gris→centro
            var polRange = W * 0.32;

            topicosDn.forEach(function (n, i) {
                var a = (i / (topicosDn.length || 1)) * 2 * Math.PI - Math.PI / 2;
                var r = Math.min(W, H) * 0.22;
                n._x = W / 2 + Math.cos(a) * r;
                n._y = H / 2 + Math.sin(a) * r;
                n._vx = 0; n._vy = 0;

                // Objetivo horizontal según el tono del propio tópico
                var ct = Math.max(-1, Math.min(1, n.Ct || 0));
                n._tx = W / 2 + ct * polRange;
                n._ty = n._y;   // mantiene la dispersión vertical inicial

                // topicPos usa el OBJETIVO (no la posición circular), para que el
                // "hogar" de los usuarios se calcule sobre dónde acabará el tópico
                topicPos[n.id] = { x: n._tx, y: n._ty };
            });

            /* ─── Similitud léxica entre tópicos (solo pares realmente afines) ─── */
            var topicTokens = {};
            topicosDn.forEach(function (n) {
                topicTokens[n.id] = new Set(
                    String(n.label || "").toLowerCase()
                        .split(/\s+/)
                        .filter(function (w) { return w.length > 4 && !STOPWORDS_ES.has(w); })
                );
            });
            _state.topicSim = {};
            for (var ti = 0; ti < topicosDn.length; ti++) {
                for (var tj = ti + 1; tj < topicosDn.length; tj++) {
                    var ida = topicosDn[ti].id, idb = topicosDn[tj].id;
                    var sa = topicTokens[ida], sb = topicTokens[idb];
                    var inter = 0;
                    sa.forEach(function (w) { if (sb.has(w)) inter++; });
                    var uni = sa.size + sb.size - inter;
                    var sim = uni > 0 ? inter / uni : 0;
                    // Umbral: solo atraer si comparten una fracción significativa
                    // de palabras con contenido semántico real
                    if (inter >= 1 && sim >= 0.2) {
                        _state.topicSim[ida] = _state.topicSim[ida] || {};
                        _state.topicSim[ida][idb] = sim;
                        _state.topicSim[idb] = _state.topicSim[idb] || {};
                        _state.topicSim[idb][ida] = sim;
                    }
                }
            }

            /* ─── Mapa usuario → tópicos conectados (con peso Wu_t) ─── */
            var userTopics = {};
            de.forEach(function (e) {
                var uid, tid;
                if (String(e.source).startsWith("topico__")) { tid = e.source; uid = e.target; }
                else { uid = e.source; tid = e.target; }
                userTopics[uid] = userTopics[uid] || [];
                userTopics[uid].push({ tid: tid, w: e.Wu_t || 0 });
            });

            /* ─── Posicionamiento de usuarios: polarización + impacto + puentes ─── */
            usuariosDn.forEach(function (n) {
                var tops = userTopics[n.id] || [];
                n._isBridge = tops.length > 1;
                n._nTopics = tops.length;

                // "Hogar": centroide ponderado por Wu_t de los tópicos conectados
                // (usando el OBJETIVO de cada tópico, no su posición circular inicial)
                var sumW = 0, cx = 0, cy = 0;
                tops.forEach(function (t) {
                    var tp = topicPos[t.tid];
                    if (!tp) return;
                    var w = (t.w || 0) + 0.01;
                    cx += tp.x * w; cy += tp.y * w; sumW += w;
                });
                var homeX = sumW > 0 ? cx / sumW : W / 2;
                var homeY = sumW > 0 ? cy / sumW : H / 2;

                // Objetivo de polarización GLOBAL del propio usuario:
                // verde → derecha, rojo → izquierda, gris → centro
                var cu = Math.max(-1, Math.min(1, n.Cu || 0));
                var polTargetX = W / 2 + cu * polRange;

                // Impacto: a más Su, más cerca de su "hogar" (junto al tópico,
                // la colisión evita que se solape); a menos Su, más hacia
                // su extremo de polarización
                var suNorm = _state._maxSu > 0 ? Math.min(1, (n.Su || 0) / _state._maxSu) : 0;
                var pull = 1 - suNorm; // 0 = pegado al tópico, 1 = extremo de polarización

                n._tx = homeX * (1 - pull) + polTargetX * pull;
                n._ty = homeY + (Math.random() - 0.5) * 40;

                n._x = n._tx + (Math.random() - 0.5) * 16;
                n._y = n._ty + (Math.random() - 0.5) * 16;
                n._vx = 0; n._vy = 0;
            });

            _state.nodes = dn;
            _state.edges = de;
            _state.nodeMap = {};
            dn.forEach(function (n) { _state.nodeMap[n.id] = n; });
            _state.transform = { x: 0, y: 0, scale: 1 };
            _state.hlNode = null;
            _state.expandedTopicId = null;
            _actualizarSidePanel(null);

            _bindCanvasEvents(canvas, W, H);

            _state.alpha = 1.0;
            _state.tickRunning = true;
            _tick(ctx, W, H);
        }

        /* ─── Simulación de fuerzas ───────────────────────────────── */
        function _tick(ctx, W, H, gen) {
            if (gen !== _state._renderGen) return;   // una renderización más nueva tomó el control
            if (_state.alpha <= 0.003) {
                _state.tickRunning = false;
                _draw(ctx, W, H);
                return;
            }
            _state.alpha *= 0.975;
            var dn = _state.nodes;
            _draw(ctx, W, H);
            if (_state.tickRunning) requestAnimationFrame(function () { _tick(ctx, W, H, gen); });

            for (var i = 0; i < dn.length; i++) {
                for (var j = i + 1; j < dn.length; j++) {
                    var a = dn[i], b = dn[j];
                    var dx = b._x - a._x, dy = b._y - a._y;
                    var d = Math.sqrt(dx * dx + dy * dy) || 0.1;
                    var minD = _nodeR(a) + _nodeR(b) + 30;
                    var str = d < minD ? 3000 / Math.max(d * d, 0.5) : (a.tipo === b.tipo ? 1.5 : 1.0) * 1200 / (d * d);
                    var k = str * _state.alpha;
                    a._vx -= (dx / d) * k; a._vy -= (dy / d) * k;
                    b._vx += (dx / d) * k; b._vy += (dy / d) * k;
                }
            }

            // Atracción entre tópicos semánticamente similares (barrios temáticos)
            if (_state.topicSim) {
                for (var si = 0; si < dn.length; si++) {
                    var a2 = dn[si];
                    if (a2.tipo !== "topico") continue;
                    var simMap = _state.topicSim[a2.id];
                    if (!simMap) continue;
                    for (var sj = si + 1; sj < dn.length; sj++) {
                        var b2 = dn[sj];
                        if (b2.tipo !== "topico") continue;
                        var sim = simMap[b2.id];
                        if (!sim) continue;
                        var dx2 = b2._x - a2._x, dy2 = b2._y - a2._y;
                        var d2 = Math.sqrt(dx2 * dx2 + dy2 * dy2) || 0.1;
                        var idealD2 = (_nodeR(a2) + _nodeR(b2) + 40) * (1.4 - sim);
                        if (d2 > idealD2) {
                            var f2 = 0.01 * sim * _state.alpha;
                            a2._vx += dx2 * f2; a2._vy += dy2 * f2;
                            b2._vx -= dx2 * f2; b2._vy -= dy2 * f2;
                        }
                    }
                }
            }
            _state.edges.forEach(function (e) {
                var u = _state.nodeMap[e.source], t = _state.nodeMap[e.target];
                if (!u || !t) return;
                var dx = t._x - u._x, dy = t._y - u._y;
                var d = Math.sqrt(dx * dx + dy * dy) || 0.1;
                var idealD = _nodeR(u) + _nodeR(t) + 80;
                if (d > idealD) {
                    var f = 0.04 * Math.log(d / idealD + 1) * _state.alpha * (1 + (e.Wu_t_norm || 0));
                    u._vx += dx * f; u._vy += dy * f;
                    t._vx -= dx * f * 0.15; t._vy -= dy * f * 0.15;
                }
            });
            dn.forEach(function (n) {
                var g = n.tipo === "topico" ? 0.007 : 0.003;
                n._vx += (W / 2 - n._x) * g * _state.alpha;
                n._vy += (H / 2 - n._y) * g * _state.alpha;
                // Fuerza suave hacia la posición objetivo (polarización/impacto/puentes para usuarios)
                if (n._tx !== undefined) {
                    var kHome = (n.tipo === "topico") ? 0.012 : 0.02;
                    n._vx += (n._tx - n._x) * kHome * _state.alpha;
                    n._vy += (n._ty - n._y) * kHome * _state.alpha;
                }
                n._vx *= 0.82; n._vy *= 0.82;
                var r = _nodeR(n);
                n._x = Math.max(r + 4, Math.min(W - r - 4, n._x + n._vx));
                n._y = Math.max(r + 4, Math.min(H - r - 4, n._y + n._vy));
            });
            _draw(ctx, W, H);
            if (_state.tickRunning) requestAnimationFrame(function () { _tick(ctx, W, H); });
        }

        /* ─── Dibujo ──────────────────────────────────────────────── */
        function _draw(ctx, W, H) {
            ctx.clearRect(0, 0, W, H);
            ctx.save();
            ctx.translate(_state.transform.x, _state.transform.y);
            ctx.scale(_state.transform.scale, _state.transform.scale);

            var visible = _nodesVisibles();
            var visNodes = visible.nodes;
            var visEdges = visible.edges;
            var visIds = new Set(visNodes.map(function (n) { return n.id; }));

            var hl = _state.hlNode;
            var anyHL = hl !== null;
            var connectedNodes = new Set();
            if (anyHL) {
                connectedNodes.add(hl);
                visEdges.forEach(function (e) {
                    if (e.source === hl) connectedNodes.add(e.target);
                    if (e.target === hl) connectedNodes.add(e.source);
                });
            }

            /* Aristas — grosor normalizado contra el máximo Wu_t visible */
            var maxWuTVisible = 0;
            visEdges.forEach(function (e) {
                if ((e.Wu_t || 0) > maxWuTVisible) maxWuTVisible = e.Wu_t || 0;
            });

            visEdges.forEach(function (e) {
                var u = _state.nodeMap[e.source];
                var t = _state.nodeMap[e.target];
                if (!u || !t || !visIds.has(u.id) || !visIds.has(t.id)) return;

                var isHL = anyHL ? (hl === e.source || hl === e.target) : false;
                var baseOp = (e.Ib_e !== undefined) ? e.Ib_e : 0.5;
                var op = anyHL ? (isHL ? baseOp + 0.3 : 0.05) : baseOp * 0.55;

                // Normalización local: la arista más pesada del grupo tendrá el grosor máximo
                var wNorm = maxWuTVisible > 0 ? (e.Wu_t || 0) / maxWuTVisible : 0;

                // El grosor va de 0.8px (mínimo) a 5px (máximo), ajustado por el zoom
                var lw = (0.8 + wNorm * 4.2) / _state.transform.scale;

                ctx.beginPath();
                ctx.moveTo(u._x, u._y);
                ctx.lineTo(t._x, t._y);
                ctx.strokeStyle = _posColor(e.Cu_t, op);
                ctx.lineWidth = lw;
                ctx.stroke();
            });

            /* Nodos usuario */
            visNodes.filter(function (n) { return n.tipo === "usuario"; }).forEach(function (n) {
                var isHL = anyHL ? connectedNodes.has(n.id) : false;
                var baseOp = (n.Ib_u !== undefined) ? n.Ib_u : 0.75;
                var op = anyHL ? (isHL ? 1.0 : 0.08) : baseOp;
                var r = _nodeR(n) / _state.transform.scale;
                ctx.beginPath();
                ctx.arc(n._x, n._y, r, 0, 2 * Math.PI);
                ctx.fillStyle = _posColor(n.Cu, op * 0.4);
                ctx.fill();
                ctx.setLineDash([3 / _state.transform.scale, 2 / _state.transform.scale]);
                ctx.strokeStyle = _posColor(n.Cu, op);
                ctx.lineWidth = 1.2 / _state.transform.scale;
                ctx.stroke();
                ctx.setLineDash([]);
            });

            /* Nodos tópico */
            visNodes.filter(function (n) { return n.tipo === "topico"; }).forEach(function (n) {
                var isSelected = (n.id === _state.expandedTopicId);
                var baseOp = (n.Ib_t !== undefined) ? n.Ib_t : 0.88;
                var op = anyHL ? (connectedNodes.has(n.id) ? 1.0 : 0.15) : baseOp;
                /* Si hay expandedTopicId, atenuar los no seleccionados */
                if (_state.expandedTopicId && n.id !== _state.expandedTopicId) op = Math.min(op, 0.3);
                var r = _nodeR(n) / _state.transform.scale;

                /* Halo para el tópico expandido */
                if (isSelected) {
                    ctx.beginPath();
                    ctx.arc(n._x, n._y, r * 1.4, 0, 2 * Math.PI);
                    ctx.fillStyle = _posColor(n.Ct, 0.12);
                    ctx.fill();
                }
                ctx.beginPath();
                ctx.arc(n._x, n._y, r, 0, 2 * Math.PI);
                ctx.fillStyle = _posColor(n.Ct, op);
                ctx.fill();
                if (isSelected) {
                    ctx.strokeStyle = "#ffffff";
                    ctx.lineWidth = 2.5 / _state.transform.scale;
                    ctx.stroke();
                }

                /* Etiqueta */
                var lbl = (n.label || "").substring(0, 26);
                var fs = Math.max(7.5, Math.min(11, 9 / _state.transform.scale));
                ctx.font = (isSelected ? "700 " : "") + fs + "px system-ui";
                ctx.textAlign = "center";
                var tw = ctx.measureText(lbl).width;
                ctx.fillStyle = "rgba(255,255,255,0.80)";
                ctx.fillRect(n._x - tw / 2 - 2, n._y - fs, tw + 4, fs + 4);
                ctx.fillStyle = "rgba(33,37,41," + (op * 0.95) + ")";
                ctx.fillText(lbl, n._x, n._y);
            });

            ctx.restore();
        }

        /* ─── Eventos canvas ──────────────────────────────────────── */
        function _bindCanvasEvents(canvas, W, H) {
            // ── Limpieza de listeners de un render anterior ──────────────────
            if (_state._evHandlers) {
                var old = _state._evHandlers;
                canvas.removeEventListener("click", old.click);
                canvas.removeEventListener("mousemove", old.mousemove);
                canvas.removeEventListener("mouseleave", old.mouseleave);
                canvas.removeEventListener("wheel", old.wheel);
                canvas.removeEventListener("mousedown", old.mousedown);
                window.removeEventListener("mousemove", old.winMousemove);
                window.removeEventListener("mouseup", old.winMouseup);
                if (old.btnReset) old.btnReset.removeEventListener("click", old.btnResetHandler);
                (old.radios || []).forEach(function (r) {
                    r.el.removeEventListener("change", r.handler);
                });
            }

            var handlers = {};

            /* Clic: seleccionar tópico o usuario */
            handlers.click = function (evt) {
                var br = canvas.getBoundingClientRect();
                var mx = (evt.clientX - br.left - _state.transform.x) / _state.transform.scale;
                var my = (evt.clientY - br.top - _state.transform.y) / _state.transform.scale;

                var clicked = null;
                var visNodes = _nodesVisibles().nodes;
                visNodes.forEach(function (n) {
                    var r = _nodeR(n);
                    var dx = n._x - mx, dy = n._y - my;
                    if (Math.sqrt(dx * dx + dy * dy) < r + 6) clicked = n;
                });

                var det = document.getElementById("lexV2GrafoDetalle");

                if (clicked) {
                    if (_state.expandedTopicId === clicked.id) {
                        _state.expandedTopicId = null;
                        _state.hlNode = null;
                        if (det) det.classList.add("d-none");
                        _actualizarSidePanel(null);
                    } else {
                        _state.expandedTopicId = clicked.id;
                        _state.hlNode = clicked.id;
                        _mostrarDetalleNodo(clicked);
                        _actualizarHint(clicked);
                        _actualizarSidePanel(clicked);
                    }
                } else {
                    _state.expandedTopicId = null;
                    _state.hlNode = null;
                    if (det) det.classList.add("d-none");
                    _actualizarHint(null);
                    _actualizarSidePanel(null);
                }

                _draw(canvas.getContext("2d"), W, H);
            };
            canvas.addEventListener("click", handlers.click);

            /* Hover */
            handlers.mousemove = function (evt) {
                var br = canvas.getBoundingClientRect();
                var mx = (evt.clientX - br.left - _state.transform.x) / _state.transform.scale;
                var my = (evt.clientY - br.top - _state.transform.y) / _state.transform.scale;
                var over = null;
                var visNodes = _nodesVisibles().nodes;
                visNodes.forEach(function (n) {
                    var r = _nodeR(n);
                    var dx = n._x - mx, dy = n._y - my;
                    if (Math.sqrt(dx * dx + dy * dy) < r + 4) over = n;
                });
                if (over) {
                    var col = _posColorHex(over.tipo === "topico" ? over.Ct : over.Cu);
                    var lbC = _posLabel(over.tipo === "topico" ? over.Ct : over.Cu);
                    var html = over.tipo === "topico"
                        ? "<strong>" + over.label + "</strong><br>" +
                        "<span style='color:#aaa;font-size:11px;'>Tema — haz clic para ver usuarios</span><br>" +
                        "Impacto: <strong>" + (over.St || 0).toFixed(1) + "</strong><br>" +
                        "Tono: <span style='color:" + col + ";font-weight:500;'>" + lbC + "</span><br>" +
                        "Publicaciones: " + (over.Nt || 0)
                        : "<strong>Usuario " + over.label + "</strong><br>" +
                        "<span style='color:#aaa;font-size:11px;'>" + (over.plataforma || "—") + "</span><br>" +
                        "Influencia: <strong>" + (over.Su || 0).toFixed(1) + "</strong><br>" +
                        "Tono: <span style='color:" + col + ";font-weight:500;'>" + lbC + "</span><br>" +
                        "Interacciones: " + (over.n_posts || 0);
                    _showTip(evt, html);
                } else {
                    _hideTip();
                }
            };
            canvas.addEventListener("mousemove", handlers.mousemove);

            handlers.mouseleave = _hideTip;
            canvas.addEventListener("mouseleave", handlers.mouseleave);

            /* Zoom */
            handlers.wheel = function (e) {
                e.preventDefault();
                _state.transform.scale = Math.max(0.2, Math.min(6,
                    _state.transform.scale * (e.deltaY < 0 ? 1.12 : 0.89)));
                _draw(canvas.getContext("2d"), W, H);
            };
            canvas.addEventListener("wheel", handlers.wheel, { passive: false });

            /* Arrastrar */
            handlers.mousedown = function (e) {
                _state.drag = { x: e.clientX, y: e.clientY, tx: _state.transform.x, ty: _state.transform.y };
            };
            canvas.addEventListener("mousedown", handlers.mousedown);

            handlers.winMousemove = function (e) {
                if (!_state.drag) return;
                _state.transform.x = _state.drag.tx + (e.clientX - _state.drag.x);
                _state.transform.y = _state.drag.ty + (e.clientY - _state.drag.y);
                var cv4 = document.getElementById("lexV2GrafoCanvas");
                if (!cv4) return;
                _draw(cv4.getContext("2d"), W, H);
            };
            window.addEventListener("mousemove", handlers.winMousemove);

            handlers.winMouseup = function () { _state.drag = null; };
            window.addEventListener("mouseup", handlers.winMouseup);

            /* Reset zoom */
            var btnReset = document.getElementById("lexV2BtnResetGrafo");
            if (btnReset) {
                handlers.btnReset = btnReset;
                handlers.btnResetHandler = function () {
                    _state.transform = { x: 0, y: 0, scale: 1 };
                    var cv5 = document.getElementById("lexV2GrafoCanvas");
                    if (!cv5) return;
                    _draw(cv5.getContext("2d"), W, H);
                };
                btnReset.addEventListener("click", handlers.btnResetHandler);
            }

            /* Cambio de nivel (tópico / usuario) */
            handlers.radios = [];
            document.querySelectorAll('input[name="lexV2GrafoNivel"]').forEach(function (radio) {
                var h = function () {
                    _state.grafoNivel = this.value;
                    _state.expandedTopicId = null;
                    _state.hlNode = null;
                    var det = document.getElementById("lexV2GrafoDetalle");
                    if (det) det.classList.add("d-none");
                    _actualizarHint(null);
                    _actualizarSidePanel(null);
                    var cv = document.getElementById("lexV2GrafoCanvas");
                    if (!cv) return;
                    _draw(cv.getContext("2d"), W, H);
                };
                radio.addEventListener("change", h);
                handlers.radios.push({ el: radio, handler: h });
            });

            _state._evHandlers = handlers;
            _state.evBound = true;
        }

        function _actualizarHint(node) {
            var hint = document.getElementById("lexV2GrafoHint");
            if (!hint) return;
            var nivel = _state.grafoNivel;
            if (!node) {
                hint.innerHTML = nivel === 'topic'
                    ? "<strong>Modo tema:</strong> Cada círculo es un argumento principal. Haz clic para ver los usuarios que lo impulsan."
                    : "<strong>Modo usuario:</strong> Cada círculo es un perfil anónimo. Haz clic para ver los temas que trabaja.";
            } else {
                var label = node.label || node.id;
                hint.innerHTML = node.tipo === "topico"
                    ? "Mostrando usuarios conectados a <strong>«" + label + "»</strong>. Haz clic de nuevo para colapsar."
                    : "Mostrando temas de <strong>«" + label + "»</strong>. Haz clic de nuevo para colapsar.";
            }
        }

        /* Panel de detalle al clic */
        function _mostrarDetalleNodo(node) {
            var det = document.getElementById("lexV2GrafoDetalle");
            var cnt = document.getElementById("lexV2GrafoDetalleContenido");
            if (!det || !cnt) return;
            det.classList.remove("d-none");

            var cVal = (node.tipo === "topico") ? node.Ct : node.Cu;
            var col = _posColorHex(cVal);
            var lbC = _posLabel(cVal);
            var html = '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;">';
            html += '<div><small style="color:#aaa;font-size:10px;text-transform:uppercase;">Tipo</small><br>' +
                '<span style="background:' + (node.tipo === "topico" ? "#6f42c1" : "#0d6efd") +
                ';color:#fff;font-size:11px;padding:2px 8px;border-radius:4px;">' +
                (node.tipo === "topico" ? "Tema" : "Perfil") + '</span></div>';
            html += '<div class="vr" style="height:2em;"></div>';
            html += '<div><small style="color:#aaa;font-size:10px;">Etiqueta</small><br><strong>' + (node.label || node.id) + '</strong></div>';
            html += '<div class="vr" style="height:2em;"></div>';
            if (node.tipo === "topico") {
                html += '<div><small style="color:#aaa;font-size:10px;">Impacto</small><br><strong>' + (node.St || 0).toFixed(1) + '</strong></div>';
                html += '<div class="vr" style="height:2em;"></div>';
                html += '<div><small style="color:#aaa;font-size:10px;">Tono</small><br><span style="color:' + col + ';font-weight:500;">' + lbC + '</span></div>';
                html += '<div class="vr" style="height:2em;"></div>';
                html += '<div><small style="color:#aaa;font-size:10px;">Publicaciones</small><br>' + (node.Nt || 0) + '</div>';
            } else {
                html += '<div><small style="color:#aaa;font-size:10px;">Influencia</small><br><strong>' + (node.Su || 0).toFixed(1) + '</strong></div>';
                html += '<div class="vr" style="height:2em;"></div>';
                html += '<div><small style="color:#aaa;font-size:10px;">Tono</small><br><span style="color:' + col + ';font-weight:500;">' + lbC + '</span></div>';
                html += '<div class="vr" style="height:2em;"></div>';
                html += '<div><small style="color:#aaa;font-size:10px;">Plataforma</small><br>' + (node.plataforma || "—") + '</div>';
                html += '<div class="vr" style="height:2em;"></div>';
                html += '<div><small style="color:#aaa;font-size:10px;">Interacciones</small><br>' + (node.n_posts || 0) + '</div>';
            }
            html += '</div>';
            cnt.innerHTML = html;
        }

        /* ═══════════ D. PANEL LATERAL BIDIRECCIONAL ═══════════════ */

        function _escAttr(s) {
            return String(s == null ? "" : s).replace(/"/g, "&quot;");
        }

        /* Devuelve los nodos conectados a nodeId vía _state.edges, con su arista */
        function _conectados(nodeId) {
            var out = [];
            _state.edges.forEach(function (e) {
                if (e.source === nodeId) {
                    var n = _state.nodeMap[e.target];
                    if (n) out.push({ node: n, edge: e });
                } else if (e.target === nodeId) {
                    var n = _state.nodeMap[e.source];
                    if (n) out.push({ node: n, edge: e });
                }
            });
            return out;
        }

        function _placeholderSidePanel() {
            return '<div class="text-center text-muted py-4">' +
                '<i class="bi bi-hand-index-thumb display-6 d-block mb-2 opacity-25"></i>' +
                '<p class="small mb-1">Explora el mapa tocando los círculos.</p>' +
                '<p class="small mb-0" style="font-size:.68rem;">' +
                'Al elegir un <strong>tema</strong>, verás quiénes hablan de él. ' +
                'Si eliges un <strong>usuario</strong>,  descubrirás qué temas defiende cada autor. ' +
                'Haz clic de nuevo para leer sus mensajes reales.' +
                '</p></div>';
        }

        function _actualizarSidePanel(node) {
            var panel = document.getElementById("lexV2GrafoSidePanel");
            if (!panel) return;
            if (!node) {
                panel.innerHTML = _placeholderSidePanel();
                return;
            }
            _renderSideConnectedList(node);
        }


        /* Lista de nodos conectados al nodo seleccionado con porcentajes */
        function _renderSideConnectedList(node) {
            var panel = document.getElementById("lexV2GrafoSidePanel");
            if (!panel) return;

            var esTopico = node.tipo === "topico";
            var conectados = _conectados(node.id);

            if (!conectados.length) {
                panel.innerHTML = '<div class="text-center text-muted py-4"><p class="small">Sin conexiones.</p></div>';
                return;
            }

            // 1. Ordenar por peso
            conectados.sort(function (a, b) { return (b.edge.Wu_t || 0) - (a.edge.Wu_t || 0); });

            // 2. Encontrar el máximo Wu_t de ESTA lista para que la barra tenga sentido visual
            var maxWuTEnLista = Math.max.apply(null, conectados.map(function (c) { return c.edge.Wu_t || 0; }));

            var html = '<div class="mb-3">' +
                '<h6 class="fw-bold mb-1" style="color:#6f42c1;font-size:.8rem;">' +
                (esTopico ? "Voces en este tema" : "Temas tratados por este autor") + '</h6>' +
                '<div class="small text-dark fw-bold mb-1">«' + (node.label || node.id) + '»</div>' +
                '</div><div class="list-group list-group-flush">';

            conectados.forEach(function (c) {
                var n = c.node, e = c.edge;
                var lbl = esTopico ? ("Usuario " + n.label) : n.label;
                var colE = _posColorHex(e.Cu_t);

                // 3. Usar el valor absoluto de influencia
                var wuT = e.Wu_t || 0;

                // 4. La barra ahora es relativa al líder de la lista (UX mucho mejor)
                var pctBarra = maxWuTEnLista > 0 ? (wuT / maxWuTEnLista) * 100 : 0;

                var nPostsLbl = e.n_posts ? (e.n_posts + (e.n_posts === 1 ? ' post' : ' posts')) : '';

                html +=
                    '<button type="button" class="list-group-item list-group-item-action lex-side-item px-2 py-2" ' +
                    'data-uid="' + _escAttr(esTopico ? n.id : node.id) + '" ' +
                    'data-topic="' + _escAttr(esTopico ? node.id.replace("topico__", "") : n.id.replace("topico__", "")) + '">' +
                    '<div class="d-flex justify-content-between align-items-center">' +
                    '<span class="small fw-bold">' + lbl + '</span>' +
                    '<span class="badge" style="background:' + colE + ';font-size:.6rem;">' + _posLabel(e.Cu_t) + '</span>' +
                    '</div>' +
                    '<div class="d-flex justify-content-between mb-1" style="font-size:.65rem;color:#888;">' +
                    '<span>Influencia: <strong>' + wuT.toFixed(1) + '</strong></span>' +
                    '<span>' + nPostsLbl + '</span>' +
                    '</div>' +
                    '<div class="progress" style="height:4px;background:rgba(0,0,0,0.05);">' +
                    '<div class="progress-bar" style="width:' + pctBarra.toFixed(1) + '%;background:' + colE + ';"></div>' +
                    '</div>' +
                    '</button>';
            });

            html += '</div>';
            panel.innerHTML = html;

            panel.querySelectorAll(".lex-side-item").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    _renderSidePosts(btn.dataset.uid, btn.dataset.topic, "", "", node);
                });
            });
        }

        /* Posts de un usuario en un tópico concreto */
        function _renderSidePosts(uid, topicKey, topicLabel, uidLabel, backNode) {
            var panel = document.getElementById("lexV2GrafoSidePanel");
            if (!panel) return;

            var platSel = document.getElementById("lexV2PlatFilter");
            var platActiva = platSel ? platSel.value.toLowerCase() : "todas";

            var posts = (rawDataset || []).filter(function (p) {
                var pUid = String(p.id_anonimo || "").trim();
                var pTopic = (p.topic || p.TOPIC || "").toLowerCase().trim();
                if (pUid !== uid) return false;
                if (pTopic !== topicKey) return false;
                if (platActiva !== "todas" && (p.plataforma || "").toLowerCase() !== platActiva) return false;
                return true;
            });

            var html =
                '<button type="button" class="btn btn-sm btn-outline-secondary mb-2" id="lexV2SideBack">' +
                '<i class="bi bi-arrow-left me-1"></i>Volver</button>' +
                '<h6 class="fw-bold mb-1" style="color:#6f42c1;font-size:.8rem;">' +
                '<i class="bi bi-person-fill me-1"></i>' + (uidLabel || uid.substring(0, 5).toUpperCase()) +
                ' <i class="bi bi-arrow-right mx-1"></i>' +
                '<i class="bi bi-tag-fill me-1"></i>' + (topicLabel || topicKey) +
                '</h6>';

            if (!posts.length) {
                html +=
                    '<div class="alert alert-info small mt-2 mb-0">' +
                    '<i class="bi bi-info-circle me-1"></i>Sin publicaciones de este usuario en este tópico' +
                    (platActiva !== "todas" ? (' para ' + platActiva) : '') + '.' +
                    '</div>';
            } else {
                posts = posts.slice().sort(function (a, b) {
                    return (parseFloat(b.ScoreOP_sup) || 0) - (parseFloat(a.ScoreOP_sup) || 0);
                });
                html += '<div class="text-muted mb-2" style="font-size:.65rem;">' + posts.length + ' publicación(es)</div><div>';
                posts.forEach(function (post) {
                    var pct = post.ScoreOP_pct != null ? parseFloat(post.ScoreOP_pct) : null;
                    var cat = pct !== null ? scoreopCategoria(pct) : null;
                    var sup = post.ScoreOP_sup != null ? parseFloat(post.ScoreOP_sup) : null;
                    var platColor = getPlatformColor(post.plataforma || "");
                    var stance = post.stance_post;
                    var stanceIcon = (stance === 1 || stance === "1") ? "bi-hand-thumbs-up text-success" :
                        (stance === -1 || stance === "-1") ? "bi-hand-thumbs-down text-danger" :
                            "bi-dash-circle text-muted";
                    html +=
                        '<div class="border rounded-3 p-2 mb-2 bg-white shadow-sm">' +
                        '<div class="d-flex justify-content-between align-items-center mb-1 flex-wrap gap-1">' +
                        '<span class="badge rounded-pill" style="background:' + platColor + ';font-size:.55rem;">' +
                        (post.plataforma || "--") + '</span>' +
                        (cat ? '<span class="badge px-1" style="' + scoreopBadgeStyle(pct) + ';font-size:.55rem;">' +
                            pct.toFixed(1) + '%</span>' : '') +
                        (sup != null ? '<span class="badge rounded-pill px-1 fw-normal" style="background:rgba(108,117,125,0.12);color:#555;font-size:.52rem;">' +
                            '<i class="bi bi-megaphone me-1"></i>' + sup.toFixed(1) + '</span>' : '') +
                        '</div>' +
                        '<p class="mb-1 small text-dark" style="max-height:60px;overflow-y:auto;white-space:pre-wrap;word-break:break-word;font-size:.7rem;">' +
                        (post.contenido_post || "Sin contenido") + '</p>' +
                        '<div class="d-flex gap-2" style="font-size:.58rem;color:#888;">' +
                        '<span><i class="bi bi-chat-dots me-1"></i>' + (post.num_comentarios || 0) + '</span>' +
                        '<span><i class="bi ' + stanceIcon + ' me-1"></i>' + _stanceLabel(stance) + '</span>' +
                        '</div></div>';
                });
                html += '</div>';
            }

            panel.innerHTML = html;

            var backBtn = document.getElementById("lexV2SideBack");
            if (backBtn) {
                backBtn.addEventListener("click", function () { _renderSideConnectedList(backNode); });
            }
        }


        /* ═══════════ Tooltip ═══════════════════════════════════════ */
        function _ensureTip() {
            if (_state.tip) return _state.tip;
            var t = document.createElement("div");
            t.id = "lexV2Tooltip";
            t.style.cssText = "position:fixed;z-index:9999;display:none;background:rgba(33,37,41,.95);color:#fff;padding:8px 12px;border-radius:8px;font-size:12px;line-height:1.5;max-width:280px;pointer-events:none;box-shadow:0 4px 16px rgba(0,0,0,.3);";
            document.body.appendChild(t);
            _state.tip = t;
            return t;
        }
        function _showTip(e, html) { var t = _ensureTip(); t.innerHTML = html; t.style.display = "block"; t.style.left = (e.clientX + 14) + "px"; t.style.top = (e.clientY - 10) + "px"; }
        function _moveTip(e) { if (_state.tip) { _state.tip.style.left = (e.clientX + 14) + "px"; _state.tip.style.top = (e.clientY - 10) + "px"; } }
        function _hideTip() { if (_state.tip) _state.tip.style.display = "none"; }

        /* ═══════════ Carga de datos desde el backend ═══════════════ */
        async function _cargarDatos(analysisId, plataforma, geo) {
            plataforma = plataforma || "todas";
            if (!geo && window._lastFilterTerms && window._lastFilterTerms.geo && window._lastFilterTerms.geo.length) {
                geo = window._lastFilterTerms.geo.join(",");
            }
            geo = geo || "";

            var url = "/analisis/" + analysisId + "/lexico-semantico-v2" +
                "?plataforma=" + encodeURIComponent(plataforma) +
                (geo ? "&geo=" + encodeURIComponent(geo) : "");

            var loader = document.getElementById("lexV2Loader");
            var content = document.getElementById("lexV2Content");
            var metaEl = document.getElementById("lexV2Meta");

            if (loader) { loader.classList.remove("d-none"); loader.innerHTML = '<div class="spinner-border" style="color:#6f42c1;width:2.5rem;height:2.5rem;"></div><p style="color:#6c757d;margin-top:10px;font-size:13px;">Construyendo representaciones semánticas…</p>'; }
            if (content) content.classList.add("d-none");

            try {
                var resp = await fetch(url);
                if (!resp.ok) { var err = await resp.json().catch(function () { return {}; }); throw new Error(err.detail || err.error || "Error " + resp.status); }
                var data = await resp.json();

                /* Guardar tópicos y nubes del dashboard principal para uso en el panel de temas */
                if (window.rawDataset) data._rawDataset = window.rawDataset;
                var topicsBase = (window._lastFilteredData && window._lastFilteredData.topics)
                    ? window._lastFilteredData.topics
                    : (_allTopics || []);
                data._topics = topicsBase;
                data._nubes = {};
                /* Intentar recuperar nubes ya cargadas en el dashboard */
                var mainNubes = document.getElementById("cloudContainer");
                if (mainNubes) {
                    mainNubes.querySelectorAll("img").forEach(function (img) {
                        var plat = img.closest("[data-plat]") ? img.closest("[data-plat]").dataset.plat : "global";
                        data._nubes[plat] = img.src.replace("data:image/png;base64,", "");
                    });
                }

                /* También leer nubes desde el contenedor original del dashboard */
                var dashCloud = document.getElementById("cloudContainer");
                if (dashCloud && window._lastDashboardData && window._lastDashboardData.nubes) {
                    data._nubes = window._lastDashboardData.nubes;
                }

                _state.data = data;
                _state.analysisId = analysisId;

                if (loader) loader.classList.add("d-none");
                if (content) content.classList.remove("d-none");

                var temasPanel = document.getElementById("lexV2PanelTemas");
                if (temasPanel && temasPanel.classList.contains("active")) {
                    _state._temosRendered = true;
                    _renderTemas(data);
                }

                /* Meta */
                if (metaEl && data.meta) {
                    var m = data.meta;
                    metaEl.innerHTML =
                        '<span style="background:#f8f9fa;border:0.5px solid #dee2e6;border-radius:6px;padding:3px 10px;font-size:11px;">' + m.total_posts + ' publicaciones</span> ' +
                        '<span style="background:#f8f9fa;border:0.5px solid #dee2e6;border-radius:6px;padding:3px 10px;font-size:11px;">' + m.plataforma + '</span>' +
                        (data.grafo_bipartito && data.grafo_bipartito.meta
                            ? ' <span style="background:#f8f9fa;border:0.5px solid #dee2e6;border-radius:6px;padding:3px 10px;font-size:11px;">' +
                            data.grafo_bipartito.meta.n_topicos + ' tópicos · ' +
                            data.grafo_bipartito.meta.n_usuarios + ' usuarios</span>'
                            : '');
                }

                /* Renderizar nube */
                _state.nubePool = data.nube_unificada || [];
                _aplicarFiltroNube();

                /* Renderizar temas (cuando se active la pestaña) */
                /* — se llama también desde el listener de tab */
                _state._temosRendered = false;

                /* Renderizar grafo */
                setTimeout(function () { _renderGrafo(data); }, 60);

            } catch (err) {
                console.error("[LEXICO-V2]", err);
                if (loader) loader.innerHTML = '<div style="color:#dc3545;font-size:13px;">' + err.message + '</div>';
            }
        }

        /* ═══════════ Inicialización ════════════════════════════════ */
        function _init() {
            var lexTab = document.getElementById("lexico-tab");
            var platSel = document.getElementById("lexV2PlatFilter");
            var btnLoad = document.getElementById("lexV2BtnCargar");

            if (!lexTab) return;

            /* Activar al mostrar la pestaña principal */
            lexTab.addEventListener("shown.bs.tab", function () {
                var projectSelect = document.getElementById("projectSelect");
                var id = projectSelect ? projectSelect.value : null;
                if (!id) return;
                var geoTerms = (window._lastFilterTerms && window._lastFilterTerms.geo) ? window._lastFilterTerms.geo.join(",") : "";
                if (window._lexicoPendingReload) {
                    window._lexicoPendingReload = false;
                    _cargarDatos(id, platSel ? platSel.value : "todas", geoTerms);
                    return;
                }
                if (!_state.data || _state.analysisId !== id) {
                    _cargarDatos(id, platSel ? platSel.value : "todas", "");
                } else {
                    var canvas = document.getElementById("lexV2GrafoCanvas");
                    if (canvas && canvas.style.width === "") { _state.evBound = false; _renderGrafo(_state.data); }
                }
            });

            /* Sub-tab "Temas detectados" — renderizar al activar */
            var temasTabBtn = document.getElementById("lexV2TemasTab");
            if (temasTabBtn) {
                temasTabBtn.addEventListener("shown.bs.tab", function () {
                    if (_state.data) {
                        /* Siempre re-renderizar para reflejar plataforma activa */
                        _state._temosRendered = true;
                        _renderTemas(_state.data);
                    }
                });
            }
            [document.getElementById("lexV2NPalabras"), document.getElementById("lexV2NBigramas")]
                .filter(Boolean)
                .forEach(function (sel) {
                    sel.addEventListener("change", function () {
                        _aplicarFiltroNube();
                    });
                });

            /* Selectores "Temas" / "Usuarios" del grafo bipartito */
            [document.getElementById("lexV2TopNTopics"), document.getElementById("lexV2TopNUsers")]
                .filter(Boolean)
                .forEach(function (sel) {
                    sel.addEventListener("change", function () {
                        if (!_state.data) return;
                        _state.evBound = false;
                        _renderGrafo(_state.data);
                    });
                });
            /* Sub-tab "Mapa de narrativas" — redibujar canvas al activar */
            var grafoTabBtn = document.getElementById("lexV2GrafoTab");
            if (grafoTabBtn) {
                grafoTabBtn.addEventListener("shown.bs.tab", function () {
                    if (_state.data) {
                        setTimeout(function () {
                            _state.evBound = false;
                            _renderGrafo(_state.data);
                        }, 50);
                    }
                });
            }

            /* Cambio de plataforma */
            if (platSel) {
                platSel.addEventListener("change", function () {
                    var projectSelect = document.getElementById("projectSelect");
                    var id = projectSelect ? projectSelect.value : null;
                    if (!id) return;
                    var geoTerms = (window._lastFilterTerms && window._lastFilterTerms.geo) ? window._lastFilterTerms.geo.join(",") : "";
                    // Reset COMPLETO del estado antes de recargar
                    _state.data = null;
                    _state.evBound = false;
                    _state._temosRendered = false;
                    _state.nodes = [];
                    _state.edges = [];
                    _state.nodeMap = {};
                    _state.expandedTopicId = null;
                    _state.hlNode = null;
                    _state.alpha = 0;
                    _state.tickRunning = false;
                    _cargarDatos(id, this.value, geoTerms).then(function () {
                        var temasPanel = document.getElementById("lexV2PanelTemas");
                        if (temasPanel && temasPanel.classList.contains("active")) {
                            _state._temosRendered = true;
                            _renderTemas(_state.data);
                        }
                    });
                });
            }

            /* Botón recargar */
            /* DESPUÉS */
            if (btnLoad) {
                btnLoad.addEventListener("click", function () {
                    var projectSelect = document.getElementById("projectSelect");
                    var id = projectSelect ? projectSelect.value : null;
                    if (!id) return;
                    var geoTerms = (window._lastFilterTerms && window._lastFilterTerms.geo) ? window._lastFilterTerms.geo.join(",") : "";
                    // Reset completo igual que cambio de plataforma
                    _state.data = null;
                    _state.evBound = false;
                    _state._temosRendered = false;
                    _state.nodes = [];
                    _state.edges = [];
                    _state.nodeMap = {};
                    _state.expandedTopicId = null;
                    _state.hlNode = null;
                    _state.alpha = 0;
                    _state.tickRunning = false;
                    _cargarDatos(id, platSel ? platSel.value : "todas", geoTerms);
                });
            }

            /* Cambio de proyecto */
            var projectSelect = document.getElementById("projectSelect");
            if (projectSelect) {
                projectSelect.addEventListener("change", function () {
                    _state.data = null; _state.evBound = false; _state._temosRendered = false;
                });
            }

            /* Filtros de subtema dentro del panel de temas */
            var btnApplyTopic = document.getElementById("lexV2BtnApplyTopic");
            var btnClearTopic = document.getElementById("lexV2BtnClearTopic");
            var topicInput = document.getElementById("lexV2TopicFilterInput");

            /* REEMPLAZAR el listener de btnApplyTopic dentro de _init() */
            if (btnApplyTopic) {
                btnApplyTopic.addEventListener("click", async function () {
                    var val = topicInput ? topicInput.value.trim() : "";
                    if (!val) return;

                    var projectSelect = document.getElementById("projectSelect");
                    var analysisId = projectSelect ? projectSelect.value : null;
                    if (!analysisId) return;

                    var topics = (_state.data && _state.data._topics) || _allTopics || [];
                    var valLower = val.toLowerCase();

                    // ── 1. Búsqueda local exacta y parcial primero (rápida, sin coste) ──
                    var foundLocal = topics.find(function (t) {
                        return (t.TOPIC || t.TOPIC_CLEAN || "").toLowerCase().trim() === valLower;
                    });
                    if (!foundLocal) {
                        foundLocal = topics.find(function (t) {
                            return (t.TOPIC || t.TOPIC_CLEAN || "").toLowerCase().includes(valLower);
                        });
                    }

                    if (foundLocal) {
                        // Coincidencia local: mostrar sin llamar al servidor
                        _renderTopicsDetail([foundLocal], (rawDataset && rawDataset.length) || 1);
                        _renderTopicPostsPanel(foundLocal.TOPIC || foundLocal.TOPIC_CLEAN || val);
                        var sel = document.getElementById("lexV2TopicDropdownSelect");
                        if (sel) sel.value = foundLocal.TOPIC || foundLocal.TOPIC_CLEAN || "";
                        var pp = document.getElementById("lexV2TopicPostsPanel");
                        if (pp) pp.scrollIntoView({ behavior: "smooth", block: "start" });
                        return;
                    }

                    // ── 2. Sin coincidencia local → llamar al LLM vía /filter-geo ────────
                    var pp2 = document.getElementById("lexV2TopicPostsPanel");
                    if (pp2) {
                        pp2.innerHTML =
                            '<div class="text-center py-4">' +
                            '<div class="spinner-border spinner-border-sm mb-2" style="color:#6f42c1;"></div>' +
                            '<p class="small text-muted">Buscando con IA…</p>' +
                            '</div>';
                    }

                    try {
                        var geoTerms = (window._lastFilterTerms && window._lastFilterTerms.geo)
                            ? window._lastFilterTerms.geo
                            : [];

                        var response = await fetch("/analisis/" + analysisId + "/filter-geo", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                terms: geoTerms,
                                custom_topic: val
                            })
                        });

                        if (!response.ok) {
                            var errData = await response.json().catch(function () { return {}; });
                            throw new Error(errData.detail || "Error del servidor (" + response.status + ")");
                        }

                        var newData = await response.json();

                        // Actualizar rawDataset con los datos filtrados
                        rawDataset = newData.raw_data || rawDataset;

                        // Reconstruir topics desde los datos filtrados
                        var topicsFiltrados = newData.topics || [];

                        if (topicsFiltrados.length === 0) {
                            if (pp2) {
                                pp2.innerHTML =
                                    '<div class="alert alert-warning small">' +
                                    '<i class="bi bi-search me-2"></i>La IA no encontró publicaciones sobre <strong>"' +
                                    val + '"</strong> en este análisis.' +
                                    '</div>';
                            }
                            return;
                        }

                        // Actualizar _state con los nuevos topics para que el dropdown refleje el filtro
                        if (_state.data) {
                            _state.data._topics = topicsFiltrados;
                        }

                        // Re-renderizar el detalle de tópicos con los resultados filtrados
                        _renderTopicsDetail(topicsFiltrados, (newData.kpis && newData.kpis.total) || rawDataset.length || 1);

                        // Mostrar posts del primer topic encontrado
                        var primerTopic = topicsFiltrados[0];
                        if (primerTopic) {
                            _renderTopicPostsPanel(primerTopic.TOPIC || primerTopic.TOPIC_CLEAN || val);
                        }

                        // Actualizar dropdown
                        var sel2 = document.getElementById("lexV2TopicDropdownSelect");
                        if (sel2) {
                            sel2.innerHTML = '<option value="">— Selecciona un subtema detectado —</option>';
                            topicsFiltrados.slice()
                                .sort(function (a, b) { return b.volumen - a.volumen; })
                                .forEach(function (t) {
                                    var lbl = t.TOPIC || t.TOPIC_CLEAN || "?";
                                    var opt = document.createElement("option");
                                    opt.value = lbl;
                                    opt.textContent = lbl + " (" + (t.volumen || 0) + " menciones)";
                                    sel2.appendChild(opt);
                                });
                            // Seleccionar el primero automáticamente
                            if (primerTopic) {
                                sel2.value = primerTopic.TOPIC || primerTopic.TOPIC_CLEAN || "";
                            }
                        }

                        // Scroll al panel
                        if (pp2) pp2.scrollIntoView({ behavior: "smooth", block: "start" });

                    } catch (err) {
                        console.error("[LEXICO-V2 topic LLM]", err);
                        if (pp2) {
                            pp2.innerHTML =
                                '<div class="alert alert-danger small">' +
                                '<i class="bi bi-exclamation-triangle me-2"></i>' + err.message +
                                '</div>';
                        }
                    }
                });
            }
            if (btnClearTopic) {
                btnClearTopic.addEventListener("click", function () {
                    if (topicInput) topicInput.value = "";

                    // Restaurar topics originales (antes del filtro LLM)
                    var topicsOriginales = _allTopics || [];
                    if (_state.data) {
                        _state.data._topics = topicsOriginales;
                    }

                    // Repoblar dropdown con todos los topics
                    var sel = document.getElementById("lexV2TopicDropdownSelect");
                    if (sel) {
                        sel.innerHTML = '<option value="">— Selecciona un subtema detectado —</option>';
                        topicsOriginales.slice()
                            .sort(function (a, b) { return b.volumen - a.volumen; })
                            .forEach(function (t) {
                                var lbl = t.TOPIC || t.TOPIC_CLEAN || "?";
                                var opt = document.createElement("option");
                                opt.value = lbl;
                                opt.textContent = lbl + " (" + (t.volumen || 0) + " menciones)";
                                sel.appendChild(opt);
                            });
                        sel.value = "";
                    }

                    _renderTopicsDetail(topicsOriginales, (rawDataset && rawDataset.length) || 1);
                    _clearTopicPostsPanel();
                });
            }

            /* API pública */
            window._lexicoV2 = {
                recargar: function (analysisId, plat, geo) {
                    _state.data = null; _state.evBound = false; _state._temosRendered = false;
                    _cargarDatos(analysisId, plat || "todas", geo || "");
                },
            };
        }

        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", _init);
        } else {
            _init();
        }

    })();

}); // fin DOMContentLoaded