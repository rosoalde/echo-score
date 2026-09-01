"""
LoRA Annotation System — FastAPI backend v2.3
Fixes:
  - Added interactive Reviewer endpoints (/api/annotations/review).
  - Export LoRA now ignores annotations rejected by the reviewer.
"""

import csv as _csv
import io
import json
import sys
import uuid
import hashlib
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

from fastapi import FastAPI, HTTPException, Body, Query
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
    print(f"[annotation_api] AVISO: logica.py no disponible ({_e}).")

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


def _inspect_folder(folder_path: Path) -> dict:
    maestro      = folder_path / "dataset_maestro_lora.csv"
    analizado    = list(folder_path.glob("*_analizado.csv"))
    pilares      = list(folder_path.glob("*pilares*.csv"))
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
    desc_tema: str = ""
    population_scope: str = ""
    languages: List[str] = ["Castellano"]
    keywords: List[Dict[str, Any]] = []

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

class ReviewDecision(BaseModel):
    annotation_id: str
    annotation_type: str
    decision: str
    reviewer_name: str

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


# ═════════════════════════════════════════════════════════════════════════════
# FRONTEND
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html_path = HERE / "annotation_ui_v1.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>annotation_ui_v1.html not found</h1>"
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
        "desc_tema": body.desc_tema,
        "population_scope": body.population_scope,
        "languages": body.languages,
        "created_at": datetime.now().isoformat(),
        "phase": "keywords",
        "keyword_decisions": [],
        "keyword_additions": [],
        "generated_keywords": body.keywords,
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


@app.get("/api/sessions/{session_id}/annotated-ids")
def get_annotated_ids(session_id: str):
    sent_anns = _load(SENTIMENT_FILE)
    session_anns = [a for a in sent_anns if a.get("session_id") == session_id]
    
    sent_ids = [a["record_id"] for a in session_anns if a.get("annotation_type") == "sentiment"]
    pil_ids = [a["record_id"] for a in session_anns if a.get("annotation_type") == "pillar"]
    
    return {
        "sentiment": list(set(sent_ids)),
        "pillar": list(set(pil_ids))
    }

@app.get("/api/sessions/{session_id}/annotations")
def get_session_annotations(session_id: str):
    """Devuelve todas las anotaciones (correcciones) de una sesión para el Revisor"""
    kws = _load(KEYWORDS_FILE)
    sents = _load(SENTIMENT_FILE)
    
    reviewable = []
    
    # Keywords: solo las añadidas manualmente o las rechazadas
    for k in kws:
        if k.get("session_id") == session_id:
            if k.get("type") == "human_added" or not k.get("accepted"):
                k["review_category"] = "keyword"
                reviewable.append(k)
                
    # Sentimientos y Pilares: solo las que son correcciones
    for s in sents:
        if s.get("session_id") == session_id:
            if s.get("is_correction"):
                s["review_category"] = s.get("annotation_type")
                reviewable.append(s)
                
    return reviewable

@app.post("/api/annotations/review")
def save_review(body: ReviewDecision):
    """Guarda la decisión del revisor (accept/reject) sobre una anotación"""
    file_path = KEYWORDS_FILE if body.annotation_type == "keyword" else SENTIMENT_FILE
    data = _load(file_path)
    
    found = False
    for item in data:
        if item.get("id") == body.annotation_id:
            item["reviewer_decision"] = body.decision
            item["reviewer_name"] = body.reviewer_name
            found = True
            break
            
    if found:
        _save(file_path, data)
        return {"ok": True}
    raise HTTPException(404, "Anotación no encontrada")


# ═════════════════════════════════════════════════════════════════════════════
# KEYWORDS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/keywords/list")
def list_keyword_decisions(session_id: str = Query(...)):
    annotations = _load(KEYWORDS_FILE)
    session_annotations = [a for a in annotations if a.get("session_id") == session_id]
    return session_annotations


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
# FOLDER PREVIEW & LINKING
# ═════════════════════════════════════════════════════════════════════════════

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
            f"Archivos encontrados: {', '.join(info['archivos_raw'])}."
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
# RECORDS — reads real CSVs, returns full LLM-style context
# ═════════════════════════════════════════════════════════════════════════════

def _infer_platform_from_filename(filename: str) -> str:
    name = filename.lower()
    if "bluesky" in name:  return "bluesky"
    if "reddit"  in name:  return "reddit"
    if "youtube" in name:  return "youtube"
    if "twitter" in name:  return "twitter"
    return "otros"


def _safe_str(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("nan", "none", "[removed]", "[deleted]", ""):
        return ""
    return s


def _infer_platform_from_row(row_lower: dict, default_plat: str) -> str:
    plat = _safe_str(row_lower.get("plataforma")).lower()
    if plat: return plat
    if "parent_uri" in row_lower or "uri" in row_lower: return "bluesky"
    if "id_video" in row_lower or "titulo_video" in row_lower: return "youtube"
    if "id_raiz" in row_lower or "id_propio" in row_lower: return "reddit"
    f = _safe_str(row_lower.get("fuente")).lower()
    if "reddit" in f or f.startswith("r/"): return "reddit"
    if "youtube" in f: return "youtube"
    if "bluesky" in f or "bsky" in f: return "bluesky"
    return _safe_str(default_plat).lower()


def _generate_id(row_lower: dict) -> str:
    for col in ["uri", "id_propio", "id"]:
        val = _safe_str(row_lower.get(col))
        if val: return val
        
    content = _safe_str(row_lower.get("contenido") or row_lower.get("contenido_post"))
    fecha = _safe_str(row_lower.get("fecha") or row_lower.get("fecha_post") or "")
    usuario = _safe_str(row_lower.get("usuario") or row_lower.get("id_anonimo") or "")
    
    raw_str = f"{content}_{fecha}_{usuario}"
    return hashlib.md5(raw_str.encode("utf-8")).hexdigest()


def _build_parent_lookup_reddit(rows: list[dict]) -> dict:
    lookup = {}
    for row in rows:
        row_lower = {k.lower(): v for k, v in row.items()}
        tipo = _safe_str(row_lower.get("tipo")).upper()
        if tipo == "POST":
            id_raiz = _safe_str(row_lower.get("id_raiz") or row_lower.get("id_propio") or row_lower.get("id"))
            if id_raiz:
                lookup[id_raiz] = row_lower
    return lookup


def _build_parent_lookup_bluesky(rows: list[dict]) -> dict:
    lookup = {}
    for row in rows:
        row_lower = {k.lower(): v for k, v in row.items()}
        tipo = _safe_str(row_lower.get("tipo")).upper()
        if tipo in ("POST", "TWEET"):
            uri = _safe_str(row_lower.get("uri"))
            if uri:
                lookup[uri] = row_lower
    return lookup


def _build_parent_lookup_youtube(rows: list[dict]) -> dict:
    lookup = {}
    for row in rows:
        row_lower = {k.lower(): v for k, v in row.items()}
        tipo = _safe_str(row_lower.get("tipo")).upper()
        if tipo == "VIDEO":
            id_video = _safe_str(row_lower.get("id_video"))
            if id_video:
                lookup[id_video] = row_lower
    return lookup


def _build_llm_context(
    row_lower: dict, 
    platform: str,
    parent_lookup_reddit: dict = None,
    parent_lookup_bluesky: dict = None,
    parent_lookup_youtube: dict = None
) -> dict:
    tipo = _safe_str(row_lower.get("tipo") or "POST").upper()
    if tipo not in ("POST", "COMENTARIO", "COMMENT", "VIDEO", "TWEET", "REPLY"):
        tipo = "POST"
    if tipo in ("COMMENT", "REPLY"):
        tipo = "COMENTARIO"

    contenido = _safe_str(row_lower.get("contenido") or row_lower.get("contenido_post"))
    
    fuente = titulo = cuerpo = descripcion = tweet_ant = ""
    es_comentario = (tipo == "COMENTARIO")

    if platform == "reddit":
        fuente = _safe_str(row_lower.get("fuente") or row_lower.get("subreddit") or row_lower.get("search_keyword"))
        if es_comentario and parent_lookup_reddit:
            id_raiz = _safe_str(row_lower.get("id_raiz"))
            padre = parent_lookup_reddit.get(id_raiz)
            if padre:
                titulo = _safe_str(padre.get("post_title") or padre.get("titulo"))
                cuerpo = _safe_str(padre.get("contenido") or padre.get("post_selftext") or padre.get("cuerpo"))
                if not fuente:
                    fuente = _safe_str(padre.get("fuente") or padre.get("subreddit") or padre.get("search_keyword"))
        else:
            titulo = _safe_str(row_lower.get("post_title") or row_lower.get("titulo"))
            cuerpo = _safe_str(row_lower.get("post_selftext") or row_lower.get("cuerpo"))

    elif platform == "youtube":
        fuente = _safe_str(row_lower.get("canal"))
        if es_comentario and parent_lookup_youtube:
            id_video = _safe_str(row_lower.get("id_video"))
            padre = parent_lookup_youtube.get(id_video)
            if padre:
                titulo = _safe_str(padre.get("titulo_video") or padre.get("titulo"))
                descripcion = _safe_str(padre.get("contenido") or padre.get("descripcion_video") or padre.get("cuerpo"))
        else:
            titulo = _safe_str(row_lower.get("titulo_video") or row_lower.get("titulo"))
            descripcion = _safe_str(row_lower.get("contenido") or row_lower.get("descripcion_video") or row_lower.get("cuerpo"))

    elif platform in ("bluesky", "twitter"):
        fuente = _safe_str(row_lower.get("usuario"))
        if es_comentario and parent_lookup_bluesky:
            parent_uri = _safe_str(row_lower.get("parent_uri"))
            padre = parent_lookup_bluesky.get(parent_uri)
            if padre:
                tweet_ant = _safe_str(padre.get("contenido"))
        if not tweet_ant:
            tweet_ant = _safe_str(row_lower.get("beforecontenido") or row_lower.get("parent_content"))
        titulo = _safe_str(row_lower.get("post_title") or row_lower.get("titulo"))

    else:
        titulo = _safe_str(row_lower.get("titulo") or row_lower.get("post_title") or row_lower.get("titulo_video"))
        cuerpo = _safe_str(row_lower.get("cuerpo") or row_lower.get("post_selftext") or row_lower.get("descripcion_video"))

    return {
        "tipo":         tipo,
        "contenido":    contenido,
        "fuente":       fuente,
        "titulo_padre": titulo,
        "cuerpo_padre": cuerpo,
        "descripcion_padre": descripcion,
        "tweet_anterior":    tweet_ant,
        "idioma_ia":  _safe_str(row_lower.get("idioma_ia")),
        "plataforma":  platform,
    }


def _read_csv_rows(csv_path: Path) -> tuple[list[dict], str]:
    with open(csv_path, encoding="utf-8") as f:
        first = f.readline()
    sep = ";" if ";" in first else ","
    with open(csv_path, encoding="utf-8") as f:
        reader = _csv.DictReader(f, delimiter=sep)
        rows = [dict(r) for r in reader]
    return rows, sep


def _rows_to_records(
    rows: list[dict],
    platform: str,
    filter_platform: str,
    parent_lookup_reddit: dict = None,
    parent_lookup_bluesky: dict = None,
    parent_lookup_youtube: dict = None,
) -> list[dict]:
    records = []
    for row in rows:
        row_lower = {k.lower(): v for k, v in row.items()}
        
        plat = _infer_platform_from_row(row_lower, platform)
        if filter_platform and filter_platform.lower() != plat:
            continue

        ctx = _build_llm_context(
            row_lower, plat,
            parent_lookup_reddit=parent_lookup_reddit,
            parent_lookup_bluesky=parent_lookup_bluesky,
            parent_lookup_youtube=parent_lookup_youtube,
        )
        if not ctx["contenido"]:
            continue

        rec_id = _generate_id(row_lower)
        sent_raw = row_lower.get("sentimiento")
        
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
            "idioma_ia":             ctx["idioma_ia"],
            "sentiment_llm":         _safe_int(sent_raw) if sent_raw is not None else 2,
            "topic_llm":             _safe_str(row_lower.get("topic")),
            "fecha":                 _safe_str(
                row_lower.get("fecha") or row_lower.get("fecha_post") or row_lower.get("fecha_comentario")
            ),
            "legitimacion":            _safe_int(row_lower.get("legitimacion")),
            "efectividad":             _safe_int(row_lower.get("efectividad")),
            "justicia_equidad":        _safe_int(row_lower.get("justicia_equidad")),
            "confianza_institucional": _safe_int(row_lower.get("confianza_institucional")),
        })
    return records


@app.get("/api/sessions/{session_id}/records")
def get_records(
    session_id: str,
    platform: str = "",
    limit: int = 5000,
    offset: int = 0,
):
    sessions = _load(SESSIONS_FILE)
    session  = next((x for x in sessions if x["id"] == session_id), None)
    if not session:
        raise HTTPException(404, "Session not found")

    records       = []
    output_folder = session.get("output_folder")
    source        = "none"

    if output_folder:
        folder = Path(output_folder)

        # ── 1. *_pilares.csv (El más completo, priorizado) ─────────────────
        pilares_files = list(folder.glob("*pilares*.csv"))
        if pilares_files:
            for pilares_path in pilares_files:
                plat_inferred = _infer_platform_from_filename(pilares_path.name)
                try:
                    rows, _ = _read_csv_rows(pilares_path)
                    lr = _build_parent_lookup_reddit(rows)
                    lb = _build_parent_lookup_bluesky(rows)
                    ly = _build_parent_lookup_youtube(rows)
                    records.extend(_rows_to_records(rows, plat_inferred, platform, lr, lb, ly))
                except Exception as exc:
                    print(f"[annotation_api] Error leyendo {pilares_path.name}: {exc}")
            if records:
                source = "real_csv"
                print(f"[annotation_api] {len(records)} registros desde *pilares*.csv")

        # ── 2. *_analizado.csv fallback ────────────────────────────────────
        if not records:
            analizado_files = list(folder.glob("*_analizado.csv"))
            for analizado_path in analizado_files:
                plat_inferred = _infer_platform_from_filename(analizado_path.name)
                try:
                    rows, _ = _read_csv_rows(analizado_path)
                    lr = _build_parent_lookup_reddit(rows)
                    lb = _build_parent_lookup_bluesky(rows)
                    ly = _build_parent_lookup_youtube(rows)
                    records.extend(_rows_to_records(rows, plat_inferred, platform, lr, lb, ly))
                except Exception as exc:
                    print(f"[annotation_api] Error leyendo {analizado_path.name}: {exc}")

            if records:
                source = "real_csv"
                print(f"[annotation_api] {len(records)} registros desde *_analizado.csv")

        # ── 3. Maestro CSV fallback ────────────────────────────────────────
        if not records:
            csv_maestro = folder / "dataset_maestro_lora.csv"
            if csv_maestro.exists():
                try:
                    rows, _ = _read_csv_rows(csv_maestro)
                    plat_inferred = platform or "otros"
                    lr = _build_parent_lookup_reddit(rows)
                    lb = _build_parent_lookup_bluesky(rows)
                    ly = _build_parent_lookup_youtube(rows)
                    records = _rows_to_records(rows, plat_inferred, platform, lr, lb, ly)
                    if records:
                        source = "real_csv"
                        print(f"[annotation_api] {len(records)} registros desde dataset_maestro_lora.csv")
                except Exception as exc:
                    print(f"[annotation_api] Error leyendo CSV Maestro: {exc}")

    # ── 4. Mock fallback ──────────────────────────────────────────────────
    if not records:
        print("[annotation_api] Sin datos reales → usando mock (10 registros)")
        records = _mock_records(10)
        source  = "mock"

    total = len(records)
    return {
        "records": records[offset: offset + limit],
        "total":   total,
        "offset":  offset,
        "limit":   limit,
        "source":  source,
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
    return [
        {
            "id":                      f"mock_{i}",
            "tipo":                    tipos[i % len(tipos)],
            "content":                 contents[i % len(contents)],
            "platform":                ["reddit", "bluesky", "youtube"][i % 3],
            "fuente":                  ["r/spain", "", "CanalAyto"][i % 3],
            "titulo_padre":            titulos[i % len(titulos)],
            "cuerpo_padre":            "Texto del post padre de ejemplo." if tipos[i % len(tipos)] == "COMENTARIO" else "",
            "descripcion_padre":       "",
            "tweet_anterior":          "",
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
# EXPORT
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
        # Ignorar si el revisor lo rechazó
        if kw.get("reviewer_decision") == "reject":
            continue
            
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
        # Ignorar si el revisor lo rechazó
        if ann.get("reviewer_decision") == "reject":
            continue
            
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
        if ann.get("reviewer_decision") == "reject":
            continue
            
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
                    
                    # Parsear keywords si vienen como string JSON
                    kw_raw = a.get("keywords", [])
                    if isinstance(kw_raw, str):
                        try:
                            kw_parsed = json.loads(kw_raw)
                        except:
                            kw_parsed = []
                    else:
                        kw_parsed = kw_raw

                    resultado.append({
                        "id":             a.get("id"),
                        "project_name":   a.get("project_name",""),
                        "tema":           a.get("tema",""),
                        "desc_tema":      a.get("desc_tema",""),
                        "population_scope": a.get("population_scope",""),
                        "created_at":     a.get("created_at",""),
                        "output_folder":  str(folder_raw),
                        "tiene_datos":    info["lista_para_anotar"],
                        "solo_scraping":  info["solo_scraping"],
                        "archivos_analizado": info["archivos_analizado"],
                        "sources":        a.get("sources",[]),
                        "languages":      a.get("languages",[]),
                        "keywords":       kw_parsed,
                    })
                return JSONResponse(resultado)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse({"error": "analysis_db.json no encontrado"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8007, reload=True)
