document.addEventListener("DOMContentLoaded", () => {

    // Barras
    new Chart(document.getElementById("barras"), {
        type: "bar",
        data: {
            labels: ["Enero", "Febrero", "Marzo", "Abril"],
            datasets: [{
                label: "Ventas",
                data: [12, 19, 8, 15],
                backgroundColor: "rgba(13,110,253,0.7)"
            }]
        },
        options: {
            responsive: true
        }
    });

    // Quesito
    new Chart(document.getElementById("quesito"), {
        type: "pie",
        data: {
            labels: ["Producto A", "Producto B", "Producto C"],
            datasets: [{
                data: [40, 35, 25],
                backgroundColor: ["#dc3545", "#0d6efd", "#198754"]
            }]
        }
    });

    // Líneas
    new Chart(document.getElementById("lineas"), {
        type: "line",
        data: {
            labels: ["Lun", "Mar", "Mié", "Jue", "Vie"],
            datasets: [{
                label: "Visitas",
                data: [5, 9, 7, 11, 15],
                borderColor: "#6610f2",
                tension: 0.4,
                fill: false
            }]
        }
    });

});
