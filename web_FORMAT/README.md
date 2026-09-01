# Project Architecture Overview

This project is designed with a clear separation of responsibilities to ensure
scalability, security, and maintainability for real external users.

## High-level Architecture

project_web/
│
├── backend/ ← API server (FastAPI)
│   # Contiene la lógica de la API que sirve datos al frontend y a los workers.
│   # Aquí se definen endpoints, autenticación, y validaciones.
│
├── Web_Proyecto/ ← User interface (Streamlit)
│   # Interfaz de usuario interactiva.
│   # Permite visualizar datos, ejecutar pipelines y mostrar resultados de manera intuitiva.
└──
workers/ ← Independent execution processes
└── clean_project/ ← Core business logic and pipelines 
    # Local path:
    # C:\Users\DATS004\Romina.albornoz Dropbox\Romina Albornoz\14. DS4M - Social Media Research\social_media_opinion_analysis\clean_project
    # Aquí se encuentra la lógica de negocio principal.
    # Los workers permiten ejecutar tareas pesadas de manera aislada.



## 🚀 Guía de Desarrollo Backend
Esta sección detalla los pasos necesarios para instalar dependencias, ejecutar el servidor y probar la API localmente.

### 1. Instalación de dependencias
Antes de empezar, asegúrate de tener las herramientas del backend instaladas en tu entorno:

```bash
pip install fastapi uvicorn python-jose passlib[bcrypt] python-multipart
```
Una vez instalado todo y creado el main, podemos iniciar el servidor local de desarrollo

### 2. Ejecutar el Servidor
```bash
uvicorn backend.main:app --reload
```
Detalles importantes:

backend.main:app indica a Uvicorn:

backend → carpeta donde está tu proyecto

main → archivo principal main.py

app → instancia de FastAPI dentro del archivo

--reload hace que el servidor se reinicie automáticamente cada vez que guardas cambios en tu código. No es necesario reiniciar manualmente.

El servidor por defecto se ejecuta en http://127.0.0.1:8000