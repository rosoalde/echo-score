
document.getElementById("loginForm").addEventListener("submit", async (e)  =>{
    e.preventDefault(); // Evita recarga

    const formData = new FormData(e.target);

    const res = await fetch("/login", {
        method: "POST",
        body: formData
    });
    const data = await res.json();

    if (res.ok) {
        localStorage.setItem("token", data.access_token);
        window.location.href = "/analisis";
    } else {
        alert("Usuario o contraseña incorrectos");
    }

});


document.getElementById("forgotPassword").addEventListener("click", function(e) {
    e.preventDefault(); // Evita que vaya a #

    alert("Si te has olvidado de tu contraseña, avísale al ADMINISTRADOR'");

    // Aquí puedes redirigir, abrir modal, enviar request, etc.
    // window.location.href = "/recuperar-password";
});

document.getElementById("signup").addEventListener("click", function(e) {
    e.preventDefault(); // Evita que vaya a #

    alert("Para registrarte, avísale al ADMINISTRADOR");

    // Aquí puedes redirigir, abrir modal, enviar request, etc.
    // window.location.href = "/recuperar-password";
});
