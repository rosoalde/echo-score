
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


// =============================
// INIT
// =============================

document.addEventListener("DOMContentLoaded", () => {
    bindEvents();
    loadUsers();

    document.getElementById("searchInput").addEventListener("input", debounce(e => {
        state.search = e.target.value;
        state.page = 1;
        loadUsers();
    }, 300));
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

        renderTable(data.items);      // ← usar la función completa, no "render"
        renderPagination(data.total_pages);
        updateSummary(data);
    } finally {
        showLoading(false);
    }
}

function render(users) {

    const tbody = document.getElementById("usersTableBody");
    tbody.innerHTML = "";

    users.forEach(u => {

        tbody.innerHTML += `
            <tr>
                <td>${u.id}</td>
                <td>${u.username}</td>
                <td>${u.email}</td>
                <td>${u.first_name ?? ""}</td>
                <td>
                    <span class="badge ${u.is_active ? 'bg-success' : 'bg-danger'}">
                        ${u.is_active ? "Activo" : "Inactivo"}
                    </span>
                </td>
                <td>
                    <button onclick="deleteUser(${u.id})" class="btn btn-sm btn-danger">Eliminar</button>
                </td>
            </tr>
        `;
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

        row.querySelector(".user-created").textContent = new Date(user.created_at).toLocaleDateString();

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


async function deleteUser(id) {

    await fetch(`/api/users/${id}`, {
        method: "DELETE"
    });

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
        is_verified: document.getElementById("editIsVerified").checked
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
// PLACEHOLDER ACTIONS
// =============================

function openEdit(id) {}
function openView(id) {}
function openPassword(id) {}
function openRoles(id) {}
function openDelete(id) {}