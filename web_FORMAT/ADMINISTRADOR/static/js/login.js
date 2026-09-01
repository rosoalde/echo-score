const form = document.getElementById("loginForm");
const errorDiv = document.getElementById("error");

form.addEventListener("submit", async (e) => {

    e.preventDefault();

    errorDiv.classList.add("d-none");

    const formData = new FormData(form);

    const response = await fetch("/login", {
        method: "POST",
        body: formData,
        credentials: "same-origin"
    });

    if (response.redirected) {
        window.location.href = response.url;
        return;
    }

    const data = await response.json();

    errorDiv.textContent = data.detail || "Usuario o contraseña incorrectos";
    errorDiv.classList.remove("d-none");

});