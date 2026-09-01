"""
nube.py  –  Motor unificado de nubes de palabras  (v2)
=======================================================
Correcciones respecto a v1:
  · _construir_stops: ahora acepta keywords como lista de dicts
    [{keyword: "bici", ...}] además de lista de strings.
  · _normalizar_columnas: usa ScoreOP_pct ([0,100]) con conversión
    correcta a [-1,1] para la función de color — antes ScoreOP raw
    podía quedar en [0,1] y colorear todo de verde.
  · generar_nubes_desde_df / asegurar_nubes_dashboard:
    acepta un DataFrame extra con comentarios (df_comentarios) para
    enriquecer las nubes con el contenido de los replies.
  · Genera UNA NUBE POR RED SOCIAL — sin nube global.
  · Excluye las keywords de búsqueda (tokens individuales + bigramas).
"""

import os
import re
import base64
from io import BytesIO
from collections import Counter
from itertools import combinations
from pathlib import Path

import pandas as pd
import nltk
import unidecode
from nltk.util import ngrams
from wordcloud import WordCloud
from deep_translator import GoogleTranslator

# ─────────────────────────────────────────────
# 0.  DETECCIÓN DE IDIOMA (langdetect)
# ─────────────────────────────────────────────
try:
    from langdetect import detect as _ld_detect, LangDetectException
    _LANGDETECT_OK = True
except ImportError:
    _LANGDETECT_OK = False
    print("  ⚠️  langdetect no instalado. Se usará traducción forzada para todo texto.")

# ─────────────────────────────────────────────
# 0b. LEMATIZACIÓN (simplemma)
# ─────────────────────────────────────────────
try:
    import simplemma as _simplemma
    from simplemma import lang_detector as _simplemma_lang_detector  # <-- NUEVO
    _SIMPLEMMA_LANGS = ("es", "en", "ca", "pt", "fr", "it", "gl")
    _SIMPLEMMA_OK    = True
    print("  ✅  simplemma cargado para detección de idioma y lematización.")
except ImportError:
    _SIMPLEMMA_OK   = False
    print("  ⚠️  simplemma no instalado. Las nubes usarán formas flexionadas.")


def _lematizar(token: str, lang: str = "es") -> str:
    """
    Devuelve el lema de un token en el idioma dado.
    Si simplemma no está disponible o falla, devuelve el token original.
    lang: código ISO-639-1 ('es', 'en', 'ca'…)
    """
    if not _SIMPLEMMA_OK:
        return token
    try:
        # simplemma.lemmatize acepta el data precompilado directamente
        return _simplemma.lemmatize(token,  lang=_SIMPLEMMA_LANGS)
    except Exception:
        return token
def _detectar_idioma(texto: str) -> str:
    """Devuelve código ISO-639-1 del idioma detectado, o 'und' si falla."""
    if len(texto) < 20:
        return "und"
        
    # 1. Intentar con simplemma primero (rápido y eficiente)
    if _SIMPLEMMA_OK:
        try:
            # Devuelve una lista de tuplas: [("es", 0.75), ("en", 0.25)]
            resultados = _simplemma_lang_detector(texto, lang=_SIMPLEMMA_LANGS)
            if resultados:
                top_lang = resultados[0][0]
                if top_lang != "unk":
                    return top_lang
        except Exception:
            pass
            
    # 2. Fallback a langdetect si simplemma devuelve "unk" o falla
    if _LANGDETECT_OK:
        try:
            return _ld_detect(texto)
        except Exception:
            pass
            
    return "und"


# ─────────────────────────────────────────────
# 1.  STOPWORDS
# ─────────────────────────────────────────────
NLTK_DATA_PATH = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(NLTK_DATA_PATH, exist_ok=True)
nltk.data.path.append(NLTK_DATA_PATH)

for _corpus in ("stopwords",):
    try:
        nltk.data.find(f"corpora/{_corpus}")
    except LookupError:
        nltk.download(_corpus, download_dir=NLTK_DATA_PATH)

from nltk.corpus import stopwords as _nltk_sw

STOPWORDS_ES = set(_nltk_sw.words("spanish"))
STOPWORDS_EN = set(_nltk_sw.words("english"))

RUIDO_SOCIAL = {
    # Genérico conversacional
    "si", "no", "así", "hacer", "ver", "ir", "tan", "cada", "bien", "solo", "hace",
    "donde", "todo", "toda", "pero", "bueno", "muchas", "felicidades", "gracias", "hola",
    # Plataformas / apps (no aportan semántica del tema)
    "twitter", "reddit", "bluesky", "youtube", "tiktok", "facebook", "instagram",
    "whatsapp", "telegram", "linkedin",
    # CTAs y vocabulario de perfil social
    "suscribete", "siguenos", "canal", "pagina", "visita", "enlace", "link",
    "suscribirse", "subscribe", "follow", "unfollow", "compartir", "share",
    "comentario", "comment", "reply", "retweet", "like", "story", "stories",
    # URLs y ruido técnico
    "https", "http", "www", "post", "video", "foto", "imagen",
    # Inglés genérico
    "also", "just", "that", "this", "with", "from", "have", "been", "they", "will",
    "when", "said", "were", "more", "than", "some", "what", "about", "would", "could",
    "their", "there", "which", "after", "before", "other", "people", "think",
    # Palabras vacías de contexto administrativo/institucional
    "nuevo", "nueva", "nuevas", "nuevos", "paso", "pasos", "todas", "usar", "seis",
    "centro", "centros", "distritos", "estacion", "estaciones", "operativas",
    "previsible", "visible", "realiza", "realización", "conduccion", "millones",
    "euros", "mayo", "instax",
    # Hashtags/cuentas que aparecen como palabras
    "txivismo", "biciurbana", "callesdemadrid", "madridenbici", "enbicipormadrid",
    "pasionmadrid", "madciclista", "modelomadrid", "callemadrid",
}

CSV_LANG_TO_CODE = {
    "castellano": "es", "español": "es", "spanish": "es", "es": "es",
    "inglés": "en",    "english": "en",  "en": "en",
    "euskera": "eu",   "basque": "eu",   "eu": "eu",
    "catalán": "ca",   "catalan": "ca",  "ca": "ca",
    "gallego": "gl",   "galician": "gl", "gl": "gl",
    "francés": "fr",   "french": "fr",   "fr": "fr",
    "alemán": "de",    "german": "de",   "de": "de",
    "portugués": "pt", "portuguese": "pt","pt": "pt",
    "italiano": "it",  "italian": "it",  "it": "it",
}


def _limpiar(texto: str) -> str:
    if not isinstance(texto, str):
        return ""
    texto = texto.lower()
    texto = re.sub(r"http\S+|www\S+", "", texto)
    texto = re.sub(r"[@#]\S+", "", texto)        # elimina @usuario y #hashtag
    texto = unidecode.unidecode(texto)
    texto = re.sub(r"[^a-z\s]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _extraer_keyword_str(kw) -> str:
    """
    CORRECCIÓN v2: acepta tanto strings como dicts del tipo
    {"keyword": "bicimad", "languages": "Castellano"}.
    Devuelve siempre un string limpio.
    """
    if isinstance(kw, dict):
        # Buscar el campo con el texto real de la keyword
        for campo in ("keyword", "term", "value", "text", "query"):
            if kw.get(campo):
                return str(kw[campo])
        return ""
    return str(kw)


def _construir_stops(keywords_extra: list | None = None) -> set:
    """
    Combina stopwords ES + EN + ruido social + keywords del análisis.
    Acepta keywords como lista de strings O lista de dicts.
    """
    stops = STOPWORDS_ES | STOPWORDS_EN | RUIDO_SOCIAL

    if keywords_extra:
        for kw_raw in keywords_extra:
            kw = _extraer_keyword_str(kw_raw)
            if not kw.strip():
                continue
            tokens_kw = _limpiar(kw).split()
            stops.update(tokens_kw)
            if len(tokens_kw) >= 2:
                for ng in ngrams(tokens_kw, 2):
                    stops.add(" ".join(ng))
            if len(tokens_kw) >= 3:
                for a, b in combinations(tokens_kw, 2):
                    stops.add(f"{a} {b}")
                    stops.add(f"{b} {a}")

    return stops


# ─────────────────────────────────────────────
# 2.  NORMALIZACIÓN DE COLUMNAS
# ─────────────────────────────────────────────

def _normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Mapea alias de columnas al esquema interno:
      CONTENIDO · SENTIMIENTO · FUENTE · IDIOMA_IA

    CORRECCIÓN v2: usa ScoreOP_pct cuando existe y lo convierte
    correctamente a [-1, 1] para la función de color de la nube:
      pct=100 → +1 (muy positivo → verde oscuro)
      pct= 50 →  0 (neutro        → gris)
      pct=  0 → -1 (muy negativo  → rojo oscuro)
    """
    import numpy as np
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # ── Contenido ────────────────────────────────────────────────────────
    if "CONTENIDO" not in df.columns:
        for alias in ("contenido_post", "contenido", "content", "text", "body"):
            if alias in df.columns:
                df["CONTENIDO"] = df[alias]
                break

    # ── Sentimiento / score ───────────────────────────────────────────────
    # Prioridad: ScoreOP_pct (0-100) > ScoreOP raw > sentimiento {-1,0,1}
    if "SENTIMIENTO" not in df.columns:
        if "ScoreOP_pct" in df.columns:
            # Convertir [0, 100] → [-1, 1]:  pct/50 - 1
            pct = pd.to_numeric(df["ScoreOP_pct"], errors="coerce").fillna(50)
            df["SENTIMIENTO"] = (pct / 50.0) - 1.0  # 100→+1, 50→0, 0→-1
        else:
            for alias in ("ScoreOP", "scoreop", "sentimiento", "sentiment", "score"):
                if alias in df.columns:
                    raw = pd.to_numeric(df[alias], errors="coerce").fillna(0)
                    max_abs = raw.abs().max()
                    df["SENTIMIENTO"] = (raw / max_abs).clip(-1, 1) if max_abs > 1 else raw
                    break
            else:
                df["SENTIMIENTO"] = 0.0
    else:
        # Columna SENTIMIENTO ya existe: normalizar igual
        raw = pd.to_numeric(df["SENTIMIENTO"], errors="coerce").fillna(0)
        max_abs = raw.abs().max()
        df["SENTIMIENTO"] = (raw / max_abs).clip(-1, 1) if max_abs > 1 else raw

    # ── Fuente / plataforma ───────────────────────────────────────────────
    if "FUENTE" not in df.columns:
        for alias in ("plataforma", "platform", "source", "red"):
            if alias in df.columns:
                df["FUENTE"] = df[alias]
                break
        else:
            df["FUENTE"] = "desconocida"

    # ── Idioma (columna opcional) ─────────────────────────────────────────
    if "IDIOMA_IA" not in df.columns:
        for alias in ("idioma", "lang", "language", "idioma_ia"):
            if alias in df.columns:
                df["IDIOMA_IA"] = df[alias]
                break
        else:
            df["IDIOMA_IA"] = None

    return df


# ─────────────────────────────────────────────
# 3.  PROCESAMIENTO CON DETECCIÓN + TRADUCCIÓN
# ─────────────────────────────────────────────

def _procesar_df(df_subset: pd.DataFrame, stops: set):
    """
    Para cada fila:
      1. Detecta el idioma real del texto (langdetect).
      2. Si no es español, traduce con Google Translate.
      3. Tokeniza, filtra stopwords, construye unigramas + bigramas.

    Devuelve (word_counts, word_sentiments).
    """
    word_counts: Counter = Counter()
    word_sentiments: dict = {}

    translator = GoogleTranslator(source="auto", target="es")

    print(f"  🔄  Procesando {len(df_subset)} filas con detección de idioma…")

    for _, row in df_subset.iterrows():
        contenido_raw = str(row.get("CONTENIDO", "")).strip()
        if len(contenido_raw) < 15:
            continue

        idioma_col = str(row.get("IDIOMA_IA", "") or "").lower().strip()
        idioma_iso = CSV_LANG_TO_CODE.get(idioma_col, None)

        if idioma_iso is None:
            idioma_iso = _detectar_idioma(contenido_raw)

        if idioma_iso not in ("es", ""):
            try:
                traducido = translator.translate(contenido_raw)
                texto_final = traducido if traducido else contenido_raw
            except Exception:
                texto_final = contenido_raw
        else:
            texto_final = contenido_raw

        texto_limpio = _limpiar(texto_final)
        if not texto_limpio:
            continue

        score = float(row.get("SENTIMIENTO", 0) or 0)

        tokens_raw = [
            t for t in texto_limpio.split()
            if len(t) > 3 and t not in stops
        ]
        if not tokens_raw:
            continue

        tokens = []
        for t in tokens_raw:
            lema = _lematizar(t)
            if lema not in stops and len(lema) > 3:
                tokens.append(lema)

        if not tokens:
            continue  
          
        for t in tokens:
            word_counts[t] += 1
            word_sentiments.setdefault(t, []).append(score)

        if len(tokens) >= 2:
            for ng in ngrams(tokens, 2):
                frase = " ".join(ng)
                if frase in stops:
                    continue
                word_counts[frase] += 4
                word_sentiments.setdefault(frase, []).append(score)

    min_ap = 3 if len(df_subset) > 20 else 2
    final_counts = {k: v for k, v in word_counts.items() if v >= min_ap}
    if not final_counts:
        final_counts = dict(word_counts)

    final_sentiments = {
        w: sum(scores) / len(scores)
        for w, scores in word_sentiments.items()
        if w in final_counts
    }

    return final_counts, final_sentiments


# ─────────────────────────────────────────────
# 4.  GENERACIÓN DE IMAGEN
# ─────────────────────────────────────────────

def _generar_imagen_base64(counts: dict, sentiments: dict) -> str | None:
    if not counts:
        return None

    def color_func(word, font_size, position, orientation, random_state=None, **kwargs):
        score = sentiments.get(word, 0)
        # Con la nueva normalización ScoreOP_pct → [-1,1]:
        # score > +0.1 significa pct > 55% (positivo)
        # score < -0.1 significa pct < 45% (negativo)
        if score > 0.1:
            return "rgb(20, 160, 20)"    # verde  → positivo
        elif score < -0.1:
            return "rgb(220, 20, 20)"    # rojo   → negativo
        else:
            return "rgb(100, 100, 100)"  # gris   → neutro/polarizado

    try:
        wc = WordCloud(
            width=1000,
            height=600,
            background_color="white",
            max_words=60,
            color_func=color_func,
            collocations=False,
            prefer_horizontal=0.8,
            relative_scaling=0.5,
        ).generate_from_frequencies(counts)

        buf = BytesIO()
        wc.to_image().save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"  ⚠️  Error generando imagen WordCloud: {e}")
        return None


# ─────────────────────────────────────────────
# 5.  FUNCIÓN INTERNA COMPARTIDA
# ─────────────────────────────────────────────

def _nubes_por_red(df: pd.DataFrame, keywords: list | None,
                   df_comentarios: pd.DataFrame | None = None) -> dict:
    stops = _construir_stops(keywords)
    resultados = {}

    if "FUENTE" not in df.columns:
        return resultados

    for red in df["FUENTE"].dropna().unique():
        df_red = df[df["FUENTE"] == red]
        if len(df_red) < 3:
            continue

        # ── Nube de POSTS ────────────────────────────────────────────────
        print(f"  ☁️  Nube posts → {red} ({len(df_red)} filas)")
        c_post, s_post = _procesar_df(df_red, stops)
        red_clean = str(red).lower().replace(" ", "")
        img_post = _generar_imagen_base64(c_post, s_post)
        if img_post:
            resultados[f"nube_{red_clean}_posts"] = img_post

        # ── Nube de COMENTARIOS (si existen para esta red) ───────────────
        if df_comentarios is not None and not df_comentarios.empty:
            # Intentar alinear columna FUENTE en comentarios
            fuente_col = "FUENTE" if "FUENTE" in df_comentarios.columns else (
                "plataforma" if "plataforma" in df_comentarios.columns else None
            )
            if fuente_col:
                df_com_red = df_comentarios[
                    df_comentarios[fuente_col].str.lower().str.replace(" ", "") == red_clean
                ]
            else:
                df_com_red = df_comentarios   # si no hay columna de red, usar todos

            if len(df_com_red) >= 3:
                print(f"  ☁️  Nube comentarios → {red} ({len(df_com_red)} filas)")
                c_com, s_com = _procesar_df(df_com_red, stops)
                img_com = _generar_imagen_base64(c_com, s_com)
                if img_com:
                    resultados[f"nube_{red_clean}_comentarios"] = img_com

    return resultados


# ─────────────────────────────────────────────
# 6.  API PÚBLICA
# ─────────────────────────────────────────────

def generar_nubes_dashboard(csv_path, target_languages=None, keywords=None) -> dict:
    """
    Genera nubes desde un CSV (formato estándar o scoreop_consolidado).
    Devuelve dict { "nube_<red>": "<base64>", … }  — SIN nube global.

    `keywords`: lista de strings O dicts [{keyword: "...", ...}] con los
    términos de búsqueda a excluir.
    """
    try:
        csv_path = Path(csv_path)
        with open(csv_path, "r", encoding="utf-8") as f:
            sep = ";" if ";" in f.readline() else ","
        df = pd.read_csv(csv_path, sep=sep, encoding="utf-8", engine="python")
        df.columns = [c.strip().upper() if c.strip().upper() in
                      {"CONTENIDO", "SENTIMIENTO", "FUENTE", "IDIOMA_IA",
                       "KEYWORD", "KEYWORDS"} else c.strip()
                      for c in df.columns]

        df = _normalizar_columnas(df)

        kw_list = list(keywords or [])
        if not kw_list:
            kw_col = next((c for c in df.columns if c.upper() == "KEYWORD"), None)
            if kw_col:
                kw_list = [str(k) for k in df[kw_col].dropna().unique() if str(k).strip()]

        return _nubes_por_red(df, kw_list)

    except Exception as e:
        print(f"  ❌  Error en generar_nubes_dashboard: {e}")
        import traceback; traceback.print_exc()
        return {}


def generar_nubes_desde_df(
    df: pd.DataFrame,
    keywords: list | None = None,
    df_comentarios: pd.DataFrame | None = None,
) -> dict:
    """
    Igual que generar_nubes_dashboard pero acepta directamente un DataFrame.

    NUEVO: parámetro opcional `df_comentarios`.
    Si se proporciona un DataFrame con filas de tipo 'comentario'
    (columnas esperadas: contenido/CONTENIDO, plataforma/FUENTE, sentimiento/ScoreOP_pct),
    se fusiona con df antes de generar las nubes, enriqueciendo el vocabulario
    con las voces de los comentaristas.

    Devuelve dict { "nube_<red>": "<base64>", … }  — SIN nube global.
    """
    try:
        df_norm = _normalizar_columnas(df)
        df_com_norm = None

        if df_comentarios is not None and not df_comentarios.empty:
            df_com_norm = _normalizar_columnas(df_comentarios)
            # Alinear columnas mínimas
            cols_comunes = list({"CONTENIDO", "SENTIMIENTO", "FUENTE", "IDIOMA_IA"}
                                & set(df_norm.columns) & set(df_com_norm.columns))
            if cols_comunes:
                df_com_norm = df_com_norm[cols_comunes]
                df_norm = df_norm[cols_comunes] if all(c in df_norm.columns for c in cols_comunes) else df_norm
                import pandas as _pd
                df_norm = _pd.concat([df_norm, df_com_norm], ignore_index=True)
                print(f"  ℹ️  Nubes: fusionados {len(df_comentarios)} comentarios con {len(df)} posts.")

        kw_list = list(keywords or [])
        return _nubes_por_red(df_norm, kw_list, df_com_norm)
    except Exception as e:
        print(f"  ❌  Error en generar_nubes_desde_df: {e}")
        import traceback; traceback.print_exc()
        return {}