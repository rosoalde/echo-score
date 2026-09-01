"""
LoRA Annotation System — FastAPI backend v2.3
Fixes v2.3:
  - get_records builds parent_lookup BEFORE iterating rows so Reddit/Bluesky/YouTube
    comments receive their parent post/video context (matching preparar_contexto_multimodal)
  - Tracks annotated record IDs per session so reloading never re-shows confirmed records
  - New endpoint POST /api/sessions/{session_id}/mark-seen  to persist seen record IDs
  - New endpoint GET  /api/sessions/{session_id}/seen-ids   to restore UI state on reload
"""

import csv as _csv
import io
import json
import sys
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

# ── Rutas del proyecto ────────────────────────────────────────────────────────
CLEAN_SRC = "/home/rrss/proyecto_web/Project_OLD/RRSS_version_stance/clean_project/src"
if CLEAN_SRC not in sys.path:
    sys.path.insert(0, CLEAN_SRC)

WEB_PROYECTO_DIR = Path(__file__).resolve().parent.parent / "Web_Proyecto"
_WEB_PROYECTO_CANDIDATES = [
    WEB_PROYECTO_DIR,
    Path("/home/rrss/proyecto_web/Project_OLD/RRSS_version_stance/project_web/Web_Proyecto"),
    Path("/home/rrss/proyecto_web/RRSS_version_stance/project_web/Web_Proyecto"),
]
WEB_PROYECTO_DIR = next((p for p in _WEB_PROYECTO_CANDIDATES if p.exists()), WEB_PROYECTO_DIR)

if str(WEB_PROYECTO_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_PROYECTO_DIR))

try:
    from logica import backend_analisis as _backend_analisis
    from logica import ejecutar_indicador_aceptacion
    from logica import _PROGRESS as _LOGICA_PROGRESS
    _LOGICA_AVAILABLE = True
    print(f"[annotation_api] logica.py importado desde {WEB_PROYECTO_DIR}")
except Exception as _e:
    _LOGICA_AVAILABLE = False
    _LOGICA_PROGRESS  = {}
    print(f"[annotation_api] AVISO: logica.py no disponible ({_e}). Usa 'Opción B'.")

MAIN_SYSTEM_URL = "http://localhost:8006"

app = FastAPI(title="LoRA Annotation System", version="2.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HERE            = Path(__file__).resolve().parent
DATA_DIR        = HERE / "lora_data"
DATA_DIR.mkdir(exist_ok=True)

SESSIONS_FILE   = DATA_DIR / "sessions.json"
KEYWORDS_FILE   = DATA_DIR / "keyword_annotations.json"
SENTIMENT_FILE  = DATA_DIR / "sentiment_annotations.json"
SEEN_IDS_FILE   = DATA_DIR / "seen_ids.json"          # NEW: tracks annotated record IDs
LORA_EXPORT_DIR = DATA_DIR / "lora_exports"
LORA_EXPORT_DIR.mkdir(exist_ok=True)

_ANALYSIS_PROGRESS: Dict[str, dict] = {}


def _load(path: Path) -> list:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _load_dict(path: Path) -> dict:
    """Load a JSON file that is a dict (not a list)."""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_session(session_id: str, updates: dict):
    sessions = _load(SESSIONS_FILE)
    for s in sessions:
        if s["id"] == session_id:
            s.update(updates)
            break
    _save(SESSIONS_FILE, sessions)


def _safe_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# ── Helper: inspect a folder for available data ──────────────────────────────

def _inspect_folder(folder_path: Path) -> dict:
    maestro      = folder_path / "dataset_maestro_lora.csv"
    analizado    = list(folder_path.glob("*_analizado.csv"))
    pilares      = list(folder_path.glob("*_pilares.csv"))
    raw_datasets = list(folder_path.glob("*_global_dataset.csv"))
    scoreop      = folder_path / "scoreop_consolidado.csv"

    return {
        "tiene_maestro":       maestro.exists(),
        "tiene_analizado":     bool(analizado),
        "tiene_pilares":       bool(pilares),
        "tiene_raw_datasets":  bool(raw_datasets),
        "tiene_scoreop":       scoreop.exists(),
        "archivos_analizado":  [f.name for f in analizado],
        "archivos_pilares":    [f.name for f in pilares],
        "archivos_raw":        [f.name for f in raw_datasets],
        "lista_para_anotar":   maestro.exists() or bool(analizado) or bool(pilares),
        "solo_scraping":       not (maestro.exists() or bool(analizado) or bool(pilares)) and bool(raw_datasets),
    }


# ═════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═════════════════════════════════════════════════════════════════════════════

class SessionCreate(BaseModel):
    annotator_name: str
    annotator_role: str = "annotator"
    tema: str
    population_scope: str
    languages: List[str]

class KeywordDecision(BaseModel):
    session_id: str
    keyword: str
    accepted: bool
    reason: Optional[str] = None
    annotator_name: str

class KeywordAddition(BaseModel):
    session_id: str
    keyword: str
    reason: str
    annotator_name: str
    languages: List[str]

class SentimentAnnotation(BaseModel):
    session_id: str
    record_id: str
    content: str
    original_sentiment: int
    corrected_sentiment: int
    is_correction: bool
    correction_reason: Optional[str] = None
    original_topic: Optional[str] = None
    corrected_topic: Optional[str] = None
    topic_reason: Optional[str] = None
    annotator_name: str
    platform: Optional[str] = None

class PillarAnnotation(BaseModel):
    session_id: str
    record_id: str
    content: str
    pillar: str
    original_value: int
    corrected_value: int
    is_correction: bool
    correction_reason: Optional[str] = None
    annotator_name: str

class GenerateKeywordsRequest(BaseModel):
    tema: str
    population_scope: str
    languages: List[str]
    session_id: str

class LaunchAnalysisRequest(BaseModel):
    session_id: str
    sources: List[str]
    start_date: str
    end_date: str
    final_keywords: List[Dict[str, Any]]
    project_name: Optional[str] = None

# NEW: payload for marking records as seen/annotated
class MarkSeenRequest(BaseModel):
    record_ids: List[str]


# ═════════════════════════════════════════════════════════════════════════════
# FRONTEND
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html_path = HERE / "annotation_ui.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>annotation_ui.html not found</h1>"
        f"<p>Expected at: {html_path}</p>"
    )


# ═════════════════════════════════════════════════════════════════════════════
# SESSIONS
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/sessions")
def create_session(body: SessionCreate):
    sessions = _load(SESSIONS_FILE)
    session = {
        "id": str(uuid.uuid4()),
        "annotator_name": body.annotator_name,
        "annotator_role": body.annotator_role,
        "tema": body.tema,
        "population_scope": body.population_scope,
        "languages": body.languages,
        "created_at": datetime.now().isoformat(),
        "phase": "keywords",
        "keyword_decisions": [],
        "keyword_additions": [],
        "final_keywords": [],
        "output_folder": None,
        "main_analysis_id": None,
    }
    sessions.append(session)
    _save(SESSIONS_FILE, sessions)
    return session


@app.get("/api/sessions")
def list_sessions():
    return _load(SESSIONS_FILE)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    sessions = _load(SESSIONS_FILE)
    s = next((x for x in sessions if x["id"] == session_id), None)
    if not s:
        raise HTTPException(404, "Session not found")
    return s


# ═════════════════════════════════════════════════════════════════════════════
# SEEN IDs — persist which records have been annotated (survives reload)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/sessions/{session_id}/seen-ids")
def get_seen_ids(session_id: str):
    """
    Returns the list of record IDs that have already been annotated/confirmed
    for this session. The UI uses this on startup to skip past them.
    """
    all_seen: dict = _load_dict(SEEN_IDS_FILE)
    return {"session_id": session_id, "seen_ids": all_seen.get(session_id, [])}


@app.post("/api/sessions/{session_id}/mark-seen")
def mark_seen(session_id: str, body: MarkSeenRequest):
    """
    Persists one or more record IDs as 'already annotated' for this session.
    Call this after the annotator clicks 'Guardar y siguiente'.
    """
    all_seen: dict = _load_dict(SEEN_IDS_FILE)
    existing = set(all_seen.get(session_id, []))
    existing.update(body.record_ids)
    all_seen[session_id] = list(existing)
    _save(SEEN_IDS_FILE, all_seen)
    return {"ok": True, "total_seen": len(all_seen[session_id])}


# ═════════════════════════════════════════════════════════════════════════════
# KEYWORDS
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/keywords/generate")
async def generate_keywords(body: GenerateKeywordsRequest):
    try:
        from clean_project.vllm.vllm_keywords2 import (
            expandir_tema, generar_keywords_por_idioma, combinar_keywords_multilingue,
            clasificar_tema, expandir_geografia, generar_keywords_hiperlocal_por_idioma,
            combinar_keywords_hiperlocal,
        )
        tipo  = clasificar_tema(body.tema, body.population_scope)
        brief = expandir_tema(body.tema, body.population_scope)
        todas = []
        if tipo == "hiperlocal":
            geo = expandir_geografia(body.tema, body.population_scope)
            with ThreadPoolExecutor(max_workers=max(1, len(body.languages))) as ex:
                futs = {
                    ex.submit(generar_keywords_hiperlocal_por_idioma, body.tema, lang,
                              body.population_scope, brief, geo): lang
                    for lang in body.languages
                }
                for f in as_completed(futs):
                    try: todas.extend(f.result())
                    except Exception: pass
            resultado = combinar_keywords_hiperlocal(todas)
        else:
            with ThreadPoolExecutor(max_workers=max(1, len(body.languages))) as ex:
                futs = {
                    ex.submit(generar_keywords_por_idioma, body.tema, lang,
                              body.population_scope, brief): lang
                    for lang in body.languages
                }
                for f in as_completed(futs):
                    try: todas.extend(f.result())
                    except Exception: pass
            resultado = combinar_keywords_multilingue(todas)

        _update_session(body.session_id, {
            "phase": "keyword_review",
            "generated_keywords": resultado["keywords"],
            "tipo_tema": tipo,
            "brief": brief.get("descripcion_breve", ""),
        })
        return {
            "keywords": resultado["keywords"],
            "tipo_tema": tipo,
            "brief": brief.get("descripcion_breve", ""),
            "source": "pipeline",
        }
    except Exception as exc:
        print(f"[annotation_api] Pipeline no disponible, usando mock. Razón: {exc}")
        lang0 = body.languages[0] if body.languages else "Castellano"
        mock_kws = [
            {"keyword": body.tema.lower(),                  "languages": lang0, "razon_tema": "Término central"},
            {"keyword": f"{body.tema.lower()} opiniones",   "languages": lang0, "razon_tema": "Búsqueda de opiniones"},
            {"keyword": f"{body.tema.lower()} valoración",  "languages": lang0, "razon_tema": "Evaluación ciudadana"},
            {"keyword": f"debate {body.tema.lower()}",      "languages": lang0, "razon_tema": "Debate público"},
            {"keyword": f"crítica {body.tema.lower()}",     "languages": lang0, "razon_tema": "Críticas al tema"},
            {"keyword": f"apoyo {body.tema.lower()}",       "languages": lang0, "razon_tema": "Voces a favor"},
            {"keyword": f"{body.tema.lower()} problemas",   "languages": lang0, "razon_tema": "Problemas detectados"},
            {"keyword": f"beneficios {body.tema.lower()}",  "languages": lang0, "razon_tema": "Argumentos positivos"},
        ]
        _update_session(body.session_id, {
            "phase": "keyword_review",
            "generated_keywords": mock_kws,
            "tipo_tema": "universal",
            "brief": f"Análisis de opinión pública sobre: {body.tema}",
        })
        return {
            "keywords": mock_kws,
            "tipo_tema": "universal",
            "brief": f"Análisis de opinión pública sobre: {body.tema}",
            "source": "mock",
            "note": "vLLM no disponible — modo demostración activo",
        }


@app.post("/api/keywords/decide")
def decide_keyword(body: KeywordDecision):
    annotations = _load(KEYWORDS_FILE)
    record = {
        "id": str(uuid.uuid4()),
        "session_id": body.session_id,
        "keyword": body.keyword,
        "accepted": body.accepted,
        "reason": body.reason,
        "annotator_name": body.annotator_name,
        "timestamp": datetime.now().isoformat(),
        "type": "llm_generated",
    }
    annotations.append(record)
    _save(KEYWORDS_FILE, annotations)
    return record


@app.post("/api/keywords/add")
def add_keyword(body: KeywordAddition):
    annotations = _load(KEYWORDS_FILE)
    record = {
        "id": str(uuid.uuid4()),
        "session_id": body.session_id,
        "keyword": body.keyword,
        "reason": body.reason,
        "languages": body.languages,
        "annotator_name": body.annotator_name,
        "timestamp": datetime.now().isoformat(),
        "type": "human_added",
        "accepted": True,
    }
    annotations.append(record)
    _save(KEYWORDS_FILE, annotations)
    return record


@app.post("/api/keywords/finalize")
def finalize_keywords(body: dict = Body(...)):
    session_id     = body.get("session_id")
    final_keywords = body.get("final_keywords", [])
    _update_session(session_id, {
        "phase": "analysis_pending",
        "final_keywords": final_keywords,
    })
    return {"ok": True, "total": len(final_keywords)}


# ═════════════════════════════════════════════════════════════════════════════
# ANÁLISIS
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/analysis/launch")
async def launch_analysis(body: LaunchAnalysisRequest):
    sessions = _load(SESSIONS_FILE)
    session  = next((s for s in sessions if s["id"] == body.session_id), None)
    if not session:
        raise HTTPException(404, "Session not found")

    kw_payload = []
    for kw in body.final_keywords:
        if isinstance(kw, dict):
            kw_payload.append(kw)
        else:
            kw_payload.append({"keyword": str(kw), "languages": session.get("languages", ["Castellano"])})

    payload_8006 = {
        "project_name": body.project_name or f"LoRA_{session['tema'][:30]}",
        "asistente": session["tema"],
        "desc_tema": session.get("brief", ""),
        "keywords": json.dumps(kw_payload),
        "start_date": body.start_date,
        "end_date": body.end_date,
        "sources": body.sources,
        "languages": session.get("languages", ["Castellano"]),
        "population": session.get("population_scope", "GLOBAL"),
        "username": session["annotator_name"],
        "role": "analista",
        "results": [{"social": s, "success": True} for s in body.sources],
    }

    if _LOGICA_AVAILABLE:
        analysis_id_8006 = str(uuid.uuid4())
        asyncio.create_task(_backend_analisis(payload_8006, analysis_id_8006))
        asyncio.create_task(_poll_local_progress(body.session_id, analysis_id_8006, session["annotator_name"]))
    else:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                await client.post(f"{MAIN_SYSTEM_URL}/login",
                                  data={"username": "admin", "password": "1234"},
                                  follow_redirects=True)
                resp = await client.post(f"{MAIN_SYSTEM_URL}/ejecutar-analisis",
                                         json=payload_8006,
                                         headers={"Content-Type": "application/json"})
                if resp.status_code not in (200, 201):
                    raise HTTPException(502, f"Error del sistema 8006: {resp.text[:200]}")
                data_8006 = resp.json()
                analysis_id_8006 = data_8006.get("analysis_id") or data_8006.get("user_id")
        except httpx.ReadTimeout:
            raise HTTPException(504, "El sistema principal tardó demasiado.")
        except httpx.ConnectError:
            raise HTTPException(503, f"No se puede conectar al sistema principal en {MAIN_SYSTEM_URL}.")
        asyncio.create_task(_poll_analysis_progress(body.session_id, analysis_id_8006))

    _update_session(body.session_id, {
        "phase": "scraping",
        "main_analysis_id": analysis_id_8006,
        "sources": body.sources,
        "start_date": body.start_date,
        "end_date": body.end_date,
    })

    return {
        "ok": True,
        "analysis_id_8006": analysis_id_8006,
        "session_id": body.session_id,
        "message": "Análisis lanzado. Sigue el progreso en la interfaz.",
    }


async def _poll_local_progress(session_id: str, analysis_id: str, username: str):
    _ANALYSIS_PROGRESS[session_id] = {
        "paso": "inicio", "mensaje": "Iniciando análisis localmente...",
        "porcentaje": 2, "error": False
    }
    while True:
        estado = _LOGICA_PROGRESS.get(analysis_id)
        if estado:
            _ANALYSIS_PROGRESS[session_id] = {
                "paso":       estado.get("paso", ""),
                "mensaje":    estado.get("mensaje", ""),
                "porcentaje": estado.get("porcentaje", 0),
                "error":      estado.get("error", False),
            }
            if estado.get("porcentaje", 0) >= 100 or estado.get("error"):
                break
        await asyncio.sleep(1)

    estado_final = _LOGICA_PROGRESS.get(analysis_id, {})
    if not estado_final.get("error"):
        _ANALYSIS_PROGRESS[session_id] = {
            "paso": "pilares",
            "mensaje": "Generando pilares de aceptación (vLLM)...",
            "porcentaje": 95,
            "error": False
        }
        try:
            user_dict = {"username": username}
            await asyncio.to_thread(ejecutar_indicador_aceptacion, analysis_id, user_dict)
            _ANALYSIS_PROGRESS[session_id] = {
                "paso": "completado",
                "mensaje": "¡Análisis y pilares completados! Registros listos.",
                "porcentaje": 100,
                "error": False
            }
        except Exception as e:
            _ANALYSIS_PROGRESS[session_id] = {
                "paso": "error_pilares",
                "mensaje": f"Análisis completado, pero fallaron los pilares: {e}",
                "porcentaje": 100,
                "error": True
            }

    await _sync_output_folder(session_id, analysis_id)


async def _poll_analysis_progress(session_id: str, analysis_id_8006: str):
    sse_url = f"{MAIN_SYSTEM_URL}/analisis/{analysis_id_8006}/progreso"
    _ANALYSIS_PROGRESS[session_id] = {
        "paso": "inicio", "mensaje": "Conectando con el sistema de análisis…",
        "porcentaje": 2, "error": False
    }
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", sse_url) as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    try:
                        estado = json.loads(raw)
                    except Exception:
                        continue
                    _ANALYSIS_PROGRESS[session_id] = {
                        "paso":       estado.get("paso", ""),
                        "mensaje":    estado.get("mensaje", ""),
                        "porcentaje": estado.get("porcentaje", 0),
                        "error":      estado.get("error", False),
                    }
                    if estado.get("porcentaje", 0) >= 100 or estado.get("error"):
                        break
        await _sync_output_folder(session_id, analysis_id_8006)
    except Exception as exc:
        _ANALYSIS_PROGRESS[session_id] = {
            "paso": "error",
            "mensaje": f"Error siguiendo el progreso: {exc}",
            "porcentaje": 0,
            "error": True,
        }


async def _sync_output_folder(session_id: str, analysis_id_8006: str):
    db_candidates = [
        HERE.parent / "Web_Proyecto" / "analysis_db.json",
        Path("/home/rrss/proyecto_web/Project_OLD/RRSS_version_stance/project_web/Web_Proyecto/analysis_db.json"),
        Path("analysis_db.json"),
    ]
    for db_path in db_candidates:
        if db_path.exists():
            try:
                db = json.loads(db_path.read_text(encoding="utf-8"))
                record = next((r for r in db if r.get("id") == analysis_id_8006), None)
                if record and record.get("output_folder"):
                    folder_raw  = Path(record["output_folder"])
                    if not folder_raw.is_absolute():
                        base = db_path.parent
                        folder_raw = (base / folder_raw).resolve()
                    _update_session(session_id, {
                        "output_folder": str(folder_raw),
                        "phase": "sentiment_review",
                    })
                    _ANALYSIS_PROGRESS[session_id] = {
                        "paso": "completado",
                        "mensaje": "¡Análisis completado! Los registros están listos para anotar.",
                        "porcentaje": 100,
                        "error": False,
                    }
                    return
            except Exception as e:
                print(f"[annotation_api] Error leyendo analysis_db: {e}")

    _ANALYSIS_PROGRESS[session_id] = {
        "paso": "completado",
        "mensaje": "Análisis completado. Vincula la carpeta de resultados si los registros no aparecen.",
        "porcentaje": 100,
        "error": False,
    }


@app.get("/api/analysis/progress/{session_id}")
async def stream_analysis_progress(session_id: str):
    async def generator():
        ultimo = None
        sin_dato = 0
        while True:
            estado = _ANALYSIS_PROGRESS.get(session_id)
            if estado is None:
                sin_dato += 1
                if sin_dato > 60:
                    yield "data: {}\n\n"
                    break
                await asyncio.sleep(1)
                continue
            sin_dato = 0
            if estado != ultimo:
                ultimo = estado
                yield f"data: {json.dumps(estado, ensure_ascii=False)}\n\n"
            if estado.get("porcentaje", 0) >= 100 or estado.get("error"):
                await asyncio.sleep(1)
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Folder preview before linking ────────────────────────────────────────────

@app.get("/api/folder-preview")
def preview_folder(path: str):
    folder_path = Path(path.strip())
    if not folder_path.exists():
        return JSONResponse({"exists": False, "path": str(folder_path)})

    info = _inspect_folder(folder_path)
    info["exists"] = True
    info["path"]   = str(folder_path)
    return JSONResponse(info)


@app.post("/api/sessions/{session_id}/link-folder")
def link_output_folder(session_id: str, body: dict = Body(...)):
    folder = body.get("output_folder", "").strip()
    if not folder:
        raise HTTPException(400, "output_folder requerido")

    folder_path = Path(folder)

    if not folder_path.is_absolute():
        _candidates = [
            HERE.parent / "Web_Proyecto" / folder,
            Path("/home/rrss/proyecto_web/Project_OLD/RRSS_version_stance/project_web/Web_Proyecto") / folder,
        ]
        for c in _candidates:
            if c.exists():
                folder_path = c.resolve()
                break

    if not folder_path.exists():
        raise HTTPException(404, f"Carpeta no encontrada: {folder_path}")

    info = _inspect_folder(folder_path)

    if info["lista_para_anotar"]:
        new_phase = "sentiment_review"
        aviso = None
    elif info["solo_scraping"]:
        new_phase = "analysis_pending"
        aviso = (
            "La carpeta tiene datos scrapeados pero el análisis LLM aún no se ha ejecutado. "
            f"Archivos encontrados: {', '.join(info['archivos_raw'])}. "
            "Ejecuta el análisis de sentimiento/topic primero desde el sistema principal."
        )
    else:
        new_phase = "analysis_pending"
        aviso = (
            "No se encontraron archivos de análisis en esta carpeta. "
            "Se esperan: *_analizado.csv, *_pilares.csv o dataset_maestro_lora.csv"
        )

    _update_session(session_id, {
        "output_folder": str(folder_path.resolve()),
        "phase": new_phase,
    })

    return {
        "ok":                True,
        "output_folder":     str(folder_path.resolve()),
        "lista_para_anotar": info["lista_para_anotar"],
        "solo_scraping":     info["solo_scraping"],
        "tiene_maestro":     info["tiene_maestro"],
        "tiene_analizado":   info["tiene_analizado"],
        "tiene_pilares":     info["tiene_pilares"],
        "tiene_raw":         info["tiene_raw_datasets"],
        "archivos_analizado": info["archivos_analizado"],
        "archivos_pilares":   info["archivos_pilares"],
        "archivos_raw":       info["archivos_raw"],
        "aviso":             aviso,
    }


# ═════════════════════════════════════════════════════════════════════════════
# RECORDS — reads CSVs, builds parent_lookup for full LLM-style context
# ═════════════════════════════════════════════════════════════════════════════


def _safe_str(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("nan", "none", "[removed]", "[deleted]", ""):
        return ""
    return s


def _read_csv_rows(csv_path: Path) -> tuple[list[dict], str]:
    """
    Read all rows from a CSV, auto-detecting ; vs , separator.
    Returns (list_of_dicts, separator).
    """
    with open(csv_path, encoding="utf-8") as f:
        first = f.readline()
    sep = ";" if ";" in first else ","
    with open(csv_path, encoding="utf-8") as f:
        reader = _csv.DictReader(f, delimiter=sep)
        rows = [dict(r) for r in reader]
    return rows, sep


def _infer_platform_from_row(row: dict, default_plat: str) -> str:
    plat = _safe_str(row.get("plataforma") or row.get("PLATAFORMA")).lower()
    if plat and plat != "otros":
        return plat
        
    # Inferir por columnas únicas
    if row.get("parent_uri") or row.get("uri"): return "bluesky"
    if row.get("id_video") or row.get("titulo_video"): return "youtube"
    if row.get("id_raiz") or row.get("id_propio"): return "reddit"
        
    # Inferir por fuente
    f = _safe_str(row.get("fuente") or row.get("FUENTE")).lower()
    if "reddit" in f or f.startswith("r/"): return "reddit"
    if "youtube" in f: return "youtube"
    if "bluesky" in f or "bsky" in f: return "bluesky"
        
    return _safe_str(default_plat).lower() or "otros"

def _build_parent_lookup_reddit(rows: list[dict]) -> dict:
    lookup: dict[str, dict] = {}
    for row in rows:
        tipo = _safe_str(row.get("tipo") or row.get("TIPO")).upper()
        if tipo == "POST":
            id_raiz = _safe_str(row.get("id_raiz") or row.get("ID_RAIZ") or row.get("id"))
            if id_raiz:
                lookup[id_raiz] = row
    return lookup

def _build_parent_lookup_bluesky(rows: list[dict]) -> dict:
    lookup: dict[str, dict] = {}
    for row in rows:
        tipo = _safe_str(row.get("tipo") or row.get("TIPO")).upper()
        if tipo in ("POST", "TWEET"):
            uri = _safe_str(row.get("uri") or row.get("URI"))
            if uri:
                lookup[uri] = row
    return lookup

def _build_parent_lookup_youtube(rows: list[dict]) -> dict:
    lookup: dict[str, dict] = {}
    for row in rows:
        tipo = _safe_str(row.get("tipo") or row.get("TIPO")).upper()
        if tipo == "VIDEO":
            id_video = _safe_str(row.get("id_video") or row.get("ID_VIDEO"))
            if id_video:
                lookup[id_video] = row
    return lookup

def _build_llm_context(
    row: dict,
    platform: str,
    parent_lookup_reddit: Optional[dict] = None,
    parent_lookup_bluesky: Optional[dict] = None,
    parent_lookup_youtube: Optional[dict] = None,
) -> dict:
    tipo = _safe_str(row.get("tipo") or row.get("TIPO") or "POST").upper()
    if tipo not in ("POST", "COMENTARIO", "COMMENT", "VIDEO", "TWEET", "REPLY"):
        tipo = "POST"
    if tipo in ("COMMENT", "REPLY"):
        tipo = "COMENTARIO"

    contenido = _safe_str(row.get("contenido") or row.get("CONTENIDO") or row.get("contenido_post"))
    
    fuente = ""
    titulo_padre = ""
    cuerpo_padre = ""
    descripcion = ""
    tweet_ant = ""
    transcripcion = ""

    es_comentario = (tipo == "COMENTARIO")

    # ── REDDIT ────────────────────────────────────────────────────────────
    if platform == "reddit":
        fuente = _safe_str(row.get("fuente") or row.get("FUENTE") or row.get("subreddit"))
        if es_comentario and parent_lookup_reddit:
            id_raiz = _safe_str(row.get("id_raiz") or row.get("ID_RAIZ"))
            padre = parent_lookup_reddit.get(id_raiz)
            if padre:
                titulo_padre = _safe_str(padre.get("post_title") or padre.get("TITULO") or padre.get("titulo"))
                # Extraemos el contenido del post padre
                cuerpo_padre = _safe_str(padre.get("contenido") or padre.get("CONTENIDO") or padre.get("post_selftext"))
                if not fuente:
                    fuente = _safe_str(padre.get("fuente") or padre.get("FUENTE") or padre.get("subreddit"))
        else:
            titulo_padre = _safe_str(row.get("post_title") or row.get("TITULO"))
            cuerpo_padre = _safe_str(row.get("post_selftext") or row.get("CUERPO"))

    # ── YOUTUBE ───────────────────────────────────────────────────────────
    elif platform == "youtube":
        fuente = _safe_str(row.get("canal") or row.get("CANAL") or row.get("usuario"))
        if es_comentario and parent_lookup_youtube:
            id_video = _safe_str(row.get("id_video") or row.get("ID_VIDEO"))
            padre = parent_lookup_youtube.get(id_video)
            if padre:
                titulo_padre = _safe_str(padre.get("titulo_video") or padre.get("TITULO") or padre.get("titulo"))
                # Extraemos el contenido del video padre
                descripcion = _safe_str(padre.get("contenido") or padre.get("CONTENIDO") or padre.get("descripcion_video"))
        else:
            titulo_padre = _safe_str(row.get("titulo_video") or row.get("TITULO") or row.get("titulo"))
            descripcion = _safe_str(row.get("contenido") or row.get("CONTENIDO") or row.get("descripcion_video"))

    # ── BLUESKY / TWITTER ─────────────────────────────────────────────────
    elif platform in ("bluesky", "twitter"):
        fuente = _safe_str(row.get("usuario") or row.get("USUARIO"))
        if es_comentario and parent_lookup_bluesky:
            parent_uri = _safe_str(row.get("parent_uri") or row.get("PARENT_URI"))
            padre = parent_lookup_bluesky.get(parent_uri)
            if padre:
                # Extraemos el contenido del post padre
                tweet_ant = _safe_str(padre.get("contenido") or padre.get("CONTENIDO"))
        if not tweet_ant:
            tweet_ant = _safe_str(row.get("BeforeContenido") or row.get("parent_content"))
        titulo_padre = _safe_str(row.get("post_title") or row.get("TITULO"))

    else:
        titulo_padre = _safe_str(row.get("TITULO") or row.get("post_title") or row.get("titulo_video"))
        cuerpo_padre = _safe_str(row.get("CUERPO") or row.get("post_selftext") or row.get("descripcion_video"))

    return {
        "tipo": tipo,
        "contenido": contenido,
        "fuente": fuente,
        "titulo_padre": titulo_padre,
        "cuerpo_padre": cuerpo_padre,
        "descripcion_padre": descripcion,
        "tweet_anterior": tweet_ant,
        "transcripcion_extracto": transcripcion,
        "idioma_ia": _safe_str(row.get("IDIOMA_IA") or row.get("idioma_ia")),
        "plataforma": platform,
    }

def _rows_to_records(
    rows: list[dict],
    platform: str,
    filter_platform: str,
    parent_lookup_reddit: Optional[dict] = None,
    parent_lookup_bluesky: Optional[dict] = None,
    parent_lookup_youtube: Optional[dict] = None,
) -> list[dict]:
    records = []
    for row in rows:
        plat = _infer_platform_from_row(row, platform)
        
        if filter_platform and filter_platform.lower() != plat:
            continue

        ctx = _build_llm_context(
            row, plat,
            parent_lookup_reddit=parent_lookup_reddit,
            parent_lookup_bluesky=parent_lookup_bluesky,
            parent_lookup_youtube=parent_lookup_youtube,
        )
        if not ctx["contenido"]:
            continue

        rec_id = (
            _safe_str(row.get("uri"))
            or _safe_str(row.get("id_raiz"))
            or _safe_str(row.get("id_propio"))
            or _safe_str(row.get("id"))
            or str(uuid.uuid4())
        )
        sent_raw = row.get("sentimiento") or row.get("SENTIMIENTO")
        records.append({
            "id":                    rec_id,
            "tipo":                  ctx["tipo"],
            "content":               ctx["contenido"],
            "platform":              plat,
            "fuente":                ctx["fuente"],
            "titulo_padre":          ctx["titulo_padre"],
            "cuerpo_padre":          ctx["cuerpo_padre"],
            "descripcion_padre":     ctx["descripcion_padre"],
            "tweet_anterior":        ctx["tweet_anterior"],
            "transcripcion_extracto": ctx["transcripcion_extracto"],
            "idioma_ia":             ctx["idioma_ia"],
            "sentiment_llm":         _safe_int(sent_raw) if sent_raw is not None else 2,
            "topic_llm":             _safe_str(row.get("topic") or row.get("TOPIC")),
            "fecha":                 _safe_str(
                row.get("fecha") or row.get("FECHA")
                or row.get("fecha_post") or row.get("fecha_comentario")
            ),
            "legitimacion":            _safe_int(row.get("legitimacion")),
            "efectividad":             _safe_int(row.get("efectividad")),
            "justicia_equidad":        _safe_int(row.get("justicia_equidad")),
            "confianza_institucional": _safe_int(row.get("confianza_institucional")),
        })
    return records

def _load_transcript_safe(path_str: str, max_chars: int = 1000) -> str:
    """
    Tries to read a transcript file from disk.
    Returns empty string on any error.
    """
    try:
        p = Path(path_str)
        if p.exists() and p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            return text[:max_chars]
    except Exception as exc:
        print(f"[annotation_api] No se pudo leer transcripción {path_str}: {exc}")
    return ""


def _rows_to_records(
    rows: list[dict],
    platform: str,
    filter_platform: str,
    parent_lookup_reddit: Optional[dict] = None,
    parent_lookup_bluesky: Optional[dict] = None,
    parent_lookup_youtube: Optional[dict] = None,
) -> list[dict]:
    """
    Convert raw CSV rows to annotation records, resolving parent context.
    Skips rows whose contenido is empty.
    """
    records = []
    for row in rows:
        plat = _safe_str(
            row.get("plataforma") or row.get("FUENTE") or platform
        ).lower()
        if filter_platform and filter_platform.lower() != plat:
            continue

        ctx = _build_llm_context(
            row, plat,
            parent_lookup_reddit=parent_lookup_reddit,
            parent_lookup_bluesky=parent_lookup_bluesky,
            parent_lookup_youtube=parent_lookup_youtube,
        )
        if not ctx["contenido"]:
            continue

        rec_id = (
            _safe_str(row.get("uri"))
            or _safe_str(row.get("id_raiz"))
            or _safe_str(row.get("id_propio"))
            or _safe_str(row.get("id"))
            or str(uuid.uuid4())
        )
        sent_raw = row.get("sentimiento") or row.get("SENTIMIENTO")
        records.append({
            "id":                    rec_id,
            # ── Context matching LLM input ──────────────────────────────
            "tipo":                  ctx["tipo"],
            "content":               ctx["contenido"],
            "platform":              plat,
            "fuente":                ctx["fuente"],
            "titulo_padre":          ctx["titulo_padre"],
            "cuerpo_padre":          ctx["cuerpo_padre"],
            "descripcion_padre":     ctx["descripcion_padre"],
            "tweet_anterior":        ctx["tweet_anterior"],
            "transcripcion_extracto": ctx["transcripcion_extracto"],
            "idioma_ia":             ctx["idioma_ia"],
            # ── Model outputs ───────────────────────────────────────────
            "sentiment_llm":         _safe_int(sent_raw) if sent_raw is not None else 2,
            "topic_llm":             _safe_str(row.get("topic") or row.get("TOPIC")),
            "fecha":                 _safe_str(
                row.get("fecha") or row.get("FECHA")
                or row.get("fecha_post") or row.get("fecha_comentario")
            ),
            # ── Pillar values ───────────────────────────────────────────
            "legitimacion":            _safe_int(row.get("legitimacion")),
            "efectividad":             _safe_int(row.get("efectividad")),
            "justicia_equidad":        _safe_int(row.get("justicia_equidad")),
            "confianza_institucional": _safe_int(row.get("confianza_institucional")),
        })
    return records


@app.get("/api/sessions/{session_id}/records")
def get_records(
    session_id: str,
    platform: str = "",
    limit: int = 50,
    offset: int = 0,
    skip_seen: bool = True,         # NEW: if True, exclude already-annotated records
):
    sessions = _load(SESSIONS_FILE)
    session  = next((x for x in sessions if x["id"] == session_id), None)
    if not session:
        raise HTTPException(404, "Session not found")

    records       = []
    output_folder = session.get("output_folder")
    source        = "none"

    # Load seen IDs once so we can filter them out
    seen_ids: set = set()
    if skip_seen:
        all_seen = _load_dict(SEEN_IDS_FILE)
        seen_ids = set(all_seen.get(session_id, []))

    if output_folder:
        folder = Path(output_folder)

        # ── 1. Maestro CSV ─────────────────────────────────────────────────
        csv_maestro = folder / "dataset_maestro_lora.csv"
        if csv_maestro.exists():
            try:
                rows, _ = _read_csv_rows(csv_maestro)
                plat_inferred = platform or "otros"

                # Build all three lookups in one pass over the rows
                lr = _build_parent_lookup_reddit(rows)
                lb = _build_parent_lookup_bluesky(rows)
                ly = _build_parent_lookup_youtube(rows)

                records = _rows_to_records(
                    rows, plat_inferred, platform,
                    parent_lookup_reddit=lr,
                    parent_lookup_bluesky=lb,
                    parent_lookup_youtube=ly,
                )
                if records:
                    source = "real_csv"
                    print(f"[annotation_api] {len(records)} registros desde dataset_maestro_lora.csv")
            except Exception as exc:
                print(f"[annotation_api] Error leyendo CSV Maestro: {exc}")

        # ── 2. *_analizado.csv fallback ────────────────────────────────────
        if not records:
            analizado_files = list(folder.glob("*_analizado.csv"))
            print(f"[annotation_api] Buscando *_analizado.csv en {folder}: {[f.name for f in analizado_files]}")

            for analizado_path in analizado_files:
                plat_inferred = _infer_platform_from_filename(analizado_path.name)
                print(f"{plat_inferred}")
                try:
                    rows, _ = _read_csv_rows(analizado_path)
                    lr = _build_parent_lookup_reddit(rows)
                    lb = _build_parent_lookup_bluesky(rows)
                    ly = _build_parent_lookup_youtube(rows)
                    records.extend(_rows_to_records(
                        rows, plat_inferred, platform,
                        parent_lookup_reddit=lr,
                        parent_lookup_bluesky=lb,
                        parent_lookup_youtube=ly,
                    ))
                except Exception as exc:
                    print(f"[annotation_api] Error leyendo {analizado_path.name}: {exc}")

            if records:
                source = "real_csv"
                print(f"[annotation_api] {len(records)} registros desde *_analizado.csv")

        # ── 3. *_pilares.csv fallback ──────────────────────────────────────
        if not records:
            pilares_files = list(folder.glob("*_pilares.csv"))
            for pilares_path in pilares_files:
                plat_inferred = _infer_platform_from_filename(pilares_path.name)
                print(f"{plat_inferred}")
                try:
                    rows, _ = _read_csv_rows(pilares_path)
                    lr = _build_parent_lookup_reddit(rows)
                    lb = _build_parent_lookup_bluesky(rows)
                    ly = _build_parent_lookup_youtube(rows)
                    records.extend(_rows_to_records(
                        rows, plat_inferred, platform,
                        parent_lookup_reddit=lr,
                        parent_lookup_bluesky=lb,
                        parent_lookup_youtube=ly,
                    ))
                except Exception as exc:
                    print(f"[annotation_api] Error leyendo {pilares_path.name}: {exc}")

            if records:
                source = "real_csv"
                print(f"[annotation_api] {len(records)} registros desde *_pilares.csv")

    # ── 4. Mock fallback ──────────────────────────────────────────────────
    if not records:
        print("[annotation_api] Sin datos reales → usando mock (10 registros)")
        records = _mock_records(10)
        source  = "mock"

    # ── Filter out already-seen records ────────────────────────────────────
    if seen_ids:
        unseen = [r for r in records if r["id"] not in seen_ids]
        total_seen_filtered = len(records) - len(unseen)
        if total_seen_filtered:
            print(f"[annotation_api] Filtrando {total_seen_filtered} registros ya anotados")
        records = unseen

    total = len(records)
    return {
        "records": records[offset: offset + limit],
        "total":   total,
        "offset":  offset,
        "limit":   limit,
        "source":  source,
        "total_seen_excluded": len(seen_ids),
    }


def _mock_records(n: int) -> list:
    sentiments = [1, -1, 0]
    topics     = ["mejora del servicio", "coste excesivo", "impacto ambiental"]
    contents   = [
        "La nueva medida parece bastante positiva para los ciudadanos de la zona.",
        "Esto es un desastre total, no sirve para nada y encima nos cuesta una fortuna.",
        "El ayuntamiento ha presentado el plan esta mañana en rueda de prensa.",
    ]
    pil_vals = [[1,-1,0,2],[-1,0,1,2],[0,1,-1,2],[2,-1,0,1]]
    tipos    = ["POST", "COMENTARIO", "POST", "VIDEO", "COMENTARIO"]
    titulos  = [
        "", "Plan de mejora del transporte público 2025",
        "", "Resumen de la rueda de prensa municipal",
        "Debate sobre la nueva ordenanza",
    ]
    cuerpos  = [
        "", "El concejal explicó los detalles del plan en la rueda de prensa de ayer.",
        "", "", "Texto completo del debate disponible en el enlace adjunto.",
    ]
    return [
        {
            "id":                      f"mock_{i}",
            "tipo":                    tipos[i % len(tipos)],
            "content":                 contents[i % len(contents)],
            "platform":                ["reddit", "bluesky", "youtube"][i % 3],
            "fuente":                  ["r/spain", "", "CanalAyto"][i % 3],
            "titulo_padre":            titulos[i % len(titulos)],
            "cuerpo_padre":            cuerpos[i % len(cuerpos)],
            "descripcion_padre":       "",
            "tweet_anterior":          "",
            "transcripcion_extracto":  "",
            "sentiment_llm":           sentiments[i % len(sentiments)],
            "topic_llm":               topics[i % len(topics)],
            "fecha":                   "2025-04-15",
            "idioma_ia":               "Castellano",
            "legitimacion":            pil_vals[i % 4][0],
            "efectividad":             pil_vals[i % 4][1],
            "justicia_equidad":        pil_vals[i % 4][2],
            "confianza_institucional": pil_vals[i % 4][3],
        }
        for i in range(n)
    ]


# ═════════════════════════════════════════════════════════════════════════════
# ANNOTATIONS
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/annotations/sentiment")
def save_sentiment(body: SentimentAnnotation):
    annotations = _load(SENTIMENT_FILE)
    record = {
        "id":              str(uuid.uuid4()),
        "annotation_type": "sentiment",
        **body.dict(),
        "timestamp":       datetime.now().isoformat(),
    }
    annotations.append(record)
    _save(SENTIMENT_FILE, annotations)
    return record


@app.post("/api/annotations/pillar")
def save_pillar(body: PillarAnnotation):
    annotations = _load(SENTIMENT_FILE)
    record = {
        "id":              str(uuid.uuid4()),
        "annotation_type": "pillar",
        **body.dict(),
        "timestamp":       datetime.now().isoformat(),
    }
    annotations.append(record)
    _save(SENTIMENT_FILE, annotations)
    return record


# ═════════════════════════════════════════════════════════════════════════════
# EXPORT LoRA (Alpaca JSONL)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/sessions/{session_id}/export/lora")
def export_lora(session_id: str, format: str = "jsonl"):
    sessions = _load(SESSIONS_FILE)
    s = next((x for x in sessions if x["id"] == session_id), None)
    if not s:
        raise HTTPException(404, "Session not found")

    kw_anns   = [x for x in _load(KEYWORDS_FILE) if x["session_id"] == session_id]
    sent_anns = [x for x in _load(SENTIMENT_FILE) if x.get("session_id") == session_id]

    tema       = s.get("tema", "")
    population = s.get("population_scope", "")
    records    = []

    for kw in kw_anns:
        if kw["type"] == "human_added":
            records.append({
                "instruction": f"Genera términos de búsqueda en redes sociales sobre: '{tema}' en '{population}'.",
                "input": "",
                "output": kw["keyword"],
                "metadata": {"type": "kw_addition", "reason": kw.get("reason",""), "annotator": kw["annotator_name"]},
            })
        elif kw["type"] == "llm_generated" and not kw["accepted"]:
            records.append({
                "instruction": f"¿Es adecuado este término para buscar contenido sobre '{tema}' en '{population}'?",
                "input": kw["keyword"],
                "output": f"NO. {kw.get('reason','Término demasiado genérico o fuera del tema.')}",
                "metadata": {"type": "kw_rejection", "annotator": kw["annotator_name"]},
            })

    sent_map = {1:"POSITIVO (a favor)", -1:"NEGATIVO (en contra)", 0:"NEUTRO", 2:"NO RELACIONADO"}
    for ann in sent_anns:
        if ann.get("annotation_type") == "sentiment":
            is_sent_corr  = ann.get("is_correction", False)
            is_topic_corr = ann.get("corrected_topic") != ann.get("original_topic")
            if is_sent_corr or is_topic_corr:
                motivos = []
                if is_sent_corr and ann.get("correction_reason"):
                    motivos.append(f"Sentimiento: {ann['correction_reason']}")
                if is_topic_corr and ann.get("topic_reason"):
                    motivos.append(f"Topic: {ann['topic_reason']}")
                motivo_final = " | ".join(motivos) if motivos else "Corrección del anotador humano."
                records.append({
                    "instruction": (
                        f"Clasifica el sentimiento y el topic de esta publicación de "
                        f"{ann.get('platform','redes sociales')} sobre el tema '{tema}'."
                    ),
                    "input":  ann.get("content",""),
                    "output": (
                        f"{sent_map.get(ann['corrected_sentiment'],'?')}. "
                        f"Topic: {ann.get('corrected_topic') or ann.get('original_topic','')}. "
                        f"Motivo: {motivo_final}"
                    ),
                    "metadata": {
                        "type":           "sentiment_topic_correction",
                        "original_sent":  ann["original_sentiment"],
                        "corrected_sent": ann["corrected_sentiment"],
                        "original_topic": ann.get("original_topic"),
                        "corrected_topic": ann.get("corrected_topic"),
                        "annotator":      ann["annotator_name"],
                    },
                })

    pil_map  = {1:"A FAVOR (+1)", -1:"EN CONTRA (-1)", 0:"NEUTRO (0)", 2:"NO APLICA"}
    pil_name = {
        "legitimacion":             "Legitimación sociopolítica",
        "efectividad":              "Efectividad percibida",
        "justicia_equidad":         "Justicia y equidad percibida",
        "confianza_institucional":  "Confianza institucional",
    }
    for ann in sent_anns:
        if ann.get("annotation_type") == "pillar" and ann.get("is_correction"):
            records.append({
                "instruction": (
                    f"Clasifica el pilar '{pil_name.get(ann.get('pillar',''),ann.get('pillar',''))}' "
                    f"de esta publicación en el contexto de '{tema}'."
                ),
                "input":  ann.get("content",""),
                "output": (
                    f"{pil_map.get(ann['corrected_value'],'?')}. "
                    f"Motivo: {ann.get('correction_reason','Corrección del anotador humano.')}"
                ),
                "metadata": {
                    "type":        "pillar_correction",
                    "pillar":      ann.get("pillar"),
                    "original_llm": ann["original_value"],
                    "corrected":   ann["corrected_value"],
                    "annotator":   ann["annotator_name"],
                },
            })

    breakdown = {
        "keyword_additions":     sum(1 for r in records if r.get("metadata",{}).get("type")=="kw_addition"),
        "keyword_rejections":    sum(1 for r in records if r.get("metadata",{}).get("type")=="kw_rejection"),
        "sentiment_corrections": sum(1 for r in records if r.get("metadata",{}).get("type")=="sentiment_topic_correction"),
        "pillar_corrections":    sum(1 for r in records if r.get("metadata",{}).get("type")=="pillar_correction"),
    }

    if format == "csv":
        out = io.StringIO()
        writer = _csv.DictWriter(out, fieldnames=["instruction","input","output"])
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k,"") for k in ["instruction","input","output"]})
        return JSONResponse({"data": out.getvalue(), "count": len(records), "format": "csv", "breakdown": breakdown})

    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    return JSONResponse({
        "data":      "\n".join(lines),
        "count":     len(records),
        "format":    "jsonl",
        "breakdown": breakdown,
    })


# ═════════════════════════════════════════════════════════════════════════════
# STATS + HEALTH
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/stats")
def global_stats():
    sessions = _load(SESSIONS_FILE)
    kw       = _load(KEYWORDS_FILE)
    sent     = _load(SENTIMENT_FILE)
    return {
        "total_sessions":              len(sessions),
        "total_keyword_annotations":   len(kw),
        "total_sentiment_annotations": len([x for x in sent if x.get("annotation_type") == "sentiment"]),
        "total_pillar_annotations":    len([x for x in sent if x.get("annotation_type") == "pillar"]),
        "corrections":                 len([x for x in sent if x.get("is_correction")]),
    }


@app.get("/api/health")
def health():
    return {
        "status":       "ok",
        "version":      "2.3.0",
        "data_dir":     str(DATA_DIR),
        "pipeline_src": CLEAN_SRC,
        "main_system":  MAIN_SYSTEM_URL,
        "logica_available": _LOGICA_AVAILABLE,
    }


# ═════════════════════════════════════════════════════════════════════════════
# PROXY: list completed analyses from 8006
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/main/analyses")
async def list_main_analyses():
    db_candidates = [
        HERE.parent / "Web_Proyecto" / "analysis_db.json",
        Path("/home/rrss/proyecto_web/Project_OLD/RRSS_version_stance/project_web/Web_Proyecto/analysis_db.json"),
        Path("analysis_db.json"),
    ]
    for db_path in db_candidates:
        if db_path.exists():
            try:
                db = json.loads(db_path.read_text(encoding="utf-8"))
                resultado = []
                for a in db:
                    if a.get("status") == "deleted":
                        continue
                    folder_raw = Path(a.get("output_folder",""))
                    if not folder_raw.is_absolute():
                        folder_raw = (db_path.parent / folder_raw).resolve()
                    info = _inspect_folder(folder_raw)
                    resultado.append({
                        "id":             a.get("id"),
                        "project_name":   a.get("project_name",""),
                        "tema":           a.get("tema",""),
                        "created_at":     a.get("created_at",""),
                        "output_folder":  str(folder_raw),
                        "tiene_datos":    info["lista_para_anotar"],
                        "solo_scraping":  info["solo_scraping"],
                        "archivos_analizado": info["archivos_analizado"],
                        "sources":        a.get("sources",[]),
                        "languages":      a.get("languages",[]),
                    })
                return JSONResponse(resultado)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse({"error": "analysis_db.json no encontrado"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8007, reload=True)