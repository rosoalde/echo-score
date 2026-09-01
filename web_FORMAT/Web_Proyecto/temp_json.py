from pathlib import Path
import json
import uuid
from datetime import datetime

# Definir BASE_DIR asegurando que es la raíz del proyecto web
BASE_DIR = Path(__file__).resolve().parent
DATOS_DIR = BASE_DIR / "datos"
ANALYSIS_DB = BASE_DIR / "analysis_db.json"

def sync_analysis_db():
    """Sincroniza la DB con el disco. Guarda rutas RELATIVAS."""

    # ---- Leer DB ----
    if ANALYSIS_DB.exists():
        try:
            db = json.loads(ANALYSIS_DB.read_text(encoding="utf-8"))
        except Exception:
            db = []
    else:
        db = []

    # Mapear DB existente
    # NOTA: Comparamos usando resolve() para igualar rutas absolutas en memoria
    db_by_path = {}
    for e in db:
        if "output_folder" in e:
            # Reconstruir la ruta absoluta local para comparar
            full_path = (BASE_DIR / e["output_folder"]).resolve()
            db_by_path[str(full_path)] = e

    seen_paths = set()
    changed = False

    # ---- Escanear disco ----
    if DATOS_DIR.exists():
        for user_folder in DATOS_DIR.iterdir():
            if not user_folder.is_dir():
                continue

            username = user_folder.name

            for project_folder in user_folder.iterdir():
                if not project_folder.is_dir():
                    continue

                # Obtenemos la ruta absoluta real actual
                abs_path = project_folder.resolve()
                path_str = str(abs_path)
                seen_paths.add(path_str)

                # Calculamos la ruta RELATIVA para guardar en JSON (ej: datos/user/proyecto)
                # as_posix() convierte los separadores "\" de Windows a "/" universales
                relative_path = project_folder.relative_to(BASE_DIR).as_posix()

                if path_str in db_by_path:
                    entry = db_by_path[path_str]
                    # Actualizamos la ruta en el JSON por si estaba absoluta antigua
                    if entry["output_folder"] != relative_path:
                        entry["output_folder"] = relative_path
                        changed = True
                    
                    if entry.get("status") == "deleted":
                        entry["status"] = "completed"
                        changed = True
                else:
                    # ➕ Nuevo proyecto
                    created_time = datetime.fromtimestamp(project_folder.stat().st_ctime)
                    db.append({
                        "id": str(uuid.uuid4()),
                        "project_name": project_folder.name,
                        "username": username,
                        "output_folder": relative_path,  # <--- GUARDAMOS RELATIVA
                        "status": "completed",
                        "created_at": created_time.isoformat()
                    })
                    print(f"🔹 Nuevo proyecto detectado: {relative_path}")
                    changed = True

    # ---- Marcar como deleted ----
    for entry in db:
        # Reconstruir ruta completa para verificar existencia
        full_check_path = (BASE_DIR / entry["output_folder"]).resolve()
        if str(full_check_path) not in seen_paths:
            if entry.get("status") != "deleted":
                entry["status"] = "deleted"
                changed = True

    # ---- Guardar ----
    if changed:
        ANALYSIS_DB.write_text(json.dumps(db, indent=4), encoding="utf-8")
        print("✅ DB sincronizada (Rutas relativas actualizadas)")

    return db