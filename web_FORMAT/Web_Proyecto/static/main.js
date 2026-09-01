/**
 * =============================================================================
 * CONFIGURACIÓN Y DICCIONARIOS GLOBALES
 * =============================================================================
 */
const PASO_INFO = {
    inicio:              { icon: "⚙️",  color: "#6c757d", label: "Configurando…" },
    scraping_bluesky:    { icon: "🔵",  color: "#0085ff", label: "Descargando de Bluesky…" },
    scraping_bluesky_ok: { icon: "✅",  color: "#198754", label: "Bluesky: completado" },
    scraping_reddit:     { icon: "🔴",  color: "#ff4500", label: "Descargando de Reddit…" },
    scraping_reddit_ok:  { icon: "✅",  color: "#198754", label: "Reddit: completado" },
    scraping_youtube:    { icon: "▶️",  color: "#ff0000", label: "Descargando de YouTube…" },
    scraping_youtube_ok: { icon: "✅",  color: "#198754", label: "YouTube: completado" },
    sentiment:           { icon: "🧠",  color: "#6f42c1", label: "Analizando sentimiento y tópicos (IA)…" },
    sentiment_ok:        { icon: "✅",  color: "#198754", label: "Sentimiento analizado" },
    sentiment_error:     { icon: "⚠️",  color: "#fd7e14", label: "Aviso: error parcial en sentimiento" },
    scoreop:             { icon: "📊",  color: "#0d6efd", label: "Calculando ScoreOP…" },
    scoreop_ok:          { icon: "✅",  color: "#198754", label: "ScoreOP calculado" },
    scoreop_error:       { icon: "⚠️",  color: "#fd7e14", label: "Aviso: error en ScoreOP" },
    reporte:             { icon: "📄",  color: "#0dcaf0", label: "Generando reportes y dashboard…" },
    reporte_ok:          { icon: "✅",  color: "#198754", label: "Reportes generados" },
    reporte_error:       { icon: "⚠️",  color: "#fd7e14", label: "Aviso: error en reportes" },
    nubes:               { icon: "☁️",  color: "#6c757d", label: "Generando nubes de palabras…" },
    nubes_ok:            { icon: "✅",  color: "#198754", label: "Nubes generadas" },
    nubes_error:         { icon: "⚠️",  color: "#fd7e14", label: "Aviso: error en nubes" },
    completado:          { icon: "🎉",  color: "#198754", label: "¡Análisis completado! Redirigiendo…" },
    error:               { icon: "❌",  color: "#dc3545", label: "Error en el análisis" },
};

function infoPaso(paso) {
    if (PASO_INFO[paso]) return PASO_INFO[paso];
    const base = paso.replace(/_ok$/, "").replace(/_error$/, "");
    return PASO_INFO[base] || { icon: "⏳", color: "#6c757d", label: paso };
}

// Estado global del análisis
let isRunning = false;
let currentBriefDescription = "";
let existingProjectNames = [];
/**
 * =============================================================================
 * LÓGICA PRINCIPAL (DOM Loaded)
 * =============================================================================
 */
document.addEventListener("DOMContentLoaded", async () => {
    console.log("🚀 JS Principal cargado.");

    // 1. Inicializar lógica de "Seleccionar todos"
    setupSelectAll("selectAllSources", 'input[name="sources[]"]');
    setupSelectAll("selectAllLanguages", 'input[name="languages[]"]');

    // 2. Inicializar Generador de Keywords IA
    initKeywordGenerator();
    await loadExistingProjects();
    initDateRestrictions();

    /**
     * =============================================================================
     * 3. RECONECTAR AL ANÁLISIS EN CURSO (CONTROL ANTI-DUPLICADOS Y LIBERACIÓN HTTP)
     * =============================================================================
     */
    const savedId = localStorage.getItem("activeAnalysisId"); 
    const savedSlug = localStorage.getItem("activeAnalysisSlug"); 
    const savedStart = parseInt(localStorage.getItem("activeAnalysisStart") || "0");
    const MAX_AGE_MS = 3 * 60 * 60 * 1000; // 3 horas máximo

    try {
        const response_projects = await fetch("/api/proyectos-sidebar");

        if (response_projects.ok) {
            const projects = response_projects.json();

            existingProjectNames = projects.map(p =>
                (p.project_name || "")
                    .trim()
                    .toLowerCase()
            );

        }

    } catch (err) {
        console.error("Error cargando proyectos:", err);
    }

    const projectNameInput = document.getElementById("project_name");
    const projectNameError = document.getElementById("projectNameError");

    if (projectNameInput) {

        projectNameInput.addEventListener("input", () => {

            const value = projectNameInput.value
                .trim()
                .toLowerCase();

            const exists = existingProjectNames.includes(value);

            if (exists) {
                projectNameInput.classList.add("is-invalid");
                projectNameError.innerHTML =
                    '<i class="bi bi-exclamation-circle-fill me-1"></i>' +
                    'Ya existe un proyecto con ese nombre';
            } else {
                projectNameInput.classList.remove("is-invalid");
            }
        });
    }

    // Puntero de control para el EventSource de reconexión
    let reconnectSource = null;

    if (savedId && (Date.now() - savedStart) < MAX_AGE_MS) {
        const progressDiv  = document.getElementById("progressContainer");
        const progressBar  = document.getElementById("progressBar");
        const progressText = document.getElementById("progressText");
        const stepLog      = document.getElementById("stepLog");
        const btnRun       = document.querySelector(".btn-ejecutar");
        const stopCol      = document.getElementById("stopCol");
        const runCol       = document.getElementById("runCol");
        const projectForm  = document.getElementById("projectForm");

        // Limpieza absoluta de la interfaz y la memoria caché local
        function liberarFormulario() {
            localStorage.removeItem("activeAnalysisId");
            localStorage.removeItem("activeAnalysisSlug");
            localStorage.removeItem("activeAnalysisStart");
            localStorage.removeItem("activeAnalysisLog");
            localStorage.removeItem("activeAnalysisPct");
            
            if (reconnectSource) {
                reconnectSource.close();
                reconnectSource = null;
            }

            if (projectForm) {
                Array.from(projectForm.children).forEach(el => {
                    el.style.display = ""; 
                });
            }
            if (progressDiv) progressDiv.classList.add("d-none");
            if (stopCol) stopCol.classList.add("d-none");
            if (runCol)  runCol.classList.remove("d-none");
            if (btnRun)  { 
                btnRun.disabled = false; 
                btnRun.innerHTML = '<i class="bi bi-rocket-takeoff me-2"></i> EJECUTAR ANÁLISIS COMPLETO';
            }
            isRunning = false;
        }

        // BLOQUEO VISUAL INMEDIATO SÍNCRONO (Cero parpadeos al recargar)
        if (projectForm) {
            Array.from(projectForm.children).forEach(el => {
                if (!el.id || (el.id !== "progressContainer" && el.id !== "resultsContainer" && el.id !== "actionButtons")) {
                    el.style.display = "none";
                }
            });
        }
        if (progressDiv) progressDiv.classList.remove("d-none");
        if (progressText) progressText.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>Sincronizando con el servidor…`;
        if (btnRun) btnRun.disabled = true;
        if (stopCol) stopCol.classList.remove("d-none");
        if (runCol)  runCol.classList.add("d-none");

        // Restaurar histórico sin duplicados viejos
        const savedLog = localStorage.getItem("activeAnalysisLog");
        if (stepLog && savedLog) {
            try {
                const logItems = JSON.parse(savedLog);
                stepLog.innerHTML = "";
                logItems.forEach(item => {
                    const li = document.createElement("li");
                    li.className = "list-group-item py-1 px-2 small border-0";
                    li.style.color = item.color;
                    li.innerHTML = item.html;
                    stepLog.appendChild(li);
                });
            } catch(e) {}
        }
        const savedPct = parseInt(localStorage.getItem("activeAnalysisPct") || "2");
        if (progressBar) progressBar.style.width = `${savedPct}%`;

        // ESCUCHA SSE INTEGRADA
        function iniciarEscuchaReconexion() {
            if (reconnectSource) reconnectSource.close();

            reconnectSource = new EventSource(`/analisis/${savedId}/progreso`);
            let _loggedSteps = new Set();
            let _reconnectRedirected = false;

            // Registrar lo que ya estaba pintado para que NUNCA se duplique
            if (stepLog) {
                stepLog.querySelectorAll("li").forEach(li => {
                    _loggedSteps.add(li.innerText.trim());
                });
            }

            reconnectSource.onmessage = (event) => {
                let estado;
                try { estado = JSON.parse(event.data); } catch { return; }
                if (!estado || !estado.paso) return;

                const pct = estado.porcentaje || 0;
                const info = infoPaso(estado.paso);
                const esError = estado.error === true;
                const esCancelado = estado.cancelled === true || estado.status === "cancelled" || estado.paso === "cancelled";

                if (esCancelado) {
                    liberarFormulario();
                    if (progressText) progressText.innerText = "⏹ El análisis en curso ha sido cancelado.";
                    return;
                }

                localStorage.setItem("activeAnalysisPct", pct);

                if (progressBar) {
                    progressBar.style.width = `${pct}%`;
                    progressBar.style.background = info.color;
                    progressBar.className = esError ? "progress-bar bg-danger" : "progress-bar progress-bar-striped progress-bar-animated";
                }
                if (progressText) {
                    progressText.innerHTML = `${info.icon} <strong>${estado.mensaje || info.label}</strong> <span class="text-muted ms-2" style="font-size:.8rem;">(${pct}%)</span>`;
                }

                // CONTROL ANTI-DUPLICADOS POR TEXTO LIMPIO
                const mensajeLimpio = `${info.icon} ${estado.mensaje || info.label}`.trim();
                const textoPlano = mensajeLimpio.replace(/<[^>]*>/g, '').trim(); 

                if (stepLog && estado.paso !== "inicio" && !_loggedSteps.has(textoPlano)) {
                    _loggedSteps.add(textoPlano);
                    const li = document.createElement("li");
                    li.className = "list-group-item py-1 px-2 small border-0";
                    li.style.color = info.color;
                    li.innerHTML = mensajeLimpio;
                    stepLog.prepend(li);
                    
                    const logItems = Array.from(stepLog.querySelectorAll("li")).map(el => ({
                        color: el.style.color,
                        html: el.innerHTML
                    }));
                    localStorage.setItem("activeAnalysisLog", JSON.stringify(logItems));
                }

                if (pct >= 100 || (esError && estado.paso === "error")) {
                    reconnectSource.close();
                    _reconnectRedirected = true;
                    
                    if (!esError) {
                        if (progressText) progressText.innerHTML = `🎉 ¡Completado! Redirigiendo...`;
                        setTimeout(() => {
                            liberarFormulario();
                            window.location.href = `/analizar-datasets?project_id=${savedSlug || savedId}`;
                        }, 1500);
                    } else {
                        if (progressBar) progressBar.className = "progress-bar bg-danger";
                        if (progressText) progressText.innerHTML = `❌ Error: ${estado.mensaje || "Fallo"}`;
                        setTimeout(() => { liberarFormulario(); }, 4000);
                    }
                }
            };

            reconnectSource.onerror = () => {
                if (reconnectSource) reconnectSource.close();
            };
        }

        // VALIDACIÓN SÍNCRONA CON FETCH PREVIO (Frena el lag de inmediato)
        fetch(`/analisis/${savedId}/progreso`)
            .then(res => {
                if (!res.ok) { liberarFormulario(); return; }
                iniciarEscuchaReconexion();
            })
            .catch(() => { liberarFormulario(); });

        // CIERRE SEGURO AL SALIR O RECARGAR LA PESTAÑA
        window.addEventListener("beforeunload", () => {
            if (reconnectSource) reconnectSource.close();
        });

        // Botón Detener desde la Reconexión
        // Lógica del botón Detener durante la reconexión
        const stopBtn = document.getElementById("stopAnalysisBtn");
        if (stopBtn) {
            stopBtn.onclick = async () => {
                if (!confirm("⚠️ ¿Seguro que quieres cancelar y eliminar definitivamente este análisis en curso?")) return;
                if (reconnectSource) reconnectSource.close();
                
                stopBtn.disabled = true;
                stopBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Cancelando y Eliminando…';
                
                // 1. Detenemos el proceso en el backend
                try {
                    await fetch(`/analisis/${savedId}/detener`, { method: "POST" });
                } catch(e) { console.warn("Error al detener:", e); }
                
                // 2. ¡EL CAMBIO AQUÍ! Ejecutamos el DELETE exactamente igual que en analisis.js
                try {
                    // Usamos savedSlug si existe, o savedId como fallback según pida tu backend
                    const targetSlug = savedSlug || savedId;
                    await fetch(`/analisis/${targetSlug}/delete`, { method: "DELETE" });
                } catch(e) { console.error("Error al eliminar:", e); }

                // 3. Limpiamos la memoria local y refrescamos la web limpia
                liberarFormulario();
                window.location.reload();
            };
        }
    }

    // 4. Manejo del Formulario Principal
    const form = document.getElementById("projectForm");
    if (form) {
        form.addEventListener("submit", (e) => {
            e.preventDefault();
            if (!isRunning) runAnalysis();
        });
    }

    // 5. Logout
    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", (e) => {
            e.preventDefault();
            fetch("/logout", { method: "POST" })
                .then(() => window.location.href = "/login");
        });
    }
});

/**
 * =============================================================================
 * COMPONENTES Y LÓGICA AUXILIAR
 * =============================================================================
 */
function initKeywordGenerator() {
    const generateBtn = document.getElementById("generateKeywordsBtn");
    const container = document.getElementById("generatedKeywordsContainer");
    const addBtn = document.getElementById("addSelectedKeywordsBtn");
    const themeInput = document.getElementById("temaInput");
    const finalInput = document.getElementById("keywordsInput"); 
    const previewSpan = document.getElementById("keywordsPreview"); 
    const toggleBtn = document.getElementById("toggleKeywordsBtn");
    const briefContainer = document.getElementById("generatedBriefContainer");
    const briefTextarea = document.getElementById("briefTextarea");

    if (!generateBtn) return;

    // Si el usuario edita el brief manualmente, lo que se envía al backend
    // debe reflejar siempre el texto actual del textarea (generado o editado).
    if (briefTextarea) {
        briefTextarea.addEventListener("input", () => {
            currentBriefDescription = briefTextarea.value;
        });
    }
    
    const manualInput = document.getElementById("manualKeywordInput");
    const manualLang = document.getElementById("manualKeywordLang");
    const addManualBtn = document.getElementById("addManualKeywordBtn");
    const manualContainer = document.getElementById("manualKeywordsContainer");

    if (addManualBtn) {
        function syncLangSelect() {
            const checked = Array.from(
                document.querySelectorAll('input[name="languages[]"]:checked')
            ).map(cb => cb.value);

            manualLang.innerHTML = checked.length
                ? checked.map(l => `<option value="${l}">${l}</option>`).join("")
                : `<option value="Castellano">Castellano</option>`;
        }

        document
            .querySelectorAll('input[name="languages[]"]')
            .forEach(cb => cb.addEventListener("change", syncLangSelect));

        syncLangSelect();

        function addManualChip(keyword, lang) {
            keyword = keyword.trim();
            if (!keyword) return;

            const kwObj = { keyword, languages: lang };
            const chip = document.createElement("div");
            chip.className = "form-check form-check-inline bg-white border rounded-pill px-3 py-2 m-1 shadow-sm";

            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.className = "form-check-input keyword-check";
            cb.value = JSON.stringify(kwObj);
            cb.id = "mkw_" + Math.random().toString(36).substr(2, 9);
            cb.checked = true;

            const lbl = document.createElement("label");
            lbl.className = "form-check-label ms-2";
            lbl.htmlFor = cb.id;
            lbl.innerHTML = `${keyword} <span class="badge bg-secondary ms-1" style="font-size:.6rem;">${lang}</span>`;

            const rmBtn = document.createElement("button");
            rmBtn.type = "button";
            rmBtn.className = "btn btn-link btn-sm p-0 ms-2 text-danger";
            rmBtn.innerHTML = '<i class="bi bi-x"></i>';
            rmBtn.onclick = () => {
                chip.remove();
                updateSelectedKeywords();
            };

            //chip.append(cb, lbl, rmBtn);
            //manualContainer.appendChild(chip);
            chip.append(cb, lbl);
            container.appendChild(chip);
            addBtn.classList.remove("d-none");
            toggleBtn.classList.remove("d-none");

            updateSelectedKeywords();
        }

        addManualBtn.addEventListener("click", () => {
            const raw = manualInput.value;
            const lang = manualLang.value || "Castellano";
            raw.split(",").forEach(kw => addManualChip(kw, lang));
            manualInput.value = "";
        });

        manualInput.addEventListener("keydown", e => {
            if (e.key === "Enter") {
                e.preventDefault();
                addManualBtn.click();
            }
        });
    }

    if (container && toggleBtn) {
        container.addEventListener("change", () => {
            const checkboxes = container.querySelectorAll(".keyword-check");
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);
            toggleBtn.innerText = allChecked ? "Desmarcar todo" : "Marcar todo";
        });
    }

    generateBtn.addEventListener("click", async () => {
        const context = themeInput.value.trim();
        const selectedLangs = Array.from(document.querySelectorAll('input[name="languages[]"]:checked')).map(cb => cb.value);
        
        const popInput = document.getElementById("populationInput");
        if (popInput) popInput.blur(); 
        
        let rawPopulation = popInput ? popInput.value.trim() : "";
        let populationList = [];

        if (!rawPopulation) {
            //const confirmarGlobal = confirm(
            //    "⚠️ No has especificado un contexto geográfico.\n\n" +
            //    "El sistema NO filtrará los datos por ubicación y recogerá menciones de cualquier lugar del mundo.\n\n" +
            //    "¿Deseas continuar con un análisis GLOBAL?"
            //);
            
            //if (!confirmarGlobal) {
            //    popInput.focus();
            //    return; 
            //}
            populationList = ["GLOBAL"]; 
        } else {
            popInput.classList.remove("is-invalid");
            populationList = rawPopulation.split(",").map(s => s.trim()).filter(s => s !== "");
        }

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
                    languages: selectedLangs, 
                    population: populationList 
                })
            });

            const data = await response.json();

            if (data.success) {
                currentBriefDescription = data.desc_tema || "";

                if (briefTextarea) {
                    briefTextarea.value = currentBriefDescription;
                }
                if (briefContainer) {
                    briefContainer.classList.remove("d-none");
                }
            }

            if (data.tipo_tema) {
                const badgeContainer = document.getElementById("tipoBadgeContainer");
                if (badgeContainer) {
                    const esHiperlocal = data.tipo_tema === 'hiperlocal';
                    badgeContainer.innerHTML = esHiperlocal
                        ? `<span class="badge bg-warning text-dark me-2"><i class="bi bi-geo-alt-fill me-1"></i>Tema hiperlocal detectado</span>`
                        : `<span class="badge bg-info text-dark me-2"><i class="bi bi-globe me-1"></i>Tema universal detectado</span>`;
                }
            }

            if (data.keywords && Array.isArray(data.keywords)) {
                container.innerHTML = ""; 
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
                    lbl.className = "form-check-label ms-2";
                    lbl.htmlFor = cb.id;
                    lbl.innerText = displayText;
                    chip.append(cb, lbl);
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

    if (addBtn) {
        function updateSelectedKeywords() {
        const selectedChecks = document.querySelectorAll(".keyword-check:checked");

        if (selectedChecks.length === 0) {
            finalInput.value = "";
            previewSpan.innerText = "Ninguna seleccionada";
            return;
        }

        const selectedObjects = Array.from(selectedChecks)
            .map(cb => JSON.parse(cb.value));

        finalInput.value = JSON.stringify(selectedObjects);

        previewSpan.innerText =
            `${selectedObjects.length} términos seleccionados.`;

        previewSpan.parentElement.classList.remove("text-muted");
        previewSpan.parentElement.classList.add(
            "text-success",
            "fw-bold",
            "border-success"
        );
    }
        addBtn.addEventListener("click", () => {
            updateSelectedKeywords();

            addBtn.className = "btn btn-success btn-sm mb-3";
            addBtn.innerHTML = '<i class="bi bi-check-lg"></i> ¡Guardado!';

            setTimeout(() => {
                addBtn.innerText = "Actualizar selección";
                addBtn.className = "btn btn-outline-success btn-sm mb-3";
            }, 2000);
        });
    }

    if (toggleBtn) {
        toggleBtn.addEventListener("click", () => {
            const checkboxes = document.querySelectorAll(".keyword-check");
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);
            checkboxes.forEach(cb => cb.checked = !allChecked);
            toggleBtn.innerText = allChecked ? "Marcar todo" : "Desmarcar todo";
        });
    }
}

async function runAnalysis() {
    const form     = document.getElementById("projectForm");
    const formData = new FormData(form);
 
    const sources   = formData.getAll("sources[]");
    const languages = formData.getAll("languages[]");
    const keywords  = formData.get("keywords");
 
    if (!formData.get("project_name"))  { alert("Falta el nombre del proyecto."); return; }
    if (sources.length === 0)           { alert("Selecciona al menos una fuente."); return; }
    if (languages.length === 0)         { alert("Selecciona al menos un idioma."); return; }
    if (!keywords)                      { alert("Debes generar y confirmar los términos de búsqueda."); return; }
    
    const projectName = formData.get("project_name")
        .trim()
        .toLowerCase();

    if (existingProjectNames.includes(projectName)) {
        alert(
            "Ya existe un proyecto con ese nombre. Debes utilizar otro."
        );
        return;
    }
    isRunning = true;
    const btnRun      = document.querySelector(".btn-ejecutar");
    const progressDiv = document.getElementById("progressContainer");
    const progressBar = document.getElementById("progressBar");
    const progressText= document.getElementById("progressText");
    const stepLog     = document.getElementById("stepLog");   
 
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
        const response = await fetch("/ejecutar-analisis", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(payload),
        });
        const startData = await response.json();
 
        if (!response.ok || startData.status == "failed") {
            throw new Error(startData.message || "Error iniciando análisis");
        }
 
        const analysisId = startData.analysis_id; // El entero PK
        const projectSlug = startData.project_slug; // El texto slug de la URL que modificamos en Python
        
        if (!analysisId) throw new Error("No se recibió el ID del análisis");
        
        // CORREGIDO: Guardamos de forma explícita ambos datos para no perderlos
        localStorage.setItem("activeAnalysisId", analysisId);
        localStorage.setItem("activeAnalysisSlug", projectSlug || "");
        localStorage.setItem("activeAnalysisStart", Date.now());
 
        const stopBtn = document.getElementById("stopAnalysisBtn");
        const stopCol = document.getElementById("stopCol");
        const runCol  = document.getElementById("runCol");

        if (stopCol) stopCol.classList.remove("d-none");
        if (runCol)  runCol.classList.add("d-none");

        // Llamamos al stream SSE usando el entero (analysisId)
        const evtSource = new EventSource(`/analisis/${analysisId}/progreso`);
        let _loggedSteps = new Set();   
        let redirected = false; 

        function doRedirect() {
            if (redirected) return;
            redirected = true;
            evtSource.close();
            
            localStorage.removeItem("activeAnalysisId");
            localStorage.removeItem("activeAnalysisSlug");
            localStorage.removeItem("activeAnalysisStart");
            localStorage.removeItem("activeAnalysisLog");
            localStorage.removeItem("activeAnalysisPct");
            
            if (stopCol) stopCol.classList.add("d-none");
            if (runCol)  runCol.classList.remove("d-none");
            
            setTimeout(() => {
                // CORREGIDO: Redirección usando el Slug de texto para el Dashboard
                window.location.href = `/analizar-datasets?project_id=${projectSlug || analysisId}`;
            }, 1500);
        }
 
        evtSource.onmessage = (event) => {
            let estado;
            try { estado = JSON.parse(event.data); } catch { return; }
            if (!estado || !estado.paso) return;
 
            const pct    = estado.porcentaje || 0;
            const info   = infoPaso(estado.paso);
            const esError= estado.error === true;

            localStorage.setItem("activeAnalysisPct", pct);
 
            if (progressBar) {
                progressBar.style.width   = `${pct}%`;
                progressBar.className = esError
                    ? "progress-bar bg-warning"
                    : "progress-bar progress-bar-striped progress-bar-animated";
                progressBar.style.background = info.color;
            }
 
            if (progressText) {
                progressText.innerHTML =
                    `${info.icon} <strong>${estado.mensaje || info.label}</strong>
                    <span class="text-muted ms-2" style="font-size:.8rem;">(${pct}%)</span>`;
            }
 
            if (stepLog && estado.paso !== "inicio" && !_loggedSteps.has(estado.paso)) {
                _loggedSteps.add(estado.paso);
                const li = document.createElement("li");
                li.className = "list-group-item py-1 px-2 small border-0";
                li.style.color      = info.color;
                li.style.fontWeight = pct >= 100 ? "600" : "normal";
                li.innerHTML = `${info.icon} ${estado.mensaje || info.label}`;
                stepLog.prepend(li);
                
                const logItems = Array.from(stepLog.querySelectorAll("li")).map(el => ({
                    color: el.style.color,
                    html: el.innerHTML
                }));
                localStorage.setItem("activeAnalysisLog", JSON.stringify(logItems));
            }
 
            if (pct >= 100 || (esError && estado.paso === "error")) {
                evtSource.close();
                if (stopCol) stopCol.classList.add("d-none");
                if (runCol)  runCol.classList.remove("d-none");
 
                if (esError && estado.paso === "error") {
                    localStorage.removeItem("activeAnalysisId");
                    localStorage.removeItem("activeAnalysisSlug");
                    localStorage.removeItem("activeAnalysisStart");
                    localStorage.removeItem("activeAnalysisLog");
                    localStorage.removeItem("activeAnalysisPct");
                    if (progressBar) progressBar.className = "progress-bar bg-danger";
                    if (progressText) progressText.innerHTML = `❌ ${estado.mensaje}`;
                    isRunning = false;
                    btnRun.disabled  = false;
                    btnRun.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i> REINTENTAR ANÁLISIS';
                    redirected = true; 
                    return;
                }
 
                doRedirect();
            }
        };
 
        evtSource.onerror = (err) => {
            console.error("SSE error:", err);

            evtSource.close();

            if (progressText) {
                progressText.innerHTML =
                    "⚠️ No se pudo conectar con el monitor de progreso";
            }

            isRunning = false;
        };

        if (stopBtn) {
            stopBtn.onclick = async () => {
                if (!confirm("⚠️ ¿Seguro que quieres cancelar y eliminar definitivamente este análisis en curso?")) return;
                stopBtn.disabled = true;
                stopBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Cancelando y Eliminando…';
                
                if (evtSource) evtSource.close();
                
                // 1. Detenemos el proceso activo
                try {
                    await fetch(`/analisis/${analysisId}/detener`, { method: "POST" });
                } catch (e) { console.warn("Stop request failed:", e); }
                
                // 2. ¡EL CAMBIO AQUÍ! Ejecutamos el DELETE inmediato para que no deje el proyecto fantasma
                try {
                    // Usamos el slug que nos devolvió la creación del proyecto, o el id como plan B
                    const targetSlug = projectSlug || analysisId;
                    await fetch(`/analisis/${targetSlug}/delete`, { method: "DELETE" });
                } catch (e) { console.error("Delete request failed:", e); }
                
                // 3. Destruimos las cookies/caché locales
                localStorage.removeItem("activeAnalysisId");
                localStorage.removeItem("activeAnalysisSlug");
                localStorage.removeItem("activeAnalysisStart");
                localStorage.removeItem("activeAnalysisLog");
                localStorage.removeItem("activeAnalysisPct");
                
                // 4. Recargamos para que el usuario vuelva a ver el formulario de creación totalmente vacío
                window.location.reload();
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

function setupSelectAll(masterId, selector) {
    const master = document.getElementById(masterId);
    if (!master) return;

    const getCheckboxes = () =>
        Array.from(document.querySelectorAll(selector)).filter(cb => !cb.disabled); 

    master.addEventListener("change", () => {
        getCheckboxes().forEach(cb => cb.checked = master.checked);
    });

    document.querySelectorAll(selector).forEach(cb => {
        cb.addEventListener("change", () => {
            if (cb.disabled) return; 
            const enabled = getCheckboxes();
            const allChecked = enabled.every(c => c.checked);
            master.checked = allChecked;
        });
    });
}

function initDateRestrictions() {

    const startInput = document.getElementById("start_date");
    const endInput = document.getElementById("end_date");

    if (!startInput || !endInput) return;

    const today = new Date().toISOString().split("T")[0];

    startInput.max = today;
    endInput.max = today;

    startInput.addEventListener("change", () => {

        endInput.min = startInput.value;

        if (
            endInput.value &&
            endInput.value < startInput.value
        ) {
            endInput.value = startInput.value;
        }
    });

    endInput.addEventListener("change", () => {

        if (
            startInput.value &&
            endInput.value < startInput.value
        ) {

            endInput.classList.add("is-invalid");

            endInput.setCustomValidity(
                "La fecha final no puede ser anterior a la inicial"
            );

        } else {

            endInput.classList.remove("is-invalid");
            endInput.setCustomValidity("");
        }
    });
}


async function loadExistingProjects() {
    try {
        const response = await fetch("/api/proyectos-sidebar");

        if (!response.ok) {
            throw new Error("Error cargando proyectos");
        }

        const projects = await response.json();

        existingProjectNames = projects.map(p =>
            (p.project_name || "")
                .trim()
                .toLowerCase()
        );

        console.log("Proyectos cargados:", existingProjectNames);

    } catch (err) {
        console.error("Error cargando proyectos:", err);
    }
}

document.addEventListener("llm-status-changed", (e) => {

    if (!e.detail.available) {
        document.getElementById("ejecutar-analisis").disabled = true;
    }

});