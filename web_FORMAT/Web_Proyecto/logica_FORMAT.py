from concurrent.futures import ThreadPoolExecutor, as_completed
import sys, json
from pathlib import Path
import os
import copy
import time
import uuid
from datetime import datetime
from types import SimpleNamespace
import asyncio
import ollama
import re
import pandas as pd
import csv
from collections import Counter, defaultdict
import base64
import numpy as np
from wordcloud import WordCloud
import math
import traceback
# --- NUEVO IMPORT PARA TOPICS ---
try:
    from sentence_transformers import SentenceTransformer, util
    print("✅ SentenceTransformers importado correctamente.")
except ImportError:
    print("⚠️ SentenceTransformers no encontrado. El filtrado por topic no funcionará.")
    SentenceTransformer = None

# --- IMPORTS DE BBDD ---
from sqlalchemy.orm import Session
from sqlalchemy import BigInteger
from bbdd.database import SessionLocal
from bbdd.models_all import Analysis, AnalysisStatus, AnalysisTask, TaskStatus, TaskTypeEnum
from aux_main.task_service import TaskService
from typing import Optional, Dict, Any

# --- PATH CONFIGURATION ---
try:
    from project_local.app_ORIGINAL import BASE_DIR
except ModuleNotFoundError:
    print("⚠️ project_local no encontrado, usando BASE_DIR_1 desde cwd")
    BASE_DIR_1 = Path.cwd()
else:
    BASE_DIR_1 = BASE_DIR

# --- IMPORTS DE CLEAN_PROJECT ---
#ROOT_DIR = ""#Path(__file__).resolve().parents[2]
RUTA_CLEAN_PROJECT = Path("clean_project/src")#ROOT_DIR / "clean_project" / "src"
ruta_str = str(RUTA_CLEAN_PROJECT)

print(f"=== RUTA CALCULADA: {ruta_str}")
if ruta_str not in sys.path:
    sys.path.insert(0, ruta_str)
    print(f"✅ Ruta añadida a sys.path[0]")

print("\n🧪 Intentando importar módulos...")

try:
    print("   - Importando settings...", end=" ")
    import clean_project.config.settings as base_settings
    print("OK ✅")

    print("   - Importando Bluesky...", end=" ")
    from clean_project.scrapers.bluesky_scraper_with_filter import run_bluesky
    print("OK ✅")

    print("   - Importando Reddit...", end=" ")
    from clean_project.scrapers.reddit_scraper_with_filter import run_reddit
    print("OK ✅")

    print("   - Importando YouTube...", end=" ")
    from clean_project.scrapers.youtube_scraper_with_filter import run_youtube
    print("OK ✅")

    try:
        print("   - Importando Telegram...", end=" ")
        from clean_project.scrapers.telegram_scraper_with_filter import run_telegram
        print("OK ✅")
    except Exception as e:
        print("⚠️ ERROR TELEGRAM NO SE IMPORTÓ:", e)    
        run_telegram = None
    
    from clean_project.filters.llm_relevance_filter import check_relevance_sync
    
    print("   - Importando procesamiento de keywords...", end=" ")
    from clean_project.keyword_processing.keyword_expansion import generate_search_forms
    print("OK ✅")

    from clean_project.prompts.builder import build_sentiment_prompt, build_acceptance_prompt
    
    try:
        from clean_project.analysis.first_analysis import llm_analysis
        print("IMPORT llm_analysis OK")
    except Exception as e:
        print("ERROR:", e)

    try:
        from clean_project.analysis.metrics import Metrics
    except Exception as e:
        print("⚠️ No se pudo importar metrics:", e)
        Metrics = None    

    try:
        from clean_project.analysis.scoreop_calculator import ejecutar_scoreop_desde_logica
    except Exception as e:
        print("⚠️ No se pudo importar ejecutar_scoreop_desde_logica:", e)
        ejecutar_scoreop_desde_logica = None    
    
    from clean_project.analysis.first_report import cargar_datos_para_reporte, generar_excel_sentimiento
    print("\n🎉 ¡ÉXITO TOTAL! Todos los imports funcionan.")

    try:
        from clean_project.prompts.keywords import get_prompt_keywords
        print("IMPORT OK")
    except Exception as e:
        print("ERROR:", e)    

except ImportError as e:
    print("\n❌ FALLÓ UN IMPORT.")
    print(f"Detalle del error: {e}")
except Exception as e:
    print(f"\n❌ Ocurrió otro error: {e}")

try:
    from clean_project.analysis.first_report import generar_excel_sentimiento, cargar_datos_para_reporte
    print("IMPORT reporting OK ✅")
except Exception as e:
    print("ERROR REPORTING:", e)

try:
    from clean_project.analysis.nube import generar_nubes_dashboard, generar_nubes_desde_df
except Exception as e:
    print("ERROR NUBE:", e)

try: 
    from clean_project.vllm.vllm_keywords2 import (
        expandir_tema, generar_keywords_por_idioma, combinar_keywords_multilingue, 
        clasificar_tema, expandir_geografia, generar_keywords_hiperlocal_por_idioma, 
        combinar_keywords_hiperlocal
    )
except Exception as e:
    print("ERROR VLLM KEYWORDS:", e)

try:
    from clean_project.vllm.vllm_sentiment_topic_new import llm_analysis as vllm_sentiment_analysis
except Exception as e:    
    print("ERROR VLLM SENTIMENT:", e)

try:    
    from clean_project.vllm.vllm_pilares import procesar_pilares_directorio
except Exception as e:
    print("ERROR VLLM PILARES:", e)

try:
    from clean_project.vllm.vllm_filter import aplicar_filtros_llm, cargar_columnas_cache
except Exception as e:
    print("ERROR VLLM FILTER:", e)


# ================= UTILITY FUNCTIONS =================

def clean_types(obj):
    import numpy as np
    import pandas as pd
    import math

    if isinstance(obj, dict):
        return {str(k): clean_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_types(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        if np.isnan(obj) or np.isinf(obj):
            return 0.0
        return float(obj)
    elif isinstance(obj, float):          # ← AÑADIR ESTE BLOQUE
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif pd.isna(obj):
        return None
    else:
        return obj


def limpiar_topic(texto: str) -> str:
    if not texto:
        return ""
    
    texto = str(texto).strip().lower()
    
    # Reemplazar guiones bajos por espacio
    texto = texto.replace("_", " ")
    
    # Quitar múltiples espacios
    texto = re.sub(r"\s+", " ", texto)
    
    # Opcional: quitar caracteres raros
    texto = re.sub(r"[^\w\s]", "", texto)
    
    return texto


def extraer_json(texto: str):
    if not texto: return None
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", texto)
        if match:
            try: return json.loads(match.group(0))
            except: return None
    return None


def _safe(val, default=0.0):
    try:
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return default


from dateutil import parser as dateutil_parser
import pytz

def _parse_fecha_robusta(serie):
    def parsear_uno(valor):
        if pd.isna(valor) or str(valor).strip() in ('', 'nan', 'None', 'NaT'):
            return 'Sin fecha'
        s = str(valor).strip()
        # Truncar nanosegundos/microsegundos excesivos en la parte decimal
        # pandas/dateutil no maneja más de 6 dígitos decimales
        import re
        s = re.sub(r'(\.\d{6})\d+', r'\1', s)
        try:
            dt = dateutil_parser.parse(s)
            # Normalizar a UTC
            if dt.tzinfo is not None:
                dt = dt.astimezone(pytz.utc)
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return 'Sin fecha'
    
    return serie.map(parsear_uno)


# ================= DASHBOARD FUNCTIONS =================

def calcular_dashboard_base(df):
    """Genera las métricas básicas para el dashboard a partir del dataset."""
    dashboard_base = {}
    
    # 1. BÚSQUEDA ROBUSTA DE COLUMNAS
    if 'FECHA' not in df.columns:
        posibles_fechas =['fecha', 'fecha_post', 'fecha_publicacion', 'created_at', 'date']
        for col in posibles_fechas:
            if col in df.columns:
                df['FECHA'] = df[col]
                break
        if 'FECHA' not in df.columns:
            for col in df.columns:
                if 'fecha' in col.lower():
                    df['FECHA'] = df[col]
                    break
                    
    if 'FUENTE' not in df.columns:
        if 'plataforma' in df.columns:
            df['FUENTE'] = df['plataforma']
        elif 'source' in df.columns:
            df['FUENTE'] = df['source']


    print("=== DEBUG FECHAS ===")
    print(f"Columnas disponibles: {df.columns.tolist()}")
    print(f"Columnas con 'fecha': {[c for c in df.columns if 'fecha' in c.lower()]}")
    if 'FECHA' in df.columns:
        print(f"Tipo columna FECHA: {df['FECHA'].dtype}")
        print(f"Nulos en FECHA: {df['FECHA'].isna().sum()} de {len(df)}")
        print(f"Por plataforma:")
        if 'FUENTE' in df.columns:
            for fuente, grupo in df.groupby('FUENTE'):
                nulos = grupo['FECHA'].isna().sum()
                total = len(grupo)
                print(f"  {fuente}: {total - nulos} con fecha, {nulos} nulos")
        print(f"Muestra valores FECHA:\n{df['FECHA'].dropna().head(5).tolist()}")
    else:
        print("¡FECHA no existe en df!")
    print("===================")        
    # 2. LIMPIEZA DE FECHAS PARA LA GRÁFICA
    if 'FECHA' in df.columns:
        df['FECHA_CLEAN'] = _parse_fecha_robusta(df['FECHA'])
    else:
        df['FECHA_CLEAN'] = 'Sin fecha'

    df['FECHA_CLEAN'] = _parse_fecha_robusta(df['FECHA'])

    # DEBUG
    print("=== FECHA_CLEAN por plataforma ===")
    for fuente, grupo in df.groupby('FUENTE'):
        print(f"\n{fuente}:")
        print(grupo[['FECHA', 'FECHA_CLEAN']].to_string())
    print("==================================")    

    # 3. KPIs BÁSICOS
    total_comentarios = 0
    if 'num_comentarios' in df.columns:
        total_comentarios = int(pd.to_numeric(df['num_comentarios'], errors='coerce').fillna(0).sum())
        
    dashboard_base["kpis"] = {
        "total": len(df),
        "total_comentarios": total_comentarios,
        "total_interacciones": len(df) + total_comentarios
    }
    
    # 4. VOLUMEN POR RED
    if 'FUENTE' in df.columns:
        dashboard_base["volumen_por_red"] = df['FUENTE'].value_counts().to_dict()
    else:
        dashboard_base["volumen_por_red"] = {}

    # 5. TENDENCIA GLOBAL
    if 'FECHA_CLEAN' in df.columns:
        tendencia = df.groupby('FECHA_CLEAN').size().to_dict()
        tendencia.pop('Sin fecha', None)
        dashboard_base["tendencia_global"] = tendencia
    else:
        dashboard_base["tendencia_global"] = {}

    # 6. TENDENCIA POR RED
    dashboard_base["tendencia_por_red"] = {}
    if 'FUENTE' in df.columns and 'FECHA_CLEAN' in df.columns:
        for fuente in df['FUENTE'].dropna().unique():
            df_fuente = df[df['FUENTE'] == fuente]
            tendencia_fuente = df_fuente.groupby('FECHA_CLEAN').size().to_dict()
            tendencia_fuente.pop('Sin fecha', None)
            dashboard_base["tendencia_por_red"][str(fuente)] = {"total": tendencia_fuente}

    # ===================================================================
    # 7. MÉTRICAS DE SCOREOP
    # ===================================================================
    # ===================================================================
    # 7. MÉTRICAS DE SCOREOP  (escala normalizada ScoreOP_pct ∈ [0,100])
    # ===================================================================
    try:
        output_folder = Path(df.attrs.get('output_folder', './'))
        scoreop_file  = output_folder / "scoreop_consolidado.csv"
 
        if scoreop_file.exists():
            df_scoreop = pd.read_csv(scoreop_file, sep=';', encoding='utf-8')
 
            if not df_scoreop.empty:
                # ── Asegurar columnas normalizadas ────────────────────────────
                # Si el CSV es antiguo (sin ScoreOP_pct), calcularlo al vuelo
                # usando ScoreOP raw para no romper análisis ya guardados.
                if 'ScoreOP_pct' not in df_scoreop.columns:
                    if 'ScoreOP_sup' in df_scoreop.columns:
                        sup = df_scoreop['ScoreOP_sup'].replace(0, np.nan)
                        df_scoreop['ScoreOP_norm'] = (df_scoreop['ScoreOP'] / sup).fillna(0).clip(-1, 1)
                    else:
                        max_abs = df_scoreop['ScoreOP'].abs().max()
                        df_scoreop['ScoreOP_norm'] = (df_scoreop['ScoreOP'] / max_abs).clip(-1, 1) if max_abs > 0 else 0.0  
                    df_scoreop['ScoreOP_pct'] = (df_scoreop['ScoreOP_norm'] + 1.0) / 2.0 * 100.0
 
                # ── Fecha ─────────────────────────────────────────────────────
                if 'FECHA' not in df_scoreop.columns:
                    for col in ['fecha', 'fecha_post', 'fecha_publicacion', 'created_at', 'date']:
                        if col in df_scoreop.columns:
                            df_scoreop['FECHA'] = df_scoreop[col]
                            break
 
                if 'FECHA' in df_scoreop.columns:
                    df_scoreop['FECHA_CLEAN'] = _parse_fecha_robusta(df_scoreop['FECHA'])
                else:
                    df_scoreop['FECHA_CLEAN'] = 'Sin fecha'
 
                df_val = df_scoreop[df_scoreop['FECHA_CLEAN'] != 'Sin fecha']
 
                # ── Tendencias temporales (basadas en ScoreOP_pct) ────────────
                tendencia_global_scoreop = (
                    df_val.groupby('FECHA_CLEAN')['ScoreOP_pct']
                    .mean().round(2).to_dict()
                )
                # "fuerza" = desviación del centro (50): cuánto se aleja de neutral
                tendencia_fuerza_scoreop = (
                    df_val.groupby('FECHA_CLEAN')['ScoreOP_pct']
                    .apply(lambda x: round(abs(x - 50).mean(), 2)).to_dict()
                )
 
                tendencia_red_scoreop    = {}
                tendencia_red_fuerza_pos = {}
                tendencia_red_fuerza_neg = {}
 
                for fuente in df_val['plataforma'].dropna().unique():
                    df_f = df_val[df_val['plataforma'] == fuente]
                    key  = str(fuente)
 
                    tendencia_red_scoreop[key] = (
                        df_f.groupby('FECHA_CLEAN')['ScoreOP_pct']
                        .mean().round(2).to_dict()
                    )
                    # pos: suma diaria de ScoreOP_pct de posts con pct > 50
                    tendencia_red_fuerza_pos[key] = (
                        df_f[df_f['ScoreOP_pct'] > 50]
                        .groupby('FECHA_CLEAN')['ScoreOP_pct']
                        .mean().round(2).to_dict()
                    )
                    # neg: suma diaria de ScoreOP_pct de posts con pct < 50
                    tendencia_red_fuerza_neg[key] = (
                        df_f[df_f['ScoreOP_pct'] < 50]
                        .groupby('FECHA_CLEAN')['ScoreOP_pct']
                        .mean().round(2).to_dict()
                    )
 
                # ── Agrupación por plataforma ─────────────────────────────────
                agg_cols = {'ScoreOP': ['mean', 'median', 'min', 'max', 'count'],
                            'ScoreOP_pct': ['mean', 'median', 'min', 'max']}
                if 'num_comentarios' in df_scoreop.columns:
                    agg_cols['num_comentarios'] = ['sum']
 
                agg_df = df_scoreop.groupby('plataforma').agg(agg_cols).round(2)
                agg_df.columns = [f"{c[0]}_{c[1]}" for c in agg_df.columns]
                scoreop_por_plataforma = agg_df.to_dict()
 
                # ── Distribución con umbrales [0,100] ─────────────────────────
                # muy_positivo  > 80   | positivo   60-80
                # neutro       40-60   | negativo  20-40
                # muy_negativo  < 20
                def _dist_pct(frame):
                    p = frame['ScoreOP_pct']
                    return {
                        'muy_positivo': int((p > 80).sum()),
                        'positivo':     int(((p >= 60) & (p <= 80)).sum()),
                        'neutro':       int(((p >= 40) & (p < 60)).sum()),
                        'negativo':     int(((p >= 20) & (p < 40)).sum()),
                        'muy_negativo': int((p < 20).sum()),
                    }
 
                scoreop_distribution = _dist_pct(df_scoreop)
 
                dist_por_plataforma = {}
                for plat in df_scoreop['plataforma'].dropna().unique():
                    df_p = df_scoreop[df_scoreop['plataforma'] == plat]
                    d = _dist_pct(df_p)
                    d['total'] = int(len(df_p))
                    dist_por_plataforma[str(plat)] = d
 
                # ── ScoreOP_pct global (KPI principal) ────────────────────────
                def _agg_pct_red_dash(grp):
                    s = grp['ScoreOP'].sum()
                    d = grp['ScoreOP_sup'].sum() if 'ScoreOP_sup' in grp.columns else 0
                    norm = s/d if d > 0 else 0
                    return round((norm + 1.0) / 2.0 * 100.0, 2) if d > 0 else 50.0

                scoreop_pct_por_red = (
                    df_scoreop.groupby('plataforma')
                    .apply(_agg_pct_red_dash)
                    .to_dict()
                )
                # scoreop_pct_por_red = (
                #     df_scoreop.groupby('plataforma')['ScoreOP_pct']
                #     .mean().round(2)
                #     .to_dict()
                # )

                col_com_dash = 'num_comentarios' if 'num_comentarios' in df_scoreop.columns else None
                N_por_red_dash = {}
                for red, grp in df_scoreop.groupby('plataforma'):
                    n_posts = len(grp)
                    n_com   = int(grp[col_com_dash].fillna(0).sum()) if col_com_dash else 0
                    N_por_red_dash[red] = n_posts + n_com

                total_N_dash = sum(N_por_red_dash.values()) or 1
                scoreop_pct_global = round(
                    sum(scoreop_pct_por_red[r] * N_por_red_dash.get(r, 0) for r in scoreop_pct_por_red)
                    / total_N_dash,
                    2
                )
 
                # ── Top / Bottom posts (estrictamente separados) ──────────────
                cols_post = [c for c in
                    ['plataforma', 'contenido_post', 'stance_post', 'FECHA',
                     'num_comentarios', 'ScoreOP', 'ScoreOP_pct', 'topic', 'ScoreOP_sup']
                    if c in df_scoreop.columns]
 
                _has_sup = 'ScoreOP_sup' in df_scoreop.columns

                _top_pool = df_scoreop[df_scoreop['ScoreOP_pct'] > 60].copy()
                if _has_sup and not _top_pool.empty:
                    top_posts = (
                        _top_pool
                        .sort_values(['ScoreOP_pct', 'ScoreOP_sup'], ascending=[False, False])
                        .head(10)[cols_post]
                        .replace({np.nan: ""}).to_dict('records')
                    )
                else:
                    top_posts = (
                        _top_pool.nlargest(10, 'ScoreOP_pct')[cols_post]
                        .replace({np.nan: ""}).to_dict('records')
                    )

                _bot_pool = df_scoreop[df_scoreop['ScoreOP_pct'] < 40].copy()
                if _has_sup and not _bot_pool.empty:
                    bottom_posts = (
                        _bot_pool
                        .sort_values(['ScoreOP_pct', 'ScoreOP_sup'], ascending=[True, False])
                        .head(10)[cols_post]
                        .replace({np.nan: ""}).to_dict('records')
                    )
                else:
                    bottom_posts = (
                        _bot_pool.nsmallest(10, 'ScoreOP_pct')[cols_post]
                        .replace({np.nan: ""}).to_dict('records')
                    )
 
                dashboard_base["scoreop"] = {
                    "disponible":          True,
                    "total_posts":         len(df_scoreop),
                    "scoreop_pct_global":  scoreop_pct_global,    # KPI principal [0,100]
                    "scoreop_pct_por_red": scoreop_pct_por_red,   # por red [0,100]
                    "por_plataforma":      scoreop_por_plataforma,
                    "tendencia_global":    tendencia_global_scoreop,
                    "tendencia_fuerza":    tendencia_fuerza_scoreop,
                    "tendencia_red":       tendencia_red_scoreop,
                    "tendencia_red_pos":   tendencia_red_fuerza_pos,
                    "tendencia_red_neg":   tendencia_red_fuerza_neg,
                    "top_posts":           top_posts,
                    "bottom_posts":        bottom_posts,
                    "distribution":        scoreop_distribution,
                    "dist_por_plataforma": dist_por_plataforma,
                    "stats": {
                        # Raw (retrocompatibilidad)
                        "media":       _safe(df_scoreop['ScoreOP'].mean()),
                        "mediana":     _safe(df_scoreop['ScoreOP'].median()),
                        "min":         _safe(df_scoreop['ScoreOP'].min()),
                        "max":         _safe(df_scoreop['ScoreOP'].max()),
                        "std":         _safe(df_scoreop['ScoreOP'].std()),
                        # Normalizado [0,100] — usar estos en frontend
                        "pct_media":   _safe(df_scoreop['ScoreOP_pct'].mean()),
                        "pct_mediana": _safe(df_scoreop['ScoreOP_pct'].median()),
                        "pct_min":     _safe(df_scoreop['ScoreOP_pct'].min()),
                        "pct_max":     _safe(df_scoreop['ScoreOP_pct'].max()),
                        "pct_std":     _safe(df_scoreop['ScoreOP_pct'].std()),
                    },
                }
            else:
                dashboard_base["scoreop"] = {
                    "disponible": False,
                    "error": "El archivo ScoreOP existe pero está vacío."
                }
        else:
            dashboard_base["scoreop"] = {"disponible": False}
 
    except Exception as e:
        print(f"⚠️ Error cargando métricas ScoreOP: {e}")
        dashboard_base["scoreop"] = {"disponible": False, "error": str(e)}

    
    # ¡ESTA LÍNEA ES LA QUE FALTABA O ESTABA MAL TABULADA!
    return dashboard_base


def _calcular_topics_df(df: pd.DataFrame) -> list:
    """
    Calcula métricas de topics usando ScoreOP_pct cuando está disponible.
    Devuelve lista de dicts lista para serializar al dashboard.
 
    Columnas resultantes:
      TOPIC         – nombre del topic
      volumen       – nº de posts con ese topic
      pos           – posts con ScoreOP_pct > 60  (motor positivo)
      neu           – posts con ScoreOP_pct 40-60 (posición neutra/polarizada)
      neg           – posts con ScoreOP_pct < 40  (motor negativo)
      scoreop_prom  – ScoreOP raw medio (retrocompat.)
      pct_medio     – ScoreOP_pct medio del topic [0,100]
    """
    topic_col = (
        "topic" if "topic" in df.columns
        else "TOPIC" if "TOPIC" in df.columns
        else None
    )
    if not topic_col:
        return []
 
    df = df.copy()
    df["TOPIC_CLEAN"] = (
        df[topic_col].fillna("Otros").astype(str).str.strip().str.lower()
    )
 
    has_pct = "ScoreOP_pct" in df.columns
 
    if has_pct:
        topics_df = df.groupby("TOPIC_CLEAN").agg(
            volumen      = ("TOPIC_CLEAN", "count"),
            pos          = ("ScoreOP_pct", lambda x: (x > 60).sum()),
            neu          = ("ScoreOP_pct", lambda x: ((x >= 40) & (x <= 60)).sum()),
            neg          = ("ScoreOP_pct", lambda x: (x < 40).sum()),
            scoreop_prom = ("ScoreOP",     "mean") if "ScoreOP" in df.columns else ("TOPIC_CLEAN", "count"),
            pct_medio    = ("ScoreOP_pct", "mean"),
        ).reset_index()
    else:
        # Fallback al método anterior con ScoreOP raw
        topics_df = df.groupby("TOPIC_CLEAN").agg(
            volumen      = ("TOPIC_CLEAN", "count"),
            pos          = ("ScoreOP", lambda x: (x > 0).sum()) if "ScoreOP" in df.columns else ("TOPIC_CLEAN", "count"),
            neu          = ("ScoreOP", lambda x: (x == 0).sum()) if "ScoreOP" in df.columns else ("TOPIC_CLEAN", "count"),
            neg          = ("ScoreOP", lambda x: (x < 0).sum()) if "ScoreOP" in df.columns else ("TOPIC_CLEAN", "count"),
            scoreop_prom = ("ScoreOP", "mean") if "ScoreOP" in df.columns else ("TOPIC_CLEAN", "count"),
        ).reset_index()
 
    topics_df.rename(columns={"TOPIC_CLEAN": "TOPIC"}, inplace=True)
    return topics_df.to_dict(orient="records")


# ================= KEYWORDS GENERATION =================

def generar_keywords_con_ia(tema: str, population_scope, target_languages: list):
    print(f"🔍 DEBUG - Population: '{population_scope}' | Tipo: {type(population_scope)}")
 
    poblacion_str = (
        ", ".join(population_scope)
        if isinstance(population_scope, list) and population_scope
        else str(population_scope).strip() or "GLOBAL"
    )
 
    if not tema:
        return {"keywords": [], "brief": ""}
 
    print(f"\n🚀 tema='{tema}' | idiomas={target_languages} | scope='{poblacion_str}'")
 
    # 1. Clasificar tipo — LLM agnóstico, sin listas hardcodeadas
    tipo_tema = clasificar_tema(tema, poblacion_str)
 
    # 2. Expandir tema (común para A y B)
    brief = expandir_tema(tema, poblacion_str)
    if not brief:
        print("⚠️ No se pudo expandir el tema.")
        return {"keywords": [], "brief": ""}
 
    print(f"   BRIEF: {brief.get('descripcion_breve', '')}")
 
    if tipo_tema == "hiperlocal":
        # ── Rama B: Hiperlocal ──────────────────────────────────────
        print(f"\n🏙️  [HIPERLOCAL] Expandiendo geografía para '{poblacion_str}'...")
        geo_expansion = expandir_geografia(tema, poblacion_str)
 
        todas = []
        with ThreadPoolExecutor(max_workers=max(1, len(target_languages))) as executor:
            futuros = {
                executor.submit(
                    generar_keywords_hiperlocal_por_idioma,
                    tema, idioma, poblacion_str, brief, geo_expansion
                ): idioma
                for idioma in target_languages
            }
            for futuro in as_completed(futuros):
                idioma = futuros[futuro]
                try:
                    kws = futuro.result()
                    print(f"   ✅ [HIPERLOCAL] {idioma}: {len(kws)} keywords")
                    todas.extend(kws)
                except Exception as e:
                    print(f"   ❌ {idioma}: {e}")
 
        resultado = combinar_keywords_hiperlocal(todas)
 
    else:
        # ── Rama A: Universal ───────────────────────────────────────
        print(f"\n🌍  [UNIVERSAL] Generando keywords estándar...")
        todas = []
        with ThreadPoolExecutor(max_workers=max(1, len(target_languages))) as executor:
            futuros = {
                executor.submit(
                    generar_keywords_por_idioma, tema, idioma, poblacion_str, brief
                ): idioma
                for idioma in target_languages
            }
            for futuro in as_completed(futuros):
                idioma = futuros[futuro]
                try:
                    kws = futuro.result()
                    print(f"   ✅ [UNIVERSAL] {idioma}: {len(kws)} keywords")
                    todas.extend(kws)
                except Exception as e:
                    print(f"   ❌ {idioma}: {e}")
 
        resultado = combinar_keywords_multilingue(todas)
 
    n = len(resultado["keywords"])
    print(
        f"\n✅ {n} keywords únicas ({tipo_tema}): "
        f"{[k['keyword'] for k in resultado['keywords']]}"
    )
 
    return {
        "keywords": resultado["keywords"],
        "brief": brief.get("descripcion_breve", ""),
        "tipo_tema": tipo_tema,
    }



# ================= SEMANTIC SEARCH =================

_embedding_model = None

def get_model():
    """Carga el modelo solo una vez (Singleton) para ahorrar memoria."""
    global _embedding_model
    if _embedding_model is None and SentenceTransformer is not None:
        print("⏳ Cargando modelo de embeddings (esto puede tardar un poco)...")
        # Usamos el modelo que tenías en retrive_topics.py
        _embedding_model = SentenceTransformer("intfloat/multilingual-e5-large", device="cpu")
        print("✅ Modelo cargado.")
    return _embedding_model



def search_by_user_topic(df, user_topic, threshold=0.65):
    """Filtra el DataFrame por similitud semántica con topics."""
    model = get_model()
    if not model or not user_topic:
        return df

    print(f"🔍 Ejecutando búsqueda semántica para: '{user_topic}' con umbral {threshold}")

    topic_cols = [c for c in df.columns if c.startswith("Topic_") or c == "TOPIC"]
    
    all_topics = set()
    for col in topic_cols:
        unique_vals = df[col].dropna().unique()
        for val in unique_vals:
            s_val = str(val).strip().lower()
            if s_val and s_val not in ["", "no relacionado", "otros"]:
                all_topics.add(s_val)
    
    all_topics_list = list(all_topics)
    
    if not all_topics_list:
        return df

    topic_embeddings = model.encode([f"passage: {t}" for t in all_topics_list])
    query_embedding = model.encode([f"query: {user_topic}"])

    from sklearn.metrics.pairwise import cosine_similarity
    scores = cosine_similarity(query_embedding, topic_embeddings)[0]

    similar_topics = [
        all_topics_list[i] for i, score in enumerate(scores)
        if score >= threshold
    ]
    
    print(f"   Topics encontrados ({len(similar_topics)}): {similar_topics[:5]} ...")

    if not similar_topics:
        print("   ⚠️ No se encontraron topics similares.")
        return df.iloc[0:0]

    similar_topics_norm = set(similar_topics)

    def row_has_topic(row):
        for col in topic_cols:
            val = str(row.get(col, "")).strip().lower()
            if val in similar_topics_norm:
                return True
        return False

    mask = df.apply(row_has_topic, axis=1)
    df_filtered = df[mask]
    
    print(f"   Registros tras filtro semántico: {len(df_filtered)}")
    return df_filtered


# ================= WORD CLOUDS =================

def asegurar_nubes_dashboard(folder, keywords=None):
    """
    Genera nubes de palabras desde scoreop_consolidado.csv (posts)
    enriquecidas con los comentarios de *_analizado.csv.
    Las keywords se excluyen del vocabulario (acepta strings o dicts).
    """
    folder_path = Path(folder)
 
    if list(folder_path.glob("nube_*.png")):
        return
 
    print("☁️ Generando nubes de palabras (posts + comentarios)…")
    csv_path = folder_path / "scoreop_consolidado.csv"
 
    if not csv_path.exists():
        print(f"⚠️ No existe scoreop_consolidado.csv para generar nubes: {csv_path}" )
        return
 
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            sep = ";" if ";" in f.readline() else ","
 
        df_posts = pd.read_csv(csv_path, sep=sep, encoding="utf-8", on_bad_lines="skip")
 
        # ── Cargar comentarios de *_analizado.csv ─────────────────────────
        df_comentarios_list = []
        for analizado_file in folder_path.glob("*_analizado.csv"):
            try:
                with open(analizado_file, "r", encoding="utf-8") as f:
                    sep_a = ";" if ";" in f.readline() else ","
                df_anal = pd.read_csv(
                    analizado_file, sep=sep_a, encoding="utf-8", on_bad_lines="skip"
                )
                # Filtrar solo filas de tipo comentario con sentimiento válido
                if "tipo" in df_anal.columns:
                    df_anal = df_anal[
                        df_anal["tipo"].str.lower().isin(["comentario", "comment"])
                    ]
                if "sentimiento" in df_anal.columns:
                    df_anal = df_anal[
                        pd.to_numeric(df_anal["sentimiento"], errors="coerce")
                        .isin([-1, 0, 1])
                    ]
                # Unificar columna plataforma desde nombre de archivo si falta
                if "plataforma" not in df_anal.columns:
                    plat = analizado_file.name.split("_")[0].lower()
                    df_anal["plataforma"] = plat
                if not df_anal.empty:
                    df_comentarios_list.append(df_anal)
                    print(f"   📝 {analizado_file.name}: {len(df_anal)} comentarios cargados.")
            except Exception as e:
                print(f"   ⚠️ Error leyendo {analizado_file.name}: {e}")
 
        df_comentarios = (
            pd.concat(df_comentarios_list, ignore_index=True)
            if df_comentarios_list else None
        )
 
        nubes = generar_nubes_desde_df(
            df_posts,
            keywords=keywords,
            df_comentarios=df_comentarios,
        )
 
        for nombre, b64_str in nubes.items():
            if b64_str:
                import base64 as _b64
                img_bytes = _b64.b64decode(b64_str)
                plat = nombre.replace("nube_", "")
                (folder_path / f"nube_{plat}.png").write_bytes(img_bytes)
 
        print("✅ Nubes generadas correctamente.")
    except Exception as e:
        print(f"❌ Error generando nubes: {e}")
        import traceback; traceback.print_exc()



# ================= FILTERING & DASHBOARD RECALCULATION =================

def filtrar_y_recalcular_dashboard(
    csv_path,
    output_folder,
    terminos_geo,
    custom_topic=None,
    keywords=None,
):
    """Filtra ScoreOP con LLM y recalcula métricas del dashboard."""
    output_folder_path = Path(output_folder)
    scoreop_csv = output_folder_path / "scoreop_consolidado.csv"
 
    if not scoreop_csv.exists():
        return {"error": "No se encontró el archivo ScoreOP. Ejecuta el análisis primero."}
 
    with open(scoreop_csv, "r", encoding="utf-8") as f:
        sep = ";" if ";" in f.readline() else ","
    df = pd.read_csv(scoreop_csv, sep=sep, encoding="utf-8", engine="python", on_bad_lines="skip")
    df = cargar_columnas_cache(df, scoreop_csv)
    # ── Compatibilidad con CSVs antiguos sin columna texto_citado ─────────────
    if "texto_citado" not in df.columns:
        df["texto_citado"] = ""
    df["texto_citado"] = df["texto_citado"].fillna("").astype(str)
 
    print(f"\n=== Filtrando ScoreOP con LLM: {len(df)} posts ===")
 
    geo_terms = [t.strip() for t in (terminos_geo or []) if t.strip()]
    topic_terms = [t.strip() for t in ([custom_topic] if custom_topic else []) if t.strip()]
 
    if not geo_terms and not topic_terms:
        return {"error": "Introduce al menos un término para filtrar."}
 
    tema = ""
    try:
        db: Session = SessionLocal()
        try:
            analysis = db.query(Analysis).filter(
                Analysis.output_folder == str(output_folder_path)
            ).first()
            if analysis:
                tema = (
                    analysis.analysis_config.get("tema") 
                    if analysis.analysis_config else ""
                )
        finally:
            db.close()
    except Exception:
        pass
 
    df_filtrado, metadata_filtros = aplicar_filtros_llm(
        df,
        terminos_geo=geo_terms,
        terminos_topic=topic_terms,
        csv_path=scoreop_csv,
        tema=tema,
    )
 
    if df_filtrado.empty:
        terminos_str = ", ".join(geo_terms + topic_terms)
        return {"error": f"No hay publicaciones que coincidan con: «{terminos_str}»"}
    
    if "FECHA" not in df_filtrado.columns:
        posibles_fechas = ["fecha", "fecha_post", "fecha_publicacion", "created_at", "date"]
        for col in posibles_fechas:
            if col in df_filtrado.columns:
                df_filtrado["FECHA"] = df_filtrado[col]
                break

    if "FECHA" in df_filtrado.columns:
        df_filtrado["FECHA_CLEAN"] = _parse_fecha_robusta(df_filtrado["FECHA"])
    else:
        df_filtrado["FECHA_CLEAN"] = "Sin fecha"
 
    print(f"📊 Posts tras filtros LLM: {len(df_filtrado)}")
 
    df_dash = df_filtrado.copy()
    if "fecha" in df_dash.columns and "FECHA" not in df_dash.columns:
        df_dash["FECHA"] = df_dash["fecha"]
    if "plataforma" in df_dash.columns and "FUENTE" not in df_dash.columns:
        df_dash["FUENTE"] = df_dash["plataforma"]
 
    df_dash.attrs["output_folder"] = str(output_folder_path)
    dashboard_data: dict = {}
 
    dashboard_data["kpis"] = {
        "total": len(df_filtrado),
        "total_comentarios": int(df_filtrado["num_comentarios"].fillna(0).sum())
            if "num_comentarios" in df_filtrado.columns else 0,
        "total_interacciones": len(df_filtrado),
    }
 
    if "FECHA" in df_dash.columns:
        df_dash["FECHA_CLEAN"] = _parse_fecha_robusta(df_dash["FECHA"])
        tendencia = (
            df_dash[df_dash["FECHA_CLEAN"] != "Sin fecha"]
            .groupby("FECHA_CLEAN").size().to_dict()
        )
    else:
        tendencia = {}
    dashboard_data["tendencia_global"] = tendencia
 
    dashboard_data["tendencia_por_red"] = {}
    if "FUENTE" in df_dash.columns and "FECHA_CLEAN" in df_dash.columns:
        for fuente in df_dash["FUENTE"].dropna().unique():
            df_f = df_dash[df_dash["FUENTE"] == fuente]
            t_f = df_f[df_f["FECHA_CLEAN"] != "Sin fecha"].groupby("FECHA_CLEAN").size().to_dict()
            dashboard_data["tendencia_por_red"][str(fuente)] = {"total": t_f}
 
    if "FUENTE" in df_dash.columns:
        dashboard_data["volumen_por_red"] = df_dash["FUENTE"].value_counts().to_dict()
 
    if 'ScoreOP_pct' not in df_filtrado.columns:
        if 'ScoreOP_sup' in df_filtrado.columns:
            sup = df_filtrado['ScoreOP_sup'].replace(0, np.nan)
            df_filtrado['ScoreOP_norm'] = (df_filtrado['ScoreOP'] / sup).fillna(0).clip(-1, 1)
        else:
            max_abs = df_filtrado['ScoreOP'].abs().max()
            df_filtrado['ScoreOP_norm'] = (df_filtrado['ScoreOP'] / max_abs).clip(-1, 1) if max_abs > 0 else 0.0
        df_filtrado['ScoreOP_pct'] = (df_filtrado['ScoreOP_norm'] + 1.0) / 2.0 * 100.0
 
    agg_cols = {'ScoreOP': ['mean', 'median', 'min', 'max', 'count'],
                'ScoreOP_pct': ['mean', 'median', 'min', 'max']}
    if "num_comentarios" in df_filtrado.columns:
        agg_cols["num_comentarios"] = ["sum"]
 
    agg_df = df_filtrado.groupby("plataforma").agg(agg_cols).round(2)
    agg_df.columns = [f"{c[0]}_{c[1]}" for c in agg_df.columns]
    scoreop_por_plataforma = agg_df.to_dict()
 
    tendencia_scoreop = {}
    tendencia_red_scoreop = {}
    tendencia_red_fuerza_pos = {}
    tendencia_red_fuerza_neg = {}
 
    if "FECHA_CLEAN" in df_dash.columns:
        df_val = df_dash[df_dash["FECHA_CLEAN"] != "Sin fecha"]
        tendencia_scoreop = (
            df_val.groupby("FECHA_CLEAN")["ScoreOP_pct"]
            .mean().round(2).to_dict()
        )
        for fuente in df_val["plataforma"].dropna().unique():
            df_f = df_val[df_val["plataforma"] == fuente]
            key = str(fuente)
            tendencia_red_scoreop[key] = (
                df_f.groupby("FECHA_CLEAN")["ScoreOP_pct"]
                .mean().round(2).to_dict()
            )
            tendencia_red_fuerza_pos[key] = (
                df_f[df_f['ScoreOP_pct'] > 50]
                .groupby('FECHA_CLEAN')['ScoreOP_pct']
                .mean().round(2).to_dict()
            )
            tendencia_red_fuerza_neg[key] = (
                df_f[df_f['ScoreOP_pct'] < 50]
                .groupby('FECHA_CLEAN')['ScoreOP_pct']
                .mean().round(2).to_dict()
            )
 
    def _dist_scoreop(frame):
        p = frame["ScoreOP_pct"]
        return {
            "muy_positivo": int((p > 80).sum()),
            "positivo": int(((p > 60) & (p <= 80)).sum()),
            "neutro": int(((p >= 40) & (p < 60)).sum()),
            "negativo": int(((p >= 20) & (p < 40)).sum()),
            "muy_negativo": int((p < 20).sum()),
        }
 
    scoreop_dist = _dist_scoreop(df_filtrado)
    dist_por_plat = {}
    for plat in df_filtrado["plataforma"].dropna().unique():
        df_p = df_filtrado[df_filtrado["plataforma"] == plat]
        d = _dist_scoreop(df_p)
        d["total"] = int(len(df_p))
        dist_por_plat[str(plat)] = d
 
    def _posts(frame, largest: bool):
        # Separación estricta: top solo >60, bottom solo <40
        # (mismo umbral que el dashboard principal)
        if largest:
            frame = frame[frame["ScoreOP_pct"] > 60]
        else:
            frame = frame[frame["ScoreOP_pct"] < 40]

        extra = ["num_comentarios"] if "num_comentarios" in frame.columns else []
        fecha_col = None
        if "fecha" in frame.columns:
            fecha_col = "fecha"
        elif "FECHA" in frame.columns:
            fecha_col = "FECHA"
        elif "FECHA_CLEAN" in frame.columns:
            fecha_col = "FECHA_CLEAN"

        cols = [
            "plataforma", "contenido_post", "stance_post",
            "ScoreOP", "ScoreOP_pct", "topic"
        ]
        if fecha_col:
            cols.append(fecha_col)
        cols += extra
        # Añadir ScoreOP_sup a las columnas si existe (para que el frontend
        # pueda mostrar el badge "Agenda X")
        if "ScoreOP_sup" in frame.columns and "ScoreOP_sup" not in cols:
            cols.append("ScoreOP_sup")
        cols = [c for c in cols if c in frame.columns]

        if frame.empty:
            return []

        _has_sup = "ScoreOP_sup" in frame.columns

        if _has_sup:
            # Ordenar primero por ScoreOP_pct, luego por ScoreOP_sup como desempate
            # (igual que el dashboard principal con datos sin filtrar)
            asc_pct = not largest   # top: desc (False), bottom: asc (True)
            return (
                frame
                .sort_values(["ScoreOP_pct", "ScoreOP_sup"], ascending=[asc_pct, False])
                .head(10)[cols]
                .replace({float("nan"): ""})
                .to_dict("records")
            )
        else:
            fn = frame.nlargest if largest else frame.nsmallest
            return fn(10, "ScoreOP_pct")[cols].replace({float("nan"): ""}).to_dict("records")
 
    def _agg_pct_red_filtrado(grp):
        s = grp['ScoreOP'].sum()
        d = grp['ScoreOP_sup'].sum() if 'ScoreOP_sup' in grp.columns else 0
        norm = s/d if d > 0 else 0
        if d > 0:
            return round((norm + 1.0) / 2.0 * 100.0, 2)
        return round(float(grp['ScoreOP_pct'].mean()), 2)

    scoreop_pct_por_red = (
        df_filtrado.groupby('plataforma')
        .apply(_agg_pct_red_filtrado)
        .to_dict()
    )

    col_com = 'num_comentarios' if 'num_comentarios' in df_filtrado.columns else None
    N_por_red = {}
    for red, grp in df_filtrado.groupby('plataforma'):
        n_posts = len(grp)
        n_com = int(grp[col_com].fillna(0).sum()) if col_com else 0
        N_por_red[red] = n_posts + n_com

    total_N = sum(N_por_red.values()) or 1
    scoreop_pct_global = round(
        sum(scoreop_pct_por_red[r] * N_por_red.get(r, 0) for r in scoreop_pct_por_red)
        / total_N,
        2
    )
 
    dashboard_data["scoreop"] = {
        "disponible": True,
        "total_posts": len(df_filtrado),
        "scoreop_pct_global": scoreop_pct_global,
        "scoreop_pct_por_red": scoreop_pct_por_red,
        "por_plataforma": scoreop_por_plataforma,
        "tendencia_global": tendencia_scoreop,
        "tendencia_fuerza": {},
        "tendencia_red": tendencia_red_scoreop,
        "tendencia_red_pos": tendencia_red_fuerza_pos,
        "tendencia_red_neg": tendencia_red_fuerza_neg,
        "top_posts": _posts(df_filtrado, True),
        "bottom_posts": _posts(df_filtrado, False),
        "distribution": scoreop_dist,
        "dist_por_plataforma": dist_por_plat,
        "stats": {
            "media": _safe(df_filtrado['ScoreOP'].mean()),
            "mediana": _safe(df_filtrado['ScoreOP'].median()),
            "min": _safe(df_filtrado['ScoreOP'].min()),
            "max": _safe(df_filtrado['ScoreOP'].max()),
            "std": _safe(df_filtrado['ScoreOP'].std()),
            "pct_media": _safe(df_filtrado['ScoreOP_pct'].mean()),
            "pct_mediana": _safe(df_filtrado['ScoreOP_pct'].median()),
            "pct_min": _safe(df_filtrado['ScoreOP_pct'].min()),
            "pct_max": _safe(df_filtrado['ScoreOP_pct'].max()),
            "pct_std": _safe(df_filtrado['ScoreOP_pct'].std()),
        },
    }

 
    arg_stance_charts: dict = {}
    for meta in metadata_filtros:
        if meta["tipo"] == "argumento" and "stance_col" in meta:
            scol = meta["stance_col"]
            if scol in df_filtrado.columns:
                col_vals = pd.to_numeric(df_filtrado[scol], errors="coerce").fillna(2)
                arg_stance_charts[meta["termino"]] = {
                    "pos": int((col_vals == 1).sum()),
                    "neu": int((col_vals == 0).sum()),
                    "neg": int((col_vals == -1).sum()),
                    "col": scol,
                }
    dashboard_data["arg_stance"] = arg_stance_charts
 
    topic_col = "topic" if "topic" in df_filtrado.columns else None
    if topic_col:
        dashboard_data["topics"] = _calcular_topics_df(df_filtrado)
    else:
        dashboard_data["topics"] = []
 
    try:
        folder_path = Path(output_folder)
        
        df_comentarios_list = []
        for analizado_file in folder_path.glob("*_analizado.csv"):
            try:
                with open(analizado_file, "r", encoding="utf-8") as f:
                    sep_a = ";" if ";" in f.readline() else ","
                df_anal = pd.read_csv(analizado_file, sep=sep_a, encoding="utf-8", on_bad_lines="skip")
                
                if "tipo" in df_anal.columns:
                    df_anal = df_anal[df_anal["tipo"].str.lower().isin(["comentario", "comment"])]
                if "sentimiento" in df_anal.columns:
                    df_anal = df_anal[pd.to_numeric(df_anal["sentimiento"], errors="coerce").isin([-1, 0, 1])]
                
                if "plataforma" not in df_anal.columns:
                    plat = analizado_file.name.split("_")[0].lower()
                    df_anal["plataforma"] = plat
                
                if not df_anal.empty:
                    df_comentarios_list.append(df_anal)
            except Exception as e:
                print(f"  ⚠️ Error leyendo comentarios de {analizado_file.name}: {e}")
        
        df_comentarios_nubes = pd.concat(df_comentarios_list, ignore_index=True) if df_comentarios_list else None

        dashboard_data["nubes"] = generar_nubes_desde_df(
            df_filtrado,
            keywords=keywords,
            df_comentarios=df_comentarios_nubes
        )
    except Exception as e:
        print(f"  ⚠️ Error generando nubes en filtrado: {e}")
        dashboard_data["nubes"] = {}
    
    dashboard_data["raw_data"] = df_filtrado.fillna("").to_dict(orient="records")
    dashboard_data["filtros_aplicados"] = metadata_filtros
 
    return clean_types(dashboard_data)


# ================= ACCEPTANCE INDICATOR (PillarOP) =================

def _interpretar_pillarop(pct_medio: float) -> str:
    """Interpreta el valor normalizado de PillarOP."""
    if pct_medio >= 75: 
        return "Fuerte Consenso Activo Positivo"
    if pct_medio >= 57: 
        return "Consenso Moderado Positivo"
    if pct_medio >= 43: 
        return "Polarización / Neutralidad"
    if pct_medio >= 25: 
        return "Consenso Moderado Negativo"
    return "Fuerte Consenso Activo Negativo"


def _pilares_pendientes(folder_path: Path) -> list:
    """Detecta archivos que necesitan procesamiento de pilares con vLLM."""
    cols_pilares = [
        "legitimacion", "efectividad",
        "justicia_equidad", "confianza_institucional",
    ]
 
    archivos_analizado = list(folder_path.glob("*_analizado.csv"))
    if not archivos_analizado:
        return []
 
    pendientes: list = []
 
    for arch_analizado in archivos_analizado:
        stem_pilares = arch_analizado.name.replace("_analizado.csv", "_pilares.csv")
        ruta_pilares = folder_path / stem_pilares
 
        if not ruta_pilares.exists():
            print(f"   ⏳ {arch_analizado.name} → {stem_pilares} no existe. Pendiente.")
            pendientes.append(arch_analizado)
            continue
 
        try:
            with open(ruta_pilares, "r", encoding="utf-8") as f:
                sep = ";" if ";" in f.readline() else ","
            df = pd.read_csv(
                ruta_pilares, sep=sep, encoding="utf-8", on_bad_lines="skip"
            )
 
            cols_presentes = [c for c in cols_pilares if c in df.columns]
 
            if not cols_presentes:
                print(f"   ⏳ {stem_pilares}: sin columnas de pilares. Pendiente.")
                pendientes.append(arch_analizado)
                continue
 
            df_num = df[cols_presentes].apply(pd.to_numeric, errors="coerce")
            filas_nan = df_num.isna().all(axis=1)
 
            if filas_nan.any():
                print(f"   ⏳ {stem_pilares}: {int(filas_nan.sum())} filas sin procesar. Pendiente.")
                pendientes.append(arch_analizado)
                continue
 
            print(f"   ✅ {stem_pilares}: completo ({len(df)} filas). Saltando.")
 
        except Exception as e:
            print(f"   ⚠️ Error leyendo {stem_pilares}: {e}. Pendiente.")
            pendientes.append(arch_analizado)
 
    return pendientes


def ejecutar_indicador_aceptacion(db: Session, analysis_slug: str, user):
    """Ejecuta el cálculo de aceptación usando BBDD PostgreSQL."""
    try:
        analysis = db.query(Analysis).filter(Analysis.slug == analysis_slug, Analysis.user_id == user.id,).first()

        if not analysis:
            raise Exception(f"Análisis {analysis_slug} no encontrado")

        folder_path = Path(analysis.output_folder) if analysis.output_folder else None
        if not folder_path or not folder_path.exists():
            raise Exception("Carpeta del análisis no encontrada")

        cfg = analysis.analysis_config or {}
        tema_recuperado = cfg.get("tema") or analysis.project_name or "Análisis General"
        idiomas_recuperados = cfg.get("languages") or ["Castellano"]
        keywords_recuperadas = cfg.get("keywords") or []

        if isinstance(keywords_recuperadas, str):
            try:    
                keywords_recuperadas = json.loads(keywords_recuperadas)
            except: 
                keywords_recuperadas = []

        if keywords_recuperadas and isinstance(keywords_recuperadas[0], dict):
            keywords_recuperadas = [k.get("keyword", "") for k in keywords_recuperadas if k.get("keyword")]

        u_conf = SimpleNamespace(
            tema=tema_recuperado,
            desc_tema=cfg.get("desc_tema", ""),
            languages=idiomas_recuperados,
            population_scope=cfg.get("population_scope", "Público General"),
            tipo_tema=cfg.get("tipo_tema", "GLOBAL"),
            general={
                "keywords": keywords_recuperadas,
                "output_folder": str(folder_path),
            }
        )

        pendientes = _pilares_pendientes(folder_path)
        
        if not pendientes:
            print("✅ Todos los pilares ya están calculados.")
        else:
            nombres = [p.name for p in pendientes]
            print(f"🧠 Ejecutando vLLM Pilares para: {nombres}")
            procesar_pilares_directorio(u_conf, archivos=pendientes)

        metricas = Metrics()
        resultados = metricas.calcular_aceptacion_pilares(u_conf)

        pct_medio = resultados["global"].get("PillarOP_pct_medio", 0)
        resultados["interpretacion"] = _interpretar_pillarop(pct_medio)

        result_path = folder_path / "aceptacion_global.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)

        print(f"✅ PillarOP_pct_medio={pct_medio:.1f}%")
        return resultados

    except Exception as e:
        print(f"❌ Error: {e}")
        raise

def read_indicador_aceptacion(db: Session, analysis_slug: str, user):
    """Leer el cálculo de aceptación usando BBDD PostgreSQL."""
    try:
        analysis = db.query(Analysis).filter(Analysis.slug == analysis_slug, Analysis.user_id == user.id,).first()

        if not analysis:
            raise Exception(f"Análisis {analysis_slug} no encontrado")

        folder_path = Path(analysis.output_folder) if analysis.output_folder else None

        if not folder_path.exists():
            return {}
        
        result_path = folder_path / "aceptacion_global.json"

        if result_path.exists():
            with open(result_path, "r", encoding="utf-8") as f:
                resultados = json.load(f)
        else:
            resultados = {}
        
        return resultados
    

    except Exception as e:
        print(f"❌ Error: {e}")
        raise
    
def recalcular_aceptacion_filtrada(db: Session, analysis_slug: str, user, terminos_geo: list):
    """Filtra datos de aceptación por términos geográficos con LLM."""
    try:
        analysis = db.query(Analysis).filter(Analysis.slug == analysis_slug, Analysis.user_id == user.id,).first()

        if not analysis:
            return {"error": "Análisis no encontrado"}

        if not analysis.output_folder:
            return {"error": "El análisis no tiene output_folder"}

        cfg = analysis.analysis_config
        tema = cfg.get("tema", "")
        folder_path = Path(analysis.output_folder)
        archivos_pilares = list(folder_path.glob("*_pilares.csv"))
        #csv_path = folder_path / "*_pilares.csv"
        print(f"📄 Buscando datos en: {archivos_pilares}")

        if not archivos_pilares:
            print("🚀 Archivo no encontrado. Ejecutando cálculo automático...")
            try:
                ejecutar_indicador_aceptacion(db, analysis_slug, user)
                archivos_pilares = list(folder_path.glob("*_pilares.csv"))
            except Exception as e:
                return {"error": f"No se pudo generar el análisis: {str(e)}"}
                
        dfs: list[pd.DataFrame] = []
        for arch in archivos_pilares:
            try:
                with open(arch, "r", encoding="utf-8") as f:
                    sep = ";" if ";" in f.readline() else ","
                df_temp = pd.read_csv(arch, sep=sep, encoding="utf-8", on_bad_lines="skip")
    
                if "plataforma" not in df_temp.columns:
                    nombre = arch.name.lower()
                    if   "youtube"  in nombre: df_temp["plataforma"] = "youtube"
                    elif "reddit"   in nombre: df_temp["plataforma"] = "reddit"
                    elif "bluesky"  in nombre: df_temp["plataforma"] = "bluesky"
                    elif "telegram" in nombre: df_temp["plataforma"] = "telegram"
                    else:                      df_temp["plataforma"] = "otros"
    
                df_temp = cargar_columnas_cache(df_temp, arch)
                dfs.append(df_temp)
            except Exception as exc:
                print(f"Error leyendo {arch.name}: {exc}")
    
        if not dfs:
            return {"error": "No hay datos válidos para filtrar."}
    
        df = pd.concat(dfs, ignore_index=True)
        # ── Compatibilidad con CSVs antiguos sin columna texto_citado ─────────────
        if "texto_citado" not in df.columns:
            df["texto_citado"] = ""
        df["texto_citado"] = df["texto_citado"].fillna("").astype(str)
    
        # ── LLM geo filter ────────────────────────────────────────────────────────
        geo_terms = [t.strip() for t in (terminos_geo or []) if t.strip()]
        metadata_filtros: list[dict] = []
    
        if geo_terms:
            persist_path = archivos_pilares[0] if len(archivos_pilares) == 1 else None
            df_filtrado, metadata_filtros = aplicar_filtros_llm(
                df,
                terminos_geo   = geo_terms,
                terminos_topic = [],
                csv_path       = persist_path,
                tema           = tema,
            )
        else:
            df_filtrado = df.copy()
    
        if df_filtrado.empty:
            return {"error": "No hay resultados para este filtro geográfico."}
    
        # ── PillarOP on filtered data ─────────────────────────────────────────────
        metricas   = Metrics()
        resultados = metricas.calcular_aceptacion_desde_df(df_filtrado)
    
        pct_medio                       = resultados["global"].get("PillarOP_pct_medio", 0)
        resultados["interpretacion"]    = _interpretar_pillarop(pct_medio)
        resultados["filtros_aplicados"] = metadata_filtros
    
        return resultados

    except Exception as e:
        print(f"❌ Error: {e}")
        return {"error": str(e)}
'''
        with open(csv_path, "r", encoding="utf-8") as f:
            sep = ";" if ";" in f.readline() else ","

        df = pd.read_csv(csv_path, sep=sep, encoding="utf-8", engine="python")
        df.columns = [c.upper() for c in df.columns]

        if "RED_SOCIAL" in df.columns:
            df.rename(columns={"RED_SOCIAL": "FUENTE"}, inplace=True)

        for col in ["CONTENIDO", "TITULO", "CUERPO"]:
            if col in df.columns:
                df[col] = df[col].fillna("").astype(str)

        if terminos_geo:
            patron = "|".join([re.escape(t.strip()) for t in terminos_geo if t.strip()])
            mask = (
                df["CONTENIDO"].str.contains(patron, case=False, na=False) |
                df["TITULO"].str.contains(patron, case=False, na=False)
            )
            df_filtrado = df[mask].copy()
        else:
            df_filtrado = df.copy()

        from clean_project.analysis.metrics import (
            aceptacion_global_promedio_pilares,
            generar_informe,
            PILARES
        )

        all_rows = [(red, group.copy()) for red, group in df_filtrado.groupby("FUENTE")]
        resultados = aceptacion_global_promedio_pilares(all_rows, PILARES)

        return generar_informe(resultados, all_rows, PILARES)

    except Exception as e:
        print(f"❌ Error: {e}")
        return {"error": str(e)}
'''

# ================= CONFIGURATION =================

def crear_config_dinamica(data, existing_output_folder=None):
    print("⚙️ Creando configuración aislada...")

    # 1. Estructura base
    u_conf = SimpleNamespace(
        general=copy.deepcopy(base_settings.general),
        scraping=copy.deepcopy(base_settings.scraping),
        keywords_base=[],
        CREDENTIALS=base_settings.CREDENTIALS 
    )

    # 2. Fechas
    u_conf.general["start_date"] = data.get("start_date")
    u_conf.general["end_date"] = data.get("end_date")
    u_conf.desc_tema = data.get("desc_tema") or "Sin descripción disponible" 

    # 3. Carpeta de Salida
    if existing_output_folder:
        output_path = Path(existing_output_folder)
        u_conf.general["output_folder"] = str(output_path)
    else:
        project_name = data.get("project_name", "sin_nombre")#.replace(" ", "_")
        output_path = BASE_DIR_1 / "datos" / f"{data.get('username')}/{project_name}"
        i=0
        while output_path.exists():
            i += 1
            output_path = BASE_DIR_1 / "datos" / f"{data.get('username')}/{project_name} ({i})"
        output_path.mkdir(parents=True, exist_ok=True)
        u_conf.general["output_folder"] = str(output_path)

    # 4. Credenciales (Resumido para no ocupar espacio, mantén tu lógica de credenciales aquí)
    creds = u_conf.CREDENTIALS
    if "bluesky" in creds:
        u_conf.USERNAME_bluesky = creds["bluesky"].get("USERNAME_bluesky", "")
        u_conf.PASSWORD_bluesky = creds["bluesky"].get("PASSWORD_bluesky", "")
    # ... (Mantén el resto de tus credenciales igual) ...
    if "reddit" in creds:
        u_conf.REDDIT_CLIENT_ID = creds["reddit"].get("reddit_client_id", "")
        u_conf.REDDIT_CLIENT_SECRET = creds["reddit"].get("reddit_client_secret", "")

    # 5. Procesamiento de Keywords y Idiomas
    raw_keywords = data.get("keywords", [])
    if isinstance(raw_keywords, str):
        try: raw_keywords = json.loads(raw_keywords)  # convertir string JSON a lista de dicts
        except: raw_keywords = []

    unique_search_forms = []
    search_form_lang_map = {}
    for item in raw_keywords:
        if isinstance(item, dict) and item.get("keyword"):
            keyword = item["keyword"]
            language = item.get("languages")
            unique_search_forms.append(item.get("keyword"))
            search_form_lang_map[keyword] = [language]  # ⚠️ lista de idiomas por keyword
    
    # Guardar en configuración
    u_conf.general["keywords"] = unique_search_forms
    u_conf.general["search_form_lang_map"] = search_form_lang_map
    for red in u_conf.scraping:
        u_conf.scraping[red]["query"] = unique_search_forms
    # Dentro de crear_config_dinamica()
    # u_conf.general["search_form_lang_map"] = {}

    # for kw in unique_search_forms:
    #     # Aquí asignas los idiomas que quieras para cada keyword
    #     u_conf.general["search_form_lang_map"][kw] = u_conf.languages
    
    ## u_conf.keywords = unique_search_forms  # 🔥 AÑADIR ESTA LÍNEA
    # 6. ASIGNACIÓN CRÍTICA DE VARIABLES PARA EL PROMPT
    # Tema
    u_conf.tema = data.get("tema") or data.get("asistente") or "Análisis General"
    
    # Idiomas (Asegurar que sea lista)
    raw_langs = data.get("languages", [])
    if isinstance(raw_langs, str):
        u_conf.languages = [raw_langs]
    else:
        u_conf.languages = raw_langs if raw_langs else ["Español"] # Default si vacío

    # Geo Scope / Population (Manejo del string vacío del JSON)
    raw_pop = data.get("population_scope") or data.get("population") or ""
    
    if isinstance(raw_pop, list):
        # Si ya es lista, úsala, si está vacía pon Global
        u_conf.geo_scope = ", ".join(raw_pop) if raw_pop else "Público General"
    elif isinstance(raw_pop, str):
        # Si es string y no está vacío, úsalo. Si es "", pon Global
        u_conf.geo_scope = raw_pop if raw_pop.strip() else "Público General"
    else:
        u_conf.geo_scope = "Público General"

    # Asignamos population_scope igual para compatibilidad
    u_conf.population_scope = u_conf.geo_scope

    u_conf.tipo_tema = data.get("tipo_tema", "GLOBAL")
 
    print(f"Configuración lista. Tema: {u_conf.tema} | Idiomas: {u_conf.languages} | Geo: {u_conf.geo_scope} | Tipo: {u_conf.tipo_tema}")
    
    return u_conf


# ================= MAIN BACKEND ANALYSIS =================

def relanzar_llm_si_pendiente(u_conf):
    """
    Si existen *_global_dataset.csv sin su *_analizado.csv correspondiente,
    relanza el análisis LLM SOLO para esos archivos pendientes.
    Los ya procesados se ocultan temporalmente con extensión .skip
    para que vllm_sentiment_analysis no los retoque.
    """
    folder = Path(u_conf.general["output_folder"])

    datasets = list(folder.glob("*_global_dataset.csv"))
    if not datasets:
        print("⚠️ No hay _global_dataset.csv. Nada que relanzar.")
        return False

    pendientes    = []
    ya_procesados = []
    for ds in datasets:
        analizado = ds.with_name(ds.stem + "_analizado.csv")
        if analizado.exists():
            ya_procesados.append(ds)
        else:
            pendientes.append(ds)

    if not pendientes:
        print("✅ Todos los datasets ya tienen su _analizado.csv. No se relanza el LLM.")
        return False

    print(f"🔁 Datasets pendientes: {[p.name for p in pendientes]}")
    print(f"⏭️  Datasets ya procesados (se ocultarán temporalmente): {[p.name for p in ya_procesados]}")

    # ── Ocultar los ya procesados para que vLLM los ignore ────────────────
    renombrados: list[tuple[Path, Path]] = []
    for ds in ya_procesados:
        tmp = ds.with_suffix(".csv.skip")
        try:
            ds.rename(tmp)
            renombrados.append((tmp, ds))
        except Exception as e:
            print(f"⚠️ No se pudo ocultar {ds.name}: {e}")

    try:
        vllm_sentiment_analysis(u_conf)
        return True
    except Exception as e:
        print(f"❌ Error relanzando LLM: {e}")
        return False
    finally:
        # ── Restaurar siempre, aunque haya error ─────────────────────────
        for tmp, original in renombrados:
            if tmp.exists():
                try:
                    tmp.rename(original)
                except Exception as e:
                    print(f"⚠️ No se pudo restaurar {original.name}: {e}")


_PROGRESS: dict = {}
_CANCEL_FLAGS: dict = {}

def _set_progress(task_id: int, db: Session, paso: str, mensaje: str, 
                  porcentaje: int, error: bool = False):
    """Actualiza progreso de la tarea en BBDD."""
    try:
        TaskService.update_status(
            db=db,
            task_id=task_id,
            status=TaskStatus.RUNNING if not error else TaskStatus.FAILED,
            message=mensaje,
            progress_percent=porcentaje,
            current_step=paso
        )
    except Exception as e:
        print(f"⚠️ Error actualizando tarea: {e}")


async def backend_analisis(db: Session, data, analysis_id, task_id):
    """Pipeline principal de análisis asincrónico."""
    print("######################")
    print("BACKEND ANALISIS START")
    print("######################")
    
    name_redes = {"youtube":"YouTube", "reddit":"Reddit", 
                "bluesky":"BlueSky", "telegram":"Telegram", "linkedin":"LinkedIn",
                "tiktok":"TikTok"}
    _set_progress(task_id, db, "inicio", "Configurando el análisis…", 2)
    print("############################")
    print(name_redes)

    try:
        u_conf = crear_config_dinamica(data)
        output_folder = Path(u_conf.general["output_folder"])
        print(u_conf)
        try:
            analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
            if analysis: 
                cfg = analysis.analysis_config
                print("############################")
                print("############################")
                print("Banckend config")
                print(f"cfg: {cfg}")
                print(f"data: {data}")
                print(f"u_conf: {u_conf}")
                print("############################")
                print("############################")
                if data.get("tema") or data.get("asistente"):
                    cfg["tema"] = data.get("tema") or data.get("asistente")

                if "desc_tema" in data:
                    cfg["desc_tema"] = data["desc_tema"]

                if "keywords" in data:
                    cfg["keywords"] = data["keywords"]

                if "languages" in data:
                    cfg["languages"] = data["languages"]

                if u_conf.population_scope is not None:
                    cfg["population_scope"] = u_conf.population_scope

                if u_conf.tipo_tema is not None:
                    cfg["tipo_tema"] = u_conf.tipo_tema
                
                analysis.analysis_config.update(cfg)
                analysis.status = AnalysisStatus.ACTIVE
                db.commit()
        except Exception as e:
            print(f"⚠️ Error actualizando análisis: {e}")
 
    except Exception as e:
        _set_progress(task_id, db, "error", f"Error en config: {e}", 0, error=True)
        db.commit()
        return {"error": str(e)}
 
    # ── SCRAPERS ──────────────────────────────────────────────────────
    redes_seleccionadas = data.get("sources", [])
    n_redes = max(len(redes_seleccionadas), 1)
    pct_por_red = 45 // n_redes
 
    for i, red in enumerate(redes_seleccionadas):
        pct_inicio = 5 + i * pct_por_red
        #print("red =", repr(red))
        #print("name_redes =", name_redes)
        _set_progress(task_id, db, f"scraping_{red}", 
                     f"Descargando {name_redes[red]}…", pct_inicio)

        try:
            if red == "bluesky":
                await run_bluesky(u_conf)
            elif red == "reddit":
                await run_reddit(u_conf)
            elif red == "youtube":
                await run_youtube(u_conf)
            elif red == "telegram":
                await run_telegram(u_conf)

            _set_progress(task_id, db, f"scraping_{red}_ok",
                         f"{red}: descarga OK ✓", pct_inicio + pct_por_red - 1)

        except Exception as e:
            print(f"❌ Error {red}: {e}")
            _set_progress(task_id, db, f"scraping_{red}_error",
                         f"{red}: error ({e})", pct_inicio + pct_por_red - 1, error=True)

    # ── LLM ANALYSIS ──────────────────────────────────────────────────
    _set_progress(task_id, db, "sentiment", "Analizando con IA…", 52)
    try:
        vllm_sentiment_analysis(u_conf)
        _set_progress(task_id, db, "sentiment_ok", "Análisis de sentimiento OK ✓", 65)
    except Exception as e:
        print(f"❌ Error LLM: {e}")
        try:
            if relanzar_llm_si_pendiente(u_conf):
                _set_progress(task_id, db, "sentiment_ok", 
                            "Análisis completado (reintento) ✓", 65)
            else:
                _set_progress(task_id, db, "sentiment_error",
                            f"Aviso: error parcial ({e})", 65, error=True)
        except Exception as e2:
            _set_progress(task_id, db, "sentiment_error",
                        f"Aviso: error ({e2})", 65, error=True)

    # ── SCOREOP ───────────────────────────────────────────────────────
    _set_progress(task_id, db, "scoreop", "Calculando ScoreOP…", 67)
    try:
        ejecutar_scoreop_desde_logica(u_conf)
        _set_progress(task_id, db, "scoreop_ok", "ScoreOP calculado ✓", 75)
    except Exception as e:
        print(f"❌ Error ScoreOP: {e}")
        _set_progress(task_id, db, "scoreop_error", f"Aviso: error ({e})", 75, error=True)

    # ── REPORTING ──────────────────────────────────────────────────────
    _set_progress(task_id, db, "reporte", "Generando reportes…", 78)
    try:
        all_rows = cargar_datos_para_reporte(u_conf)
        output_folder_path = Path(u_conf.general["output_folder"])

        if all_rows:
            df_final, _ = generar_excel_sentimiento(all_rows, output_folder_path)

            if df_final is not None and not df_final.empty:
                col_map = {
                    "sentimiento": "SENTIMIENTO",
                    "topic": "TOPIC",
                    "contenido": "CONTENIDO",
                    "fecha": "FECHA"
                }
                df_final.rename(columns=col_map, inplace=True)
                df_final.attrs["output_folder"] = str(output_folder_path)

                dashboard_base = calcular_dashboard_base(df_final)
                dashboard_base["raw_data"] = df_final.fillna("").to_dict("records")

                with open(output_folder_path / "dashboard_data.json", "w", encoding="utf-8") as f:
                    json.dump(dashboard_base, f, indent=2, default=str)

        _set_progress(task_id, db, "reporte_ok", "Reportes OK ✓", 88)

    except Exception as e:
        print(f"❌ Error reporting: {e}")
        _set_progress(task_id, db, "reporte_error", f"Aviso: error ({e})", 88, error=True)

    # ── WORD CLOUDS ───────────────────────────────────────────────────
    _set_progress(task_id, db, "nubes", "Generando nubes…", 90)
    try:
        asegurar_nubes_dashboard(
            Path(u_conf.general["output_folder"]),
            keywords=u_conf.general.get("keywords", [])
        )
        _set_progress(task_id, db, "nubes_ok", "Nubes OK ✓", 95)
    except Exception as e:
        print(f"❌ Error nubes: {e}")
        _set_progress(task_id, db, "nubes_error", f"Aviso: error ({e})", 95, error=True)

    # ── FINALIZE ───────────────────────────────────────────────────────
    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis:
            analysis.status = AnalysisStatus.COMPLETED
            analysis.progress_percent = 100
            db.commit()
    except Exception as e:
        print(f"⚠️ Error finalizando: {e}")

    _set_progress(task_id, db, "completado", "¡Análisis completado!", 100)

    return {
        "mensaje": "Análisis completado",
        "analysis_id": analysis_id,
        "output_folder": str(output_folder),
    }


def recalcular_filas_incompletas(df):
    '''
    cols_indicadores = [
        'sent_Legitimación_sociopolítica',
        'sent_Efectividad_percibida',
        'sent_Justicia_y_equidad_percibida',
        'sent_Confianza_y_legitimidad_institucional'
    ]
    
    filas_incompletas = df[df[cols_indicadores].isna().any(axis=1)]
    for idx, fila in filas_incompletas.iterrows():
        resultados = vllm_pilares_analysis(fila) # ejecutar_pilares_analysis(fila)
        for col in cols_indicadores:
            df.at[idx, col] = resultados.get(col, 0)
    '''
    return df
# ====================================================
# Implementa las tres representaciones:

#   1. construir_nube_bigramas  
#   2. construir_nube_topicos    
#   3. construir_grafo_bipartito 


from collections import Counter, defaultdict
from typing import Optional

# ── Stopwords (misma cadena que main.py / nube.py) ──────────────────────────
try:
    from nltk.corpus import stopwords as _nltk_sw
    _SW_ES = set(_nltk_sw.words("spanish"))
    _SW_EN = set(_nltk_sw.words("english"))
except Exception:
    _SW_ES = set()
    _SW_EN = set()
try:
    import simplemma as _sm
    _SM_LANGS = ("es", "en", "ca", "pt", "fr", "it")
    _SM_OK = True
except ImportError:
    _SM_OK = False

try:
    import unidecode as _ud
    _UD_OK = True
except ImportError:
    _UD_OK = False

_STOPS_MANUAL = {
    "para", "como", "pero", "porque", "sobre", "desde", "hasta",
    "esto", "esta", "este", "todos", "todas", "solo", "bien",
    "también", "aunque", "puede", "después", "antes", "entre",
    "mismo", "cada", "otro", "otra", "también", "decir", "hacer",
    "tener", "poder", "saber", "https", "http",
}

_RUIDO_SOCIAL = {
    "si", "no", "así", "hacer", "ver", "ir", "tan", "cada", "bien", "solo", "hace",
    "donde", "todo", "toda", "pero", "bueno", "muchas", "felicidades", "gracias", "hola",
    "twitter", "reddit", "bluesky", "youtube", "tiktok", "facebook", "instagram",
    "whatsapp", "telegram", "linkedin", "suscribete", "siguenos", "canal", "pagina", 
    "visita", "enlace", "link", "suscribirse", "subscribe", "follow", "unfollow", 
    "compartir", "share", "comentario", "comment", "reply", "retweet", "like", "story", 
    "stories", "https", "http", "www", "post", "video", "foto", "imagen",
    "also", "just", "that", "this", "with", "from", "have", "been", "they", "will",
    "when", "said", "were", "more", "than", "some", "what", "about", "would", "could",
    "their", "there", "which", "after", "before", "other", "people", "think",
    "nuevo", "nueva", "nuevas", "nuevos", "paso", "pasos", "todas", "usar", "seis",
    "centro", "centros", "distritos", "estacion", "estaciones", "operativas",
    "previsible", "visible", "realiza", "realización", "conduccion", "millones",
    "euros", "mayo", "instax", "txivismo", "biciurbana", "callesdemadrid", 
    "madridenbici", "enbicipormadrid", "pasionmadrid", "madciclista", "modelomadrid", "callemadrid", "dale campanita",
}
_STOPS = _SW_ES | _SW_EN | _STOPS_MANUAL | _RUIDO_SOCIAL
_STOPS_NORM = {_ud.unidecode(w) for w in _STOPS} if _UD_OK else _STOPS


# ══════════════════════════════════════════════════════════════════════════════
# 0. Utilidades comunes
# ══════════════════════════════════════════════════════════════════════════════
def _limpiar_texto(texto: str) -> str:
    texto = str(texto).lower()
    texto = re.sub(r"http\S+|[@#]\S+", "", texto)
    texto = re.sub(r"[^\w\sáéíóúüñàèìòùâêîôûäëïöüãõç]", " ", texto)
    texto = re.sub(r"_+|\s+", " ", texto).strip()
    return texto

def _lematizar(tokens: list) -> list:
    if not _SM_OK:
        return tokens
    out = []
    for w in tokens:
        try:
            out.append(_sm.lemmatize(w, lang=_SM_LANGS))
        except Exception:
            out.append(w)
    return out

def _filtrar_tokens(tokens: list, extra_stops: set = None) -> list:
    stops = _STOPS | (extra_stops or set())
    stops_norm = _STOPS_NORM | ({_ud.unidecode(w) for w in (extra_stops or set())} if _UD_OK else set())
    return [
        w for w in tokens
        if len(w) > 3
        and w not in stops
        and (_ud.unidecode(w) not in stops_norm if _UD_OK else True)
    ]

def _tokenizar_post(contenido: str, extra_stops: set = None) -> list:
    """Pipeline completo: limpia → tokeniza → lematiza → filtra stopwords."""
    texto = _limpiar_texto(contenido)
    tokens = [w for w in texto.split() if len(w) > 2]
    tokens = _lematizar(tokens)
    return _filtrar_tokens(tokens, extra_stops)

# ══════════════════════════════════════════════════════════════════════════════
# 1. Factor de peso Wi por plataforma (ecuaciones 37–39 del PDF)
# ══════════════════════════════════════════════════════════════════════════════

def _calcular_wi(df_posts: pd.DataFrame) -> pd.Series:
    print("[TRACE _calcular_wi] Llamada desde:")
    traceback.print_stack(limit=5)
    """
    Calcula el factor de peso Wi normalizado por plataforma.
    Robusto ante columnas ausentes (karma, seguidores, vistas, suscriptores).
    """
    wi = pd.Series(1.0, index=df_posts.index)

    def _col_numeric(sub: pd.DataFrame, *nombres_alias, default=0.0) -> pd.Series:
        """
        Busca la primera columna disponible entre los alias dados.
        Si ninguna existe, devuelve una Serie de `default`.
        Siempre devuelve pd.Series (nunca int/float), lista para fillna/clip.
        """
        for nombre in nombres_alias:
            if nombre in sub.columns:
                return pd.to_numeric(sub[nombre], errors="coerce").fillna(default)
        # Columna ausente: devolver Serie de default con el índice correcto
        return pd.Series(default, index=sub.index, dtype=float)

    for plat, idx in df_posts.groupby("plataforma").groups.items():
        sub = df_posts.loc[idx]
        plat_lower = str(plat).lower()

        if "youtube" in plat_lower:
            V = _col_numeric(sub, "vistas", "views")
            S = _col_numeric(sub, "suscriptores", "subscribers")
            Vt, St = V.sum(), S.sum()
            fv = (1 + np.log1p(V / Vt)) if Vt > 0 else pd.Series(1.0, index=idx)
            fs = (1 + np.log1p(S / St)) if St > 0 else pd.Series(1.0, index=idx)
            wi_plat = fv * fs

        elif "bluesky" in plat_lower:
            F = _col_numeric(sub, "seguidores", "followers")
            Ft = F.sum()
            wi_plat = (1 + np.log1p(F / Ft)) if Ft > 0 else pd.Series(1.0, index=idx)

        elif "reddit" in plat_lower:
            K = _col_numeric(sub, "karma").clip(lower=0)
            Kt = K.sum()
            wi_plat = (1 + np.log1p(K / Kt)) if Kt > 0 else pd.Series(1.0, index=idx)
        elif "telegram" in plat_lower:
            '''         ROMINAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
                        ROMINA
            '''
            print("ROMINA FALTA TELEGRAM: CALCULAR WI") #PARECE QUE NO SE LLAMA
            pass
        else:
            wi_plat = pd.Series(1.0, index=idx)

        # Normalización inter-plataforma
        max_wi = wi_plat.max()
        if max_wi > 0:
            wi_plat = wi_plat / max_wi

        wi.loc[idx] = wi_plat.values

    return wi

def _umbral_adaptativo(valores: list, percentil: float = 0.80, minimo_abs: int = 2) -> float:
    """
    Calcula un umbral que combina percentil dinámico y mínimo absoluto.

    Ejemplo: percentil=0.80 significa "top 20% de valores".
    Si el valor en el percentil es menor que minimo_abs, usa minimo_abs.

    Esto garantiza:
    - En datasets grandes: se muestran solo los más relevantes (percentil)
    - En datasets pequeños: siempre hay algo que mostrar (mínimo absoluto)
    """
    if not valores:
        return minimo_abs
    arr = sorted(valores, reverse=True)
    idx = max(0, int(len(arr) * (1 - percentil)) - 1)
    umbral_pct = arr[idx] if idx < len(arr) else arr[-1]
    return max(umbral_pct, float(minimo_abs))
# ══════════════════════════════════════════════════════════════════════════════
# 2. Nube de bigramas (PDF ecuaciones 40–42)
# ══════════════════════════════════════════════════════════════════════════════

def _coherencia_bigrama_heuristica(bigrama: tuple, posicion_post: int, contenido: str) -> int:
    """
    Aproximación heurística a ci,b (PDF eq. 42).

    El ABSA completo requiere una llamada LLM por (post, bigrama), lo que es
    prohibitivo en tiempo real para cientos de posts. Se usa una heurística
    basada en la Teoría de la Estructura Retórica (RST):

      - Si la posición del post es neutra (0): ci,b = 1 siempre (no hay
        postura a contradecir).
      - Si el bigrama contiene términos de contraste explícito ("pero",
        "aunque", "sin embargo", "a pesar", "no", "nunca", "jamás"):
        ci,b = 0  (el bigrama probablemente invierte la postura).
      - En caso contrario: ci,b = 1.

    # TODO (ABSA diferido): Para mayor precisión, sustituir esta función
    # por una llamada batch al LLM con el prompt:
    #   "¿El fragmento «{bigrama}» apoya (+1) o contradice (0) la postura
    #    global del post «{contenido[:200]}» cuya posición es {posicion_post}?"
    # Referencia: Pontiki et al. (2014) SemEval Task 4; Zhang et al. (2022)
    # "A Survey on Aspect-Based Sentiment Analysis".

    Parámetros
    ----------
    bigrama      : par de lemas (w1, w2)
    posicion_post: sentimiento del post ∈ {-1, 0, 1}
    contenido    : texto completo del post (para buscar marcadores RST)
    """
    if posicion_post == 0:
        return 1  # post neutro: no hay postura que contradecir

    MARCADORES_CONTRASTE = {
        "pero", "aunque", "sin embargo", "a pesar", "no obstante",
        "empero", "mas", "sino", "excepto", "salvo",
        "no", "nunca", "jamás", "tampoco", "ningún", "ninguna",
    }
    texto_bajo = contenido.lower()
    b_str = " ".join(bigrama)

    # Buscar si el bigrama aparece en un contexto de contraste
    for marcador in MARCADORES_CONTRASTE:
        # Ventana de 8 palabras antes del bigrama
        patron = rf"{re.escape(marcador)}\s+(?:\w+\s+){{0,6}}{re.escape(b_str)}"
        if re.search(patron, texto_bajo):
            return 0  # contraste → incoherente con la postura global

    return 1


def construir_nube_bigramas(
    df_all: pd.DataFrame,
    df_scoreop: Optional[pd.DataFrame],
    keywords: list,
    top_n: int = 40,
    folder: Path = None,
    tema: str = "",
    usar_coherencia_llm: bool = True,
) -> list:
    """
    Construye los top_n bigramas según PDF §A.4.2 con coherencia LLM real.

    Mejoras respecto a la versión anterior:
    - Coherencia (Ib) calculada por LLM con cache en CSV
    - Umbral adaptativo: solo bigramas en top percentil de Sb
    - Devuelve también sent_topic_medio (sentimiento del topic del post)
      para distinguir postura sobre el tema vs sentimiento argumental
    """
    TIPOS_POST = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}

    # Usar 'posicion' sobre el tema si existe, si no 'sent_num'
    col_posicion = "sent_num"   # ya normalizado en _cargar_analizado_csvs

    posts = df_all[df_all["tipo_norm"].isin(TIPOS_POST) & (df_all[col_posicion] != 2)].copy()
    if posts.empty:
        return []

    # Stopwords extra: keywords de búsqueda
    extra_stops = set()
    for kw in (keywords or []):
        for tok in _limpiar_texto(kw).split():
            if len(tok) > 2:
                extra_stops.add(tok)
                if _UD_OK:
                    extra_stops.add(_ud.unidecode(tok))

    wi = _calcular_wi(posts)

    # Acumuladores
    bigrama_posts   = defaultdict(set)
    bigrama_wi      = defaultdict(float)
    bigrama_pi      = defaultdict(list)   # posicion sobre el tema
    bigrama_si      = defaultdict(list)   # sentimiento del topic
    bigrama_pct     = defaultdict(list)
    bigrama_posts_data = defaultdict(list)  # para coherencia LLM

    col_contenido = "contenido" if "contenido" in posts.columns else "contenido_post"

    for idx, row in posts.iterrows():
        contenido = str(row.get(col_contenido, "") or "")
        posicion  = int(row.get(col_posicion, 0))
        sent_top  = int(row.get("sent_topic", posicion))
        w_i       = float(wi.loc[idx])
        post_id   = str(row.get("_anchor_own", idx))

        tokens = _tokenizar_post(contenido, extra_stops)
        if len(tokens) < 2:
            continue

        bigramas_post = set(zip(tokens[:-1], tokens[1:]))
        for bg in bigramas_post:
            bigrama_posts[bg].add(idx)
            bigrama_wi[bg]  += w_i
            bigrama_pi[bg].append(posicion)
            bigrama_si[bg].append(sent_top)
            bigrama_posts_data[bg].append({
                "post_id":   post_id,
                "contenido": contenido,
                "posicion":  posicion,
            })
            if "ScoreOP_pct" in row.index:
                bigrama_pct[bg].append(float(row.get("ScoreOP_pct", 50)))

    if not bigrama_posts:
        return []

    # Calcular Sb para umbral adaptativo
    sb_vals = {
        bg: len(post_idx) * bigrama_wi[bg]
        for bg, post_idx in bigrama_posts.items()
    }
    umbral_sb = _umbral_adaptativo(list(sb_vals.values()), percentil=0.80, minimo_abs=2)

    # Filtrar candidatos por umbral antes de la coherencia LLM (evita calcular todo)
    candidatos = {
        bg: post_idx
        for bg, post_idx in bigrama_posts.items()
        if sb_vals[bg] >= umbral_sb
    }
    # Tomar top_n*2 para dejar margen tras aplicar coherencia
    candidatos_ordenados = sorted(candidatos.items(), key=lambda x: sb_vals[x[0]], reverse=True)
    candidatos_top = dict(candidatos_ordenados[:top_n * 2])

    # ── Coherencia LLM (o heurística si no hay folder/tema) ──────────────────
    coh_cache: dict = {}
    if usar_coherencia_llm and folder is not None:
        # Preparar lista de (post, terminos) para el LLM
        posts_para_llm = []
        for bg in candidatos_top:
            bg_str = f"{bg[0]} {bg[1]}"
            for item in bigrama_posts_data[bg][:5]:  # max 5 posts por bigrama
                posts_para_llm.append({
                    "post_id":   item["post_id"],
                    "contenido": item["contenido"],
                    "posicion":  item["posicion"],
                    "terminos":  [bg_str],
                })
        # Deduplicar por (post_id, termino)
        vistos = set()
        posts_para_llm_dedup = []
        for p in posts_para_llm:
            k = f"{p['post_id']}::{p['terminos'][0]}"
            if k not in vistos:
                vistos.add(k)
                posts_para_llm_dedup.append(p)

        coh_cache = _calcular_coherencia_llm_batch(
            posts_para_llm_dedup, folder=folder, tema=tema
        )

    # ── Calcular métricas finales ─────────────────────────────────────────────
    resultados = []
    for bg, post_idx in candidatos_top.items():
        Nb  = len(post_idx)
        Sb  = sb_vals[bg]
        Cb  = sum(bigrama_pi[bg]) / len(bigrama_pi[bg])   # eq. 41: posición sobre tema
        St  = sum(bigrama_si[bg]) / len(bigrama_si[bg])   # sentimiento argumental (topic)
        bg_str = f"{bg[0]} {bg[1]}"

        # Coherencia: media de ci,b de todos los posts del bigrama (eq. 42)
        if coh_cache:
            ci_vals = []
            for item in bigrama_posts_data[bg]:
                key = f"{item['post_id']}::{bg_str}"
                if key in coh_cache:
                    ci_vals.append(coh_cache[key])
            Ib = sum(ci_vals) / len(ci_vals) if ci_vals else 0.5
        else:
            # Heurística fallback (eq. 42 aproximada)
            Ib = _coherencia_bigrama_heuristica(
                bg,
                int(round(Cb)),
                " ".join(item["contenido"] for item in bigrama_posts_data[bg][:3])
            )

        pct_medio = (
            sum(bigrama_pct[bg]) / len(bigrama_pct[bg])
            if bigrama_pct[bg] else 50.0
        )

        resultados.append({
            "text":              bg_str,
            "Sb":                round(Sb, 4),
            "Cb":                round(Cb, 4),   # posición sobre el tema
            "Cb_topic":          round(St, 4),   # sentimiento del argumento
            "Ib":                round(max(0.05, Ib), 4),
            "Nb":                Nb,
            "scoreop_pct_medio": round(pct_medio, 2),
        })

    resultados.sort(key=lambda x: x["Sb"], reverse=True)
    return resultados[:top_n]
def _betweenness_approx(nodes: list, edges: list, max_nodes: int = 200) -> dict:
    """
    Centralidad de intermediación aproximada por muestreo de caminos.

    No está en el PDF pero es estándar en el análisis de redes sociodigitales
    (Himelboim et al., 2017) para identificar "usuarios puente".
    Solo se calcula si hay ≤ max_nodes nodos (evitar O(n³) en grafos grandes).

    # NOTA: Para grafos grandes, usar networkx.betweenness_centrality
    # con k=min(100, n) para aproximación por muestreo.
    # Referencia: Brandes (2001) "A Faster Algorithm for Betweenness Centrality".
    """
    if len(nodes) > max_nodes:
        return {n["id"]: 0.0 for n in nodes}

    try:
        import networkx as nx
        G = nx.Graph()
        G.add_nodes_from([n["id"] for n in nodes])
        G.add_edges_from([(e["source"], e["target"]) for e in edges])
        k = min(50, len(nodes))
        bc = nx.betweenness_centrality(G, k=k, normalized=True)
        return bc
    except ImportError:
        # networkx no disponible: devolver ceros
        # # NOTA: pip install networkx para activar esta métrica
        return {n["id"]: 0.0 for n in nodes}


def construir_nube_topicos(
    df_all: pd.DataFrame,
    df_scoreop: Optional[pd.DataFrame],
    top_n: int = 20,
    percentil_umbral: float = 0.70,
) -> list:
    """
    Construye los top_n tópicos con umbral adaptativo.
    
    Mejoras:
    - Umbral percentil + mínimo absoluto (no siempre top-15 fijo)
    - Devuelve coherencia (Ib_topic) basada en concordancia
      entre sentimiento_topic y posición sobre el tema
    - Incluye plataformas donde aparece el tópico
    """
    TIPOS_POST = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}
    EXCLUIR    = {"sin topic", "no relacionado", "otros", "error", ""}

    posts = df_all[df_all["tipo_norm"].isin(TIPOS_POST) & (df_all["sent_num"] != 2)].copy()
    if posts.empty or "topic" not in posts.columns:
        return []

    wi = _calcular_wi(posts)

    topico_wi:    dict = defaultdict(float)
    topico_pi:    dict = defaultdict(list)   # posicion sobre tema
    topico_si:    dict = defaultdict(list)   # sentimiento del topic (argumental)
    topico_cnt:   dict = Counter()
    topico_pct:   dict = defaultdict(list)
    topico_plats: dict = defaultdict(set)

    for idx, row in posts.iterrows():
        topic    = str(row.get("topic", "") or "").strip().lower()
        posicion = int(row.get("sent_num", 0))
        sent_top = int(row.get("sent_topic", posicion))
        w_i      = float(wi.loc[idx])
        plat     = str(row.get("plataforma", ""))

        if topic in EXCLUIR:
            continue

        topico_wi[topic]    += w_i
        topico_pi[topic].append(posicion)
        topico_si[topic].append(sent_top)
        topico_cnt[topic]   += 1
        topico_plats[topic].add(plat)

        if "ScoreOP_pct" in row.index:
            topico_pct[topic].append(float(row.get("ScoreOP_pct", 50)))

    if not topico_cnt:
        return []

    # Umbral adaptativo por St
    st_vals = {t: topico_cnt[t] * topico_wi[t] for t in topico_cnt}
    umbral_st = _umbral_adaptativo(list(st_vals.values()), percentil=percentil_umbral, minimo_abs=2)

    resultados = []
    for topic, Nt in topico_cnt.items():
        St = st_vals[topic]
        if St < umbral_st and Nt < 2:
            continue  # excluir ruido

        Ct     = sum(topico_pi[topic]) / Nt                    # eq. 44: posición media tema
        St_arg = sum(topico_si[topic]) / Nt                    # sentimiento argumental

        # Coherencia del tópico: concordancia entre sent_topic y posición sobre tema
        # Si sent_topic y posición apuntan en la misma dirección → coherente (1)
        # Si contradicen → incoherente (0), ej: topic con sent -1 pero posicion +1
        concordancias = [
            1 if (s == p or p == 0) else 0
            for s, p in zip(topico_si[topic], topico_pi[topic])
        ]
        Ib_topic = sum(concordancias) / len(concordancias) if concordancias else 0.5

        pct_medio = (
            sum(topico_pct[topic]) / len(topico_pct[topic])
            if topico_pct[topic] else 50.0
        )

        resultados.append({
            "topic":             topic,
            "St":                round(St, 4),
            "Ct":                round(Ct, 4),         # posición sobre tema (color)
            "Ct_argumental":     round(St_arg, 4),     # sentimiento argumental
            "Ib_topic":          round(Ib_topic, 4),   # coherencia pos↔sent_topic
            "Nt":                Nt,
            "plataformas":       list(topico_plats[topic]),
            "scoreop_pct_medio": round(pct_medio, 2),
        })

    resultados.sort(key=lambda x: x["St"], reverse=True)
    return resultados[:top_n]

def construir_grafo_bipartito(
    df_all: pd.DataFrame,
    df_scoreop: Optional[pd.DataFrame],
    top_n_topicos: int = 15,
    percentil_topics: float = 0.70,
    percentil_usuarios: float = 0.80,
) -> dict:
    """
    Grafo G = (VT ∪ VU, E) con umbrales adaptativos.

    Mejoras:
    - Umbral percentil + mínimo: solo topics e influencers relevantes
    - Nodos de usuario con indicador 'es_puente' (betweenness alto)
    - Aristas con Cu,t basado en posición sobre el tema (no sentimiento topic)
    - Meta incluye estadísticas de umbrales aplicados
    """
    TIPOS_POST = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}
    EXCLUIR    = {"sin topic", "no relacionado", "otros", "error", ""}

    posts = df_all[df_all["tipo_norm"].isin(TIPOS_POST) & (df_all["sent_num"] != 2)].copy()
    if posts.empty:
        return {"nodes": [], "edges": [], "meta": {"aviso": "Sin posts"}}

    wi = _calcular_wi(posts)

    # ── A. Tópicos ────────────────────────────────────────────────────────────
    topico_wi  = defaultdict(float)
    topico_pi  = defaultdict(list)
    topico_cnt = Counter()

    for idx, row in posts.iterrows():
        topic    = str(row.get("topic", "") or "").strip().lower()
        posicion = int(row.get("sent_num", 0))
        w_i      = float(wi.loc[idx])
        if topic in EXCLUIR:
            continue
        topico_wi[topic]  += w_i
        topico_pi[topic].append(posicion)
        topico_cnt[topic] += 1

    # Umbral adaptativo topics
    st_vals_t = {t: topico_cnt[t] * topico_wi[t] for t in topico_cnt}
    umbral_st = _umbral_adaptativo(list(st_vals_t.values()), percentil=percentil_topics, minimo_abs=2)

    top_topics = sorted(
        [t for t in topico_cnt if st_vals_t[t] >= umbral_st],
        key=lambda t: st_vals_t[t],
        reverse=True
    )[:top_n_topicos]
    top_topics_set = set(top_topics)

    nodes_topico = []
    for t in top_topics:
        Nt = topico_cnt[t]
        St = st_vals_t[t]
        Ct = sum(topico_pi[t]) / Nt
        nodes_topico.append({
            "id":    f"topico__{t}",
            "label": t,
            "tipo":  "topico",
            "St":    round(St, 4),
            "Ct":    round(Ct, 4),
            "Nt":    Nt,
            "es_relevante": True,
        })

    # ── B. Usuarios con umbral adaptativo ─────────────────────────────────────
    usuario_wi  = defaultdict(float)
    usuario_pi  = defaultdict(list)
    usuario_plat = {}
    arista_wi   = defaultdict(float)
    arista_pi   = defaultdict(list)

    for idx, row in posts.iterrows():
        topic    = str(row.get("topic", "") or "").strip().lower()
        uid      = str(row.get("id_anonimo", "") or "").strip()
        plat     = str(row.get("plataforma", ""))
        posicion = int(row.get("sent_num", 0))
        w_i      = float(wi.loc[idx])

        if not uid or uid == "DESCONOCIDO":
            continue

        usuario_wi[uid]  += w_i
        usuario_pi[uid].append(posicion)
        if uid not in usuario_plat:
            usuario_plat[uid] = plat

        if topic and topic not in EXCLUIR and topic in top_topics_set:
            arista_wi[(uid, topic)]  += w_i
            arista_pi[(uid, topic)].append(posicion)

    # Umbral adaptativo usuarios: solo influencers relevantes
    su_vals = dict(usuario_wi)
    umbral_su = _umbral_adaptativo(list(su_vals.values()), percentil=percentil_usuarios, minimo_abs=1)

    nodes_usuario = []
    for uid, Su in usuario_wi.items():
        if Su < umbral_su:
            continue   # excluir usuarios de muy bajo alcance
        pis = usuario_pi[uid]
        Cu  = sum(pis) / len(pis) if pis else 0
        nodes_usuario.append({
            "id":         uid,
            "label":      uid[:5].upper(),
            "tipo":       "usuario",
            "plataforma": usuario_plat.get(uid, ""),
            "Su":         round(Su, 4),
            "Cu":         round(Cu, 4),
            "n_posts":    len(pis),
            "es_influyente": Su >= umbral_su,
        })

    # Aristas (solo entre usuarios que pasaron el umbral)
    uid_set_filtrado = {n["id"] for n in nodes_usuario}
    edges = []
    for (uid, topic), Wu_t in arista_wi.items():
        if uid not in uid_set_filtrado:
            continue
        pis_ut = arista_pi[(uid, topic)]
        Cu_t   = sum(pis_ut) / len(pis_ut) if pis_ut else 0
        edges.append({
            "source":  uid,
            "target":  f"topico__{topic}",
            "Wu_t":    round(Wu_t, 4),
            "Cu_t":    round(Cu_t, 4),
            "n_posts": len(pis_ut),
        })

    # ── C. Betweenness para "usuarios puente" ─────────────────────────────────
    all_nodes = nodes_topico + nodes_usuario
    bc = _betweenness_approx(all_nodes, edges)
    bc_vals = list(bc.values())
    umbral_bc = _umbral_adaptativo(bc_vals, percentil=0.85, minimo_abs=0) if bc_vals else 0

    for n in nodes_usuario:
        n["betweenness"] = round(bc.get(n["id"], 0.0), 6)
        n["es_puente"]   = n["betweenness"] >= umbral_bc and n["betweenness"] > 0
    for n in nodes_topico:
        n["betweenness"] = round(bc.get(n["id"], 0.0), 6)
        n["es_puente"]   = False

    return {
        "nodes": all_nodes,
        "edges": edges,
        "meta": {
            "n_topicos":            len(nodes_topico),
            "n_usuarios":           len(nodes_usuario),
            "n_aristas":            len(edges),
            "umbral_St_aplicado":   round(umbral_st, 3),
            "umbral_Su_aplicado":   round(umbral_su, 3),
            "n_usuarios_excluidos": len(usuario_wi) - len(nodes_usuario),
        },
    }

# ══════════════════════════════════════════════════════════════════════════════
# CÁLCULO DE POSICIÓN ON-DEMAND con vLLM
# Se invoca desde _cargar_analizado_csvs cuando la columna 'posicion' falta
# o está incompleta. Usa exactamente el mismo contexto que el análisis
# topic/sentimiento original (contenido, contexto padre, transcripción, red).
# ══════════════════════════════════════════════════════════════════════════════

def _calcular_posicion_on_demand(
    df: pd.DataFrame,
    csv_path: Path,
    tema: str,
    desc_tema: str = "",
    keywords: list = None,
    population_scope: str = "GLOBAL",
    languages: list = None,
    red_social: str = "",
) -> pd.DataFrame:
    print("[TRACE _calcular_posicion_on_demand] Llamada desde:")
    traceback.print_stack(limit=5)
    """
    Añade la columna 'posicion' al DataFrame procesando únicamente las filas
    que no la tienen (posts originales con sentimiento válido).

    La posición mide la POSTURA EXPLÍCITA sobre el tema/medida/servicio,
    que es DISTINTA del sentimiento del topic (tono argumental):

        sentimiento = -1, posicion = 0  →  critica algo relacionado, no el tema en sí
        sentimiento = -1, posicion = -1 →  rechaza explícitamente el tema
        sentimiento = -1, posicion =  1 →  usuario que se queja pero defiende el tema

    Parámetros
    ----------
    df          : DataFrame ya cargado del CSV (con sentimiento y topic)
    csv_path    : ruta al CSV original (para guardar progreso incremental)
    tema        : tema de análisis (ej: "Bikesharing")
    desc_tema   : descripción técnica del tema
    keywords    : lista de keywords de búsqueda (para contexto)
    population_scope : ámbito geográfico
    languages   : idiomas permitidos
    red_social  : "bluesky" | "reddit" | "youtube" | ""

    Retorna
    -------
    df con columna 'posicion' rellena
    """
    try:
        from openai import OpenAI as _OpenAI
        from clean_project.vllm.model_config import MODELO_ACTIVO as _MODEL
    except Exception as e:
        print(f"[POSICION] ⚠️ No se pudo conectar al vLLM: {e}. Usando fallback sent=posicion.")
        # Fallback: posicion = sentimiento cuando hay postura clara, 0 cuando no
        if "sentimiento" in df.columns:
            df["posicion"] = pd.to_numeric(
                df["sentimiento"], errors="coerce"
            ).fillna(0).apply(lambda s: s if s in (-1, 1) else 0).astype(int)
        else:
            df["posicion"] = 0
        return df

    _client = _OpenAI(base_url="http://localhost:8001/v1", api_key="local-token", timeout=45.0)

    keywords   = keywords   or []
    languages  = languages  or ["Castellano"]
    kw_str     = ", ".join(keywords[:10]) if keywords else ""
    langs_str  = ", ".join(languages)
    sep = ";" if ";" in csv_path.read_text(encoding="utf-8", errors="ignore")[:200] else ","

    # ── Identificar tipos POST/VIDEO (misma lógica que el análisis original) ──
    TIPOS_POST = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}
    if "tipo" in df.columns:
        mask_tipo = df["tipo"].fillna("POST").str.strip().str.upper().isin(TIPOS_POST)
    else:
        mask_tipo = pd.Series([True] * len(df), index=df.index)

    # Inicializar columna
    if "posicion" not in df.columns:
        df["posicion"] = ""

    # Pendientes: posts con sentimiento válido y sin posición calculada
    sent_validos = pd.to_numeric(df.get("sentimiento", pd.Series(dtype=float)),
                                 errors="coerce").isin([-1, 0, 1])
    mask_pendiente = mask_tipo & sent_validos & (
        df["posicion"].isna() |
        (df["posicion"].astype(str).str.strip().isin(["", "nan", "None"]))
    )

    indices = df[mask_pendiente].index.tolist()

    if not indices:
        print(f"[POSICION] ✅ Todos los posts ya tienen posición ({len(df)} filas).")
        # Asegurar tipo numérico
        df["posicion"] = pd.to_numeric(df["posicion"], errors="coerce").fillna(0).astype(int)
        return df

    print(f"[POSICION] 📊 Calculando posición para {len(indices)} posts de {csv_path.name}…")

    def _build_prompt(row_data: dict) -> str:
        """
        Construye el mismo contexto que preparar_contexto_multimodal:
        contenido principal + contexto padre cuando corresponde.
        """
        contenido  = str(row_data.get("contenido", "") or "")[:600]
        sentimiento = int(row_data.get("sentimiento", 0) or 0)
        topic      = str(row_data.get("topic", "") or "")
        titulo     = str(row_data.get("titulo_video", "") or
                         row_data.get("titulo", "") or "")
        padre      = str(row_data.get("_ctx_padre", "") or "")
        citado      = str(row_data.get("_texto_citado", "") or "")

        # Contexto adicional según red
        ctx_parts = []
        if titulo:
            ctx_parts.append(f"[TÍTULO/CONTEXTO]\n{titulo[:200]}")
        if padre:
            ctx_parts.append(f"[POST PADRE]\n{padre[:300]}")
        ctx_parts.append(f"[CONTENIDO]\n{contenido}")
        if citado:
            ctx_parts.append(f"[POST CITADO]\n{citado[:500]}")
        ctx = "\n\n".join(ctx_parts)

        return f"""Eres un clasificador de POSTURA en redes sociales.

TEMA DE ANÁLISIS: "{tema}"
{f'Descripción: {desc_tema[:200]}' if desc_tema else ''}
{f'Keywords relacionadas: {kw_str}' if kw_str else ''}
Idiomas válidos: {langs_str}

POST A CLASIFICAR:
{ctx}

Sentimiento detectado del argumento: {sentimiento} (-1=negativo, 0=neutro, 1=positivo)
Topic del argumento: "{topic}"

TAREA: Determina la POSICIÓN EXPLÍCITA del autor sobre el propio tema "{tema}".

⚠️ DISTINCIÓN CRÍTICA — sentimiento ≠ posición:
- Criticar la gestión municipal sobre el tema  → posicion=0  (critica contexto, no el tema)
- Señalar un fallo puntual del servicio        → posicion=0  (usuario, no detractor)
- "Esto destruye el comercio" sobre el tema    → posicion=-1 (rechazo explícito al concepto)
- "Me encanta poder coger una bici"            → posicion=1  (apoyo explícito)
- Noticia informativa sin valoración           → posicion=0

REGLA DE ORO: Si el autor NO dice explícitamente que el tema le parece bien/mal,
la posición es 0, aunque hable negativamente de algo relacionado.

Valores:
  1  = Apoya / defiende / promueve explícitamente "{tema}"
 -1  = Rechaza / critica / se opone explícitamente a "{tema}" como concepto
  0  = No hay postura explícita sobre "{tema}" en sí mismo

Responde SOLO con JSON:
{{"posicion": 1|0|-1, "razon": "<una frase breve justificando>"}}"""

    def _procesar_fila(idx) -> tuple:
        """Procesa una sola fila y devuelve (idx, posicion_int)."""
        row = df.loc[idx]


        # Texto citado propio (si esta fila es en sí misma un POST/CITA)
        texto_citado_propio = str(row.get("texto_citado", "") or "")

        # Construir contexto padre igual que en preparar_contexto_multimodal
        ctx_padre = ""
        if red_social == "reddit":
            id_raiz = str(row.get("id_raiz", "") or "")
            if id_raiz:
                padre_rows = df[
                    (df.get("tipo", pd.Series(dtype=str)).str.upper() == "POST") &
                    (df.get("id_raiz", pd.Series(dtype=str)) == id_raiz)
                ]
                if not padre_rows.empty:
                    ctx_padre = str(padre_rows.iloc[0].get("contenido", ""))[:300]
        elif red_social == "youtube":
            ctx_padre = str(row.get("titulo_video", "") or "")[:200]
        elif red_social == "bluesky":
            parent_uri = str(row.get("parent_uri", "") or "")
            propio_uri = str(row.get("uri", "") or "")
            if parent_uri and parent_uri != propio_uri:
                padre_rows = df[df.get("uri", pd.Series(dtype=str)) == parent_uri]
                if not padre_rows.empty:
                    fila_padre = padre_rows.iloc[0]
                    ctx_padre = str(fila_padre.get("contenido", ""))[:300]
                    padre_citado = str(fila_padre.get("texto_citado", "") or "")
                    if padre_citado:
                        ctx_padre += f"\n[TEXTO CITADO POR EL PADRE]\n{padre_citado[:300]}"
        elif red_social == "telegram":
            '''         ROMINAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
                        ROMINA
            '''
            print("ROMINA FALTA TELEGRAM: Procesar fila") # parece que no se llama
            
        row_data = {
            "contenido":   str(row.get("contenido", "") or ""),
            "sentimiento": row.get("sentimiento", 0),
            "topic":       str(row.get("topic", "") or ""),
            "titulo_video": str(row.get("titulo_video", "") or ""),
            "_ctx_padre":  ctx_padre,
            "_texto_citado": texto_citado_propio,
        }

        prompt = _build_prompt(row_data)

        for intento in range(2):
            try:
                resp = _client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    response_format={"type": "json_object"},
                    max_tokens=120,
                )
                raw  = resp.choices[0].message.content
                data = json.loads(raw)
                pos  = int(data.get("posicion", 0))
                if pos not in (-1, 0, 1):
                    pos = 0
                razon = data.get("razon", "")[:80]
                print(f"  [POSICION] idx={idx} sent={row_data['sentimiento']} "
                      f"→ pos={pos} | {razon}")
                return (idx, pos)
            except Exception as e:
                print(f"  [POSICION] ⚠️ idx={idx} intento {intento+1}: {e}")
                if intento == 1:
                    return (idx, 0)
                time.sleep(0.3)
        return (idx, 0)

    # ── Procesar en paralelo con guardado incremental ─────────────────────────
    BATCH        = 30   # filas por lote (balance velocidad/memoria)
    MAX_WORKERS  = 8    # hilos simultáneos

    import concurrent.futures as _cf

    for i in range(0, len(indices), BATCH):
        batch_idx = indices[i: i + BATCH]
        n_lote    = i // BATCH + 1
        n_total   = (len(indices) - 1) // BATCH + 1
        print(f"  [POSICION] Lote {n_lote}/{n_total} ({len(batch_idx)} filas)…")

        with _cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futuros = {executor.submit(_procesar_fila, idx): idx for idx in batch_idx}
            for futuro in _cf.as_completed(futuros):
                try:
                    idx_res, pos_res = futuro.result()
                    df.loc[idx_res, "posicion"] = str(pos_res)
                except Exception as e:
                    idx_orig = futuros[futuro]
                    print(f"  [POSICION] ❌ Error fila {idx_orig}: {e}")
                    df.loc[idx_orig, "posicion"] = "0"

        # Guardar progreso tras cada lote (tolerante a interrupciones)
        df.to_csv(csv_path, index=False, sep=sep, encoding="utf-8")
        print(f"  [POSICION] 💾 Guardado lote {n_lote}/{n_total}")

    # Asegurar tipo numérico al final
    df["posicion"] = pd.to_numeric(df["posicion"], errors="coerce").fillna(0).astype(int)
    print(f"[POSICION] ✅ Completado. Columna 'posicion' añadida a {csv_path.name}")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# CARGA UNIFICADA DE *_analizado.csv (multi-plataforma con anchors)
# Incluye cálculo on-demand de 'posicion' si la columna no existe
# ══════════════════════════════════════════════════════════════════════════════

def _cargar_analizado_csvs(
    db: Session,
    folder,
    analysis_id: BigInteger = None,
    tema: str = "",
    desc_tema: str = "",
    keywords: list = None,
    population_scope: str = "GLOBAL",
    languages: list = None,
) -> "pd.DataFrame | None":
    """
    Carga y concatena todos los *_analizado.csv de la carpeta.
    Recupera metadatos desde la BBDD PostgreSQL en lugar de JSON.

    Columnas garantizadas en el resultado:
    - sent_num   : posición sobre el tema (-1, 0, 1, 2=no rel.)
    - sent_topic : sentimiento argumental del topic (-1, 0, 1)
    - tipo_norm  : tipo de publicación normalizado a mayúsculas
    - id_anonimo : hash del usuario
    - _anchor_own / _anchor_parent : identificadores multi-plataforma

    Parámetros:
    - db: sesión de SQLAlchemy
    - folder: ruta a la carpeta con CSVs
    - analysis_id: ID del análisis (para buscar metadatos en BBDD)
    - tema, desc_tema, keywords, population_scope, languages: metadatos (si no se encuentran en BBDD)
    """
    folder = Path(folder)
    print(f"\n[CARGA] Buscando *_analizado.csv en: {folder}")
    archivos = list(folder.glob("*_analizado.csv"))
    print(f"folder: {folder}")
    print(f"[CARGA] Archivos encontrados: {[f.name for f in archivos]}")

    if not archivos:
        print("[CARGA] ⚠️ No se encontraron archivos _analizado.csv")
        return None

    # ── Recuperar metadatos desde BBDD ────────────────────────────────────────
    if not tema and analysis_id:
        try:
            analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
            if analysis and analysis.analysis_config:
                cfg = analysis.analysis_config
                tema             = cfg.get("tema", "")
                desc_tema        = cfg.get("desc_tema", "")
                population_scope = cfg.get("population_scope", "GLOBAL")
                languages        = cfg.get("languages", ["Castellano"])
                kw_raw           = cfg.get("keywords", [])
                
                if isinstance(kw_raw, list) and kw_raw:
                    if isinstance(kw_raw[0], dict):
                        keywords = [k.get("keyword", "") for k in kw_raw if k.get("keyword")]
                    else:
                        keywords = [str(k) for k in kw_raw if k]
                
                print(f"[CARGA] 🎯 Metadatos recuperados de BBDD: tema='{tema}'")
        except Exception as e:
            print(f"[CARGA] ⚠️ Error leyendo BBDD: {e}")

    # ── Cargar y concatenar CSVs ──────────────────────────────────────────────
    dfs = []
    for f in archivos:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                primera = fh.readline()
                sep = ";" if ";" in primera else ","
            df_tmp = pd.read_csv(f, sep=sep, encoding="utf-8", on_bad_lines="skip")
            print(f"[CARGA]   {f.name}: {len(df_tmp)} filas, "
                  f"cols: {df_tmp.columns.tolist()[:8]}…")

            # Detectar red social desde nombre de archivo
            nombre = f.name.lower()
            if   "bluesky" in nombre: 
                plat = "bluesky"
            elif "reddit"  in nombre: 
                plat = "reddit"
            elif "youtube" in nombre: 
                plat = "youtube"
            elif "telegram" in nombre: 
                plat = "telegram"
            else:                     
                plat = "otros"

            if "plataforma" not in df_tmp.columns:
                df_tmp["plataforma"] = plat

            # Guardar ruta del CSV para el guardado incremental
            df_tmp["_csv_path"]   = str(f)
            df_tmp["_csv_sep"]    = sep
            df_tmp["_red_social"] = plat

            dfs.append(df_tmp)
        except Exception as exc:
            print(f"[CARGA] ❌ Error leyendo {f.name}: {exc}")

    if not dfs:
        return None

    df = pd.concat(dfs, ignore_index=True)
    # ── Compatibilidad con CSVs antiguos sin columna texto_citado ─────────────
    if "texto_citado" not in df.columns:
        df["texto_citado"] = ""
    df["texto_citado"] = df["texto_citado"].fillna("").astype(str)
    print(f"[CARGA] Total filas concatenadas: {len(df)}")

    # ── Normalizar tipo ───────────────────────────────────────────────────────
    if "tipo" not in df.columns:
        df["tipo"] = "POST"
    df["tipo_norm"] = df["tipo"].fillna("POST").astype(str).str.strip().str.upper()

    # ── id_anonimo ────────────────────────────────────────────────────────────
    if "id_anonimo" not in df.columns:
        col_user = "usuario" if "usuario" in df.columns else None
        if col_user:
            df["id_anonimo"] = df[col_user].fillna("").astype(str).apply(
                lambda x: hashlib.sha256(x.encode()).hexdigest()[:16].upper()
            )
        else:
            df["id_anonimo"] = "DESCONOCIDO"

    # ── sent_topic: SIEMPRE viene de 'sentimiento' (tono argumental) ──────────
    if "sentimiento" in df.columns:
        df["sent_topic"] = pd.to_numeric(
            df["sentimiento"], errors="coerce"
        ).fillna(0).astype(int)
    else:
        df["sent_topic"] = 0

    # ── sent_num: viene de 'posicion' (postura sobre el tema) ────────────────
    # Calcular on-demand por archivo si falta o está incompleta
    tiene_posicion = (
        "posicion" in df.columns and
        pd.to_numeric(df["posicion"], errors="coerce").notna().mean() > 0.3
    )

    if not tiene_posicion:
        print(f"[CARGA] 🔄 Columna 'posicion' ausente o incompleta. "
            f"Calculando on-demand con vLLM…")

        dfs_con_posicion = []

        for f_path_str in df["_csv_path"].unique():
            f_path = Path(f_path_str)

            red = df.loc[
                df["_csv_path"] == f_path_str,
                "_red_social"
            ].iloc[0]

            sep = df.loc[
                df["_csv_path"] == f_path_str,
                "_csv_sep"
            ].iloc[0]

            df_ind = pd.read_csv(
                f_path,
                sep=sep,
                encoding="utf-8",
                on_bad_lines="skip"
            )

            if "plataforma" not in df_ind.columns:
                df_ind["plataforma"] = red

            df_ind = _calcular_posicion_on_demand(
                df=df_ind,
                csv_path=f_path,
                tema=tema,
                desc_tema=desc_tema,
                keywords=keywords or [],
                population_scope=population_scope,
                languages=languages or ["Castellano"],
                red_social=red,
            )

            dfs_con_posicion.append(df_ind)

        df_reconstruido = pd.concat(
            dfs_con_posicion,
            ignore_index=True
        )

        df["posicion"] = df_reconstruido.get("posicion", 0)

    # Garantizar que exista siempre
    if "posicion" not in df.columns:
        df["posicion"] = 0

    df["posicion"] = pd.to_numeric(
        df["posicion"],
        errors="coerce"
    ).fillna(0)

    # sent_num = posicion, pero preservar 2 (no relacionado) desde sentimiento
    sent_serie = pd.to_numeric(df.get("sentimiento", pd.Series(dtype=float)),
                               errors="coerce").fillna(2)
    df["sent_num"] = df["posicion"].where(
        sent_serie != 2,   # si sentimiento=2 (no rel.), mantener 2
        other=2
    ).astype(int)

    print(f"[CARGA] sent_num distribucion: "
          f"{df['sent_num'].value_counts().to_dict()}")

    # ── topic ─────────────────────────────────────────────────────────────────
    if "topic" not in df.columns:
        df["topic"] = "sin topic"
    df["topic"] = df["topic"].fillna("sin topic").astype(str).str.strip().str.lower()

    # ── contenido unificado ───────────────────────────────────────────────────
    if "contenido" not in df.columns:
        for alias in ("contenido_post", "content", "body", "text"):
            if alias in df.columns:
                df["contenido"] = df[alias]
                break
        else:
            df["contenido"] = ""
    df["contenido"] = df["contenido"].fillna("").astype(str)

    # ── Anchors multi-plataforma ──────────────────────────────────────────────
    TIPOS_POST_SET = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}

    def _own(row):
        plat = str(row["plataforma"]).lower()
        tn   = str(row["tipo_norm"])
        pfx  = plat[:3] + ":"
        if "bluesky" in plat:
            return pfx + str(row.get("uri", ""))
        if "youtube" in plat:
            vid = str(row.get("id_video", ""))
            return pfx + (vid if tn in TIPOS_POST_SET else f"{vid}#{row.name}")
        if "telegram" in plat:
            '''         ROMINAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
                        ROMINA
            print("ROMINA FALTA TELEGRAM: _cargar_analizado_csvs -> _own") # parece que SÍ se llama
            '''
            return pfx + str(row.get("uri", ""))
        if tn in TIPOS_POST_SET:
            return pfx + str(row.get("id_raiz", str(row.name)))
        return pfx + str(row.get("id_propio", row.get("id_raiz", str(row.name))))

    def _parent(row):
        plat = str(row["plataforma"]).lower()
        tn   = str(row["tipo_norm"])
        pfx  = plat[:3] + ":"
        if tn in TIPOS_POST_SET:
            return ""
        if "bluesky" in plat:
            return pfx + str(row.get("parent_uri", ""))
        if "youtube" in plat:
            return pfx + str(row.get("id_video", ""))
        if "telegram" in plat:
            '''         ROMINAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
                        ROMINA
            print("ROMINA FALTA TELEGRAM: _cargar_analizado_csvs -> _parent") # parece que SÍ se llama
            '''
            return pfx + str(row.get("parent_uri", ""))
        return pfx + str(row.get("id_raiz", ""))

    df["_anchor_own"]    = df.apply(_own,    axis=1)
    df["_anchor_parent"] = df.apply(_parent, axis=1)

    # Limpiar columnas auxiliares de carga
    df.drop(columns=["_csv_path", "_csv_sep", "_red_social"],
            errors="ignore", inplace=True)

    print(f"[CARGA] ✅ DataFrame listo: {len(df)} filas | "
          f"sent_num (posición sobre tema): {df['sent_num'].value_counts().to_dict()} | "
          f"sent_topic (sentimiento argumental): {df['sent_topic'].value_counts().to_dict()}")
    return df

# ── Stopwords ─────────────────────────────────────────────────────────────────
try:
    from nltk.corpus import stopwords as _nltk_sw
    _SW_ES = set(_nltk_sw.words("spanish"))
    _SW_EN = set(_nltk_sw.words("english"))
except Exception:
    _SW_ES = set()
    _SW_EN = set()

try:
    import simplemma as _sm
    _SM_LANGS = ("es", "en", "ca", "pt", "fr", "it")
    _SM_OK = True
except ImportError:
    _SM_OK = False

try:
    import unidecode as _ud
    _UD_OK = True
except ImportError:
    _UD_OK = False

_STOPS_MANUAL = {
    "para", "como", "pero", "porque", "sobre", "desde", "hasta", "esto",
    "esta", "este", "todos", "todas", "solo", "bien", "también", "aunque",
    "puede", "después", "antes", "entre", "mismo", "cada", "otro", "otra",
    "decir", "hacer", "tener", "poder", "saber", "https", "http",
    "share", "post", "tweet", "video", "foto", "hola", "gracias", "puntocomunica",
}
_STOPS = _SW_ES | _SW_EN | _STOPS_MANUAL
_STOPS_NORM = ({_ud.unidecode(w) for w in _STOPS} if _UD_OK else _STOPS)

TIPOS_POST = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}
EXCLUIR_TOPICS = {"sin topic", "no relacionado", "otros", "error", "", "none"}


import re
import math
from collections import Counter, defaultdict
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np

from deep_translator import GoogleTranslator

try:
    from nltk.corpus import stopwords as _nltk_sw
    _SW_ES = set(_nltk_sw.words("spanish"))
    _SW_EN = set(_nltk_sw.words("english"))
except Exception:
    _SW_ES = set()
    _SW_EN = set()

try:
    import simplemma as _sm
    from simplemma import lang_detector as _simplemma_lang_detector
    _SM_LANGS = ("es", "en", "ca", "pt", "fr", "it")
    _SM_OK = True
except ImportError:
    _SM_OK = False

try:
    import unidecode as _ud
    _UD_OK = True
except ImportError:
    _UD_OK = False

try:
    from langdetect import detect as _ld_detect
    _LANGDETECT_OK = True
except ImportError:
    _LANGDETECT_OK = False

# 1. Cargar stopwords personalizadas desde los directorios locales
_STOPS_CUSTOM = set()
_STOPWORDS_DIR = Path("/home/rrss/proyecto_web/Project_OLD/RRSS_version_stance/stopwords")
_LANG_FILES = ["spanish", "basque", "catalan", "french", "italian", "portuguese"]

for lang_file in _LANG_FILES:
    file_path = _STOPWORDS_DIR / lang_file
    if file_path.exists() and file_path.is_file():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    w = line.strip().lower()
                    if w:
                        _STOPS_CUSTOM.add(w)
        except Exception as e:
            print(f"⚠️ Error cargando stopwords de {file_path}: {e}")

_STOPS_MANUAL = {
    "para", "como", "pero", "porque", "sobre", "desde", "hasta", "esto",
    "esta", "este", "todos", "todas", "solo", "bien", "también", "aunque",
    "puede", "después", "antes", "entre", "mismo", "cada", "otro", "otra",
    "decir", "hacer", "tener", "poder", "saber", "https", "http",
    "share", "post", "tweet", "video", "foto", "hola", "gracias",
    "síguenos", "suscríbete", "canal", "instagram", "facebook",
    "twitter", "youtube", "tiktok", "link", "bio", "leer", "historia",
    "noticia", "canal", "comar", "tras", "Instagram", "Facebook", "Twitter", "YouTube", "TikTok", "puntocomunica", "luego", "dale campanita", "dale like", "comparte", "compartir", "seguir", "suscribir", "suscríbete", "nuevo video", "nuevo post",
}

# Unir todas las stopwords (NLTK + Manuales + Archivos Locales)
_STOPS = _SW_ES | _SW_EN | _STOPS_MANUAL | _STOPS_CUSTOM | _RUIDO_SOCIAL
_STOPS_NORM = ({_ud.unidecode(w) for w in _STOPS} if _UD_OK else _STOPS)

TIPOS_POST = {"POST", "VIDEO", "TWEET", "PUBLICACION", "PUBLICACIÓN", "VÍDEO"}
EXCLUIR_TOPICS = {"sin topic", "no relacionado", "otros", "error", "", "none", "nan"}

# ══════════════════════════════════════════════════════════════════════════════
# 0. Utilidades y Procesamiento de Texto
# ══════════════════════════════════════════════════════════════════════════════

def _limpiar(texto: str) -> str:
    if not texto: return ""
    texto = str(texto).lower()
    
    # 1. Eliminar URLs, emails y menciones
    texto = re.sub(r'http\S+|www\S+|[\w\.-]+@[\w\.-]+', ' ', texto)
    texto = re.sub(r'[@#]\S+', ' ', texto)
    
    # 2. Eliminar códigos hexadecimales o IDs raros (ej: c8ebf1, 1_c980f2)
    texto = re.sub(r'\b\d*_[a-f0-9]+\b', ' ', texto)
    texto = re.sub(r'\b[a-f0-9]{6,}\b', ' ', texto)
    
    # 3. Eliminar dominios y palabras basura específicas
    basura = [
        'eldiario', 'rtve', 'ctxt', 'wordpress', 'europapress', 
        'discord', 'homyhub', 'parainmigrantes', 'elpais', 'elnacional'
    ]
    for b in basura:
        texto = texto.replace(b, ' ')
        
    # 4. Quitar caracteres especiales y dejar solo letras
    texto = re.sub(r"[^\w\sáéíóúüñàèìòùâêîôûäëïöüãõç]", " ", texto)
    
    # 5. Quitar espacios extra
    return re.sub(r"_+|\s+", " ", texto).strip()

# Lista negra de bigramas que no queremos que se formen NUNCA
BIGRAMAS_BASURA = {
    "redes sociales", "red social", "dale campanita", "rtve play", 
    "rtve noticias", "duda llamanos", "suport chatgpt", "suscribete canal"
}

def _filtrar(tokens: list, extra_stops: set = None) -> list:
    stops = _STOPS | (extra_stops or set())
    stops_n = _STOPS_NORM | (
        {_ud.unidecode(w) for w in (extra_stops or set())} if _UD_OK else set()
    )
    return [
        w for w in tokens
        if len(w) > 3
        and w not in stops
        and (_ud.unidecode(w) not in stops_n if _UD_OK else True)
    ]

def _detectar_idioma(texto: str) -> str:
    if len(texto) < 20:
        return "und"
    if _SM_OK:
        try:
            res = _simplemma_lang_detector(texto, lang=_SM_LANGS)
            if res and res[0][0] != "unk":
                return res[0][0]
        except:
            pass
    if _LANGDETECT_OK:
        try:
            return _ld_detect(texto)
        except:
            pass
    return "und"

def _procesar_texto_nube(contenido: str, extra_stops: set = None) -> dict:
    """
    Detecta idioma, traduce si es necesario, lematiza y extrae unigramas y bigramas
    REALES (solo si las palabras estaban adyacentes en el texto original).
    """
    if not contenido or not str(contenido).strip():
        return {"unigramas": [], "bigramas": []}
        
    texto_str = str(contenido)
    lang = _detectar_idioma(texto_str)
    
    # Traducir si no es un idioma soportado por simplemma
    if lang not in _SM_LANGS and lang != "und":
        try:
            texto_str = GoogleTranslator(source='auto', target='es').translate(texto_str)
            lang = "es"
        except Exception:
            pass
            
    if lang not in _SM_LANGS:
        lang = "es"
        
    texto_limpio = _limpiar(texto_str)
    tokens_orig = [w for w in texto_limpio.split() if len(w) > 2]
    
    if not tokens_orig:
        return {"unigramas": [], "bigramas": []}
        
    # Lematizar manteniendo el orden original
    if _SM_OK:
        try:
            tokens_lema = [_sm.lemmatize(w, lang=lang) for w in tokens_orig]
        except Exception:
            tokens_lema = tokens_orig
    else:
        tokens_lema = tokens_orig
        
    # Preparar stopwords
    stops = _STOPS | (extra_stops or set())
    stops_n = _STOPS_NORM | ({_ud.unidecode(w) for w in (extra_stops or set())} if _UD_OK else set())
    
    def es_valido(w):
        if len(w) <= 3: return False
        if w in stops: return False
        if _UD_OK and _ud.unidecode(w) in stops_n: return False
        return True
        
    # Identificar qué palabras son válidas (True/False)
    valid_flags = [es_valido(w) for w in tokens_lema]
    
    # Extraer palabras sueltas válidas
    unigramas = [w for i, w in enumerate(tokens_lema) if valid_flags[i]]
    
    # Extraer bigramas SOLO si ambas palabras eran adyacentes y ambas son válidas
    bigramas = []
    for i in range(len(tokens_lema) - 1):
        if valid_flags[i] and valid_flags[i+1]:
            bg = f"{tokens_lema[i]} {tokens_lema[i+1]}"
            if bg not in BIGRAMAS_BASURA:
                bigramas.append(bg)
            
    return {"unigramas": unigramas, "bigramas": bigramas}

def _safe_float(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return default


# ══════════════════════════════════════════════════════════════════════════════
# 1. Obtener peso de magnitud por post
#    Prioridad: ScoreOP_sup > Wi (eqs. 37-39 del PDF)
# ══════════════════════════════════════════════════════════════════════════════

def _obtener_pesos_magnitud(df: pd.DataFrame) -> pd.Series:
    print("[TRACE _obtener_pesos_magnitud] Llamada desde:")
    traceback.print_stack(limit=5)
    """
    Devuelve una Serie con el peso de magnitud de cada post.
    
    Si ScoreOP_sup está disponible (join con scoreop_consolidado.csv hecho
    previamente), lo usa directamente normalizado por plataforma.
    
    Si no, recalcula Wi (eqs. 37-39) como fallback.
    
    Normalización inter-plataforma: dentro de cada plataforma se normaliza
    al máximo de esa plataforma, lo que permite comparar usuarios de YouTube
    con usuarios de Reddit sin que la escala bruta de vistas domine.
    """
    pesos = pd.Series(1.0, index=df.index, dtype=float)
    
    # ── Intento 1: ScoreOP_sup (magnitud real del impacto calculado) ──────────
    if "ScoreOP_sup" in df.columns:
        sup_raw = pd.to_numeric(df["ScoreOP_sup"], errors="coerce").fillna(0.0)
        if sup_raw.sum() > 0:
            # Normalizar por plataforma
            for plat, idx in df.groupby("plataforma").groups.items():
                sup_plat = sup_raw.loc[idx]
                mx = sup_plat.max()
                if mx > 0:
                    pesos.loc[idx] = (sup_plat / mx).values
                else:
                    pesos.loc[idx] = 1.0
            return pesos
    
    # ── Fallback: Wi por plataforma (eqs. 37-39) ─────────────────────────────
    def _col(sub: pd.DataFrame, *aliases, default: float = 0.0) -> pd.Series:
        for name in aliases:
            if name in sub.columns:
                return pd.to_numeric(sub[name], errors="coerce").fillna(default)
        return pd.Series(default, index=sub.index, dtype=float)

    for plat, idx in df.groupby("plataforma").groups.items():
        sub = df.loc[idx]
        pl  = str(plat).lower()

        if "youtube" in pl:
            V    = _col(sub, "vistas", "views")
            S    = _col(sub, "suscriptores", "subscribers")
            Vt, St = V.sum(), S.sum()
            fv   = (1 + np.log1p(V / Vt)) if Vt > 0 else pd.Series(1.0, index=idx)
            fs   = (1 + np.log1p(S / St)) if St > 0 else pd.Series(1.0, index=idx)
            wi_p = fv * fs
        elif "bluesky" in pl:
            F    = _col(sub, "seguidores", "followers")
            Ft   = F.sum()
            wi_p = (1 + np.log1p(F / Ft)) if Ft > 0 else pd.Series(1.0, index=idx)
        elif "reddit" in pl:
            K    = _col(sub, "karma").clip(lower=0)
            Kt   = K.sum()
            wi_p = (1 + np.log1p(K / Kt)) if Kt > 0 else pd.Series(1.0, index=idx)
        
        elif "telegram" in pl:
            '''         ROMINAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
                        ROMINA
            '''
            print("ROMINA FALTA TELEGRAM: _obtener_pesos_magnitud") #parece que no se llama
        else:
            wi_p = pd.Series(1.0, index=idx)

        mx = wi_p.max()
        if mx > 0:
            wi_p = wi_p / mx
        pesos.loc[idx] = wi_p.values

    return pesos


# ══════════════════════════════════════════════════════════════════════════════
# 2. Coherencia ci,b (eq. 42)
#    ci,b = 1 si sentimiento y posición apuntan en la misma dirección
#           o si alguno es neutro (no hay postura que contradecir)
#    ci,b = 0 si contradicen explícitamente
# ══════════════════════════════════════════════════════════════════════════════

def _coherencia(sentimiento: int, posicion: int) -> float:
    """
    Casos del documento de diseño:
      caso 1: autor apoya tema (+1) y bigrama apoya → coherencia 1
      caso 2: autor apoya tema (+1) y bigrama rechaza → incoherencia 0
      caso 3: autor rechaza tema (-1) y bigrama rechaza → coherencia 1
      caso 4: autor rechaza tema (-1) y bigrama apoya → incoherencia 0
      
    Si posicion==0 (neutro sobre el tema) o sentimiento==0 (argumento neutro):
      no hay postura clara → coherencia 0.5 (ni suma ni resta)
    """
    if posicion == 0 or sentimiento == 0:
        return 0.5
    return 1.0 if (sentimiento > 0) == (posicion > 0) else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 3. Join con scoreop_consolidado.csv para obtener ScoreOP_sup
# ══════════════════════════════════════════════════════════════════════════════

def _enriquecer_con_scoreop(df_all: pd.DataFrame, folder) -> pd.DataFrame:
    from pathlib import Path
    import re
    import unidecode

    if folder is None: return df_all
    scoreop_csv = Path(folder) / "scoreop_consolidado.csv"
    
    print(f"\n[DEBUG-JOIN] 📂 Buscando ScoreOP en: {scoreop_csv}")
    if not scoreop_csv.exists():
        print(f"[DEBUG-JOIN] ⚠️ El archivo no existe. Se usará cálculo fallback.")
        return df_all
    
    try:
        with open(scoreop_csv, "r", encoding="utf-8") as f:
            sep = ";" if ";" in f.readline() else ","
        df_sc = pd.read_csv(scoreop_csv, sep=sep, encoding="utf-8", on_bad_lines="skip")

        # Función para crear una clave de cruce que ignore espacios, tildes y símbolos
        ##### --_> Problema próximo: No se tiene en cuenta como en models_all.py si un usuario tiene más de 1
        #####      proyecto con el mismo nombre
        import unicodedata
        def crear_slug_robusto(name):
            replacements = {
                # Español
                'ñ': 'ny',
                'Ñ': 'NY',

                # Valenciano / Catalán
                'ç': 'c',
                'Ç': 'C',
                'l·l': 'll',
                'L·L': 'LL',
                'L·l': 'Ll',
                'l·L': 'lL',
            }

            for old, new in replacements.items():
                name = name.replace(old, new)

            # Eliminar acentos
            name = unicodedata.normalize('NFKD', name)
            name = name.encode('ascii', 'ignore').decode('ascii')

            slug = name.lower()
            slug = re.sub(r'[^a-z0-9()_.\-]+', '-', slug).strip('-')

            return slug

        col_cont_all = "contenido" if "contenido" in df_all.columns else "contenido_post"
        col_cont_sc  = "contenido_post" if "contenido_post" in df_sc.columns else "contenido"

        # Crear claves temporales para el join
        df_sc["_join_key"] = df_sc["plataforma"].str.lower() + "||" + df_sc[col_cont_sc].apply(crear_slug_robusto)
        df_all["_join_key"] = df_all["plataforma"].str.lower() + "||" + df_all[col_cont_all].apply(crear_slug_robusto)
        
        scoreop_map = df_sc.drop_duplicates("_join_key").set_index("_join_key")
        
        # Mapear columnas del consolidado al dataframe principal
        for col in ["ScoreOP", "ScoreOP_sup", "ScoreOP_pct"]:
            if col in scoreop_map.columns:
                df_all[col] = df_all["_join_key"].map(scoreop_map[col])

        coincidencias = df_all["ScoreOP"].notna().sum()
        print(f"[DEBUG-JOIN] ✅ Cruce exitoso: {coincidencias}/{len(df_all)} filas vinculadas.")
        df_all.drop(columns=["_join_key"], errors="ignore", inplace=True)
        
    except Exception as e:
        print(f"[DEBUG-JOIN] ❌ Error crítico en join: {e}")
    
    return df_all

def _calcular_coherencia_llm_batch(
    posts_con_bigramas: list,
    folder: Path,
    tema: str = "",
    forzar_recalculo: bool = False,
) -> dict:
    """
    Calcula coherencia contextual (ci,b) con cache en CSV.
    Robusto ante JSON malformado del LLM.
    """
    cache_path = Path(folder) / "coherencia_llm_cache.json"

    # Invalidador por antigüedad (7 días)
    if cache_path.exists():
        import time
        if (time.time() - cache_path.stat().st_mtime) > (7 * 86400):
            print("[COH] Caché antigua detectada. Eliminando para recalcular con datos corregidos.")
            cache_path.unlink()

    # ── Cache ─────────────────────────────────────────────────────────────────
    cache: dict = {}
    if not forzar_recalculo and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            print(f"[COH] Cache cargada: {len(cache)} entradas")
        except Exception:
            cache = {}

    # ── Pendientes ────────────────────────────────────────────────────────────
    pendientes = []
    for item in posts_con_bigramas:
        post_id   = str(item["post_id"])
        posicion  = int(item.get("posicion", 0))
        contenido = str(item.get("contenido", ""))
        for termino in item.get("terminos", []):
            key = f"{post_id}::{termino}"
            if key not in cache:
                pendientes.append({
                    "key":      key,
                    "posicion": posicion,
                    "contenido": contenido,
                    "termino":  termino,
                })

    if not pendientes:
        print("[COH] Todo en cache.")
        return cache

    print(f"[COH] Calculando coherencia para {len(pendientes)} pares…")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _limpiar_para_json(texto: str, max_chars: int = 150) -> str:
        """
        Elimina caracteres que rompen JSON dentro de strings:
        comillas, backslashes, saltos de línea, tabulaciones, caracteres de control.
        """
        texto = str(texto)[:max_chars]
        # Eliminar caracteres de control ASCII (0-31) excepto espacio
        texto = re.sub(r'[\x00-\x1f\x7f]', ' ', texto)
        # Escapar comillas y backslashes que romperían el JSON del prompt
        texto = texto.replace('\\', ' ').replace('"', "'").replace('\n', ' ').replace('\r', ' ')
        return texto.strip()

    def _extraer_resultados(raw: str, n_esperado: int) -> list | None:
        """
        Intenta extraer la lista de resultados del JSON con múltiples estrategias.
        Devuelve lista de ints o None si no se puede parsear.
        """
        if not raw:
            return None

        # Intento 1: JSON directo
        try:
            data = json.loads(raw)
            res = data.get("resultados", data.get("results", data.get("r", None)))
            if isinstance(res, list) and len(res) == n_esperado:
                return [int(bool(v)) for v in res]
        except Exception:
            pass

        # Intento 2: Limpiar markdown y reintentar
        raw_clean = re.sub(r"```json|```", "", raw, flags=re.IGNORECASE).strip()
        try:
            data = json.loads(raw_clean)
            res = data.get("resultados", data.get("results", data.get("r", None)))
            if isinstance(res, list) and len(res) == n_esperado:
                return [int(bool(v)) for v in res]
        except Exception:
            pass

        # Intento 3: Extraer array directamente con regex
        # Busca el primer array JSON en el texto: [1, 0, 1, ...]
        match = re.search(r'\[([0-9,\s]+)\]', raw)
        if match:
            try:
                vals = [int(v.strip()) for v in match.group(1).split(",") if v.strip()]
                if len(vals) == n_esperado:
                    return [int(bool(v)) for v in vals]
                # Si tiene más o menos valores, truncar/rellenar
                if len(vals) > 0:
                    vals = (vals + [1] * n_esperado)[:n_esperado]
                    return [int(bool(v)) for v in vals]
            except Exception:
                pass

        # Intento 4: Extraer números individuales en orden de aparición
        nums = re.findall(r'\b([01])\b', raw)
        if len(nums) >= n_esperado:
            return [int(n) for n in nums[:n_esperado]]
        if len(nums) > 0:
            # Rellenar con 1 (coherente) si faltan
            nums = (nums + ['1'] * n_esperado)[:n_esperado]
            return [int(n) for n in nums]

        return None

    # ── Conexión LLM ──────────────────────────────────────────────────────────
    try:
        from openai import OpenAI
        client_coh = OpenAI(
            base_url="http://localhost:8001/v1",
            api_key="local-token",
            timeout=30.0,
        )
        from clean_project.vllm.model_config import MODELO_ACTIVO
        MODEL_COH = MODELO_ACTIVO
        llm_disponible = True
    except Exception as e:
        print(f"[COH] ⚠️ LLM no disponible: {e}. Usando heurística.")
        llm_disponible = False

    if not llm_disponible:
        _CONTRASTE = {"pero", "aunque", "sin embargo", "no", "nunca", "jamás",
                      "tampoco", "excepto", "salvo", "a pesar"}
        for item in pendientes:
            t   = item["termino"].lower()
            ctx = item["contenido"].lower()
            pos = item["posicion"]
            idx_t = ctx.find(t)
            ventana = ctx[max(0, idx_t - 60): idx_t + 10] if idx_t >= 0 else ""
            es_contraste = any(m in ventana for m in _CONTRASTE)
            cache[item["key"]] = 0 if (es_contraste and pos != 0) else 1
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        return cache

    # ── Procesar en lotes pequeños ────────────────────────────────────────────
    # Lotes de 10 (no 20) para reducir longitud del prompt y errores de JSON
    BATCH = 10

    for i in range(0, len(pendientes), BATCH):
        lote = pendientes[i: i + BATCH]

        # Construir items con texto limpio para evitar JSON roto
        items_str = "\n".join([
            f'{j+1}. "{_limpiar_para_json(it["termino"], 40)}" | '
            f'postura={it["posicion"]} | '
            f'texto="{_limpiar_para_json(it["contenido"], 120)}"'
            for j, it in enumerate(lote)
        ])

        prompt = (
            f'Tema: "{_limpiar_para_json(tema, 80)}"\n\n'
            f'Para cada par (término, texto), indica si el término expresa un aspecto\n'
            f'coherente con la postura del post sobre el tema (1) o lo contradice/no\n'
            f'es relevante para la postura (0).\n\n'
            f'{items_str}\n\n'
            f'Responde SOLO con este JSON exacto (array de {len(lote)} enteros 0 o 1):\n'
            f'{{"resultados": [VALORES]}}'
        )

        exito = False
        for intento in range(3):  # 3 intentos (era 2)
            try:
                resp = client_coh.chat.completions.create(
                    model=MODEL_COH,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=80,  # solo necesitamos el array corto
                )
                raw = resp.choices[0].message.content or ""
                print(f"[COH] Lote {i//BATCH} raw: {raw[:100]!r}")

                resultados = _extraer_resultados(raw, len(lote))

                if resultados is not None:
                    for k, it in enumerate(lote):
                        cache[it["key"]] = resultados[k]
                    exito = True
                    break
                else:
                    print(f"[COH] Lote {i//BATCH} intento {intento}: no se pudo parsear. "
                          f"Raw: {raw[:200]!r}")

            except Exception as e:
                print(f"[COH] Lote {i//BATCH} intento {intento} excepción: {e}")

            time.sleep(0.5)

        if not exito:
            print(f"[COH] ⚠️ Lote {i//BATCH} fallido tras 3 intentos. "
                  f"Asignando coherencia=1 (heurística).")
            for it in lote:
                cache.setdefault(it["key"], 1)

        # Guardar cache incremental tras cada lote
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    print(f"[COH] ✅ Coherencia calculada. Cache total: {len(cache)} entradas.")
    return cache

# ══════════════════════════════════════════════════════════════════════════════
# 4. NUBE UNIFICADA v2 — palabras + bigramas (15 de cada)
# ══════════════════════════════════════════════════════════════════════════════

def construir_nube_unificada_v2(df_all: pd.DataFrame, keywords: List[str] = None, top_n: int = 40, top_palabras: int = 50,
    top_bigramas: int = 50, folder=None) -> List[Dict[str, Any]]:
    if folder is not None:
        df_all = _enriquecer_con_scoreop(df_all, folder)
    
    posts = df_all[df_all["tipo_norm"].isin(TIPOS_POST) & (df_all["sent_num"] != 2)].copy()
    if posts.empty: return []

    # Acumuladores
    t_sup: Dict[str, float] = defaultdict(float)
    t_raw: Dict[str, float] = defaultdict(float)
    t_data: Dict[str, list] = defaultdict(list)
    t_tipo: Dict[str, str] = {}
    t_cnt: Counter = Counter()

    for _, row in posts.iterrows():
        sup_i = _safe_float(row.get("ScoreOP_sup", 1.0))
        raw_i = _safe_float(row.get("ScoreOP", 0.0))
        pos   = int(_safe_float(row.get("sent_num", 0)))
        sent  = int(_safe_float(row.get("sent_topic", 0)))
        
        extraidos = _procesar_texto_nube(row.get("contenido", ""), set(keywords or []))

        # Unigramas y Bigramas
        for term in set(extraidos["unigramas"] + extraidos["bigramas"]):
            tipo = "bigrama" if " " in term else "palabra"
            t_sup[term] += sup_i
            t_raw[term] += raw_i
            t_data[term].append((sent, pos))
            t_tipo[term] = tipo
            t_cnt[term] += 1

    resultados = []
    for term, total_sup in t_sup.items():
        # ELIMINADO EL FILTRO Nb < 2 para ver todo
        Cb = t_raw[term] / total_sup if total_sup > 0 else 0.0
        
        # Coherencia ponderada
        data = t_data[term]
        Ib = sum(1.0 - abs(s - p)/2.0 for s, p in data) / len(data)

        resultados.append({
            "text": term,
            "tipo": t_tipo[term],
            "Sb": round(total_sup, 4),
            "Cb": round(Cb, 4),
            "Ib": round(max(0.10, Ib), 4),
            "Nb": t_cnt[term]
        })

    # Separar y tomar top 20 de cada para el mix
    palabras = sorted([r for r in resultados if r["tipo"]=="palabra"], key=lambda x: x["Sb"], reverse=True)[:top_palabras]
    bigramas = sorted([r for r in resultados if r["tipo"]=="bigrama"], key=lambda x: x["Sb"], reverse=True)[:top_bigramas]

    
    return sorted(palabras + bigramas, key=lambda x: x["Sb"], reverse=True)

# ══════════════════════════════════════════════════════════════════════════════
# 5. GRAFO BIPARTITO v2 — G = (VT ∪ VU, E), ecuaciones 43-48 adaptadas
# ══════════════════════════════════════════════════════════════════════════════

def construir_grafo_bipartito_v2(df_all: pd.DataFrame, top_n_topicos: int = 15, folder=None, max_topicos: int = 200, 
    max_usuarios: int = 500,     # pool enviado al frontend; "Todos" en el selector usa esto como techo
) -> Dict[str, Any]:
    if folder is not None:
        df_all = _enriquecer_con_scoreop(df_all, folder)
    
    # Filtro estricto
    posts = df_all[df_all["tipo_norm"].isin(TIPOS_POST) & (df_all["sent_num"] != 2)].copy()
    if posts.empty: 
        print("[DEBUG-GRAFO] ⚠️ No hay posts después de filtrar por tipo y sentimiento.")
        return {"nodes": [], "edges": []}

    print(f"\n[DEBUG-GRAFO] Procesando {len(posts)} posts.")
    print(f"[DEBUG-GRAFO] Columnas disponibles: {posts.columns.tolist()}")
    sample = posts[['sent_topic', 'sent_num', 'ScoreOP', 'ScoreOP_sup']].head(3)
    print(f"[DEBUG-GRAFO] Muestra de valores:\n{sample}")

    # ACUMULADORES
    top_sup: Dict[str, float] = defaultdict(float) # Suma de ScoreOP_sup (Energía real)
    top_raw: Dict[str, float] = defaultdict(float) # Suma de ScoreOP (Raw real)
    top_pos: Dict[str, list]  = defaultdict(list)  # Para la sigma (opacidad)
    top_cnt: Counter          = Counter()

    usr_sup: Dict[str, float] = defaultdict(float)
    usr_raw: Dict[str, float] = defaultdict(float)
    usr_stance: Dict[str, list] = defaultdict(list)
    usr_plat: Dict[str, str] = {}

    aris_sup: Dict[tuple, float] = defaultdict(float)
    aris_raw: Dict[tuple, float] = defaultdict(float)
    aris_data: Dict[tuple, list] = defaultdict(list)

    for idx, row in posts.iterrows():
        topic = str(row.get("topic", "otros")).strip().lower()
        if topic in EXCLUIR_TOPICS: continue
        
        uid = str(row.get("id_anonimo", "DESCONOCIDO"))
        # USAR VALORES REALES DEL CSV
        s_sup = _safe_float(row.get("ScoreOP_sup", 1.0))
        s_raw = _safe_float(row.get("ScoreOP", 0.0))
        pos   = int(_safe_float(row.get("sent_num", 0)))
        sent  = int(_safe_float(row.get("sent_topic", 0)))

        # Acumular Tópico
        top_sup[topic] += s_sup
        top_raw[topic] += s_raw
        top_pos[topic].append(pos)
        top_cnt[topic] += 1

        # Acumular Usuario
        usr_sup[uid] += s_sup
        usr_raw[uid] += s_raw
        usr_stance[uid].append((sent, pos))
        if uid not in usr_plat: usr_plat[uid] = str(row.get("plataforma", ""))

        # Acumular Arista
        aris_sup[(uid, topic)] += s_sup
        aris_raw[(uid, topic)] += s_raw
        aris_data[(uid, topic)].append((sent, pos))

    # --- CONSTRUIR NODOS TÓPICO ---
    topicos_ordenados = sorted(top_sup.keys(), key=lambda t: top_sup[t], reverse=True)[:max_topicos]

    nodes_topico = []
    for t in topicos_ordenados:
        sup_t = top_sup[t]
        raw_t = top_raw[t]
        Ct = raw_t / sup_t if sup_t > 0 else 0.0

        sigma_p = float(np.std(top_pos[t])) if len(top_pos[t]) > 1 else 0.0
        Ib_t = 1.0 / (1.0 + sigma_p)

        nodes_topico.append({
            "id": f"topico__{t}",
            "label": t.upper(),
            "tipo": "topico",
            "St": round(sup_t, 4),
            "Ct": round(Ct, 4),
            "Ib_t": round(max(0.15, Ib_t), 4),
            "Nt": top_cnt[t]
        })
    
    nodes_usuario = []
    uids_ordenados = sorted(usr_sup, key=lambda u: usr_sup[u], reverse=True)

    for uid in uids_ordenados[:max_usuarios]: # Solo limitamos por rendimiento
        sup_u = usr_sup[uid]
        raw_u = usr_raw[uid]
        Cu = raw_u / sup_u if sup_u > 0 else 0.0
        
        # Coherencia (Alineación)
        pares = usr_stance[uid]
        Ib_u = sum(1.0 - abs(s - p)/2.0 for s, p in pares) / len(pares) if pares else 0.5

        nodes_usuario.append({
            "id": uid,
            "label": uid[:5].upper(),
            "tipo": "usuario",
            "plataforma": usr_plat.get(uid, ""),
            "Su": round(sup_u, 4),
            "Cu": round(Cu, 4),
            "Ib_u": round(max(0.15, Ib_u), 4),
            "n_posts": len(pares)
        })

    # --- ARISTAS ---
    edges = []
    uid_set = {n["id"] for n in nodes_usuario}
    for (uid, topic), s_local in aris_sup.items():
        if uid not in uid_set or topic not in top_sup: continue
        
        r_local = aris_raw[(uid, topic)]
        Cu_t = r_local / s_local if s_local > 0 else 0.0
        
        data_local = aris_data[(uid, topic)]
        Ib_e = sum(1.0 - abs(s - p)/2.0 for s, p in data_local) / len(data_local)

        edges.append({
            "source": uid,
            "target": f"topico__{topic}",
            "Wu_t": round(s_local, 4),
            "Cu_t": round(Cu_t, 4),
            "Ib_e": round(max(0.15, Ib_e), 4),
            "n_posts": len(data_local),
        })

    return {"nodes": nodes_topico + nodes_usuario, "edges": edges}
