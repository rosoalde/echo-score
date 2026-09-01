function renderAdvancedResults(results) {
    const advancedContainer = document.getElementById("advancedResults");

    // Crear contenedor si no existe
    if (!advancedContainer) {
        const container = document.createElement("div");
        container.id = "advancedResults";
        container.className = "mt-4";
        document.getElementById("resultsContainer").appendChild(container);
    }

    // Limpieza
    document.getElementById("advancedResults").innerHTML = "";

    // Ejemplo: gráfico de barras con Chart.js (si quieres usar)
    const canvas = document.createElement("canvas");
    canvas.id = "resultsChart";
    document.getElementById("advancedResults").appendChild(canvas);

    // Preparar datos
    const labels = results.map(r => r.social);
    const data = results.map(r => r.success ? 1 : 0); // 1=ok, 0=fallo

    // Graficar con Chart.js (necesitas añadir la librería en tu HTML)
    if (typeof Chart !== "undefined") {
        new Chart(canvas.getContext("2d"), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [{
                    label: 'Éxito del análisis',
                    data: data,
                    backgroundColor: data.map(v => v ? 'green' : 'red')
                }]
            },
            options: {
                scales: {
                    y: { min: 0, max: 1, ticks: { stepSize: 1 } }
                }
            }
        });
    }

    // Ejemplo de descripción
    const summary = document.createElement("p");
    const total = results.length;
    const exitos = results.filter(r => r.success).length;
    summary.textContent = `✅ ${exitos} de ${total} análisis completados correctamente.`;
    document.getElementById("advancedResults").appendChild(summary);
}
