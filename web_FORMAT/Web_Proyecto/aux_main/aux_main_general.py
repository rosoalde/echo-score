import io
import os
import json
import math
import csv
import base64
import asyncio
import traceback
import re as _re
import shutil
import nltk
import zipfile

from pathlib import Path
from datetime import datetime
from collections import Counter as _Counter, defaultdict as _defaultdict

import pandas as pd

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from bbdd.database import SessionLocal
from bbdd.models_all import Analysis
from bbdd.response.user_response import UserResponse
from seguridad.audit_service import AuditService, EventType, EventResult, ActorType

from generate_report import build_analysis_pdf
from logica_FORMAT import (
    recalcular_filas_incompletas, backend_analisis, generar_keywords_con_ia,
    calcular_dashboard_base, ejecutar_indicador_aceptacion, read_indicador_aceptacion, asegurar_nubes_dashboard,
    recalcular_aceptacion_filtrada, filtrar_y_recalcular_dashboard,
    #ejecutar_scoreop_desde_logica, cargar_datos_para_reporte, generar_excel_sentimiento,
    construir_nube_bigramas, construir_nube_topicos,
    construir_grafo_bipartito, clean_types, _calcular_topics_df, _cargar_analizado_csvs,
    construir_nube_unificada_v2, construir_grafo_bipartito_v2,
)

from .classes_main import FilterRequest


BASE_DIR = Path("../")

# =============================================================================
# NLTK + stopwords (usadas por helpers de grafo)
# =============================================================================

_NLTK_DATA_PATH = "nltk_data"
os.makedirs(_NLTK_DATA_PATH, exist_ok=True)
if _NLTK_DATA_PATH not in nltk.data.path:
    nltk.data.path.append(_NLTK_DATA_PATH)
try:
    nltk.data.find("corpora/stopwords")
except LookupError:
    nltk.download("stopwords", download_dir=_NLTK_DATA_PATH)

try:
    from nltk.corpus import stopwords as _nltk_sw
    _NLTK_STOPS_ES = set(_nltk_sw.words("spanish"))
    _NLTK_STOPS_EN = set(_nltk_sw.words("english"))
except Exception:
    _NLTK_STOPS_ES = set()
    _NLTK_STOPS_EN = set()

try:
    import simplemma as _simplemma
    _SIMPLEMMA_LANGS = ("es", "en", "ca", "pt", "fr", "it")
    _SIMPLEMMA_OK = True
except ImportError:
    _SIMPLEMMA_OK = False

_STOPS_MANUAL = {
    "para", "como", "pero", "porque", "sobre", "desde", "hasta", "esto", "esta", "este", "estos", "estas",
    "tiene", "hace", "donde", "cuando", "todo", "todos", "todas", "solo", "bien", "muy", "más", "que", "con",
    "una", "por", "del", "los", "las", "les", "nos", "hay", "sus", "sin", "ser", "han", "sido", "está", "estan",
    "también", "aunque", "puede", "después", "antes", "entre", "mismo", "cada", "otro", "otra",
    "also", "just", "that", "this", "with", "from", "have", "been", "they", "will", "when", "said",
    "were", "more", "than", "some", "what", "about", "would", "could", "their", "there", "which",
    "https", "http", "twitter", "reddit", "bluesky", "youtube",
    "comentario", "comment", "reply", "share", "post", "video", "foto",
}
_STOPS_GRAFO = _STOPS_MANUAL | _NLTK_STOPS_ES | _NLTK_STOPS_EN

try:
    import unidecode as _ud_mod
    _STOPS_GRAFO_NORM = {_ud_mod.unidecode(w) for w in _STOPS_GRAFO}
    _HAS_UNIDECODE = True
except ImportError:
    _STOPS_GRAFO_NORM = _STOPS_GRAFO
    _HAS_UNIDECODE = False


# =============================================================================
# Helpers internos de grafo
# =============================================================================

def _top_words_grafo(texto: str, n: int = 8) -> list:
    texto = str(texto).lower()
    texto = _re.sub(r"http\S+|[@#]\S+", "", texto)
    texto = _re.sub(r"[^\w\sáéíóúüñàèìòùâêîôûäëïöüãõç]", " ", texto)
    texto = _re.sub(r"_+|\s+", " ", texto).strip()
    tokens = [w for w in texto.split() if len(w) > 2]
    if _SIMPLEMMA_OK:
        lemmatized = []
        for w in tokens:
            try:
                lemmatized.append(_simplemma.lemmatize(w, lang=_SIMPLEMMA_LANGS))
            except Exception:
                lemmatized.append(w)
        tokens = lemmatized
    if _HAS_UNIDECODE:
        filtered = [w for w in tokens if len(w) > 3 and w not in _STOPS_GRAFO and _ud_mod.unidecode(w) not in _STOPS_GRAFO_NORM]
    else:
        filtered = [w for w in tokens if len(w) > 3 and w not in _STOPS_GRAFO]
    return [w for w, _ in _Counter(filtered).most_common(n)]


def _top_words_desde_df(df_subset, n: int = 8) -> list:
    word_freq = _Counter()
    word_scores = {}
    col_texto = None
    for alias in ("contenido_post", "contenido", "content", "body"):
        if alias in df_subset.columns:
            col_texto = alias
            break
    if col_texto is None:
        return []
    for _, row in df_subset.iterrows():
        texto_raw = str(row.get(col_texto, "") or "").lower()
        if len(texto_raw) < 5:
            continue
        if "ScoreOP_pct" in df_subset.columns:
            peso = float(row.get("ScoreOP_pct", 50) or 50)
        elif "sentimiento" in df_subset.columns:
            s = float(row.get("sentimiento", 0) or 0)
            peso = (s + 1.0) / 2.0 * 100.0
        else:
            peso = 50.0
        texto = _re.sub(r"http\S+|[@#]\S+", "", texto_raw)
        texto = _re.sub(r"[^\w\sáéíóúüñàèìòùâêîôûäëïöüãõç]", " ", texto)
        texto = _re.sub(r"_+|\s+", " ", texto).strip()
        tokens = [w for w in texto.split() if len(w) > 2]
        if _SIMPLEMMA_OK:
            lematized = []
            for w in tokens:
                try:
                    lematized.append(_simplemma.lemmatize(w, lang=_SIMPLEMMA_LANGS))
                except Exception:
                    lematized.append(w)
            tokens = lematized
        if _HAS_UNIDECODE:
            tokens = [w for w in tokens if len(w) > 3 and w not in _STOPS_GRAFO and _ud_mod.unidecode(w) not in _STOPS_GRAFO_NORM]
        else:
            tokens = [w for w in tokens if len(w) > 3 and w not in _STOPS_GRAFO]
        for t in tokens:
            word_freq[t] += 1
            word_scores.setdefault(t, []).append(peso)
    min_ap = 2
    candidates = {
        w: (cnt, abs(sum(word_scores[w]) / len(word_scores[w]) - 50.0))
        for w, cnt in word_freq.items()
        if cnt >= min_ap and w in word_scores
    }
    top = sorted(candidates.items(), key=lambda x: (x[1][0], x[1][1]), reverse=True)
    return [w for w, _ in top[:n]]


def _scoreop_color_cat(pct: float) -> str:
    if pct > 70: return "muy_positivo"
    if pct > 55: return "positivo"
    if pct > 45: return "neutro"
    if pct > 30: return "negativo"
    return "muy_negativo"


def _scoreop_pct_map_from_csv(folder: Path) -> dict:
    scoreop_csv = Path(folder) / "scoreop_consolidado.csv"
    if not scoreop_csv.exists():
        return {}
    try:
        with open(scoreop_csv, "r", encoding="utf-8") as fh:
            sep = ";" if ";" in fh.readline() else ","
        df_sc = pd.read_csv(scoreop_csv, sep=sep, encoding="utf-8", on_bad_lines="skip")
        if "ScoreOP_pct" in df_sc.columns and "topic" in df_sc.columns:
            return df_sc.groupby("topic")["ScoreOP_pct"].mean().round(2).to_dict()
    except Exception as exc:
        print(f"⚠️ scoreop map error: {exc}")
    return {}


def _build_grafo_topic(df_all, scoreop_pct_map: dict, keywords: list = None) -> dict:
    TIPOS_POST = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}
    TIPOS_COM  = {"COMENTARIO", "COMMENT", "REPLY", "RESPUESTA"}
    posts       = df_all[df_all["tipo_norm"].isin(TIPOS_POST) & (df_all["sent_num"] != 2)]
    comentarios = df_all[df_all["tipo_norm"].isin(TIPOS_COM)  & (df_all["sent_num"] != 2)]
    if posts.empty:
        posts = df_all.copy()
        comentarios = pd.DataFrame(columns=df_all.columns)

    topic_nodes = {}
    for topic, grp in posts.groupby("topic"):
        if not topic or topic in ("sin topic", "no relacionado", "otros", ""):
            continue
        pct = float(scoreop_pct_map.get(topic, 50.0))
        topic_nodes[topic] = {
            "id": f"topic__{topic}", "label": topic, "type": "topic",
            "volumen": int(len(grp)), "scoreop_pct": round(pct, 1),
            "scoreop_cat": _scoreop_color_cat(pct),
            "plataformas": grp["plataforma"].dropna().unique().tolist(),
            "top_words": _top_words_desde_df(grp, n=8),
        }

    subtopic_nodes = {}
    for subtopic, grp in comentarios.groupby("topic"):
        if not subtopic or subtopic in ("sin topic", "no relacionado", "otros", ""):
            continue
        sents = grp["sent_num"].tolist()
        sent_med = sum(sents) / len(sents) if sents else 0
        pct_sub = round((sent_med + 1) / 2 * 100, 1)
        subtopic_nodes[subtopic] = {
            "id": f"subtopic__{subtopic}", "label": subtopic, "type": "subtopic",
            "volumen": int(len(grp)), "scoreop_pct": pct_sub,
            "scoreop_cat": _scoreop_color_cat(pct_sub), "sent_medio": round(sent_med, 3),
            "top_words": _top_words_desde_df(grp, n=8),
        }

    edges_ts: dict = {}
    has_anchors = "_anchor_parent" in comentarios.columns and "_anchor_own" in posts.columns
    if has_anchors and not comentarios.empty:
        post_topic_map = dict(zip(posts["_anchor_own"].astype(str), posts["topic"].astype(str)))
        for _, row in comentarios.iterrows():
            parent_id     = str(row.get("_anchor_parent", ""))
            topic_padre   = post_topic_map.get(parent_id)
            subtopic_hijo = str(row.get("topic", ""))
            if not topic_padre or not subtopic_hijo or topic_padre == subtopic_hijo:
                continue
            key = (topic_padre, subtopic_hijo)
            if key not in edges_ts:
                edges_ts[key] = {"weight": 0, "sent_sum": 0.0, "n": 0}
            edges_ts[key]["weight"]   += 1
            edges_ts[key]["sent_sum"] += float(row.get("sent_num", 0))
            edges_ts[key]["n"]        += 1
    else:
        # Fallback: solapamiento de nombres
        for subtopic in subtopic_nodes:
            for tp in topic_nodes:
                if subtopic in tp or tp in subtopic:
                    key = (tp, subtopic)
                    if key not in edges_ts:
                        edges_ts[key] = {"weight": 1, "sent_sum": 0.0, "n": 1}

    edges_topic_subtopic = []
    for (src, tgt), data in edges_ts.items():
        if src == tgt:
            continue
        avg_sent = data["sent_sum"] / data["n"] if data["n"] > 0 else 0
        pct_e = round((avg_sent + 1) / 2 * 100, 1)
        edges_topic_subtopic.append({
            "source": f"topic__{src}", "target": f"subtopic__{tgt}",
            "weight": data["weight"], "type": "topic_subtopic",
            "avg_scoreop_pct": pct_e, "scoreop_cat": _scoreop_color_cat(pct_e),
        })

    edges_tt = []
    if has_anchors and not posts.empty:
        hilo_topics = _defaultdict(set)
        for _, row in posts.iterrows():
            hid = str(row.get("_anchor_own", ""))
            t   = str(row.get("topic", ""))
            if t and t not in ("sin topic", ""):
                hilo_topics[hid].add(t)
        pair_count = _Counter()
        for ts in hilo_topics.values():
            tlist = sorted(ts)
            for i in range(len(tlist)):
                for j in range(i + 1, len(tlist)):
                    pair_count[(tlist[i], tlist[j])] += 1
        for (t1, t2), cnt in pair_count.most_common(20):
            if t1 in topic_nodes and t2 in topic_nodes and cnt >= 2:
                edges_tt.append({
                    "source": f"topic__{t1}", "target": f"topic__{t2}",
                    "weight": cnt, "type": "topic_topic", "avg_scoreop_pct": None,
                })

    # Nube global (excluyendo keywords del análisis)
    _stops_nube = _STOPS_GRAFO.copy()
    if keywords:
        for _kw in keywords:
            _kw_clean = _re.sub(r"[^\w\sáéíóúüñàèìòùâêîôûäëïöüãõç]", " ", str(_kw).lower()).strip()
            for _tok in _kw_clean.split():
                if len(_tok) > 2:
                    _stops_nube.add(_tok)
                    if _HAS_UNIDECODE:
                        _stops_nube.add(_ud_mod.unidecode(_tok))

    wcount = _Counter()
    wsent  = _defaultdict(list)
    wtopics = _defaultdict(set)
    for _, row in df_all.iterrows():
        contenido = str(row.get("contenido", "") or "")
        topic     = str(row.get("topic", ""))
        sent      = float(row.get("sent_num", 0))
        texto = contenido.lower()
        texto = _re.sub(r"http\S+|[@#]\S+", "", texto)
        texto = _re.sub(r"[^\w\sáéíóúüñàèìòùâêîôûäëïöüãõç]", " ", texto)
        texto = _re.sub(r"_+|\s+", " ", texto).strip()
        tokens = [w for w in texto.split() if len(w) > 2]
        if _SIMPLEMMA_OK:
            lems = []
            for w in tokens:
                try:
                    lems.append(_simplemma.lemmatize(w, lang=_SIMPLEMMA_LANGS))
                except Exception:
                    lems.append(w)
            tokens = lems
        if _HAS_UNIDECODE:
            tokens = [w for w in tokens if len(w) > 3 and w not in _stops_nube and _ud_mod.unidecode(w) not in _stops_nube]
        else:
            tokens = [w for w in tokens if len(w) > 3 and w not in _stops_nube]
        for w in tokens[:20]:
            wcount[w] += 1
            wsent[w].append(sent)
            wtopics[w].add(topic)

    words = [
        {"text": w, "value": int(c), "sentiment": round(sum(wsent[w]) / len(wsent[w]), 3) if wsent[w] else 0, "topics": list(wtopics[w])}
        for w, c in wcount.most_common(80) if c >= 2
    ]

    all_edges = edges_topic_subtopic + edges_tt
    adj: dict = {}
    for e in all_edges:
        adj.setdefault(e["source"], []).append(e["target"])
        adj.setdefault(e["target"], []).append(e["source"])

    return {
        "nivel": "topic",
        "nodes": list(topic_nodes.values()) + list(subtopic_nodes.values()),
        "edges": all_edges, "words": words, "adj": adj,
        "meta": {
            "total_posts": int(len(posts)), "total_comentarios_activos": int(len(comentarios)),
            "n_topics": len(topic_nodes), "n_subtopics": len(subtopic_nodes),
        },
    }


def _build_grafo_usuario(df_all, scoreop_pct_map: dict) -> dict:
    TIPOS_POST = {"POST", "VIDEO", "VÍDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN"}
    TIPOS_COM  = {"COMENTARIO", "COMMENT", "REPLY", "RESPUESTA"}
    posts       = df_all[df_all["tipo_norm"].isin(TIPOS_POST)]
    comentarios = df_all[df_all["tipo_norm"].isin(TIPOS_COM)]

    def _hash_short(id_anon: str) -> str:
        return str(id_anon).strip()[:5].upper()

    nodos_raw: dict = {}

    def _ensure(uid: str, plat: str):
        if uid not in nodos_raw:
            nodos_raw[uid] = {
                "id": uid, "label": _hash_short(uid), "type": "usuario",
                "plataforma": plat, "n_posts": 0, "n_comentarios": 0,
                "sent_list": [], "topics": set(), "contenido_acum": "",
            }

    for _, row in posts.iterrows():
        uid = str(row.get("id_anonimo", "")).strip()
        plat = str(row.get("plataforma", ""))
        if not uid or uid == "DESCONOCIDO":
            continue
        _ensure(uid, plat)
        nodos_raw[uid]["n_posts"] += 1
        nodos_raw[uid]["sent_list"].append(float(row.get("sent_num", 0)))
        nodos_raw[uid]["topics"].add(str(row.get("topic", "")))
        nodos_raw[uid]["contenido_acum"] += " " + str(row.get("contenido", ""))

    for _, row in comentarios.iterrows():
        uid = str(row.get("id_anonimo", "")).strip()
        plat = str(row.get("plataforma", ""))
        if not uid or uid == "DESCONOCIDO":
            continue
        _ensure(uid, plat)
        nodos_raw[uid]["n_comentarios"] += 1
        nodos_raw[uid]["sent_list"].append(float(row.get("sent_num", 0)))
        nodos_raw[uid]["topics"].add(str(row.get("topic", "")))
        nodos_raw[uid]["contenido_acum"] += " " + str(row.get("contenido", ""))

    nodes_payload = []
    for uid, n in nodos_raw.items():
        sents = n["sent_list"]
        sent_med = sum(sents) / len(sents) if sents else 0
        pct = round((sent_med + 1) / 2 * 100, 1)
        n_total = n["n_posts"] + n["n_comentarios"]
        nodes_payload.append({
            "id": uid, "label": n["label"], "type": "usuario", "plataforma": n["plataforma"],
            "n_posts": n["n_posts"], "n_comentarios": n["n_comentarios"],
            "size": max(6, min(40, 6 + (n_total ** 0.4) * 3)),
            "scoreop_pct": pct, "scoreop_cat": _scoreop_color_cat(pct),
            "topics": list(n["topics"] - {"", "sin topic"}),
            "top_words": _top_words_grafo(n["contenido_acum"], n=8),
        })

    edges_map: dict = {}
    has_anchors = "_anchor_parent" in comentarios.columns and "_anchor_own" in posts.columns
    if has_anchors:
        post_author_map = dict(zip(posts["_anchor_own"].astype(str), posts["id_anonimo"].astype(str)))
        for _, row in comentarios.iterrows():
            src    = str(row.get("id_anonimo", "")).strip()
            parent = str(row.get("_anchor_parent", ""))
            tgt    = post_author_map.get(parent, "")
            if not src or not tgt or src == tgt or src == "DESCONOCIDO":
                continue
            key = f"{src}→{tgt}"
            if key not in edges_map:
                edges_map[key] = {"source": src, "target": tgt, "weight": 0, "sent_sum": 0.0, "n": 0, "type": "comentario"}
            edges_map[key]["weight"]   += 1
            edges_map[key]["sent_sum"] += float(row.get("sent_num", 0))
            edges_map[key]["n"]        += 1

    edges_payload = []
    for e in edges_map.values():
        avg_sent = e["sent_sum"] / e["n"] if e["n"] > 0 else 0
        pct_e = round((avg_sent + 1) / 2 * 100, 1)
        edges_payload.append({
            "source": e["source"], "target": e["target"], "weight": e["weight"],
            "type": e["type"], "avg_scoreop_pct": pct_e, "scoreop_cat": _scoreop_color_cat(pct_e),
        })

    wcount = _Counter()
    wsent  = _defaultdict(list)
    wusers = _defaultdict(set)
    for n in nodos_raw.values():
        uid = n["id"]
        for w in _top_words_grafo(n["contenido_acum"], n=20):
            wcount[w] += 1
            wsent[w].extend(n["sent_list"][:3])
            wusers[w].add(uid)

    words_payload = [
        {"text": w, "value": int(c), "sentiment": round(sum(wsent[w]) / len(wsent[w]), 3) if wsent[w] else 0, "user_ids": list(wusers[w])}
        for w, c in wcount.most_common(80) if c >= 2
    ]
    adj: dict = {}
    for e in edges_payload:
        adj.setdefault(e["source"], []).append(e["target"])
        adj.setdefault(e["target"], []).append(e["source"])

    return {
        "nivel": "usuario", "nodes": nodes_payload, "edges": edges_payload,
        "words": words_payload, "adj": adj,
        "meta": {
            "total_usuarios": len(nodes_payload), "total_interacciones": len(edges_payload),
            "aviso": "Los nodos muestran solo los primeros 5 caracteres del id_anonimo.",
        },
    }


def _extract_keywords_from_analysis(analysis) -> list:
    """Extrae la lista de keywords desde el objeto Analysis (config JSON)."""
    cfg = analysis.analysis_config or {}
    kw_raw = cfg.get("keywords", [])
    if isinstance(kw_raw, list) and kw_raw and isinstance(kw_raw[0], dict):
        return [k.get("keyword", "") for k in kw_raw if k.get("keyword")]
    elif isinstance(kw_raw, str):
        try:
            parsed = json.loads(kw_raw)
            return [k.get("keyword", k) if isinstance(k, dict) else str(k) for k in parsed]
        except Exception:
            return [kw_raw]
    return [str(k) for k in (kw_raw or []) if k]


def _apply_geo_filter(df: pd.DataFrame, geo: str) -> pd.DataFrame:
    """Filtra el DataFrame por términos geográficos sobre la columna 'contenido'."""
    geo_terms = [t.strip() for t in geo.split(",") if t.strip()] if geo else []
    if not geo_terms:
        return df
    col_texto = "contenido" if "contenido" in df.columns else None
    if not col_texto:
        return df
    patron = "|".join(_re.escape(t) for t in geo_terms)
    mask = df[col_texto].fillna("").str.contains(patron, case=False, na=False)
    filtered = df[mask]
    return filtered if not filtered.empty else df


# =============================================================================
# aux_mis_analisis
# =============================================================================

def aux_mis_analisis(user: UserResponse):
    """Lee análisis desde el JSON legacy (usado por analizar_datasets)."""
    from temp_json import sync_analysis_db

    db = sync_analysis_db()
    if not db:
        return []

    user_analyses = []
    for a in db:
        if a.get("username") != user.username or a.get("status") == "deleted":
            continue
        created_raw = a.get("created_at")
        try:
            created_dt = datetime.fromisoformat(created_raw)
            created_str = created_dt.strftime("%d-%m-%Y %H:%M")
        except Exception:
            created_dt = datetime.min
            created_str = "Fecha desconocida"

        folder_name = Path(a.get("output_folder")).name if a.get("output_folder") else a.get("project_name")
        user_analyses.append({
            "id":           a.get("id"),
            "project_name": folder_name,
            "created_at":   created_str,
            "order_by":     created_dt,
            "status":       a.get("status", "completed"),
            "progress":     100 if a.get("status") == "completed" else 0,
            "download_url": f"/analisis/{a.get('id')}/download",
        })

    return sorted(user_analyses, key=lambda x: x["order_by"], reverse=True)


# =============================================================================
# get_analyses_for_user (PostgreSQL)
# =============================================================================

def get_analyses_for_user(db: Session, user_id: int):
    analyses_query = (
        db.query(Analysis)
        .filter(Analysis.user_id == user_id)
        .filter(Analysis.status != "archived")
        .order_by(Analysis.created_at.desc())
        .all()
    )

    result = []
    for a in analyses_query:
        progress = a.progress_percent if a.progress_percent is not None else 0
        result.append({
            "id":               a.id,
            "project_name":     a.project_name,
            "project_name_slug": a.slug,
            "created_at":       a.created_at.strftime("%d-%m-%Y %H:%M") if a.created_at else None,
            "order_by":         a.created_at,
            "status":           a.status.value if hasattr(a.status, "value") else str(a.status),
            "progress":         progress,
            "download_url":     f"/analisis/{a.id}/download",
        })
    return result


# =============================================================================
# aux_analysis_by_id  (legacy JSON)
# =============================================================================

def aux_analysis_by_id(analysis_id: str, user: UserResponse):
    ANALYSIS_DB = Path("../analysis_db.json").resolve()
    if not ANALYSIS_DB.exists():
        raise HTTPException(status_code=404, detail="No hay análisis guardados")
    db = json.loads(ANALYSIS_DB.read_text())
    analysis = next(
        (a for a in db if a.get("id") == analysis_id and a.get("username") == user.username),
        None,
    )
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")
    return analysis


def _log_idor_attempt(
    db: Session,
    user: UserResponse,
    ctx: dict | None,
    slug: str | None = None,
    analysis_id: int | None = None,
):
    """
    Llamar en el punto donde una query con filtro de propiedad
    (Analysis.user_id == user.id) no ha devuelto nada. Comprueba, SOLO
    para el log, si el proyecto existe pero es de otro usuario (posible
    IDOR) o directamente no existe (probablemente un enlace roto/typo,
    nada sospechoso). No cambia la respuesta al usuario -- eso lo sigue
    decidiendo cada función exactamente igual que antes (siempre 404,
    para no filtrar si el proyecto existe o no).
    Si `ctx` es None (función llamada fuera de un request HTTP, por
    ejemplo desde una tarea interna), no hace nada.
    """
    if ctx is None:
        return
    query_filter = (Analysis.slug == slug) if slug is not None else (Analysis.id == analysis_id)
    analisis_ajeno = db.query(Analysis.id, Analysis.user_id).filter(query_filter).first()
    if not analisis_ajeno:
        return  # de verdad no existe, no hay nada sospechoso que registrar
    audit_db = SessionLocal()
    try:
        AuditService.log(
            audit_db, EventType.ACCESS_DENIED, result=EventResult.WARNING,
            message=f"@{user.username} intentó acceder a un proyecto que no es suyo ({slug or analysis_id})",
            actor_type=ActorType.USER, actor_id=user.id, actor_username=user.username,
            target_type="analysis", target_id=analisis_ajeno[0],
            **ctx,
        )
    finally:
        audit_db.close()

def aux_analysis_by_id_slug(db: Session, analysis_id: str, user: UserResponse, ctx: dict | None = None):
    analysis = (
        db.query(Analysis)
        .filter(Analysis.slug == analysis_id, Analysis.user_id == user.id)
        .first()
    )
    if not analysis:
        _log_idor_attempt(db, user, ctx, slug=analysis_id)
        raise HTTPException(status_code=404, detail="Análisis no encontrado")
    return analysis


# =============================================================================
# aux_dashboard_data  (con lógica ScoreOP completa)
# =============================================================================

def aux_dashboard_data(db: Session, analysis_id_slug: str, current_user):
    """
    Obtiene los datos del dashboard desde BBDD + filesystem.
    Implementa la lógica completa basada en ScoreOP de main.py.
    """
    # 1. Buscar en BBDD
    analysis = db.query(Analysis).filter(
        Analysis.slug == analysis_id_slug,
        Analysis.user_id == current_user.id,
    ).first()

    if not analysis:
        return JSONResponse({"error": "Análisis no encontrado"}, status_code=404)

    cfg    = analysis.analysis_config or {}
    folder = Path(analysis.output_folder or cfg.get("output_folder", "")).resolve()

    csv_path  = folder / "scoreop_consolidado.csv"
    json_path = folder / "dashboard_data.json"

    # 2. Asegurar nubes (lazy generation)
    try:
        kws_nubes = _extract_keywords_from_analysis(analysis)
        asegurar_nubes_dashboard(folder, keywords=kws_nubes)
    except Exception as e:
        print(f"⚠️ Error asegurando nubes: {e}")

    # 3. Si no existe el CSV de ScoreOP → pipeline incompleto
    if not csv_path.exists():
        datasets   = list(folder.glob("*_global_dataset.csv"))
        analizados = list(folder.glob("*_analizado.csv"))
        if datasets or analizados:
            fase = "llm" if not analizados else "scoreop"
            return JSONResponse({
                "procesando": True,
                "fase": fase,
                "mensaje": "Completando análisis automáticamente…",
            }, status_code=202)
        return JSONResponse({"error": "No hay datos disponibles. Ejecuta el análisis primero."}, status_code=404)

    # 4. Verificar caché JSON
    data = {}
    regenerar = False
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if (
                "scoreop" not in data
                or not data["scoreop"].get("disponible", False)
                or "topics" not in data
                or len(data["topics"]) == 0
                or "dist_por_plataforma" not in data.get("scoreop", {})
            ):
                regenerar = True
        except Exception:
            regenerar = True
    else:
        regenerar = True

    # 5. Regenerar desde ScoreOP
    if regenerar:
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                sep = ";" if ";" in f.readline() else ","
            df = pd.read_csv(csv_path, sep=sep, encoding="utf-8", engine="python", on_bad_lines="skip")
            df.attrs["output_folder"] = str(folder)
            if "fecha" in df.columns and "FECHA" not in df.columns:
                df["FECHA"] = df["fecha"]
            if "plataforma" in df.columns and "FUENTE" not in df.columns:
                df["FUENTE"] = df["plataforma"]

            data = calcular_dashboard_base(df)
            data["desc_tema"] = cfg.get("desc_tema", "Sin descripción")
            data["raw_data"]  = df.fillna("").to_dict(orient="records")
            data["topics"]    = _calcular_topics_df(df)

            data_to_save = clean_types(data)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            data = data_to_save

        except Exception as e:
            traceback.print_exc()
            return JSONResponse({"error": f"Error procesando ScoreOP: {str(e)}"}, status_code=500)

    # 6. Inyectar nubes
    if "nubes" not in data:
        data["nubes"] = {}
    for img_file in folder.glob("nube_*.png"):
        try:
            with open(img_file, "rb") as image_file:
                data["nubes"][img_file.stem] = base64.b64encode(image_file.read()).decode("utf-8")
        except Exception:
            pass

    # 7. Metadatos finales
    data["project_name"] = analysis.project_name or cfg.get("project_name", "Sin nombre")
    data["tema"]         = cfg.get("tema", "Sin tema")
    data["desc_tema"]    = cfg.get("desc_tema", data.get("desc_tema", "No hay descripción."))

    return JSONResponse(content=jsonable_encoder(clean_types(data)))


# =============================================================================
# aux_filter_analysis_geo
# =============================================================================

#    analysis = db.query(Analysis).filter(
    #    Analysis.slug == analysis_id_slug,
    #    Analysis.user_id == current_user.id,
    #).first()

def aux_filter_analysis_geo(db: Session, analysis_slug: str, payload: FilterRequest, user: UserResponse):
    print(f"📍 Filtro para {analysis_slug}. Geo: {payload.terms}, Topic: {payload.custom_topic}")

    analysis = db.query(Analysis).filter(
        Analysis.slug == analysis_slug,
        Analysis.user_id == user.id,
    ).first()

    if not analysis:
        return JSONResponse({"error": "Análisis no encontrado"}, status_code=404)
    
    cfg    = analysis.analysis_config or {}
    output_folder = Path(analysis.output_folder or cfg.get("output_folder", "")).resolve()

    keywords_raw = cfg.get("keywords", [])
    if isinstance(keywords_raw, list) and keywords_raw and isinstance(keywords_raw[0], dict):
        keywords = [k.get("keyword", "") for k in keywords_raw if k.get("keyword")]
    elif isinstance(keywords_raw, list):
        keywords = [str(k) for k in keywords_raw if k]
    else:
        keywords = []

    try:
        new_dashboard_data = filtrar_y_recalcular_dashboard(
            csv_path=output_folder / "scoreop_consolidado.csv",
            output_folder=output_folder,
            terminos_geo=payload.terms,
            custom_topic=payload.custom_topic,
            keywords=keywords,
        )
        if "error" in new_dashboard_data:
            raise HTTPException(status_code=404, detail=new_dashboard_data["error"])
        return JSONResponse(content=jsonable_encoder(new_dashboard_data))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# aux_run_aceptacion
# =============================================================================

async def aux_run_aceptacion(analysis_slug: str, user: UserResponse):
    db = SessionLocal()
    if user.role == "user":
        filename = f"datos/user/user_{analysis_id}.json"
        if not os.path.exists(filename):
            raise HTTPException(status_code=404, detail=f"No existe el archivo {filename}")
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"ok": True, **data}

    result = await asyncio.to_thread(ejecutar_indicador_aceptacion, db, analysis_slug, user)
    return {"ok": True, **result}


# =============================================================================
# aux_read_aceptacion
# =============================================================================

async def aux_read_aceptacion(analysis_slug: str, user: UserResponse):
    db = SessionLocal()
    if user.role == "user":
        filename = f"datos/user/user_{analysis_id}.json"
        if not os.path.exists(filename):
            raise HTTPException(status_code=404, detail=f"No existe el archivo {filename}")
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"ok": True, **data}

    result = await asyncio.to_thread(read_indicador_aceptacion, db, analysis_slug, user)
    return {"ok": True, **result}


# =============================================================================
# aux_filter_aceptacion_geo
# =============================================================================

def clean_nans(obj):
    if isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nans(v) for v in obj]
    elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0
    return obj


def aux_filter_aceptacion_geo(db: Session, analysis_slug: str, payload: FilterRequest, current_user: UserResponse):
    result = recalcular_aceptacion_filtrada(db,
        analysis_slug=analysis_slug,
        user=current_user,
        terminos_geo=payload.terms,
    )
    return JSONResponse(content=jsonable_encoder(clean_nans(result)))


# =============================================================================
# aux_download_aceptacion_txt
# =============================================================================

async def aux_download_aceptacion_txt(analysis_id: str, current_user: UserResponse = None):
    ANALYSIS_DB = Path("analysis_db.json").resolve()
    if not ANALYSIS_DB.exists():
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    db_json = json.loads(ANALYSIS_DB.read_text(encoding="utf-8"))
    analysis = next((a for a in db_json if a["id"] == analysis_id), None)
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")

    folder_raw = Path(analysis["output_folder"])
    output_folder = folder_raw if folder_raw.is_absolute() else folder_raw
    txt_path = output_folder / "aceptacion_global.txt"

    if not txt_path.exists():
        raise HTTPException(status_code=404, detail="El informe TXT aún no ha sido generado.")

    return txt_path


# =============================================================================
# aux_download_analysis_pdf  (desde PostgreSQL)
# =============================================================================

async def aux_download_analysis_pdf(analysis_id: int, current_user):
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not analysis:
            raise HTTPException(status_code=404, detail="Análisis no encontrado")

        if (current_user.role != "admin" or current_user.role != "analista") and analysis.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Sin permisos")

        cfg = analysis.analysis_config or {}

        folder = Path(analysis.output_folder or cfg.get("output_folder", "")).resolve()

        if not folder.exists():
            raise HTTPException(status_code=404, detail="Carpeta de resultados no encontrada")

        dashboard_data = load_dashboard_data(folder, cfg)
        dashboard_data = inject_wordclouds(dashboard_data, folder)
        aceptacion_data = load_aceptacion_data(folder)

        # ── Calcular nube unificada v2 y grafo bipartito v2 para el PDF ────────
        try:
            #from logica_FORMAT import _cargar_analizado_csvs, construir_nube_unificada_v2, construir_grafo_bipartito_v2

            kw_pdf = _extract_keywords_from_analysis(analysis)
            '''
            if isinstance(kw_raw, list) and kw_raw and isinstance(kw_raw[0], dict):
                kw_pdf = [k.get("keyword", "") for k in kw_raw if k.get("keyword")]
            elif isinstance(kw_raw, str):
                try:
                    _parsed = json.loads(kw_raw)
                    kw_pdf = [k.get("keyword", k) if isinstance(k, dict) else str(k) for k in _parsed]
                except Exception:
                    kw_pdf = [kw_raw]
            else:
                kw_pdf = [str(k) for k in (kw_raw or []) if k]
            '''
            df_all_pdf = _cargar_analizado_csvs(
                db,
                folder           = analysis.output_folder,
                tema             = cfg.get("tema", ""),
                desc_tema        = cfg.get("desc_tema", ""),
                keywords         = kw_pdf,
                population_scope = cfg.get("population_scope", "GLOBAL"),
                languages        = cfg.get("languages", ["Castellano"]),
            )

            print("##########################")
            print("##########################")
            print(kw_pdf)
            print(f"{df_all_pdf.head(5)}")
            #df_all_pdf.to_csv('eliminar_df_all_pdf.csv', index=False)
            print("##########################")
            print("##########################")
            if df_all_pdf is not None and not df_all_pdf.empty:
                dashboard_data["nube_unificada_v2"] = construir_nube_unificada_v2(
                    df_all_pdf, keywords=kw_pdf, top_palabras=80, top_bigramas=40, folder=folder,
                )
                dashboard_data["grafo_bipartito_v2"] = construir_grafo_bipartito_v2(
                    df_all_pdf, folder=folder, max_topicos=200, max_usuarios=500,
                )
        except Exception as e:
            print(f"⚠️ No se pudo calcular nube/grafo v2 para el PDF: {e}")
            dashboard_data.setdefault("nube_unificada_v2", [])
            dashboard_data.setdefault("grafo_bipartito_v2", {"nodes": [], "edges": []})

        # ── Generar PDF ────────────────────────────────────────────────────────
        print(cfg)
        print("############################")
        pdf_bytes = build_analysis_pdf(dashboard_data, cfg, aceptacion_data)

        safe_name = (analysis.project_name or f"analisis_{analysis_id}").replace(" ", "_")[:60]
        filename  = f"informe_{safe_name}.pdf"

        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generando PDF: {e}")
    finally:
        db.close()


# =============================================================================
# aux_download_analysis (ZIP, legacy)
# =============================================================================

async def aux_download_analysis(analysis_id: str, user: UserResponse):
    ANALYSIS_DB = Path("analysis_db.json").resolve()
    if not ANALYSIS_DB.exists():
        raise HTTPException(status_code=404, detail="No hay análisis guardados")

    db_json = json.loads(ANALYSIS_DB.read_text(encoding="utf-8"))
    analysis = next((a for a in db_json if a["id"] == analysis_id), None)
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")

    if user.role != "admin" and analysis["username"] != user.username:
        raise HTTPException(status_code=403, detail="No autorizado")

    project_name = analysis.get("project_name", f"proyecto_{analysis_id}").replace(" ", "_")
    folder_raw = Path(analysis["output_folder"])
    folder = folder_raw if folder_raw.is_absolute() else folder_raw

    if not folder.exists():
        raise HTTPException(status_code=404, detail="Carpeta de resultados no existe")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file in folder.iterdir():
            if not file.is_file():
                continue
            if (
                file.name == "reporte_analisis.xlsx"
                or file.name.endswith("datos_con_pilares.csv")
                or file.name.endswith("datos_sentimiento_filtrados.csv")
                or file.name.endswith("_global_dataset.csv")
                or file.name.endswith("datos_combinados.csv")
            ):
                zipf.write(file, arcname=f"{project_name}/{file.name}")

        info_text = f"""
        INFORMACIÓN DEL ANÁLISIS
        ------------------------
        Proyecto: {analysis.get("project_name")}
        ID: {analysis.get("id")}
        Usuario: {analysis.get("username")}

        Tema:
        {analysis.get("tema", "No disponible")}

        Keywords:
        {analysis.get("keywords", "No disponible")}

        Fuentes:
        {", ".join(analysis.get("sources", []))}

        Idiomas:
        {", ".join(analysis.get("languages", []))}

        Fecha inicio búsqueda:
        {analysis.get("start_date", "No disponible")}

        Fecha fin búsqueda:
        {analysis.get("end_date", "No disponible")}

        Fecha creación análisis:
        {analysis.get("created_at")}
        """.strip()
        zipf.writestr(f"{project_name}/info_busqueda.txt", info_text)

    buffer.seek(0)
    return buffer


# =============================================================================
# aux_generate_keywords
# =============================================================================

def aux_generate_keywords(data: dict):
    context    = data.get("context", "")
    languages  = data.get("languages", [])
    population = data.get("population", "")
    return generar_keywords_con_ia(context, languages, population)


# =============================================================================
# aux_get_grafo  (endpoint grafo completo con PostgreSQL)
# =============================================================================

async def aux_get_grafo(
    db: Session,
    analysis_slug: str,
    nivel: str,
    plataforma: str,
    geo: str,
    current_user,
):
    if nivel == "usuario" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="El nivel de usuario requiere rol admin.")

    analysis = db.query(Analysis).filter(
        Analysis.slug == analysis_slug,
        Analysis.user_id == current_user.id,
    ).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")

    folder = Path(analysis.output_folder) if analysis.output_folder else None
    if not folder or not folder.exists():
        raise HTTPException(status_code=404, detail="Carpeta del análisis no encontrada")

    cfg = analysis.analysis_config or {}
    
    df_all = _cargar_analizado_csvs(db,
        folder           = analysis.output_folder,
        tema             = cfg.get("tema", ""),
        desc_tema        = cfg.get("desc_tema", ""),
        keywords         = _extract_keywords_from_analysis(analysis),
        population_scope = cfg.get("population_scope", "GLOBAL"),
        languages        = cfg.get("languages", ["Castellano"]),
    )
    if df_all is None or df_all.empty:
        return JSONResponse(content={
            "nivel": nivel, "nodes": [], "edges": [], "words": [],
            "meta": {"total_posts": 0, "total_comentarios_activos": 0,
                     "n_topics": 0, "n_subtopics": 0,
                     "aviso": "No se encontraron archivos *_analizado.csv en la carpeta del análisis."},
        })

    if plataforma and plataforma.lower() != "todas":
        df_all = df_all[df_all["plataforma"].str.lower() == plataforma.lower()]
        if df_all.empty:
            return JSONResponse(content={
                "nivel": nivel, "nodes": [], "edges": [], "words": [],
                "meta": {"aviso": f"Sin datos para plataforma '{plataforma}'"},
            })

    df_all = _apply_geo_filter(df_all, geo)

    scoreop_map = _scoreop_pct_map_from_csv(folder)
    kws_grafo   = _extract_keywords_from_analysis(analysis)

    if nivel == "topic":
        payload = _build_grafo_topic(df_all, scoreop_map, keywords=kws_grafo)
    else:
        payload = _build_grafo_usuario(df_all, scoreop_map)

    return JSONResponse(content=jsonable_encoder(clean_types(payload)))


# =============================================================================
# aux_get_visual_semantico
# =============================================================================
#NO USAMOS ESTE ENDPOINT
async def aux_get_visual_semantico(
    db: Session,
    analysis_slug: str,
    plataforma: str,
    geo: str,
    current_user,
):
    analysis = db.query(Analysis).filter(
        Analysis.slug == analysis_slug,
        Analysis.user_id == current_user.id,
    ).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")

    folder = Path(analysis.output_folder) if analysis.output_folder else None

    print("###########################")
    print("###########################")

    print(f"el folder es: {folder}")
    print("###########################")
    print("###########################")
    
    if not folder or not folder.exists():
        raise HTTPException(status_code=404, detail="Carpeta del análisis no encontrada")

    cfg      = analysis.analysis_config or {}
    keywords = _extract_keywords_from_analysis(analysis)
    tema             = cfg.get("tema", "")
    desc_tema        = cfg.get("desc_tema", "")
    population_scope = cfg.get("population_scope", "GLOBAL")
    languages        = cfg.get("languages", ["Castellano"])

    df_all = _cargar_analizado_csvs(db,
        folder = analysis.output_folder,
        tema=tema, desc_tema=desc_tema,
        keywords=keywords, population_scope=population_scope, languages=languages,
    )
    if df_all is None or df_all.empty:
        return JSONResponse(content={"error": f"Sin datos analizados{folder}"}, status_code=404)

    plataformas_disponibles = df_all["plataforma"].dropna().unique().tolist()

    if plataforma and plataforma.lower() != "todas":
        df_all = df_all[df_all["plataforma"].str.lower() == plataforma.lower()]
        if df_all.empty:
            return JSONResponse(content={"error": f"Sin datos para plataforma '{plataforma}'"}, status_code=404)

    df_all = _apply_geo_filter(df_all, geo)

    # Cargar ScoreOP si existe
    df_scoreop = None
    scoreop_csv = folder / "scoreop_consolidado.csv"
    if scoreop_csv.exists():
        try:
            with open(scoreop_csv, "r", encoding="utf-8") as f:
                sep = ";" if ";" in f.readline() else ","
            df_scoreop = pd.read_csv(scoreop_csv, sep=sep, encoding="utf-8", on_bad_lines="skip")
        except Exception as e:
            print(f"⚠️ No se pudo cargar scoreop: {e}")

    TIPOS_POST_SET = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}

    payload = {
        "nube_bigramas": construir_nube_bigramas(
            df_all, df_scoreop, keywords,
            folder=folder, tema=tema, usar_coherencia_llm=True,
        ),
        "nube_topicos":    construir_nube_topicos(df_all, df_scoreop),
        "grafo_bipartito": construir_grafo_bipartito(df_all, df_scoreop),
        "meta": {
            "analysis_id":     analysis_id,
            "plataforma":      plataforma,
            "plataformas":     plataformas_disponibles,
            "total_posts":     int(len(df_all[df_all["tipo_norm"].isin(TIPOS_POST_SET)])),
            "coherencia_llm":  True,
            "tiene_posicion":  "posicion" in df_all.columns,
        },
    }

    return JSONResponse(content=jsonable_encoder(clean_types(payload)))


# =============================================================================
# Helpers de PDF
# =============================================================================

def load_dashboard_data(folder: Path, analysis_data: dict):
    json_path = folder / "dashboard_data.json"
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    csv_path = folder / "scoreop_consolidado.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="No existe dashboard_data.json ni scoreop_consolidado.csv")

    with open(csv_path, "r", encoding="utf-8") as f:
        sep = ";" if ";" in f.readline() else ","
    df = pd.read_csv(csv_path, sep=sep, encoding="utf-8", on_bad_lines="skip")

    if "fecha" in df.columns and "FECHA" not in df.columns:
        df["FECHA"] = df["fecha"]
    if "plataforma" in df.columns and "FUENTE" not in df.columns:
        df["FUENTE"] = df["plataforma"]

    dashboard_data = calcular_dashboard_base(df)
    dashboard_data["desc_tema"] = analysis_data.get("desc_tema", "")
    dashboard_data["raw_data"]  = []
    return dashboard_data


def inject_wordclouds(dashboard_data: dict, folder: Path):
    if "nubes" not in dashboard_data:
        dashboard_data["nubes"] = {}
    for img_file in folder.glob("nube_*.png"):
        if img_file.stem not in dashboard_data["nubes"]:
            try:
                with open(img_file, "rb") as fimg:
                    dashboard_data["nubes"][img_file.stem] = base64.b64encode(fimg.read()).decode()
            except Exception:
                pass
    return dashboard_data


def load_aceptacion_data(folder: Path):
    aceptacion_path = folder / "aceptacion_global.json"
    if not aceptacion_path.exists():
        return None
    try:
        with open(aceptacion_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None



# =============================================================================
# aux_get_lexico_semantico_v2  (endpoint léxico semántico v2 con PostgreSQL)
# =============================================================================

async def aux_get_lexico_semantico_v2(
    db: Session,
    analysis_slug: str,
    plataforma: str,
    geo: str,
    top_nube: int,
    top_topicos: int,
    current_user,
):
    """
    Devuelve:
      nube_unificada  — palabras + bigramas, top-N por Sb (construir_nube_unificada_v2)
      grafo_bipartito — nodos VT (tópicos) + VU (usuarios) + aristas E (construir_grafo_bipartito_v2)
      meta            — estadísticas de contexto
    """
    analysis = db.query(Analysis).filter(
        Analysis.slug == analysis_slug,
        Analysis.user_id == current_user.id,
    ).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")

    folder = Path(analysis.output_folder) if analysis.output_folder else None
    if not folder or not folder.exists():
        raise HTTPException(status_code=404, detail="Carpeta del análisis no encontrada")

    cfg      = analysis.analysis_config or {}
    keywords = _extract_keywords_from_analysis(analysis)
    tema             = cfg.get("tema", "")
    desc_tema        = cfg.get("desc_tema", "")
    population_scope = cfg.get("population_scope", "GLOBAL")
    languages        = cfg.get("languages", ["Castellano"])

    df_all = _cargar_analizado_csvs(db,
        folder = analysis.output_folder,
        tema=tema, desc_tema=desc_tema,
        keywords=keywords, population_scope=population_scope, languages=languages,
    )
    if df_all is None or df_all.empty:
        return JSONResponse(content={"error": f"Sin datos analizados en {folder}"}, status_code=404)

    plataformas_disponibles = df_all["plataforma"].dropna().unique().tolist()

    if plataforma and plataforma.lower() != "todas":
        df_all = df_all[df_all["plataforma"].str.lower() == plataforma.lower()]
        if df_all.empty:
            return JSONResponse(
                content={"error": f"Sin datos para plataforma '{plataforma}'"},
                status_code=404,
            )

    df_all = _apply_geo_filter(df_all, geo)

    TIPOS_POST = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}

    try:
        nube = construir_nube_unificada_v2(df_all, keywords=keywords, top_n=top_nube, folder = folder)
    except Exception as exc:
        traceback.print_exc()
        nube = []

    try:
        grafo = construir_grafo_bipartito_v2(df_all, top_n_topicos=top_topicos, folder = folder)
    except Exception as exc:
        traceback.print_exc()
        grafo = {"nodes": [], "edges": [], "meta": {"error": str(exc)}}

    payload = {
        "nube_unificada":  nube,
        "grafo_bipartito": grafo,
        "meta": {
            "analysis_id":  analysis_slug,
            "plataforma":   plataforma,
            "plataformas":  plataformas_disponibles,
            "top_nube":     top_nube,
            "top_topicos":  top_topicos,
            "total_posts":  int(len(df_all[
                df_all["tipo_norm"].isin(TIPOS_POST) & (df_all["sent_num"] != 2)
            ])),
        },
    }
    return JSONResponse(content=jsonable_encoder(clean_types(payload)))


# =============================================================================
# Eliminación
# =============================================================================

def ejecutar_eliminacion_sana_by_slug(db: Session, slug: str, user_id: int, ctx: dict | None = None, actor_username: str | None = None) -> dict:
    try:
        analysis = db.query(Analysis).filter(
            Analysis.slug == slug,
            Analysis.user_id == user_id,
        ).first()

        if not analysis:
            if ctx is not None:
                analisis_ajeno = db.query(Analysis.id).filter(Analysis.slug == slug).first()
                if analisis_ajeno:
                    audit_db = SessionLocal()
                    try:
                        AuditService.log(
                            audit_db, EventType.ACCESS_DENIED, result=EventResult.WARNING,
                            message=f"Intento de borrar un proyecto ajeno ({analysis.project_name})",
                            actor_type=ActorType.USER, actor_id=user_id, actor_username=actor_username,
                            target_type="analysis", target_id=analisis_ajeno[0],
                            **ctx,
                        )
                    finally:
                        audit_db.close()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El proyecto solicitado no existe o no tienes permisos sobre él.",
            )
        analysis_name = analysis.project_name
        analysis_id_for_log = analysis.id
        
        carpetas_a_eliminar = [Path(f"{analysis.output_folder}")]
        for ruta in carpetas_a_eliminar:
            if ruta.exists() and ruta.is_dir():
                shutil.rmtree(ruta)
            elif ruta.exists() and ruta.is_file():
                ruta.unlink()

        db.delete(analysis)
        db.commit()
        
        if ctx is not None:
            AuditService.user_action(
                db, EventType.PROJECT_DELETED,
                user_id=user_id, username=actor_username,
                message=f"@{actor_username} eliminó el proyecto '{analysis_name}'",
                target_type="analysis", target_id=analysis_id_for_log, target_label=slug,
                ctx=ctx,
            )
        return {"status": "success", "message": f"El proyecto '{slug}' y sus archivos fueron purgados con éxito."}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del sistema al purgar el repositorio: {str(e)}",
        )


def ejecutar_eliminacion_sana_by_id(db: Session, analysis_id: int) -> dict:
    """
        Nota: hoy en día el único caller es la limpieza automática tras un fallo
        en tasks.py (ejecutar_analisis_task), no un usuario pulsando un botón --
        por eso el actor de auditoría es SYSTEM.
    """
    
    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El proyecto solicitado no existe o no tienes permisos sobre él.",
            )

        slug_for_log = analysis.slug
        
        carpetas_a_eliminar = [Path(f"{analysis.output_folder}")]
        for ruta in carpetas_a_eliminar:
            if ruta.exists() and ruta.is_dir():
                shutil.rmtree(ruta)
            elif ruta.exists() and ruta.is_file():
                ruta.unlink()

        db.delete(analysis)
        db.commit()
        
        AuditService.log(
            db, EventType.PROJECT_DELETED, result=EventResult.SUCCESS,
            message=f"Limpieza automática: proyecto '{slug_for_log}' (#{analysis_id}) eliminado tras fallo de análisis",
            actor_type=ActorType.SYSTEM,
            target_type="analysis", target_id=analysis_id, target_label=slug_for_log,
        )
        return {"status": "success", "message": f"El proyecto con ID '{analysis_id}' fue eliminado correctamente."}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno eliminando proyecto: {str(e)}",
        )
