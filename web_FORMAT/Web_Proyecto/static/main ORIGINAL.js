document.addEventListener("DOMContentLoaded", () => {
    toggleSelectAll(
        "selectAllSources",
        'input[name="sources[]"]'
    );

    toggleSelectAll(
        "selectAllLanguages",
        'input[name="languages[]"]'
    );

    uncheckSelectAllOnManualChange(
        "selectAllSources",
        'input[name="sources[]"]'
    );

    uncheckSelectAllOnManualChange(
        "selectAllLanguages",
        'input[name="languages[]"]'
    );
});


document.getElementById("projectForm").addEventListener("submit", function (e) {
    if (isRunning) return;
    e.preventDefault();
    runAnalysis(true); // cambiar a false para usar resultados reales
});

let isRunning = false;
let currentAnalysisId = null;
let analysisTimeout = null;

/** ---------------- Funciones ---------------- **/

// Obtener redes seleccionadas
function getSelectedSources() {
    const selected = Array.from(
        document.querySelectorAll('input[name="sources[]"]:checked')
    ).map(cb => cb.nextElementSibling.innerText);
    if (selected.length === 0) {
        alert("Selecciona al menos una red social");
        return null;
    }
    return selected;
}

function getSelectedLanguages() {
    const selected = Array.from(
        document.querySelectorAll('input[name="languages[]"]:checked')
    ).map(cb => cb.nextElementSibling.innerText);

    return selected;
}


function resetActionButtons() {
    const runCol = document.getElementById("runCol");
    const stopCol = document.getElementById("stopCol");
    const runBtn = document.querySelector(".btn-ejecutar");

    runCol.classList.remove("col-10");
    runCol.classList.add("col-12");

    stopCol.classList.add("d-none");

    runBtn.disabled = false;
    runBtn.innerText = "▶ Ejecutar análisis";
}


// Generar resultados demo aleatorios
function generateDemoResults(sources, languages) {
    return sources.map(social => ({
        social,
        success: Math.random() > 0.1 // 90% éxito
    }));
}

// Placeholder para resultados reales (ej: fetch a backend)
async function fetchRealResults(sources, languages) {
    // Ejemplo: llamar a tu FastAPI /ejecutar y pasar sources
    // return await fetch("/ejecutar", { ... }).then(res => res.json());
    // Por ahora devolvemos demo
    return generateDemoResults(sources, languages);
}

// Mostrar resultados y crear botón de descarga
function displayResults(results, analysisId) {
    const resultsContainer = document.getElementById("resultsContainer");
    resultsContainer.innerHTML = "<h5>Resultados por red:</h5>";

    results.forEach(r => {
        const line = document.createElement("div");
        line.textContent = `${r.social}: ${r.success ? "✅ Completado" : "❌ Fallo"}`;
        resultsContainer.appendChild(line);
    });

    let downloadBtn = document.getElementById("downloadBtn");
    // Botón de descargar
    if (!document.getElementById("downloadBtn")) {
        downloadBtn = document.createElement("button");
        downloadBtn.id = "downloadBtn";
        downloadBtn.className = "btn btn-outline-primary btn-sm mt-3";
        downloadBtn.textContent = "💾 Descargar resultados";
        resultsContainer.appendChild(downloadBtn);

    }

    downloadBtn.addEventListener("click", () => {
        if (!analysisId) {
            alert("El análisis aún no está listo para descargar");
            return;
        }

        window.location.href = `/analisis/${analysisId}/download`;
    });
}

// Actualizar barra de progreso
function updateProgress(current, total, social) {
    const progressBar = document.getElementById("progressBar");
    const progressText = document.getElementById("progressText");
    const percent = Math.round((current / total) * 100);
    progressBar.style.width = percent + "%";
    progressText.innerText = `🔍 Analizando ${social}...`;
}

// Función principal que ejecuta el análisis
async function runAnalysis(useDemo = true) {
    const button = document.querySelector(".btn-ejecutar");
    const progressContainer = document.getElementById("progressContainer");
    const resultsContainer = document.getElementById("resultsContainer");

    const selectedSources = getSelectedSources();
    const selectedLanguages = getSelectedLanguages();

    if (!selectedSources) return;

    isRunning = true
    // Preparar UI
    button.disabled = true;
    button.innerText = "⏳ Analizando...";
    progressContainer.classList.remove("d-none");
    resultsContainer.innerHTML = "";
    document.getElementById("progressBar").style.width = "0%";

    // Ajustar columnas de botones al iniciar análisis
    document.getElementById("runCol").classList.remove("col-12");
    document.getElementById("runCol").classList.add("col-10");
    document.getElementById("stopCol").classList.remove("d-none");

    const total = selectedSources.length;
    const stepTime = 10000 / total; // 10 segundos totales
    let current = 0;
    const results = [];

    async function analizarSiguiente() {

        if (!isRunning) {
            document.getElementById("progressText").innerText = "⛔ Análisis detenido";
            return;
        }

        if (current >= total) {
            document.getElementById("progressBar").style.width = "100%";
            document.getElementById("progressText").innerText = "✅ Análisis completado";

            // Obtener resultados demo o reales
            const finalResults = useDemo
                ? generateDemoResults(selectedSources, selectedLanguages)
                : await fetchRealResults(selectedSources, selectedLanguages);
            
            sendResultsToBackend(finalResults);
            //(finalResults);
            // Devolver botón
            button.disabled = false;
            button.innerText = "▶ Ejecutar análisis";

            resetActionButtons();

            return;
        }

        const social = selectedSources[current];
        updateProgress(current, total, social);

        current++;
        setTimeout(analizarSiguiente, stepTime);
    }

    async function sendResultsToBackend(finalResults) {
        const projectForm = document.getElementById("projectForm");
        const formData = new FormData(projectForm);

        const dataToSend = {
            project_name: formData.get("project_name"),
            keywords: formData.get("keywords"),
            start_date: formData.get("start_date"),
            end_date: formData.get("end_date"),
            sources: Array.from(document.querySelectorAll('input[name="sources[]"]:checked')).map(cb => cb.value),
            languages: Array.from(document.querySelectorAll('input[name="languages[]"]:checked')).map(cb => cb.value),
            results: finalResults // [{social: "Twitter", success: true}, ...]
        };

        try {
            const response = await fetch("/ejecutar-analisis", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(dataToSend)
            });

            const resJson = await response.json();
            console.log("Respuesta backend:", resJson);
            currentAnalysisId = resJson.user_id;

            displayResults(finalResults, currentAnalysisId);
            ///###
            const resultsContainer = document.getElementById("resultsContainer");
            const backendOutputDiv = document.createElement("div");
            backendOutputDiv.className = "mt-3 p-2 border bg-light";
            backendOutputDiv.innerHTML = `<strong>Salida backend:</strong><br><pre>${resJson.output}</pre>`;
            resultsContainer.appendChild(backendOutputDiv);
        } catch (error) {
            console.error("Error enviando resultados al backend:", error);
        }
    }


    analizarSiguiente();
}

document.getElementById("stopAnalysisBtn").addEventListener("click", () => {
    if (!isRunning) return;

    isRunning = false;
    clearTimeout(analysisTimeout);

    const progressText = document.getElementById("progressText");
    const progressContainer = document.getElementById("progressContainer");

    progressText.innerText = "⛔ Análisis detenido";

    // Espera unos segundos y vuelve al estado inicial
    setTimeout(() => {
        progressContainer.classList.add("d-none");
        document.getElementById("progressBar").style.width = "0%";
        progressText.innerText = "";

        resetActionButtons();
    }, 2000); // 👈 "segundillos" (ajusta a gusto)
});


function logout() {
    fetch("/logout", {
        method: "POST"
    }).then(() => {
        window.location.href = "/login";
    });
}

document.addEventListener("DOMContentLoaded", () => {
    const logoutBtn = document.getElementById("logoutBtn");

    if (logoutBtn) {
        logoutBtn.addEventListener("click", (e) => {
            e.preventDefault();
            logout();
        });
    }
});


function toggleSelectAll(selectAllId, checkboxSelector) {
    const selectAll = document.getElementById(selectAllId);
    if (!selectAll) return;

    selectAll.addEventListener("change", () => {
        const checkboxes = document.querySelectorAll(checkboxSelector);

        checkboxes.forEach(cb => {
            cb.checked = selectAll.checked;
            cb.dispatchEvent(new Event("change", { bubbles: true }));
        });
    });
}


function uncheckSelectAllOnManualChange(selectAllId, checkboxSelector) {
    const selectAll = document.getElementById(selectAllId);
    const checkboxes = document.querySelectorAll(checkboxSelector);

    checkboxes.forEach(cb => {
        cb.addEventListener("change", () => {
            if (!cb.checked) {
                selectAll.checked = false;
            }
        });
    });
}

function generateKeywordsFromContext(context) {
    return new Promise(resolve => {
        setTimeout(() => {
            const base = context.toLowerCase();

            const keywords = [
                base,
                "opinión pública",
                "redes sociales",
                "análisis político",
                "tendencias",
                "sentimiento"
            ];

            resolve(keywords);
        }, 1200); // “pensando” 😄
    });
}


document.addEventListener("DOMContentLoaded", () => {


    
    
    const generatedContainer = document.getElementById("generatedKeywordsContainer");
    const addSelectedBtn = document.getElementById("addSelectedKeywordsBtn");


    const generateBtn = document.getElementById("generateKeywordsBtn");
    const contextInput = document.querySelector('input[name="asistente"]');
    const keywordsInput = document.querySelector('input[name="keywords"]');

    generateBtn.addEventListener("click", async () => {
        const context = contextInput.value.trim();
        if (!context) {
            alert("Introduce un contexto para generar keywords");
            return;
        }

        generateBtn.disabled = true;
        generateBtn.innerText = "⏳ Generando...";

        try {
            const response = await fetch("/generate_keywords", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ context })
            });

            const data = await response.json();
            const generatedKeywords = data.keywords;

            // Crear checkbox para cada keyword
            generatedKeywords.forEach(kw => {
                const div = document.createElement("div");
                div.className = "form-check form-check-inline";

                const checkbox = document.createElement("input");
                checkbox.type = "checkbox";
                checkbox.className = "form-check-input";
                checkbox.value = kw;
                checkbox.id = "kw_" + kw;

                const label = document.createElement("label");
                label.className = "form-check-label";
                label.htmlFor = "kw_" + kw;
                label.innerText = kw;

                div.appendChild(checkbox);
                div.appendChild(label);

                generatedContainer.appendChild(div);
            });

        // Mostrar botón para añadir seleccionadas
        addSelectedBtn.classList.remove("d-none");
        } catch (err) {
            console.error(err);
            alert("Error generando keywords");
        } finally {
            generateBtn.disabled = false;
            generateBtn.innerText = "🤖 Generar keywords";
        }
    });

    addSelectedBtn.addEventListener("click", () => {
        const checkboxes = generatedContainer.querySelectorAll("input[type='checkbox']:checked");

        if (checkboxes.length === 0) {
            alert("Selecciona al menos una palabra");
            return;
        }

        const selectedWords = Array.from(checkboxes).map(cb => cb.value);

        if (keywordsInput.value.trim()) {
            keywordsInput.value += ", " + selectedWords.join(", ");
        } else {
            keywordsInput.value = selectedWords.join(", ");
        }

        // Opcional: desmarcar todas después de añadir
        checkboxes.forEach(cb => cb.checked = false);
    });
});


document.addEventListener("DOMContentLoaded", () => {

    const keywordsInput = document.querySelector('input[name="keywords"]');
    const promptTropicos = document.querySelector('textarea[name="config_description"]');
    const promptPilares = document.querySelector('textarea[name="additional_notes"]');

    function updatePromptsWithKeywords() {
        const keywords = keywordsInput.value.trim();

        if (!keywords) return;

        const baseText = `Los datos del prompt para analizar son estos: ${keywords}`;

        // Solo autocompletar si están vacíos o fueron autogenerados antes
        if (!promptTropicos.dataset.manual) {
            promptTropicos.value = baseText;
        }

        if (!promptPilares.dataset.manual) {
            promptPilares.value = baseText;
        }
    }

    // Detectar cambios en keywords
    keywordsInput.addEventListener("input", updatePromptsWithKeywords);

    // Si el usuario edita manualmente el prompt, no lo sobreescribimos más
    promptTropicos.addEventListener("input", () => {
        promptTropicos.dataset.manual = "true";
    });

    promptPilares.addEventListener("input", () => {
        promptPilares.dataset.manual = "true";
    });

});



// -------------------------- Estadisticas -------------------------
function displayEstadisticas(results) {
    const resultsContainer = document.getElementById("estadisticasContainer");
    resultsContainer.innerHTML = "<h5>Resultados por red:</h5>";
    
    results.forEach(r => {
        const line = document.createElement("div");
        line.textContent = `${r.social}: ${r.success ? "✅ Completado" : "❌ Fallo"}`;
        resultsContainer.appendChild(line);
    });

    // Llamamos a resultados avanzados
    if (typeof renderAdvancedResults === "function") {
        renderAdvancedResults(results);
    }
}

