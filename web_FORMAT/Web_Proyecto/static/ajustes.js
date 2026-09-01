function toggleSection(section, button) {

    const fields = document.querySelectorAll(".editable-" + section);
    if (!fields.length) return;

    const isDisabled = fields[0].hasAttribute("disabled");

    // 🔹 Obtener el ID del collapse según la sección
    let collapseId = "";
    if (section === "personal") collapseId = "collapsePersonal";
    if (section === "security") collapseId = "collapseSecurity";
    if (section === "role") collapseId = "collapseRole";

    const collapseElement = document.getElementById(collapseId);
    const collapseInstance = new bootstrap.Collapse(collapseElement, {
        toggle: false
    });

    fields.forEach(field => {

        if (isDisabled) {
            // ACTIVAR EDICIÓN
            field.dataset.original = field.value;
            field.removeAttribute("disabled");
        } else {
            // CANCELAR EDICIÓN
            if (field.dataset.original !== undefined) {
                field.value = field.dataset.original;
            }
            field.setAttribute("disabled", true);
        }
    });

    if (isDisabled) {
        // 🔹 Abrir el desplegable
        collapseInstance.show();

        button.textContent = "Cancelar";
        button.classList.remove("btn-outline-primary");
        button.classList.add("btn-outline-danger");

    } else {
        // 🔹 Cerrar el desplegable
        //collapseInstance.hide();

        button.textContent = "Editar";
        button.classList.remove("btn-outline-danger");
        button.classList.add("btn-outline-primary");
    }
}