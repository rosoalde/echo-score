document.addEventListener("DOMContentLoaded", () => {
    
    console.log("🚀 JS Principal cargado.");

    // 1. Inicializar lógica de "Seleccionar todos"
    setupSelectAll("selectAllSources", 'input[name="sources[]"]');
    setupSelectAll("selectAllLanguages", 'input[name="languages[]"]');

    // 2. Inicializar Generador de Keywords IA
    initKeywordGenerator();
    // ── Reconectar al análisis en curso si el usuario navegó y volvió ──────
    const savedId = localStorage.getItem("activeAnalysisId");
    const savedStart = parseInt(localStorage.getItem("activeAnalysisStart") || "0");
    const MAX_AGE_MS = 3 * 60 * 60 * 1000; // 3 horas máximo

    if (savedId && (Date.now() - savedStart) < MAX_AGE_MS) {
        // Verificar que el análisis sigue activo en el backend
        fetch(`/analisis/${savedId}/progreso`, { method: "GET" })
            .catch(() => {}); // Solo comprobamos que el endpoint existe

        // Mostrar la UI de progreso inmediatamente
        const progressDiv  = document.getElementById("progressContainer");
        const progressBar  = document.getElementById("progressBar");
        const progressText = document.getElementById("progressText");
        const stepLog      = document.getElementById("stepLog");
        const btnRun       = document.querySelector(".btn-ejecutar");
        const stopCol      = document.getElementById("stopCol");
        const runCol       = document.getElementById("runCol");

        if (progressDiv) progressDiv.classList.remove("d-none");
        if (progressText) progressText.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>Reconectando al análisis en curso…`;
        if (btnRun) btnRun.disabled = true;
        if (stopCol) stopCol.classList.remove("d-none");
        if (runCol)  runCol.classList.add("d-none");

        // Reconectar al stream SSE
        const reconnectSource = new EventSource(`/analisis/${savedId}/progreso`);
        let _loggedSteps = new Set();

        reconnectSource.onmessage = (event) => {
            let estado;
            try { estado = JSON.parse(event.data); } catch { return; }
            if (!estado || !estado.paso) return;

            const pct  = estado.porcentaje || 0;
            const info = infoPaso(estado.paso);
            const esError = estado.error === true;

            if (progressBar) {
                progressBar.style.width = `${pct}%`;
                progressBar.style.background = info.color;
                progressBar.className = esError
                    ? "progress-bar bg-warning"
                    : "progress-bar progress-bar-striped progress-bar-animated";
            }
            if (progressText) {
                progressText.innerHTML = `${info.icon} <strong>${estado.mensaje || info.label}</strong>
                    <span class="text-muted ms-2" style="font-size:.8rem;">(${pct}%)</span>`;
            }
            if (stepLog && estado.paso !== "inicio" && !_loggedSteps.has(estado.paso)) {
                _loggedSteps.add(estado.paso);
                const li = document.createElement("li");
                li.className = "list-group-item py-1 px-2 small border-0";
                li.style.color = info.color;
                li.innerHTML = `${info.icon} ${estado.mensaje || info.label}`;
                stepLog.prepend(li);
            }

            if (pct >= 100 || (esError && estado.paso === "error")) {
                reconnectSource.close();
                localStorage.removeItem("activeAnalysisId");
                if (stopCol) stopCol.classList.add("d-none");
                if (runCol)  runCol.classList.remove("d-none");
                if (btnRun)  { btnRun.disabled = false; }

                if (!esError) {
                    setTimeout(() => {
                        window.location.href = `/analizar-datasets?project_id=${savedId}`;
                    }, 1500);
                } else {
                    if (progressBar) progressBar.className = "progress-bar bg-danger";
                    if (progressText) progressText.innerHTML = `❌ ${estado.mensaje}`;
                }
            }
        };

        reconnectSource.onerror = () => {
            // El SSE se cerró porque el análisis ya terminó
            reconnectSource.close();
            localStorage.removeItem("activeAnalysisId");
            if (stopCol) stopCol.classList.add("d-none");
            if (runCol)  runCol.classList.remove("d-none");
            if (btnRun)  btnRun.disabled = false;
            if (progressText) progressText.innerHTML = `✅ Análisis finalizado (reconectado). Comprueba la <a href="/mis-analisis">biblioteca</a>.`;
        };

        // Botón detener también funciona en reconexión
        const stopBtn = document.getElementById("stopAnalysisBtn");
        if (stopBtn) {
            stopBtn.onclick = async () => {
                if (!confirm("¿Detener el análisis en curso?")) return;
                reconnectSource.close();
                localStorage.removeItem("activeAnalysisId");
                await fetch(`/analisis/${savedId}/detener`, { method: "POST" }).catch(() => {});
                if (stopCol) stopCol.classList.add("d-none");
                if (runCol)  runCol.classList.remove("d-none");
                if (btnRun)  { btnRun.disabled = false; btnRun.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i> REINTENTAR ANÁLISIS'; }
                if (progressBar) { progressBar.className = "progress-bar bg-danger"; progressBar.style.width = "100%"; }
                if (progressText) progressText.innerHTML = "⏹ Análisis detenido.";
            };
        }
    }

    // 3. Manejo del Formulario Principal
    const form = document.getElementById("projectForm");
    if (form) {
        form.addEventListener("submit", (e) => {
            e.preventDefault();
            if (!isRunning) runAnalysis();
        });
    }

    // 4. Logout
    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", (e) => {
            e.preventDefault();
            fetch("/logout", { method: "POST" })
                .then(() => window.location.href = "/login");
        });
    }
});

// Estado global del análisis
let isRunning = false;
let currentBriefDescription = "";
/*************************************************
 * LÓGICA DE KEYWORDS (IA) - VERSIÓN CORREGIDA
 *************************************************/
/*************************************************
 * LÓGICA DE KEYWORDS (IA) - VERSIÓN ROBUSTA
 *************************************************/
function initKeywordGenerator() {
    const generateBtn = document.getElementById("generateKeywordsBtn");
    const container = document.getElementById("generatedKeywordsContainer");
    const addBtn = document.getElementById("addSelectedKeywordsBtn");
    const themeInput = document.getElementById("temaInput");
    const finalInput = document.getElementById("keywordsInput"); // Input real (oculto)
    const previewSpan = document.getElementById("keywordsPreview"); // Texto visual
    const toggleBtn = document.getElementById("toggleKeywordsBtn");

    if (!generateBtn) return;
    
    // ─────────────────────────────────────────────
    // TÉRMINOS MANUALES
    // ─────────────────────────────────────────────

    const manualInput = document.getElementById("manualKeywordInput");
    const manualLang = document.getElementById("manualKeywordLang");
    const addManualBtn = document.getElementById("addManualKeywordBtn");
    const manualContainer = document.getElementById("manualKeywordsContainer");

    if (addManualBtn) {

        // sincronizar idiomas
        function syncLangSelect() {

            const checked = Array.from(
                document.querySelectorAll('input[name="languages[]"]:checked')
            ).map(cb => cb.value);

            manualLang.innerHTML = checked.length
                ? checked.map(
                    l => `<option value="${l}">${l}</option>`
                  ).join("")
                : `<option value="Castellano">Castellano</option>`;
        }

        document
            .querySelectorAll('input[name="languages[]"]')
            .forEach(cb => cb.addEventListener("change", syncLangSelect));

        syncLangSelect();

        // añadir chip manual
        function addManualChip(keyword, lang) {

            keyword = keyword.trim();

            if (!keyword) return;

            const kwObj = {
                keyword,
                languages: lang
            };

            const chip = document.createElement("div");

            chip.className =
                "form-check form-check-inline bg-white border rounded-pill px-3 py-2 m-1 shadow-sm";

            const cb = document.createElement("input");

            cb.type = "checkbox";
            cb.className = "form-check-input keyword-check";
            cb.value = JSON.stringify(kwObj);
            cb.id = "mkw_" + Math.random().toString(36).substr(2, 9);
            cb.checked = true;

            const lbl = document.createElement("label");

            lbl.className = "form-check-label ms-2";
            lbl.htmlFor = cb.id;

            lbl.innerHTML =
                `${keyword} <span class="badge bg-secondary ms-1" style="font-size:.6rem;">${lang}</span>`;

            // botón eliminar
            const rmBtn = document.createElement("button");

            rmBtn.type = "button";
            rmBtn.className =
                "btn btn-link btn-sm p-0 ms-2 text-danger";

            rmBtn.innerHTML = '<i class="bi bi-x"></i>';

            rmBtn.onclick = () => chip.remove();

            chip.append(cb, lbl, rmBtn);

            manualContainer.appendChild(chip);
        }

        // botón añadir
        addManualBtn.addEventListener("click", () => {

            const raw = manualInput.value;

            const lang = manualLang.value || "Castellano";

            raw.split(",").forEach(
                kw => addManualChip(kw, lang)
            );

            manualInput.value = "";
        });

        // enter
        manualInput.addEventListener("keydown", e => {

            if (e.key === "Enter") {

                e.preventDefault();

                addManualBtn.click();
            }
        });
    }


    // LISTENER GLOBAL PARA CAMBIOS EN CHECKBOXES
    if (container && toggleBtn) {
        container.addEventListener("change", () => {
            const checkboxes = container.querySelectorAll(".keyword-check");
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);
            toggleBtn.innerText = allChecked ? "Desmarcar todo" : "Marcar todo";
        });
    }
    // --- A. GENERAR KEYWORDS ---
    // --- A. GENERAR KEYWORDS ---
    generateBtn.addEventListener("click", async () => {
        const context = themeInput.value.trim();
        const selectedLangs = Array.from(document.querySelectorAll('input[name="languages[]"]:checked')).map(cb => cb.value);
        
        // 1. Captura del input de población
        const popInput = document.getElementById("populationInput");
        if (popInput) popInput.blur(); // Forzar actualización
        
        let rawPopulation = popInput ? popInput.value.trim() : "";
        let populationList = [];

        if (!rawPopulation) {
            // Informamos al usuario de la consecuencia de dejarlo vacío
            const confirmarGlobal = confirm(
                "⚠️ No has especificado un contexto geográfico.\n\n" +
                "El sistema NO filtrará los datos por ubicación y recogerá menciones de cualquier lugar del mundo.\n\n" +
                "¿Deseas continuar con un análisis GLOBAL?"
            );
            
            if (!confirmarGlobal) {
                popInput.focus();
                return; // Detiene la ejecución para que el usuario corrija
            }
            // Si acepta, enviamos un marcador especial
            populationList = ["GLOBAL"]; 
        } else {
            popInput.classList.remove("is-invalid");
            populationList = rawPopulation.split(",").map(s => s.trim()).filter(s => s !== "");
        }

        console.log("📤 Enviando a IA:", { context, selectedLangs, population: populationList });

        if (!context) { alert("⚠️ Introduce un tema."); themeInput.focus(); return; }
        if (selectedLangs.length === 0) { alert("⚠️ Selecciona al menos un idioma."); return; }
        

        const originalText = generateBtn.innerHTML;
        generateBtn.disabled = true;
        generateBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Generando...';
        
        try {
            const response = await fetch("/generate_keywords", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 
                    context: context, 
                    languages: selectedLangs, population: populationList // <--- AHORA ENVIAMOS UN ARRAY
                })
            });

            const data = await response.json();

            if (data.success) {
                currentBriefDescription = data.desc_tema || ""; // 💾 GUARDAMOS LA DESCRIPCIÓN
                console.log("✅ Descripción recibida:", currentBriefDescription);
            }

            if (data.tipo_tema) {
                const badgeContainer = document.getElementById("tipoBadgeContainer");
                if (badgeContainer) {
                    const esHiperlocal = data.tipo_tema === 'hiperlocal';
                    badgeContainer.innerHTML = esHiperlocal
                        ? `<span class="badge bg-warning text-dark me-2">
                            <i class="bi bi-geo-alt-fill me-1"></i>Tema hiperlocal detectado
                        </span>
                        <small class="text-muted">Se han generado términos específicos por municipio/zona sin filtro de genéricos.</small>`
                        : `<span class="badge bg-info text-dark me-2">
                            <i class="bi bi-globe me-1"></i>Tema universal detectado
                        </span>
                        <small class="text-muted">Se han generado términos independientes de la geografía. Usa el filtro del dashboard para segmentar por zona.</small>`;
                }
            }

            if (data.keywords && Array.isArray(data.keywords)) {
                container.innerHTML = ""; 
                // ... (El resto del código de renderizado de chips sigue igual) ...
                data.keywords.forEach(item => {
                    let kwObject;
                    let displayText;
                    if (typeof item === 'object' && item.keyword) {
                        kwObject = item;
                        displayText = item.keyword;
                    } else {
                        kwObject = { keyword: item, languages: selectedLangs };
                        displayText = item;
                    }
                    const chip = document.createElement("div");
                    chip.className = "form-check form-check-inline bg-white border rounded-pill px-3 py-2 m-1 shadow-sm user-select-none";
                    const cb = document.createElement("input");
                    cb.type = "checkbox";
                    cb.className = "form-check-input keyword-check";
                    cb.value = JSON.stringify(kwObject); 
                    cb.id = "kw_" + Math.random().toString(36).substr(2, 9);
                    cb.checked = true; 
                    const lbl = document.createElement("label");
                    lbl.className = "form-check-label ms-2 cursor-pointer";
                    lbl.htmlFor = cb.id;
                    lbl.innerText = displayText;
                    chip.appendChild(cb);
                    chip.appendChild(lbl);
                    container.appendChild(chip);
                });
                container.classList.remove("d-none");
                addBtn.classList.remove("d-none");
                addBtn.innerText = "Confirmar selección";
                toggleBtn.classList.remove("d-none");
                toggleBtn.innerText = "Desmarcar todo";
            } else {
                alert("No se pudieron generar keywords.");
            }

        } catch (err) {
            console.error(err);
            alert("Error de conexión con la IA.");
        } finally {
            generateBtn.disabled = false;
            generateBtn.innerHTML = originalText;
        }
    });

    // --- B. CONFIRMAR SELECCIÓN ---
    if (addBtn) {
        addBtn.addEventListener("click", () => {
            const selectedChecks = document.querySelectorAll(".keyword-check:checked");
            
            if (selectedChecks.length === 0) {
                alert("⚠️ No hay ninguna palabra seleccionada.");
                finalInput.value = "";
                previewSpan.innerText = "Ninguna seleccionada";
                return;
            }

            const selectedObjects = Array.from(selectedChecks).map(cb => JSON.parse(cb.value));
            finalInput.value = JSON.stringify(selectedObjects);

            const textSummary = selectedObjects.map(o => o.keyword).join(", ");
            previewSpan.innerText = `${selectedObjects.length} términos seleccionados.`;
            previewSpan.title = textSummary;
            
            previewSpan.parentElement.classList.remove("text-muted");
            previewSpan.parentElement.classList.add("text-success", "fw-bold", "border-success");
            
            addBtn.className = "btn btn-success btn-sm mb-3";
            addBtn.innerHTML = '<i class="bi bi-check-lg"></i> ¡Guardado!';
            setTimeout(() => {
                addBtn.innerText = "Actualizar selección";
                addBtn.className = "btn btn-outline-success btn-sm mb-3";
            }, 2000);
        });
    }
    // --- C. MARCAR / DESMARCAR TODO ---
    if (toggleBtn) {
        toggleBtn.addEventListener("click", () => {
            const checkboxes = document.querySelectorAll(".keyword-check");
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);

            checkboxes.forEach(cb => {
                cb.checked = !allChecked;
            });

            toggleBtn.innerText = allChecked ? "Marcar todo" : "Desmarcar todo";
        });
    }
}

/*************************************************
 * EJECUCIÓN DEL ANÁLISIS
 *************************************************/
async function runAnalysis2() {
    const form = document.getElementById("projectForm");
    const formData = new FormData(form);

    const sources = formData.getAll("sources[]");
    const languages = formData.getAll("languages[]");
    const keywords = formData.get("keywords");

    if (!formData.get("project_name")) { alert("Falta el nombre del proyecto"); return; }
    if (sources.length === 0) { alert("Selecciona al menos una fuente."); return; }
    if (languages.length === 0) { alert("Selecciona al menos un idioma."); return; }
    if (!keywords) { alert("Debes generar y confirmar los términos de búsqueda primero."); return; }

    // Preparar UI
    isRunning = true;
    const btnRun = document.querySelector(".btn-ejecutar");
    const progressDiv = document.getElementById("progressContainer");
    const progressBar = document.getElementById("progressBar");
    const progressText = document.getElementById("progressText");

    btnRun.disabled = true;
    btnRun.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Procesando...';
    if(progressDiv) progressDiv.classList.remove("d-none");
    if(progressBar) progressBar.style.width = "0%";
    if(progressText) progressText.innerText = "Iniciando análisis...";

    const payload = {
        project_name: formData.get("project_name"),
        asistente: formData.get("asistente"),
        keywords: keywords,
        start_date: formData.get("start_date"),
        end_date: formData.get("end_date"),
        sources: sources,
        languages: languages,
        population: formData.get("population") || "",
        results: sources.map(s => ({ social: s, success: true })) // placeholder
    };

    try {
        // 1️⃣ Inicia el análisis y recibe un ID de seguimiento
        const startResponse = await fetch("/ejecutar-analisis", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const startData = await startResponse.json();
        if (startData.status !== "ok") throw new Error(startData.message || "Error iniciando análisis");

        const analysisId = startData.analysis_id;
        progressText.innerText = "Análisis iniciado...";

        // 2️⃣ Polling de estado
        let completed = false;
        while (!completed) {
            await new Promise(r => setTimeout(r, 2000)); // Espera 2s

            const statusResponse = await fetch(`/estado-analisis?analysis_id=${analysisId}`);
            const statusData = await statusResponse.json();
            
            // statusData podría tener la forma:
            // { status: "iniciado"|"progress"|"terminado", current_source: "twitter", progress: 0-100, sources: [{name:"twitter", status:"progress"}, ...] }
            
            if (statusData.status === "iniciado") {
                progressText.innerText = "Iniciando análisis...";
                progressBar.style.width = "5%";
            } else if (statusData.status === "progress") {
                const current = statusData.current_source || "Procesando...";
                progressText.innerText = `Ejecutando en ${current}...`;
                progressBar.style.width = `${statusData.progress || 50}%`;
            } else if (statusData.status === "terminado") {
                completed = true;
                progressText.innerText = "¡Análisis completado!";
                progressBar.style.width = "100%";
                progressBar.classList.replace("bg-primary","bg-success");
            }
        }

        // Redirigir tras breve pausa
        setTimeout(() => {
            window.location.href = `/analizar-datasets?project_id=${analysisId}`;
        }, 2000);

    } catch(e) {
        console.error(e);
        alert("❌ Error: " + e.message);

        isRunning = false;
        btnRun.disabled = false;
        btnRun.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i> REINTENTAR ANÁLISIS';
        if(progressBar) progressBar.classList.add("bg-danger");
    }
}

/*************************************************
 * EJECUCIÓN DEL ANÁLISIS (SIN ESTADO / POLLING)
 *************************************************/
// Icono y color por paso (clave = valor de "paso" que emite el backend)
const PASO_INFO = {
    // Inicio
    inicio:             { icon: "⚙️",  color: "#6c757d", label: "Configurando…"                              },
 
    // Scrapers — patrón: scraping_<red>  y  scraping_<red>_ok / _error
    scraping_bluesky:   { icon: "🔵",  color: "#0085ff", label: "Descargando de Bluesky…"                    },
    scraping_bluesky_ok:{ icon: "✅",  color: "#198754", label: "Bluesky: completado"                        },
    scraping_reddit:    { icon: "🔴",  color: "#ff4500", label: "Descargando de Reddit…"                     },
    scraping_reddit_ok: { icon: "✅",  color: "#198754", label: "Reddit: completado"                         },
    scraping_youtube:   { icon: "▶️",  color: "#ff0000", label: "Descargando de YouTube…"                    },
    scraping_youtube_ok:{ icon: "✅",  color: "#198754", label: "YouTube: completado"                        },
 
    // Análisis IA
    sentiment:          { icon: "🧠",  color: "#6f42c1", label: "Analizando sentimiento y tópicos (IA)…"     },
    sentiment_ok:       { icon: "✅",  color: "#198754", label: "Sentimiento analizado"                       },
    sentiment_error:    { icon: "⚠️",  color: "#fd7e14", label: "Aviso: error parcial en sentimiento"         },
 
    // ScoreOP
    scoreop:            { icon: "📊",  color: "#0d6efd", label: "Calculando ScoreOP…"                         },
    scoreop_ok:         { icon: "✅",  color: "#198754", label: "ScoreOP calculado"                            },
    scoreop_error:      { icon: "⚠️",  color: "#fd7e14", label: "Aviso: error en ScoreOP"                     },
 
    // Reportes
    reporte:            { icon: "📄",  color: "#0dcaf0", label: "Generando reportes y dashboard…"             },
    reporte_ok:         { icon: "✅",  color: "#198754", label: "Reportes generados"                          },
    reporte_error:      { icon: "⚠️",  color: "#fd7e14", label: "Aviso: error en reportes"                    },
 
    // Nubes
    nubes:              { icon: "☁️",  color: "#6c757d", label: "Generando nubes de palabras…"                },
    nubes_ok:           { icon: "✅",  color: "#198754", label: "Nubes generadas"                             },
    nubes_error:        { icon: "⚠️",  color: "#fd7e14", label: "Aviso: error en nubes"                       },
 
    // Fin
    completado:         { icon: "🎉",  color: "#198754", label: "¡Análisis completado! Redirigiendo…"        },
    error:              { icon: "❌",  color: "#dc3545", label: "Error en el análisis"                        },
};
 
function infoPaso(paso) {
    // soporte para claves dinámicas como scraping_bluesky_ok  → busca exacta primero
    if (PASO_INFO[paso]) return PASO_INFO[paso];
    // fallback: recorte el sufijo _ok / _error si no hay entrada exacta
    const base = paso.replace(/_ok$/, "").replace(/_error$/, "");
    return PASO_INFO[base] || { icon: "⏳", color: "#6c757d", label: paso };
}
 
// ─── FUNCIÓN PRINCIPAL (reemplaza runAnalysis completa) ───────────────────
async function runAnalysis() {
    const form     = document.getElementById("projectForm");
    const formData = new FormData(form);
 
    const sources   = formData.getAll("sources[]");
    const languages = formData.getAll("languages[]");
    const keywords  = formData.get("keywords");
 
    // Validaciones
    if (!formData.get("project_name"))  { alert("Falta el nombre del proyecto."); return; }
    if (sources.length === 0)           { alert("Selecciona al menos una fuente."); return; }
    if (languages.length === 0)         { alert("Selecciona al menos un idioma."); return; }
    if (!keywords)                      { alert("Debes generar y confirmar los términos de búsqueda."); return; }
 
    // ── Referencias DOM ────────────────────────────────────────────────
    isRunning = true;
    const btnRun      = document.querySelector(".btn-ejecutar");
    const progressDiv = document.getElementById("progressContainer");
    const progressBar = document.getElementById("progressBar");
    const progressText= document.getElementById("progressText");
    const stepLog     = document.getElementById("stepLog");   // nuevo elemento HTML (ver index.html)
 
    btnRun.disabled   = true;
    btnRun.innerHTML  = '<span class="spinner-border spinner-border-sm me-2"></span>Procesando…';
    if (progressDiv) progressDiv.classList.remove("d-none");
    if (progressBar) { progressBar.style.width = "2%"; progressBar.className = "progress-bar progress-bar-striped progress-bar-animated bg-primary"; }
    if (progressText) progressText.innerText = "Iniciando análisis…";
    if (stepLog)      stepLog.innerHTML = "";
 
    const populationValue = (formData.get("population") || "").trim();
    const payload = {
        project_name: formData.get("project_name"),
        asistente:    formData.get("asistente"),
        desc_tema:    currentBriefDescription,
        keywords:     keywords,
        start_date:   formData.get("start_date"),
        end_date:     formData.get("end_date"),
        sources,
        languages,
        population:   populationValue || "GLOBAL",
        results:      sources.map(s => ({ social: s, success: true })),
    };
 
    try {
        // ── 1. Iniciar análisis (responde inmediatamente con analysis_id) ──
        const response = await fetch("/ejecutar-analisis", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(payload),
        });
        const startData = await response.json();
 
        if (!response.ok || startData.status == "failed") {
            throw new Error(startData.message || "Error iniciando análisis");
        }
 
        const analysisId = startData.analysis_id || startData.user_id;
        if (!analysisId) throw new Error("No se recibió el ID del análisis");
        // Persistir en localStorage para sobrevivir navegaciones y recargas durante el proceso
        localStorage.setItem("activeAnalysisId", analysisId);
        localStorage.setItem("activeAnalysisStart", Date.now());
 
        // ── 2. Suscribirse al stream de progreso (SSE) ─────────────────
        const evtSource = new EventSource(`/analisis/${analysisId}/progreso`);
        let _loggedSteps = new Set();   // tracks which paso values we've already rendered
        let currentAnalysisId = analysisId; // captured for the stop button
 
        evtSource.onmessage = (event) => {
            let estado;
            try { estado = JSON.parse(event.data); } catch { return; }
            if (!estado || !estado.paso) return;
 
            const pct    = estado.porcentaje || 0;
            const info   = infoPaso(estado.paso);
            const esError= estado.error === true;
 
            // Barra de progreso
            if (progressBar) {
                progressBar.style.width   = `${pct}%`;
                progressBar.style.background = info.color;
                progressBar.className = esError
                    ? "progress-bar bg-warning"
                    : "progress-bar progress-bar-striped progress-bar-animated";
                progressBar.style.background = info.color;
            }
 
            // Texto principal
            if (progressText) {
                progressText.innerHTML =
                    `${info.icon} <strong>${estado.mensaje || info.label}</strong>
                    <span class="text-muted ms-2" style="font-size:.8rem;">(${pct}%)</span>`;
            }
 
            // Log de pasos (lista acumulativa)
            if (stepLog && estado.paso !== "inicio" && !_loggedSteps.has(estado.paso)) {
                _loggedSteps.add(estado.paso);
                const li = document.createElement("li");
                li.className = "list-group-item py-1 px-2 small border-0";
                li.style.color      = info.color;
                li.style.fontWeight = pct >= 100 ? "600" : "normal";
                li.innerHTML = `${info.icon} ${estado.mensaje || info.label}`;
                stepLog.prepend(li);
            }
 
            // Al llegar al 100 % o error fatal → redirigir
            if (pct >= 100 || (esError && estado.paso === "error")) {
                evtSource.close();
                if (stopCol) stopCol.classList.add("d-none");
                if (runCol)  runCol.classList.remove("d-none");
 
                if (esError && estado.paso === "error") {
                    localStorage.removeItem("activeAnalysisId");
                    if (progressBar) progressBar.className = "progress-bar bg-danger";
                    if (progressText) progressText.innerHTML = `❌ ${estado.mensaje}`;
                    isRunning = false;
                    btnRun.disabled  = false;
                    btnRun.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i> REINTENTAR ANÁLISIS';
                    return;
                }
 
                // Éxito → esperar 1,5 s y redirigir
                setTimeout(() => {
                    localStorage.removeItem("activeAnalysisId");
                    window.location.href = `/analizar-datasets?project_id=${analysisId}`;
                }, 1500);
            }
        };
 
        evtSource.onerror = () => {
            // El SSE puede cerrarse naturalmente cuando el servidor termina.
            // Solo actuamos si aún no hemos redirigido.
            evtSource.close();
        };

        // Wire Stop button
        const stopBtn = document.getElementById("stopAnalysisBtn");
        const stopCol = document.getElementById("stopCol");
        const runCol  = document.getElementById("runCol");
        if (stopBtn) {
            stopCol.classList.remove("d-none");
            runCol.classList.add("d-none");

            stopBtn.onclick = async () => {
                if (!confirm("¿Seguro que quieres detener el análisis en curso?")) return;
                stopBtn.disabled = true;
                stopBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deteniendo…';
                try {
                    await fetch(`/analisis/${currentAnalysisId}/detener`, { method: "POST" });
                } catch (e) { console.warn("Stop request failed:", e); }
                evtSource.close();
                stopCol.classList.add("d-none");
                runCol.classList.remove("d-none");
                isRunning = false;
                btnRun.disabled  = false;
                btnRun.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i> REINTENTAR ANÁLISIS';
                if (progressBar) { progressBar.className = "progress-bar bg-danger"; progressBar.style.width = "100%"; }
                if (progressText) progressText.innerHTML = 
                    "⏳ Cancelación solicitada. El proceso actual terminará antes de parar.";
            };
        }
 
    } catch (e) {
        console.error(e);
        alert("❌ Error: " + e.message);
        isRunning = false;
        btnRun.disabled  = false;
        btnRun.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i> REINTENTAR ANÁLISIS';
        if (progressBar)  { progressBar.className = "progress-bar bg-danger"; progressBar.style.width = "100%"; }
        if (progressText) progressText.innerText = "Error en el análisis.";
    }
}
/*************************************************
 * UTILIDADES UI
 *************************************************/
function setupSelectAll(masterId, selector) {
    const master = document.getElementById(masterId);
    if (!master) return;

    const getCheckboxes = () =>
        Array.from(document.querySelectorAll(selector))
            .filter(cb => !cb.disabled); // 👈 SOLO LOS HABILITADOS

    // Maestro controla hijos
    master.addEventListener("change", () => {
        getCheckboxes().forEach(cb => cb.checked = master.checked);
    });

    // Hijos controlan maestro
    document.querySelectorAll(selector).forEach(cb => {
        cb.addEventListener("change", () => {
            if (cb.disabled) return; // 👈 ignorar deshabilitados

            const enabled = getCheckboxes();
            const allChecked = enabled.every(c => c.checked);
            master.checked = allChecked;
        });
    });
}