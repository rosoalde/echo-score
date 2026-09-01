"""
vllm_geo_filter.py
==================
LLM-based geographic / argument filter with persistent column caching.

• Geographic filter  → binary column  geo_<slug>  (1 = references the place, 0 = doesn't)
• Argument filter    → stance column  topicf_<slug>  (-1 / 0 / 1 / 2)
    -1  → content argues AGAINST the given argument
     0  → content mentions the argument neutrally / informatively
     1  → content argues IN FAVOUR of the given argument
     2  → content does NOT address the argument at all  (filtered out)

The -1/0/1/2 schema mirrors the main sentiment analysis so the dashboard
can reuse all existing ScoreOP and chart logic on the filtered subset.

Public API
----------
aplicar_filtro_geo(df, termino, csv_path, u_conf)
    → df filtrado (filas con geo_<slug> == 1)

aplicar_filtro_argumento(df, argumento, tema, csv_path, u_conf)
    → (df_filtrado, col_name)
      df_filtrado: filas con topicf_<slug> in {-1, 0, 1}  (excluye 2)
      col_name: column name so callers can read stance distribution

aplicar_filtros_llm(df, terminos_geo, terminos_topic, csv_path, u_conf, tema)
    → (df_filtrado, metadata)
      metadata: list[dict] ready for the PDF section
"""

from __future__ import annotations

import concurrent.futures
import re
import unicodedata
from pathlib import Path
from typing import Optional

import pandas as pd
from openai import OpenAI

from clean_project.vllm.model_config import MODELO_ACTIVO

# ── vLLM client ──────────────────────────────────────────────────────────────
client = OpenAI(
    base_url="http://host.docker.internal:8001/v1",
    api_key="local-token",
    timeout=60.0,
)
MODEL_NAME = MODELO_ACTIVO
BATCH_SIZE = 80


# ── Column-name helpers ───────────────────────────────────────────────────────

def _slug(text: str) -> str:
    text = str(text).strip().lower()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:40]


def col_name_geo(termino: str) -> str:
    return f"geo_{_slug(termino)}"


def col_name_topic(argumento: str) -> str:
    """Stance column for a sub-argument. Values: -1 / 0 / 1 / 2."""
    return f"topicf_{_slug(argumento)}"


# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_GEO = (
    "Eres un clasificador binario. "
    "Tu única salida debe ser JSON con una sola clave 'r' cuyo valor es 0 o 1. "
    "Sin texto adicional."
)

_SYSTEM_TOPIC = (
    "Eres un analizador de opinión. "
    "Tu única salida debe ser JSON con una sola clave 'r' cuyo valor es -1, 0, 1 o 2. "
    "Sin texto adicional."
)


def _build_prompt_geo(termino: str, texto: str) -> str:
    return (
        f"¿El siguiente texto hace alguna referencia, directa o indirecta, "
        f"a «{termino}»? Considera nombres de calles, barrios, lugares, "
        f"servicios locales, gentilicios u otras referencias geográficas "
        f"que permitan inferir que el autor habla de ese lugar.\n\n"
        f"Texto:\n{texto[:3000]}\n\n"
        f"Responde SOLO con {{\"r\":1}} si SÍ hay referencia, {{\"r\":0}} si NO."
    )


def _build_prompt_topic(argumento: str, tema: str, texto: str) -> str:
    """
    Asks the model for the stance on a *specific argument* within the main topic.
    Mirrors the main sentiment analysis but scoped to the argument.

    Output:
         1 → a favor / positivo / beneficios del argumento
        -1 → en contra / crítica / problemas con el argumento
         0 → neutro / informativo / equilibrado sobre el argumento
         2 → el texto NO aborda este argumento (no relacionado)
    """
    return f"""Tema de análisis general: «{tema}»
Argumento específico a evaluar: «{argumento}»

Analiza el texto y determina la POSTURA del autor respecto al argumento «{argumento}».

🚨 PASO 0 — FILTRO:
¿El texto aborda, aunque sea de forma secundaria, el argumento «{argumento}»?
Si NO lo aborda en absoluto → responde {{"r":2}} y detente.

Ten en cuenta ironía y sarcasmo al filtrar: si el autor menciona el argumento de forma irónica o sarcástica, SÍ lo aborda.

🚨 PASO 1 — POSTURA (solo si el texto SÍ aborda el argumento):
Determina la postura sobre «{argumento}»:
 "1"  → A favor / Positivo / El autor apoya o ve beneficios en este argumento
"-1"  → En contra / Crítica / El autor cuestiona, critica o ve problemas en este argumento
 "0"  → Neutro / Informativo / El autor menciona el argumento sin posicionarse claramente
 "2"  → El texto no aborda este argumento (usar solo si no hay ninguna referencia)

REGLAS:
- Ironía o sarcasmo que critica el argumento → -1
- Apoyo implícito (aunque no se diga explícitamente) → 1
- Duda razonable → 0, nunca 2
- Solo usar 2 cuando sea CLARO e INEQUÍVOCO que el texto no menciona ni implica el argumento

Texto:
{texto[:3000]}

Responde SOLO con el JSON. Ejemplos: {{"r":1}} {{"r":-1}} {{"r":0}} {{"r":2}}"""


# ── Text builder ──────────────────────────────────────────────────────────────

def _preparar_texto(row: pd.Series) -> str:
    def safe(val) -> str:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        s = str(val).strip()
        return "" if s.lower() in {"nan", "none", ""} else s

    partes: list[str] = []
    contenido = safe(row.get("contenido") or row.get("contenido_post"))
    if contenido.lower() in {"[removed]", "[deleted]"}:
        return ""
    if contenido:
        partes.append(f"[CONTENIDO]\n{contenido}")

    for campo, etiqueta in [
        ("titulo_video",    "TÍTULO VIDEO"),
        ("post_title",      "TÍTULO POST"),
        ("post_selftext",   "CUERPO POST"),
        ("BeforeContenido", "TWEET ANTERIOR"),
        ("subreddit",       "FUENTE"),
        ("transcripcion",   "TRANSCRIPCIÓN"),
        ("texto_citado", "POST CITADO"),
    ]:
        val = safe(row.get(campo))
        if val:
            partes.append(f"[{etiqueta}]\n{val[:500]}")

    return "\n\n".join(partes)


# ── Workers ───────────────────────────────────────────────────────────────────

def _worker_geo(idx: int, texto: str, termino: str) -> tuple[int, Optional[int]]:
    if not texto:
        return idx, 0
    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": _SYSTEM_GEO},
                {"role": "user",   "content": _build_prompt_geo(termino, texto)},
            ],
            temperature=0.0,
            max_tokens=12,
        )
        raw = resp.choices[0].message.content.strip()
        m   = re.search(r'"r"\s*:\s*([01])', raw)
        if m:
            return idx, int(m.group(1))
        return idx, 1 if "1" in raw else 0
    except Exception as exc:
        print(f"  ❌ geo idx={idx}: {exc}")
        return idx, None


def _worker_topic(
    idx: int,
    texto: str,
    argumento: str,
    tema: str,
) -> tuple[int, Optional[int]]:
    if not texto:
        return idx, 2
    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": _SYSTEM_TOPIC},
                {"role": "user",   "content": _build_prompt_topic(argumento, tema, texto)},
            ],
            temperature=0.0,
            max_tokens=15,
        )
        raw = resp.choices[0].message.content.strip()
        m   = re.search(r'"r"\s*:\s*(-?[012])', raw)
        if m:
            val = int(m.group(1))
            return idx, val if val in {-1, 0, 1, 2} else 2
        # bare number fallback
        m2 = re.search(r'-?[012]', raw)
        if m2:
            val = int(m2.group(0))
            return idx, val if val in {-1, 0, 1, 2} else 2
        return idx, 2
    except Exception as exc:
        print(f"  ❌ topic idx={idx}: {exc}")
        return idx, None


# ── Generic batch runner ──────────────────────────────────────────────────────

def _run_batch(
    df: pd.DataFrame,
    col: str,
    worker_fn,
    default_miss: int,
    *worker_args,
) -> pd.DataFrame:
    """
    1. Ensures *col* exists in df.
    2. Identifies rows where col is NaN (pending).
    3. Calls worker_fn(idx, texto, *worker_args) in parallel batches.
    4. Writes results back to df[col].
    """
    if col not in df.columns:
        df[col] = float("nan")
    df[col] = pd.to_numeric(df[col], errors="coerce")

    indices = df[df[col].isna()].index.tolist()

    if not indices:
        print(f"  ✅ Columna '{col}' ya completa ({len(df)} filas).")
        return df

    tareas = [(idx, _preparar_texto(df.loc[idx])) for idx in indices]

    for batch_start in range(0, len(tareas), BATCH_SIZE):
        batch = tareas[batch_start : batch_start + BATCH_SIZE]

        with concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_SIZE) as ex:
            futures = {
                ex.submit(worker_fn, idx, texto, *worker_args): idx
                for idx, texto in batch
            }
            for future in concurrent.futures.as_completed(futures):
                ridx, valor = future.result()
                df.at[ridx, col] = float(
                    valor if valor is not None else default_miss
                )

    return df


# ── Public filter functions ───────────────────────────────────────────────────

def aplicar_filtro_geo(
    df: pd.DataFrame,
    termino: str,
    csv_path: Optional[Path] = None,
    *,
    u_conf=None,
) -> pd.DataFrame:
    """
    Filters df to rows referencing *termino* geographically.
    Caches results in column  geo_<slug>  (0 / 1).
    """
    col     = col_name_geo(termino)
    pending = df[col].isna().sum() if col in df.columns else len(df)
    print(f"  🗺️  Geo filter «{termino}»: {pending} pendientes de {len(df)}")

    df = _run_batch(df, col, _worker_geo, 0, termino)

    if csv_path is not None:
        _persistir_columna(df, col, csv_path)

    matches = int(df[col].fillna(0).sum())
    print(f"  📍 «{termino}»: {matches}/{len(df)} ({matches / max(len(df), 1) * 100:.1f}%)")
    return df[df[col] == 1.0].copy()


def aplicar_filtro_argumento(
    df: pd.DataFrame,
    argumento: str,
    tema: str = "",
    csv_path: Optional[Path] = None,
    *,
    u_conf=None,
) -> tuple[pd.DataFrame, str]:
    """
    Assigns a stance (-1/0/1/2) to each row for *argumento*.
    Caches results in column  topicf_<slug>.

    Returns:
        (df_filtrado, col_name)
        df_filtrado → rows where stance ∈ {-1, 0, 1}  (2 = not related, excluded)
        col_name    → column name so callers can build stance charts
    """
    col     = col_name_topic(argumento)
    pending = df[col].isna().sum() if col in df.columns else len(df)
    print(f"  🧠 Arg filter «{argumento}»: {pending} pendientes de {len(df)}")

    df = _run_batch(df, col, _worker_topic, 2, argumento, tema)

    if csv_path is not None:
        _persistir_columna(df, col, csv_path)

    col_vals = pd.to_numeric(df[col], errors="coerce").fillna(2)
    dist     = {v: int((col_vals == v).sum()) for v in (1, 0, -1, 2)}
    n_rel    = dist[1] + dist[0] + dist[-1]
    print(
        f"  📊 «{argumento}»: {n_rel}/{len(df)} relacionados "
        f"| +{dist[1]} ~{dist[0]} -{dist[-1]} ✗{dist[2]}"
    )

    df_filtrado = df[col_vals != 2].copy()
    return df_filtrado, col


def aplicar_filtros_llm(
    df: pd.DataFrame,
    terminos_geo:   list[str],
    terminos_topic: list[str],
    csv_path:       Optional[Path] = None,
    *,
    u_conf=None,
    tema: str = "",
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Applies geographic AND argument filters sequentially (AND logic).

    Returns:
        (df_filtrado, metadata_filtros)

    metadata item shapes:
        Geographic:
            {"tipo": "geográfico", "termino": str, "columna": str,
             "total_entrada": int, "coincidencias": int}

        Argument:
            {"tipo": "argumento", "termino": str, "columna": str,
             "total_entrada": int, "coincidencias": int,
             "distribucion": {"pos": int, "neu": int, "neg": int},
             "stance_col": str}
    """
    df_actual = df.copy()
    metadata: list[dict] = []

    # ── Geographic filters ────────────────────────────────────────────────────
    for termino in terminos_geo:
        total_antes = len(df_actual)
        col         = col_name_geo(termino)
        df_actual   = aplicar_filtro_geo(df_actual, termino, csv_path, u_conf=u_conf)
        metadata.append({
            "tipo":          "geográfico",
            "termino":       termino,
            "columna":       col,
            "total_entrada": total_antes,
            "coincidencias": len(df_actual),
        })

    # ── Argument filters (stance -1/0/1/2) ────────────────────────────────────
    for argumento in terminos_topic:
        total_antes         = len(df_actual)
        col                 = col_name_topic(argumento)
        df_actual, col_back = aplicar_filtro_argumento(
            df_actual, argumento, tema, csv_path, u_conf=u_conf
        )
        # Stance distribution for the PDF / dashboard charts
        col_vals = pd.to_numeric(df_actual[col_back], errors="coerce").fillna(2)
        dist     = {
            "pos": int((col_vals ==  1).sum()),
            "neu": int((col_vals ==  0).sum()),
            "neg": int((col_vals == -1).sum()),
        }
        metadata.append({
            "tipo":          "argumento",
            "termino":       argumento,
            "columna":       col,
            "total_entrada": total_antes,
            "coincidencias": len(df_actual),
            "distribucion":  dist,
            "stance_col":    col_back,   # so the dashboard can build a mini chart
        })

    return df_actual, metadata


# ── CSV persistence ───────────────────────────────────────────────────────────

def _persistir_columna(df: pd.DataFrame, col: str, csv_path: Path) -> None:
    """
    Merges column *col* back into the on-disk CSV.
    Uses index alignment when row counts match; falls back to key-column merge.
    """
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            sep = ";" if ";" in f.readline() else ","
        df_disk = pd.read_csv(csv_path, sep=sep, encoding="utf-8", on_bad_lines="skip")

        if len(df_disk) == len(df):
            df_disk[col] = df[col].values
        else:
            key_cols = [
                c for c in ["id", "url", "contenido"]
                if c in df_disk.columns and c in df.columns
            ]
            if key_cols:
                merge_df = df[[key_cols[0], col]].drop_duplicates(subset=key_cols[0])
                df_disk  = df_disk.merge(
                    merge_df, on=key_cols[0], how="left", suffixes=("_old", "")
                )
                old_col = f"{col}_old"
                if old_col in df_disk.columns:
                    df_disk[col] = df_disk[col].combine_first(df_disk[old_col])
                    df_disk.drop(columns=[old_col], inplace=True)
            else:
                print(f"  ⚠️  No key column found; using positional alignment for '{col}'.")
                df_disk[col] = df[col].values[: len(df_disk)]

        df_disk.to_csv(csv_path, sep=sep, index=False, encoding="utf-8")
        print(f"  💾 '{col}' persistida → {csv_path.name}")

    except Exception as exc:
        print(f"  ⚠️  Error persistiendo '{col}': {exc}")


def cargar_columnas_cache(df: pd.DataFrame, csv_path: Path) -> pd.DataFrame:
    """
    Reads cached geo_* / topicf_* columns from *csv_path* into *df*.
    Safe to call even if the file doesn't exist or has no cache columns.
    """
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            sep = ";" if ";" in f.readline() else ","
        df_disk    = pd.read_csv(csv_path, sep=sep, encoding="utf-8", on_bad_lines="skip")
        cache_cols = [
            c for c in df_disk.columns
            if c.startswith("geo_") or c.startswith("topicf_")
        ]
        if len(df_disk) == len(df):
            for col in cache_cols:
                if col not in df.columns:
                    df[col] = df_disk[col].values
    except Exception:
        pass
    return df