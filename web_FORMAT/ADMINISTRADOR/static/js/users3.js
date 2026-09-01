// =============================
// CONFIG
// =============================

const API_URL = "/api/users";

let state = {
    page: 1,
    page_size: 25,
    search: "",
    sort: "id",
    order: "desc",
    filters: {},
    selected: new Set()
};

// caché en memoria de la última página cargada y de los roles disponibles
let usersCache = [];
let rolesCache = [];


// =============================
// INIT
// =============================

document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadRoles();
    loadUsers();
});


// =============================
// EVENTOS
// =============================

function bindEvents() {

    // búsqueda con debounce
    document.getElementById("searchInput").addEventListener("input", debounce((e) => {
        state.search = e.target.value;
        state.page = 1;
        loadUsers();
    }, 400));


    // filtros básicos
    document.getElementById("filterActive").addEventListener("change", (e) => {
        state.filters.is_active = e.target.value;
        loadUsers();
    });

    document.getElementById("filterVerified").addEventListener("change", (e) => {
        state.filters.is_verified = e.target.value;
        loadUsers();
    });


    // page size
    document.getElementById("pageSize").addEventListener("change", (e) => {
        state.page_size = parseInt(e.target.value);
        state.page = 1;
        loadUsers();
    });


    // reload
    document.getElementById("reloadUsers").addEventListener("click", loadUsers);


    // check all
    document.getElementById("checkAll").addEventListener("change", (e) => {
        document.querySelectorAll(".row-check").forEach(cb => {
            cb.checked = e.target.checked;
            toggleSelect(cb.dataset.id, cb.checked);
        });
        updateBulkUI();
    });


    // ordenación columnas
    document.querySelectorAll(".sortable").forEach(el => {
        el.addEventListener("click", () => {
            const field = el.dataset.sort;

            if (state.sort === field) {
                state.order = state.order === "asc" ? "desc" : "asc";
            } else {
                state.sort = field;
                state.order = "asc";
            }

            loadUsers();
        });
    });


    // crear usuario
    document.getElementById("createUserSubmit").addEventListener("click", createUser);


    // editar usuario
    document.getElementById("editUserSubmit").addEventListener("click", updateUser);


    // password
    document.getElementById("savePasswordBtn").addEventListener("click", changePassword);


    // delete
    document.getElementById("confirmDeleteBtn").addEventListener("click", deleteUser);


    // roles
    document.getElementById("saveRolesBtn").addEventListener("click", saveRoles);


    // filtros avanzados
    document.getElementById("applyAdvancedFilters").addEventListener("click", applyAdvancedFilters);

    document.getElementById("resetFilters").addEventListener("click", resetFilters);


    // bulk actions
    document.getElementById("bulkDelete").addEventListener("click", bulkDelete);

}


// =============================
// LOAD USERS
// =============================

async function loadUsers() {

    showLoading(true);

    try {

        const res = await fetch(`${API_URL}?page=${state.page}&search=${state.search}`);
        const data = await res.json();

        usersCache = data.items;

        renderTable(data.items);
        renderPagination(data.total_pages);
        updateSummary(data);

    } finally {
        showLoading(false);
    }
}


async function loadRoles() {

    try {
        const res = await fetch("/api/roles");
        const data = await res.json();
        rolesCache = data.items;

        fillRoleSelect(document.getElementById("createUserRoles"), []);
        fillRoleSelect(document.getElementById("editUserRoles"), []);
    } catch (err) {
        console.error("No se pudieron cargar los roles", err);
    }
}


function fillRoleSelect(select, selectedIds) {

    if (!select) return;

    select.innerHTML = "";

    rolesCache.forEach(role => {
        const opt = document.createElement("option");
        opt.value = role.id;
        opt.textContent = role.name;
        opt.selected = selectedIds.includes(role.id);
        select.appendChild(opt);
    });
}

// =============================
// RENDER TABLE
// =============================

function renderTable(users) {

    const tbody = document.getElementById("usersTableBody");
    tbody.innerHTML = "";

    const template = document.getElementById("userRowTemplate");

    if (!users.length) {
        document.getElementById("emptyState").style.display = "block";
        document.getElementById("tableContainer").style.display = "none";
        return;
    }

    document.getElementById("emptyState").style.display = "none";
    document.getElementById("tableContainer").style.display = "block";

    users.forEach(user => {

        const row = template.content.cloneNode(true);

        row.querySelector(".user-id").textContent = user.id;
        row.querySelector(".user-username").textContent = user.username;
        row.querySelector(".user-name").textContent = `${user.first_name} ${user.last_name || ""}`;
        row.querySelector(".user-email").textContent = user.email;

        row.querySelector(".user-created").textContent = user.created_at
            ? new Date(user.created_at).toLocaleDateString()
            : "—";

        // roles
        const rolesEl = row.querySelector(".user-roles");
        rolesEl.innerHTML = "";
        (user.roles || []).forEach(role => {
            const badge = document.createElement("span");
            badge.className = "badge bg-info me-1";
            badge.textContent = role.name;
            rolesEl.appendChild(badge);
        });
        if (!user.roles || !user.roles.length) {
            rolesEl.innerHTML = '<span class="text-muted">Sin roles</span>';
        }

        // status
        const status = row.querySelector(".user-status");
        status.textContent = user.is_active ? "Activo" : "Inactivo";
        status.className = `badge ${user.is_active ? "bg-success" : "bg-secondary"}`;

        // verified
        const verified = row.querySelector(".user-verified");
        verified.textContent = user.is_verified ? "OK" : "NO";
        verified.className = `badge ${user.is_verified ? "bg-primary" : "bg-warning"}`;

        // counts
        row.querySelector(".analyses-count").textContent = user.analyses_count || 0;
        row.querySelector(".sessions-count").textContent = user.sessions_count || 0;

        // checkbox
        const cb = row.querySelector(".row-check");
        cb.dataset.id = user.id;
        cb.addEventListener("change", () => toggleSelect(user.id, cb.checked));

        // actions
        row.querySelector(".btn-edit").addEventListener("click", () => openEdit(user.id));
        row.querySelector(".btn-view").addEventListener("click", () => openView(user.id));
        row.querySelector(".btn-password").addEventListener("click", () => openPassword(user.id));
        row.querySelector(".btn-roles").addEventListener("click", () => openRoles(user.id));
        row.querySelector(".btn-delete").addEventListener("click", () => openDelete(user.id));

        tbody.appendChild(row);

    });
}


async function deleteUser() {

    const id = document.getElementById("deleteUserId").value;

    await fetch(`/api/users/${id}`, {
        method: "DELETE"
    });

    bootstrap.Modal.getInstance(document.getElementById("deleteUserModal"))?.hide();

    showToast("Usuario eliminado");
    loadUsers();
}

// =============================
// PAGINATION
// =============================

function renderPagination(totalPages) {

    const el = document.getElementById("pagination");
    el.innerHTML = "";

    for (let i = 1; i <= totalPages; i++) {

        el.innerHTML += `
            <li class="page-item ${i === state.page ? 'active' : ''}">
                <a class="page-link" onclick="goTo(${i})">${i}</a>
            </li>
        `;
    }
}

function goTo(page) {
    state.page = page;
    loadUsers();
}



// =============================
// CREATE USER
// =============================

async function createUser() {

    const form = document.getElementById("createUserForm");
    const data = Object.fromEntries(new FormData(form));

    // los <select multiple> no salen bien de Object.fromEntries (solo 1 valor)
    data.roles = Array.from(document.getElementById("createUserRoles").selectedOptions)
        .map(opt => parseInt(opt.value));

    data.is_active = document.querySelector('#createUserForm [name="is_active"]').checked;
    data.is_verified = document.querySelector('#createUserForm [name="is_verified"]').checked;

    try {

        const res = await fetch(API_URL, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(data)
        });

        if (!res.ok) throw await res.json();

        bootstrap.Modal.getInstance(document.getElementById("createUserModal")).hide();

        form.reset();

        showToast("Usuario creado correctamente");

        loadUsers();

    } catch (err) {
        showError("createUserError", err.detail || "Error creando usuario");
    }
}


// =============================
// UPDATE USER
// =============================

async function updateUser() {

    const id = document.getElementById("editUserId").value;

    const data = {
        username: document.getElementById("editUsername").value,
        email: document.getElementById("editEmail").value,
        first_name: document.getElementById("editFirstName").value,
        last_name: document.getElementById("editLastName").value,
        is_active: document.getElementById("editIsActive").checked,
        is_verified: document.getElementById("editIsVerified").checked,
        roles: Array.from(document.getElementById("editUserRoles").selectedOptions)
            .map(opt => parseInt(opt.value))
    };

    const res = await fetch(`${API_URL}/${id}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data)
    });

    if (res.ok) {
        bootstrap.Modal.getInstance(document.getElementById("editUserModal")).hide();
        showToast("Usuario actualizado");
        loadUsers();
    }
}


// =============================
// DELETE
// =============================



// =============================
// PASSWORD
// =============================

async function changePassword() {

    const id = document.getElementById("passwordUserId").value;

    const password = document.getElementById("newPassword").value;

    const res = await fetch(`${API_URL}/${id}/password`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({password})
    });

    if (res.ok) {
        bootstrap.Modal.getInstance(document.getElementById("passwordModal")).hide();
        showToast("Contraseña actualizada");
    }
}


// =============================
// BULK DELETE
// =============================

async function bulkDelete() {

    if (!confirm("¿Eliminar usuarios seleccionados?")) return;

    await fetch(`${API_URL}/bulk-delete`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ids: Array.from(state.selected)})
    });

    state.selected.clear();
    loadUsers();
}


// =============================
// FILTERS
// =============================

function applyAdvancedFilters() {

    state.filters.date_from = document.getElementById("filterDateFrom").value;
    state.filters.date_to = document.getElementById("filterDateTo").value;

    state.filters.min_analyses = document.getElementById("filterMinAnalyses").value;
    state.filters.max_analyses = document.getElementById("filterMaxAnalyses").value;

    state.filters.min_sessions = document.getElementById("filterMinSessions").value;
    state.filters.max_sessions = document.getElementById("filterMaxSessions").value;

    state.filters.order_by = document.getElementById("filterOrderBy").value;

    loadUsers();
}


function resetFilters() {

    state.filters = {};

    document.querySelectorAll("input, select").forEach(el => {
        if (el.type !== "checkbox") el.value = "";
    });

    loadUsers();
}


// =============================
// HELPERS
// =============================

function toggleSelect(id, selected) {

    if (selected) state.selected.add(id);
    else state.selected.delete(id);

    updateBulkUI();
}

function updateBulkUI() {

    const count = state.selected.size;

    document.getElementById("selectedCounter").textContent = `${count} seleccionados`;

    document.getElementById("bulkActions").style.display = count ? "block" : "none";
}


function showLoading(show) {

    document.getElementById("tableLoading").style.display = show ? "block" : "none";
    document.getElementById("tableContainer").style.display = show ? "none" : "block";
}


function updateSummary(data) {

    document.getElementById("tableSummary").textContent =
        `Mostrando ${data.items.length} usuarios de ${data.total}`;
}


function showToast(msg) {

    const toast = new bootstrap.Toast(document.getElementById("actionToast"));

    document.getElementById("actionToastBody").textContent = msg;

    toast.show();
}


function showError(id, msg) {

    const el = document.getElementById(id);

    el.textContent = msg;

    el.classList.remove("d-none");
}


// debounce
function debounce(fn, delay) {

    let t;

    return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), delay);
    };
}


// =============================
// ACTIONS
// =============================

function findUser(id) {
    return usersCache.find(u => String(u.id) === String(id));
}

function openEdit(id) {

    const user = findUser(id);
    if (!user) return;

    document.getElementById("editUserId").value = user.id;
    document.getElementById("editUsername").value = user.username;
    document.getElementById("editEmail").value = user.email;
    document.getElementById("editFirstName").value = user.first_name || "";
    document.getElementById("editLastName").value = user.last_name || "";
    document.getElementById("editIsActive").checked = !!user.is_active;
    document.getElementById("editIsVerified").checked = !!user.is_verified;

    fillRoleSelect(
        document.getElementById("editUserRoles"),
        (user.roles || []).map(r => r.id)
    );

    bootstrap.Modal.getOrCreateInstance(document.getElementById("editUserModal")).show();
}

function openView(id) {
    // No existe un modal de "solo ver" en el HTML todavía;
    // de momento reutilizamos el de edición.
    openEdit(id);
}

function openPassword(id) {

    document.getElementById("passwordUserId").value = id;
    document.getElementById("newPassword").value = "";

    bootstrap.Modal.getOrCreateInstance(document.getElementById("passwordModal")).show();
}

function openRoles(id) {

    const user = findUser(id);
    if (!user) return;

    document.getElementById("rolesUserId").value = id;

    const container = document.getElementById("rolesContainer");
    container.innerHTML = "";

    const selectedIds = (user.roles || []).map(r => r.id);

    rolesCache.forEach(role => {
        const div = document.createElement("div");
        div.className = "form-check";
        div.innerHTML = `
            <input class="form-check-input role-checkbox" type="checkbox"
                   value="${role.id}" id="role-${role.id}"
                   ${selectedIds.includes(role.id) ? "checked" : ""}>
            <label class="form-check-label" for="role-${role.id}">${role.name}</label>
        `;
        container.appendChild(div);
    });

    bootstrap.Modal.getOrCreateInstance(document.getElementById("rolesModal")).show();
}

async function saveRoles() {

    const id = document.getElementById("rolesUserId").value;

    const roleIds = Array.from(document.querySelectorAll(".role-checkbox:checked"))
        .map(cb => parseInt(cb.value));

    const res = await fetch(`${API_URL}/${id}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({roles: roleIds})
    });

    if (res.ok) {
        bootstrap.Modal.getInstance(document.getElementById("rolesModal")).hide();
        showToast("Roles actualizados");
        loadUsers();
    } else {
        const err = await res.json().catch(() => ({}));
        showError("rolesError", err.detail || "Error guardando roles");
    }
}

function openDelete(id) {

    document.getElementById("deleteUserId").value = id;

    bootstrap.Modal.getOrCreateInstance(document.getElementById("deleteUserModal")).show();
}