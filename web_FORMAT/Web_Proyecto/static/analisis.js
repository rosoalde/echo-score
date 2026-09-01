document.addEventListener("DOMContentLoaded", () => {

    /* ===== POLLING DE PROGRESO — SSE ===== */
    document.querySelectorAll(".progress-sm[data-analysis-id]").forEach(container => {
        const analysisId = container.dataset.analysisId;
        if (!analysisId) return;
        
        // Si ya viene cancelado del servidor originalmente, no abrimos conexión SSE
        if (container.dataset.status === "cancelled") {
            return;
        }

        const bar   = container.querySelector(".progress-bar");
        const badge = document.querySelector(`.pct-badge[data-analysis-id="${analysisId}"]`);

        const initialPct = parseFloat(container.dataset.progress) || 0;
        if (bar) {
            bar.style.width = initialPct + "%";
            bar.setAttribute("aria-valuenow", initialPct);
        }

        let lastPct   = initialPct;
        let completed = false;
        let reconnectTimeout = null;

        function connectSSE() {
            if (completed) return;
            
            if (container._evtSource) {
                container._evtSource.close();
            }

            container._evtSource = new EventSource(`/analisis/${analysisId}/progreso`);

            container._evtSource.onmessage = (event) => {
                let estado;
                try { estado = JSON.parse(event.data); } catch { return; }
                if (!estado) return;

                const pct = estado.porcentaje ?? estado.progress ?? lastPct;
                const esError = estado.error === true;
                const cancelled = estado.cancelled === true || estado.status === "cancelled";

                lastPct = pct;

                if (bar) {
                    bar.style.width = pct + "%";
                    bar.setAttribute("aria-valuenow", pct);
                    if (esError) {
                        bar.classList.remove("progress-bar-striped", "progress-bar-animated");
                        bar.classList.add("bg-danger");
                    } else if (cancelled) {
                        bar.classList.remove("progress-bar-striped", "progress-bar-animated");
                        bar.classList.add("bg-secondary");
                    }
                }
                if (badge) {
                    badge.textContent = esError ? "Error" : cancelled ? "Cancelado" : Math.round(pct) + "%";
                }

                // Caso Éxito 100% -> Recargamos para mostrar el botón de ir al Dashboard
                if (pct >= 100 && !esError && !cancelled) {
                    completed = true;
                    if (container._evtSource) container._evtSource.close();
                    clearTimeout(reconnectTimeout);
                    setTimeout(() => location.reload(), 1200);
                }

                // Caso Cancelado por SSE (Alguien más lo canceló o evento en segundo plano)
                // Detenemos el SSE para evitar bucles, pero NO recargamos la página aquí.
                if (cancelled) {
                    completed = true;
                    if (container._evtSource) container._evtSource.close();
                    clearTimeout(reconnectTimeout);
                    return;
                }
                
                if (esError && (estado.paso === "error" || estado.paso === "failed")) {
                    completed = true;
                    if (container._evtSource) container._evtSource.close();
                    clearTimeout(reconnectTimeout);
                }
            };

            container._evtSource.onerror = (e) => {
                if (container._evtSource) container._evtSource.close();
                if (completed) return;

                clearTimeout(reconnectTimeout);
                reconnectTimeout = setTimeout(() => {
                    if (!completed) connectSSE();
                }, 5000);
            };
        }

        connectSSE();
    });

    /* ===== CANCELAR ANÁLISIS ===== */
    document.querySelectorAll(".abort-analysis-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const id = btn.dataset.id; 
            if (!id) return;
            if (!confirm("¿Seguro que quieres cancelar este análisis?")) return;

            btn.disabled = true;
            btn.innerText = "Cancelando...";

            fetch(`/analisis/${id}/detener`, { method: "POST" })
                .then(res => { 
                    if (!res.ok) throw new Error(); 
                    
                    // Cerramos el SSE de esta tarjeta antes de irnos por si acaso
                    const container = document.querySelector(`.progress-sm[data-analysis-id="${id}"]`);
                    if (container && container._evtSource) {
                        container._evtSource.close();
                    }

                    // ¡LA SOLUCIÓN SIMPLE! Recargamos la página inmediatamente tras la confirmación del servidor.
                    // Esto hará que el backend pinte el botón de basura nativo perfectamente estructurado.
                    location.reload();
                })
                .catch(() => {
                    alert("No se pudo cancelar el análisis");
                    btn.disabled = false;
                    btn.innerText = "Cancelar";
                });
        });
    });

    /* ===== ELIMINAR ANÁLISIS ===== */
    document.querySelectorAll(".delete-analysis-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const slug = btn.dataset.slug; 
            const card = btn.closest('.card'); 
            const progressContainer = card ? card.querySelector(".progress-sm") : null;

            if (!slug) return;
            if (!confirm("⚠️ Esto eliminará el análisis y todos sus reportes definitivamente. ¿Continuar?")) return;

            if (progressContainer && progressContainer._evtSource) {
                progressContainer._evtSource.close();
            }

            btn.disabled = true;
            btn.innerText = "Eliminando...";

            fetch(`/analisis/${slug}/delete`, { method: "DELETE" })
                .then(res => {
                    if (!res.ok) throw new Error("No se pudo eliminar");
                    location.reload();
                })
                .catch((err) => {
                    console.error(err);
                    alert("Error al eliminar el análisis.");
                    btn.disabled = false;
                    btn.innerText = "Eliminar";
                });
        });
    });
});