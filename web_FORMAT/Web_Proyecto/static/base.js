async function reloadSidebarProjects() {
    const sidebarList = document.getElementById("sidebarProjectList");

    if (!sidebarList) return;

    try {
        const response = await fetch("/api/proyectos-sidebar");
        const projects = await response.json();

        if (!projects || projects.length === 0) {
            sidebarList.innerHTML =
                '<div class="py-2 px-3 small text-muted fst-italic">No hay proyectos aún</div>';
            return;
        }

        sidebarList.innerHTML = "";

        projects.forEach(proj => {
            const a = document.createElement("a");

            // 1. Definimos primero la clase base para evitar que sobrescriba los estilos activos
            a.className = "list-group-item list-group-item-action small border-0 py-2 ps-4";

            // 2. Evaluamos si es el proyecto activo a través de la URL
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get("project_id") === proj.project_url) {
                a.classList.add("active", "bg-primary", "text-white");
            }

            a.href = `/analizar-datasets?project_id=${proj.project_url}`;

            a.innerHTML = `
                <div class="d-flex align-items-center">
                    <i class="bi bi-file-earmark-bar-graph me-2 text-secondary"></i>
                    <span class="text-truncate">${proj.project_name}</span>
                </div>
            `;

            sidebarList.appendChild(a);
        });

    } catch (err) {
        console.error("Error cargando proyectos:", err);
        sidebarList.innerHTML =
            '<div class="py-2 px-3 small text-danger">Error al cargar</div>';
    }
}


document.addEventListener("DOMContentLoaded", async () => {
    // Logout Logic
    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", (e) => {
            e.preventDefault();
            fetch("/logout", { method: "POST" })
                .then(() => window.location.href = "/login");
        });
    }

    // Sidebar Toggle (Corregido con el ID real de tu HTML: #sidebar-wrapper)
    const toggleBtn = document.querySelector("#sidebarToggle");
    const sidebar = document.querySelector("#sidebar-wrapper"); 

    if (toggleBtn && sidebar) {
        toggleBtn.addEventListener("click", () => {
            sidebar.classList.toggle("collapse");
        });
    }
    
    // Forzamos la ejecución de la carga de proyectos
    console.log("Iniciando carga de proyectos en el sidebar...");
    await reloadSidebarProjects();
});

function updateLLMButtons(available) {
    document.querySelectorAll("[data-requires-llm]").forEach(btn => {

        // ¿Este botón estaba deshabilitado por permisos?
        const disabledByRole = btn.classList.contains("disabled");

        if (available && !disabledByRole) {
            btn.disabled = false;
            btn.title = "";
        } else {
            btn.disabled = true;

            if (!available) {
                btn.title = "El servicio de IA no está disponible";
            }
        }
    });
}

window.llmAvailable = false;

async function checkLLMStatus() {
    try {
        const response = await fetch("/api/llm/status");
        const data = await response.json();

        window.llmAvailable = data.available;

        updateLLMButtons(data.available);

        document.dispatchEvent(
            new CustomEvent("llm-status-changed", {
                detail: data
            })
        );

    } catch (e) {
        window.llmAvailable = false;

        updateLLMButtons(false);

        document.dispatchEvent(
            new CustomEvent("llm-status-changed", {
                detail: { available: false }
            })
        );
    }
}

document.addEventListener("DOMContentLoaded", checkLLMStatus);