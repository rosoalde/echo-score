"""
generate_report.py
==================
Genera un informe PDF profesional con todas las gráficas y métricas del
dashboard de análisis de opinión en redes sociales.

Paleta institucional DS4M Mediterráneo (Universidad de Valencia / INTRAS):
  Azul primario   #1B3A6B  · Azul secundario #2E5FA3
  Amarillo acento #F5A623  · Azul claro      #4A7CC1
  Fondo suave     #F4F6FA  · Borde           #D0D9EC
  Texto oscuro    #1A1A2E  · Texto medio     #3D3D5C

Uso desde main.py:
    from generate_report import build_analysis_pdf
    pdf_bytes = build_analysis_pdf(dashboard_data, analysis_meta, aceptacion_data)
"""

from __future__ import annotations

import base64
from collections import defaultdict
import io
import json
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
import numpy as np
import pandas as pd
import math

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    FrameBreak,
    HRFlowable,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Frame,
    KeepTogether,
)
from reportlab.platypus.flowables import Flowable

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ─────────────────────────────────────────────────────────────────────────────
# PALETA INSTITUCIONAL DS4M Mediterráneo
# ─────────────────────────────────────────────────────────────────────────────
C_PRIMARY    = colors.HexColor("#1B3A6B")
C_SECONDARY  = colors.HexColor("#2E5FA3")
C_ACCENT     = colors.HexColor("#F5A623")
C_ACCENT2    = colors.HexColor("#4A7CC1")
C_LIGHT_BG   = colors.HexColor("#F4F6FA")
C_BORDER     = colors.HexColor("#D0D9EC")
C_TEXT_DARK  = colors.HexColor("#1A1A2E")
C_TEXT_MID   = colors.HexColor("#3D3D5C")
C_TEXT_LIGHT = colors.HexColor("#7A7A9A")
C_WHITE      = colors.white

C_VERY_POS   = colors.HexColor("#0a7c4a")
C_POS        = colors.HexColor("#0eb26c")
C_NEU        = colors.HexColor("#adb5bd")
C_NEG        = colors.HexColor("#f28c8c")
C_VERY_NEG   = colors.HexColor("#d8535f")

PLT_PLATFORM = {
    "bluesky": "#01A5FF",
    "reddit":  "#FF4500",
    "telegram": "#0088CC",
    "youtube": "#FF0000",
}

PLT_COLORS = ["#2E5FA3", "#F5A623", "#0eb26c", "#f28c8c", "#4A7CC1", "#e8c302"]

PLATFORM_ORDER_NAME = ["bluesky", "reddit", "telegram", "youtube"]

import unicodedata
import re



_SOURCE_UNIT_LABEL = {
    "reddit":   "publicaciones en Reddit",
    "bluesky":  "publicaciones en Bluesky",
    "youtube":  "vídeos publicados en YouTube",
    "telegram": "mensajes publicados en canales de Telegram",
}



def _build_sources_description(fuentes_ordenadas: list[str]) -> str:
    """Genera la frase descriptiva de tipos de contenido según las fuentes presentes."""
    posts_platforms = []
    other_labels = []
    for f in fuentes_ordenadas:
        key = str(f).lower()
        if key in ("reddit", "bluesky"):
            posts_platforms.append(f.capitalize())
        elif key == "youtube":
            other_labels.append("vídeos publicados en YouTube")
        elif key == "telegram":
            other_labels.append("mensajes publicados en canales de Telegram")
        else:
            other_labels.append(f"contenido de {f.capitalize()}")

    parts = []
    if posts_platforms:
        if len(posts_platforms) == 1:
            parts.append(f"publicaciones en {posts_platforms[0]}")
        else:
            parts.append(f"publicaciones en {' y '.join(posts_platforms)}")
    parts.extend(other_labels)

    if not parts:
        return "—"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + ", así como " + parts[-1]    

def _build_sources_desc_short(fuentes_ordenadas: list[str]) -> str:
    """Versión breve para frases tipo 'Publicaciones de X, Y y vídeos de Z'."""
    posts_platforms = []
    other_labels = []
    for f in fuentes_ordenadas:
        key = str(f).lower()
        if key in ("reddit", "bluesky"):
            posts_platforms.append(f.capitalize())
        elif key == "youtube":
            other_labels.append("vídeos de YouTube")
        elif key == "telegram":
            other_labels.append("mensajes de canales de Telegram")
        else:
            other_labels.append(f"contenido de {f.capitalize()}")

    parts = []
    if posts_platforms:
        if len(posts_platforms) == 1:
            parts.append(f"publicaciones de {posts_platforms[0]}")
        else:
            parts.append(f"publicaciones de {' o '.join(posts_platforms)}")
    parts.extend(other_labels)

    if not parts:
        return "contenido"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " y " + parts[-1]

def limpiar_texto_pdf(txt):
    if not txt:
        return ""

    txt = str(txt)

    # Normalizar unicode raro
    txt = unicodedata.normalize("NFKD", txt)

    # Convertir letras unicode fancy a ASCII normal
    txt = txt.encode("ascii", "ignore").decode("ascii")

    # Eliminar caracteres de control
    txt = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', txt)

    # Compactar espacios
    txt = re.sub(r'\s+', ' ', txt).strip()

    return txt


def _plat_color(name: str, idx: int = 0) -> str:
    key = (name or "").lower()
    for k, v in PLT_PLATFORM.items():
        if k in key:
            return v
    return PLT_COLORS[idx % len(PLT_COLORS)]


def _scoreop_cat(pct: float) -> tuple[str, str]:
    if pct > 80:  return "Convergencia positiva alta",        "#0a7c4a"
    if pct >= 60: return "Predominancia positiva",             "#0eb26c"
    if pct >= 40: return "Equilibrio / Polarización",   "#adb5bd"
    if pct >= 20: return "Predominancia negativa",          "#f28c8c"
    return             "Convergencia negativa alta",         "#d8535f"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS MATPLOTLIB
# ─────────────────────────────────────────────────────────────────────────────
def _fig_to_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _fmt_date(raw: str) -> str:
    if not raw or raw == "—":
        return raw
    s = str(raw).strip()
    import re as _re
    if _re.match(r"^\d{2}/\d{2}/\d{4}$", s):
        return s
    try:
        if _re.match(r"^\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        if _re.match(r"^\d{2}-\d{2}-\d{4}", s):
            return datetime.strptime(s[:10], "%d-%m-%Y").strftime("%d/%m/%Y")
        from dateutil import parser as _dp
        return _dp.parse(s).strftime("%d/%m/%Y")
    except Exception:
        return s


def _img_from_bytes(data: bytes, width: float, height: float | None = None) -> Image:
    reader = ImageReader(io.BytesIO(data))
    if height is None:
        iw, ih = reader.getSize()
        height = width * ih / iw if iw else width * 0.5
    return Image(io.BytesIO(data), width=width, height=height)


def _b64_to_img(b64str: str, width: float) -> Image | None:
    try:
        raw = base64.b64decode(b64str)
        return _img_from_bytes(raw, width)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# GRÁFICAS
# ─────────────────────────────────────────────────────────────────────────────
def _apply_ds4m_style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_color("#D0D9EC")
    ax.spines["bottom"].set_color("#D0D9EC")
    ax.tick_params(colors="#3D3D5C", labelsize=8)
    ax.yaxis.label.set_color("#3D3D5C")
    ax.xaxis.label.set_color("#3D3D5C")
    ax.title.set_color("#1B3A6B")
    ax.grid(axis="y", color="#D0D9EC", alpha=0.6, linewidth=0.5)


def _chart_donut_platforms(vol_por_red: dict, order: list | None = None) -> bytes:
    labels = order if order else list(vol_por_red.keys())
    values = [vol_por_red[l] for l in labels]
    clrs   = [_plat_color(l, i) for i, l in enumerate(labels)]

    fig, ax = plt.subplots(figsize=(4.5, 3.5), facecolor="white")
    wedges, texts, autotexts = ax.pie(
        values, labels=None, autopct="%1.0f%%",
        colors=clrs, startangle=90,
        wedgeprops=dict(width=0.55, edgecolor="white", linewidth=2),
        pctdistance=0.75,
    )
    for at in autotexts:
        at.set_fontsize(9); at.set_color("white"); at.set_fontweight("bold")

    ax.legend(
        wedges, [f"{l.capitalize()} ({_fmt_int(v)})" for l, v in zip(labels, values)],
        loc="lower center", bbox_to_anchor=(0.5, -0.18),
        ncol=min(len(labels), 3), fontsize=8, frameon=False,
    )
    ax.set_title("Publicaciones por plataforma", fontsize=10, fontweight="bold",
                 color="#1B3A6B", pad=10)
    fig.tight_layout()
    return _fig_to_bytes(fig)


def _chart_comments_by_platform(vol_por_red: dict, scoreop: dict) -> bytes | None:
    por_plat = scoreop.get("por_plataforma", {})
    if not por_plat:
        return None

    plats  = list(vol_por_red.keys())
    counts = [vol_por_red.get(p, 0) for p in plats]

    comment_key = next(
        (k for k in por_plat.keys() if "comment" in k.lower() and "sum" in k.lower()), None
    )
    if comment_key:
        comments = [por_plat[comment_key].get(p, 0) for p in plats]
    else:
        comments = [0] * len(plats)

    x  = np.arange(len(plats))
    w  = 0.35
    fig, ax = plt.subplots(figsize=(6, 3.5), facecolor="white")
    b1 = ax.bar(x - w/2, counts,   w, label="Publicaciones",   color="#2E5FA3", alpha=0.85, edgecolor="white", linewidth=0.5)
    b2 = ax.bar(x + w/2, comments, w, label="Comentarios",     color="#F5A623", alpha=0.85, edgecolor="white", linewidth=0.5)

    for bar in b1:
        h = bar.get_height()
        if h: ax.text(bar.get_x() + bar.get_width()/2, h + 0.5, f"{_fmt_int(h)}", ha="center", fontsize=7.5)
    for bar in b2:
        h = bar.get_height()
        if h: ax.text(bar.get_x() + bar.get_width()/2, h + 0.5, f"{_fmt_int(h)}", ha="center", fontsize=7.5)

    ax.set_xticks(x)
    ax.set_xticklabels([p.capitalize() for p in plats], fontsize=9)
    ax.set_ylabel("Cantidad", fontsize=8)
    ax.set_title("Publicaciones y comentarios por plataforma", fontsize=10, fontweight="bold", color="#1B3A6B")
    ax.legend(fontsize=8, frameon=False)
    _apply_ds4m_style(ax)
    fig.tight_layout()
    return _fig_to_bytes(fig)


def _chart_trend_line(tendencia_global: dict, tendencia_por_red: dict) -> bytes:
    fechas_all: set[str] = set(tendencia_global.keys())
    for red, data in tendencia_por_red.items():
        fechas_all.update((data.get("total") or {}).keys())
    fechas = sorted(fechas_all)
    if not fechas:
        fig, ax = plt.subplots(figsize=(8, 3), facecolor="white")
        ax.text(0.5, 0.5, "Sin datos de tendencia", ha="center", va="center", color="#7A7A9A")
        return _fig_to_bytes(fig)

    fig, ax = plt.subplots(figsize=(8.5, 3.2), facecolor="white")
    global_vals = [tendencia_global.get(f, 0) for f in fechas]
    ax.fill_between(range(len(fechas)), global_vals, alpha=0.12, color="#2E5FA3")
    ax.plot(range(len(fechas)), global_vals,
            color="#2E5FA3", linewidth=2.5, label="Global", zorder=3)

    for i, (red, data) in enumerate(tendencia_por_red.items()):
        total = data.get("total", {})
        vals  = [total.get(f, 0) for f in fechas]
        ax.plot(range(len(fechas)), vals,
                color=_plat_color(red, i), linewidth=1.8, linestyle="--",
                label=red.capitalize(), alpha=0.85)

    step = max(1, len(fechas) // 12)
    ax.set_xticks(range(0, len(fechas), step))
    ax.set_xticklabels([_fmt_date(fechas[i]) for i in range(0, len(fechas), step)],
                       rotation=35, ha="right", fontsize=7)
    ax.set_ylabel("Publicaciones", fontsize=8)
    ax.set_title("Evolución temporal de la actividad", fontsize=10, fontweight="bold", color="#1B3A6B")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    _apply_ds4m_style(ax)
    fig.tight_layout()
    return _fig_to_bytes(fig)


def _chart_scoreop_dist_stacked(dist: dict, dist_por_plat: dict) -> bytes:
    cats      = ["muy_positivo", "positivo", "neutro", "negativo", "muy_negativo"]
    clrs      = ["#0a7c4a", "#0eb26c", "#adb5bd", "#f28c8c", "#d8535f"]
    labels_es = ["Muy positivo\n(>80%)", "Positivo\n(60-80%)", "Neutro\n(40-60%)",
                 "Negativo\n(20-40%)", "Muy negativo\n(<20%)"]

    if dist_por_plat:
        plats = list(dist_por_plat.keys())
        data_matrix = []
        for cat in cats:
            row = []
            for p in plats:
                d = dist_por_plat[p]
                total = d.get("total", 1) or 1
                row.append(d.get(cat, 0) / total * 100)
            data_matrix.append(row)
        x = np.arange(len(plats))
        fig, ax = plt.subplots(figsize=(7, 3.5), facecolor="white")
        bottom = np.zeros(len(plats))
        for cat_vals, clr, lbl in zip(data_matrix, clrs, labels_es):
            ax.bar(x, cat_vals, bottom=bottom, color=clr, label=lbl,
                   edgecolor="white", linewidth=0.5)
            bottom += np.array(cat_vals)
        ax.set_xticks(x)
        ax.set_xticklabels([p.capitalize() for p in plats], fontsize=9)
        ax.set_ylabel("% de publicaciones", fontsize=8)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
        ax.set_title("Distribución de polaridad por plataforma\n(% de publicaciones en cada categoría)",
                     fontsize=9, fontweight="bold", color="#1B3A6B")
        ax.legend(fontsize=7, frameon=False, loc="upper right", ncol=2, bbox_to_anchor=(1, 1.02))
        _apply_ds4m_style(ax)
    else:
        vals  = [dist.get(c, 0) for c in cats]
        total = sum(vals) or 1
        pcts  = [v / total * 100 for v in vals]
        fig, ax = plt.subplots(figsize=(5, 3.5), facecolor="white")
        ax.bar(labels_es, pcts, color=clrs, edgecolor="white")
        ax.set_ylabel("%", fontsize=8)
        ax.set_title("Distribución de polaridad global", fontsize=10, fontweight="bold", color="#1B3A6B")
        _apply_ds4m_style(ax)

    fig.tight_layout()
    return _fig_to_bytes(fig)


def _chart_scoreop_trend_by_red(scoreop: dict, order: list | None = None) -> dict[str, bytes]:
    tr = scoreop.get("tendencia_red", {})
    if not tr:
        return {}
    charts = {}
    redes_iter = [r for r in (order or tr.keys()) if r in tr]
    for i, red in enumerate(redes_iter):
        data = tr[red]
        fechas = sorted(data.keys())
        if not fechas:
            continue

        x = np.arange(len(fechas))
        vals = np.array([data.get(f, 50) for f in fechas], dtype=float)

        acum = np.cumsum(vals - 50)
        if len(acum) > 3:
            acum = np.convolve(acum, np.ones(3)/3, mode='same')

        fig, ax = plt.subplots(figsize=(9, 3.6), facecolor="white")
        ax2 = ax.twinx()

        color = _plat_color(red, i)

        ax.plot(x, vals, color=color, linewidth=3, label="Media diaria", zorder=3)
        ax.axhline(50, linestyle="--", color="#999", linewidth=1)
        ax.fill_between(x, vals, 50, where=vals >= 50, color="#0eb26c", alpha=0.10)
        ax.fill_between(x, vals, 50, where=vals < 50,  color="#d8535f", alpha=0.10)

        ax2.plot(x, acum, linestyle="--", linewidth=2.2, color="#7b61ff", alpha=0.9,
                 label="Tendencia acumulada (sesgo)")

        ymin = min(0, vals.min() - 5)
        ymax = max(100, vals.max() + 5)
        ax.set_ylim(ymin, ymax)

        ax2.set_ylabel("Sesgo acumulado", fontsize=8)
        ax.set_ylabel("Indicador_pct (%)", fontsize=9)
        ax.set_title(f"Dinámica de polaridad y balance neto del debate · {red.capitalize()}",
                     fontsize=11, fontweight="bold", color="#1B3A6B")

        step = max(1, len(fechas)//5)
        ax.set_xticks(range(0, len(fechas), step))
        ax.set_xticklabels(
            [_fmt_date(fechas[j]) for j in range(0, len(fechas), step)],
            rotation=25, ha="right", fontsize=8
        )

        ax.grid(True, axis="y", alpha=0.10)

        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc="upper center",
                  bbox_to_anchor=(0.5, -0.20), ncol=2, fontsize=8, frameon=False)

        fig.subplots_adjust(bottom=0.30)
        fig.tight_layout(rect=[0, 0.05, 1, 1])

        charts[red] = _fig_to_bytes(fig)

    return charts


def _chart_topics_bar(topics: list) -> bytes | None:
    if not topics:
        return None
    top = sorted(topics, key=lambda t: t.get("volumen", 0), reverse=True)[:12]
    if not top:
        return None

    labels  = [str(t.get("TOPIC", t.get("TOPIC_CLEAN", "?")))[:28] for t in top]
    pos     = [t.get("pos", 0)  for t in top]
    neu     = [t.get("neu", 0)  for t in top]
    neg     = [t.get("neg", 0)  for t in top]
    totals  = [p + n + ne or 1 for p, n, ne in zip(pos, neu, neg)]

    pct_pos = [p / t * 100 for p, t in zip(pos, totals)]
    pct_neu = [n / t * 100 for n, t in zip(neu, totals)]
    pct_neg = [n / t * 100 for n, t in zip(neg, totals)]

    y   = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(8, max(3, len(labels) * 0.45)), facecolor="white")

    ax.barh(y, pct_pos, color="#0eb26c", label="Favorable (>60%)", height=0.6)
    ax.barh(y, pct_neu, left=pct_pos, color="#adb5bd", label="Neutro (40-60%)", height=0.6, alpha=0.7)
    ax.barh(y, pct_neg, left=[a + b for a, b in zip(pct_pos, pct_neu)],
            color="#f28c8c", label="En contra (<40%)", height=0.6)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("% de publicaciones", fontsize=8)
    ax.set_title("Temas detectados — distribución de polaridad en posts",
                 fontsize=10, fontweight="bold", color="#1B3A6B")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.axvline(50, color="#D0D9EC", linewidth=0.8, linestyle="--")
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    _apply_ds4m_style(ax)
    ax.invert_yaxis()
    fig.tight_layout()
    return _fig_to_bytes(fig)


def _chart_pillarop(global_data: dict, por_red: dict) -> bytes | None:
    PILARES = ["legitimacion", "efectividad", "justicia_equidad", "confianza_institucional"]
    LABELS  = ["Legitimación", "Efectividad", "Justicia y\nEquidad", "Confianza\nInstitucional"]
    UMBRAL_POS = 57
    UMBRAL_NEG = 43

    g_vals = [global_data.get(f"PillarOP_pct_{p}", 50) for p in PILARES]
    if all(v == 0 for v in g_vals):
        return None

    def _bar_color(v):
        if v >= UMBRAL_POS: return "#0eb26c"
        if v >= UMBRAL_NEG: return "#adb5bd"
        return "#f28c8c"

    clrs_bar = [_bar_color(v) for v in g_vals]

    if por_red and len(por_red) > 1:
        fig, axes = plt.subplots(1, 2, figsize=(10, 4), facecolor="white")
        ax1, ax2 = axes
    else:
        fig, ax1 = plt.subplots(figsize=(7, 3.5), facecolor="white")
        ax2 = None

    y = np.arange(len(LABELS))
    ax1.barh(y, g_vals, color=clrs_bar, edgecolor="white", height=0.55)
    ax1.axvline(50, color="#F5A623", linewidth=1.5, linestyle="--", alpha=0.8, label="Umbral neutro (50%)")
    ax1.set_yticks(y)
    ax1.set_yticklabels(LABELS, fontsize=9)
    ax1.set_xlabel("PillarOP (%)", fontsize=8)
    ax1.set_title("PillarOP global por pilar\n(50% = neutralidad · >60% = aceptación · <40% = rechazo)",
                  fontsize=9, fontweight="bold", color="#1B3A6B")
    ax1.set_xlim(0, 105)
    _apply_ds4m_style(ax1)
    ax1.invert_yaxis()
    for i, v in enumerate(g_vals):
        ax1.text(v + 1, i, f"{v:.2f}%", va="center", ha="left", fontsize=8, fontweight="bold",
                 color=_bar_color(v))

    if ax2 is not None and por_red:
        redes = list(por_red.keys())
        x     = np.arange(len(LABELS))
        w     = 0.8 / len(redes)
        for j, (red, vals_red) in enumerate(por_red.items()):
            red_vals = [vals_red.get(f"PillarOP_pct_{p}", 50) for p in PILARES]
            ax2.bar(x + j * w - 0.4 + w / 2, red_vals, width=w,
                    label=red.capitalize(), color=_plat_color(red, j),
                    alpha=0.85, edgecolor="white")
        ax2.axhline(50, color="#F5A623", linewidth=1.5, linestyle="--", alpha=0.8)
        ax2.axhline(60, color="#0eb26c", linewidth=0.8, linestyle=":", alpha=0.6)
        ax2.axhline(40, color="#f28c8c", linewidth=0.8, linestyle=":", alpha=0.6)
        ax2.set_xticks(x)
        ax2.set_xticklabels(LABELS, fontsize=8)
        ax2.set_ylabel("PillarOP (%)", fontsize=8)
        ax2.set_title("PillarOP por pilar y plataforma", fontsize=10, fontweight="bold", color="#1B3A6B")
        ax2.legend(fontsize=8, frameon=False)
        _apply_ds4m_style(ax2)

    fig.tight_layout()
    return _fig_to_bytes(fig)





# ─────────────────────────────────────────────────────────────────────────────
# Paleta de postura (idéntica a la web)
# ─────────────────────────────────────────────────────────────────────────────
_COL_FAV  = "#0a7c4a"   # Cb > 0.15  → verde
_COL_NEG  = "#d8535f"   # Cb < -0.15 → rojo
_COL_NEU  = "#6c757d"   # resto      → gris

def _pos_color(c: float) -> str:
    if c > 0.15:  return _COL_FAV
    if c < -0.15: return _COL_NEG
    return _COL_NEU


def _pos_label(c: float) -> str:
    if c > 0.15:  return "Favorable"
    if c < -0.15: return "Crítico"
    return "Neutro"


def _fig_to_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# Utilidad: colocar texto en espiral sin solapamientos (wordcloud manual)
# ─────────────────────────────────────────────────────────────────────────────

def _spiral_place(
    ax,
    terms: List[Dict[str, Any]],
    fig_w: float,
    fig_h: float,
    fontsize_min: float = 7,
    fontsize_max: float = 28,
    max_attempts: int = 1200,
):
    """
    Coloca los términos en espiral Arquimediana, de mayor a menor Sb.
    Usa renderer de matplotlib para medir bboxes reales y evitar solapamientos.
    """
    if not terms:
        return

    sb_vals = [t["Sb"] for t in terms]
    sb_min, sb_max = min(sb_vals), max(sb_vals)

    # Bboxes en coordenadas de axes (0..1) con margen
    placed: List[tuple] = []

    def overlaps(rx0, ry0, rx1, ry1, margin=0.008) -> bool:
        for bx0, by0, bx1, by1 in placed:
            if not (rx1 + margin < bx0 or rx0 - margin > bx1 or
                    ry1 + margin < by0 or ry0 - margin > by1):
                return True
        return False

    rng = np.random.default_rng(42)
    # Factor de escala de fuente a coordenadas de axes (empírico para 180 dpi)
    # fz puntos → fracción del eje Y en axes coords
    dpi   = 180.0
    px_y  = fig_h * dpi                 # píxeles totales eje Y
    px_x  = fig_w * dpi

    for term in terms:
        Sb    = term["Sb"]
        Cb    = term.get("Cb", 0.0)
        Ib    = max(0.30, min(1.0, term.get("Ib", 0.7)))
        texto = term["text"]
        tipo  = term.get("tipo", "palabra")
        is_bg = tipo == "bigrama"

        # Tamaño proporcional a sqrt normalizado
        t  = math.sqrt(max(0, Sb - sb_min) / (sb_max - sb_min + 1e-9))
        fz = fontsize_min + t * (fontsize_max - fontsize_min)

        color  = _pos_color(Cb)
        style  = "italic" if is_bg else "normal"
        weight = "bold"

        # Estimar bbox en axes coords (conservador: sobreestima un 20%)
        n_chars  = len(texto)
        # Ancho promedio por carácter en puntos (bold ~0.6 * fz)
        char_pt  = fz * 0.62
        w_pt     = n_chars * char_pt
        h_pt     = fz * 1.15
        est_w    = (w_pt  / 72 * dpi) / px_x  # axes fraction
        est_h    = (h_pt  / 72 * dpi) / px_y

        found = False
        for attempt in range(1, max_attempts + 1):
            angle  = 0.30 * attempt
            # Espiral más compacta al inicio, más abierta después
            radius = 0.0012 * attempt
            # Elongación horizontal porque las palabras son más anchas que altas
            cx = 0.5 + radius * math.cos(angle)
            cy = 0.5 + radius * math.sin(angle) * 0.65

            x0 = cx - est_w / 2
            x1 = cx + est_w / 2
            y0 = cy - est_h / 2
            y1 = cy + est_h / 2

            # Dentro del canvas con margen
            if x0 < 0.015 or x1 > 0.985 or y0 < 0.025 or y1 > 0.965:
                continue

            if not overlaps(x0, y0, x1, y1):
                ax.text(
                    cx, cy, texto,
                    fontsize=fz,
                    color=color,
                    alpha=Ib,
                    ha="center",
                    va="center",
                    fontweight=weight,
                    fontstyle=style,
                    transform=ax.transAxes,
                    zorder=3,
                )
                placed.append((x0, y0, x1, y1))
                found = True
                break

        if not found:
            # Fallback: zona aleatoria no ocupada
            for _ in range(80):
                cx = rng.uniform(0.05, 0.95)
                cy = rng.uniform(0.05, 0.92)
                x0, x1 = cx - est_w/2, cx + est_w/2
                y0, y1 = cy - est_h/2, cy + est_h/2
                if not overlaps(x0, y0, x1, y1):
                    ax.text(
                        cx, cy, texto,
                        fontsize=max(fontsize_min, fz * 0.8),
                        color=color, alpha=Ib * 0.65,
                        ha="center", va="center",
                        fontweight=weight, fontstyle=style,
                        transform=ax.transAxes, zorder=2,
                    )
                    placed.append((x0, y0, x1, y1))
                    break


# ─────────────────────────────────────────────────────────────────────────────
# 1. NUBE UNIFICADA v2
# ─────────────────────────────────────────────────────────────────────────────

def _chart_nube_unificada_v2(
    pool: List[Dict[str, Any]],
    max_palabras: int = 20,
    max_bigramas: int = 20,
) -> Optional[bytes]:
    """
    Genera la nube de términos para el PDF, replicando fielmente la web:
      - Tamaño  ∝ sqrt(Sb/Sb_max)  → impacto
      - Color   basado en Cb        → postura (verde/gris/rojo)
      - Opacidad basada en Ib       → coherencia argumental
      - Bigramas en cursiva

    Separa palabras (top max_palabras) y bigramas (top max_bigramas),
    luego los mezcla y ordena por Sb para la espiral.
    """
    if not pool:
        return None

    # Separar y filtrar por tipo
    palabras = sorted(
        [t for t in pool if t.get("tipo", "palabra") == "palabra"],
        key=lambda x: x["Sb"], reverse=True
    )[:max_palabras]

    bigramas = sorted(
        [t for t in pool if t.get("tipo", "bigrama") == "bigrama"],
        key=lambda x: x["Sb"], reverse=True
    )[:max_bigramas]

    terms = sorted(palabras + bigramas, key=lambda x: x["Sb"], reverse=True)

    if not terms:
        return None

    fig_w, fig_h = 13, 11
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor="white")
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Título sutil
    ax.text(
        0.5, 0.98,
        "Términos clave por impacto social acumulado",
        transform=ax.transAxes,
        ha="center", va="top",
        fontsize=8, color="#9aa5b1",
        fontstyle="italic",
    )

    # Colocar términos
    _spiral_place(ax, terms, fig_w, fig_h, fontsize_min=7, fontsize_max=30)

    # Leyenda compacta (igual que la web)
    legend_elements = [
        mpatches.Patch(facecolor=_COL_FAV, label="Favorable", alpha=0.85),
        mpatches.Patch(facecolor=_COL_NEU, label="Neutro",    alpha=0.85),
        mpatches.Patch(facecolor=_COL_NEG, label="Crítico",   alpha=0.85),
    ]
    ax.legend(
        handles=legend_elements,
        loc="lower right",
        bbox_to_anchor=(1.0, -0.01),
        fontsize=7.5,
        frameon=True,
        framealpha=0.85,
        facecolor="white",
        edgecolor="#dee2e6",
        ncol=3,
        handlelength=1.0,
        title="Tono",
        title_fontsize=7,
    )

    # Nota sobre cursiva
    ax.text(
        0.0, -0.025,
        "Cursiva = bigrama · Opacidad = coherencia argumental · Tamaño = impacto social",
        transform=ax.transAxes,
        ha="left", va="top",
        fontsize=6.5, color="#9aa5b1",
        fontstyle="italic",
    )

    fig.tight_layout(pad=0.3)
    return _fig_to_bytes(fig)


# ─────────────────────────────────────────────────────────────────────────────
# 2. MAPA DE NARRATIVAS (grafo bipartito) v2
# ─────────────────────────────────────────────────────────────────────────────

def _chart_mapa_narrativas_v2(
    grafo_data: Dict[str, Any],
    max_topicos: int = 10,
    max_usuarios: int = 10,
) -> Optional[bytes]:
    """
    Replica visualmente el canvas del mapa de narrativas de la web:

    NODOS TÓPICO (círculos sólidos):
      - Tamaño  ∝ sqrt(St / St_max)
      - Color   = postura (Ct)
      - Opacidad = Ib_t

    NODOS USUARIO (círculos con borde punteado):
      - Tamaño  ∝ sqrt(Su / Su_max)
      - Color   = postura (Cu)
      - Opacidad = Ib_u

    ARISTAS:
      - Grosor  ∝ Wu_t normalizado
      - Color   = Cu_t (postura local)
      - Opacidad = Ib_e

    Ejes:
      X: ← CRÍTICA / RECHAZO  |  APOYO / FAVOR →   (basado en Ct / Cu)
      Y: ← POLARIZACIÓN        |  CONSENSO →         (basado en Ib_t / Ib_u)

    Selección: top max_topicos por St, top max_usuarios por Su
               con al menos una arista al conjunto de tópicos seleccionados.
    """
    nodes_all = grafo_data.get("nodes", [])
    edges_all = grafo_data.get("edges", [])

    if not nodes_all:
        return None

    topicos  = [n for n in nodes_all if n.get("tipo") == "topico"]
    usuarios = [n for n in nodes_all if n.get("tipo") == "usuario"]

    if not topicos:
        return None

    # ── Selección de nodos top ────────────────────────────────────────────────
    topicos_sel = sorted(topicos,  key=lambda n: n.get("St", 0), reverse=True)[:max_topicos]
    topic_ids   = {n["id"] for n in topicos_sel}

    # Usuarios que tienen al menos una arista con los tópicos seleccionados
    aristas_valid = [
        e for e in edges_all
        if (e.get("source") in topic_ids or e.get("target") in topic_ids)
    ]
    uids_conectados = set()
    for e in aristas_valid:
        uids_conectados.add(e["source"])
        uids_conectados.add(e["target"])
    uids_conectados -= topic_ids  # quitar los tópicos

    usuarios_candidatos = [u for u in usuarios if u["id"] in uids_conectados]
    usuarios_sel = sorted(
        usuarios_candidatos, key=lambda n: n.get("Su", 0), reverse=True
    )[:max_usuarios]
    uid_ids_sel = {n["id"] for n in usuarios_sel}

    aristas_plot = [
        e for e in aristas_valid
        if (e.get("source") in uid_ids_sel or e.get("target") in uid_ids_sel)
        and (e.get("source") in topic_ids or e.get("target") in topic_ids)
    ]

    # ── Calcular posiciones (igual que la simulación JS pero estática) ─────────
    # X = valor de postura (Ct o Cu), Y = coherencia (Ib_t o Ib_u)
    # Rangos: X ∈ [-1, 1], Y ∈ [0, 1]

    rng = np.random.default_rng(7)

    def _assign_pos_topic(node: Dict, idx: int, total: int) -> tuple:
        """
        Posiciona tópicos distribuidos en el eje X según postura (Ct),
        con separación vertical forzada para evitar solapamientos.
        """
        ct = float(node.get("Ct", 0.0))
        ib = float(node.get("Ib_t", 0.5))
        # Distribuir verticalmente en filas (máx 5 por columna)
        col   = idx % 5
        row   = idx // 5
        n_rows = max(1, math.ceil(total / 5))
        # Y base según coherencia, ajustado por fila para separación
        y_base = max(0.15, min(0.90, ib))
        y_off  = (row / max(1, n_rows - 1) - 0.5) * 0.30
        y      = max(0.12, min(0.92, y_base + y_off + rng.uniform(-0.04, 0.04)))
        x      = max(-0.90, min(0.90, ct + rng.uniform(-0.04, 0.04)))
        return (x, y)

    def _assign_pos_user(node: Dict, connected_topic_positions: List[tuple]) -> tuple:
        """
        Posiciona usuarios cerca del centroide de sus tópicos conectados,
        con separación radial.
        """
        cu = float(node.get("Cu", 0.0))
        ib = float(node.get("Ib_u", 0.5))
        if connected_topic_positions:
            cx = sum(p[0] for p in connected_topic_positions) / len(connected_topic_positions)
            cy = sum(p[1] for p in connected_topic_positions) / len(connected_topic_positions)
        else:
            cx, cy = cu, ib
        # Desplazar hacia afuera del centro del tópico
        angle = rng.uniform(0, 2 * math.pi)
        r     = rng.uniform(0.07, 0.18)
        x = max(-0.92, min(0.92, cx + r * math.cos(angle)))
        y = max(0.05,  min(0.95, cy + r * math.sin(angle) * 0.6))
        return (x, y)

    pos_map: Dict[str, tuple] = {}

    # Posicionar tópicos primero
    for i, n in enumerate(topicos_sel):
        pos_map[n["id"]] = _assign_pos_topic(n, i, len(topicos_sel))

    # Posicionar usuarios: centroide de sus tópicos conectados
    for n in usuarios_sel:
        uid = n["id"]
        conn_positions = []
        for e in aristas_plot:
            src, tgt = e.get("source"), e.get("target")
            if src == uid and tgt in pos_map:
                conn_positions.append(pos_map[tgt])
            elif tgt == uid and src in pos_map:
                conn_positions.append(pos_map[src])
        pos_map[uid] = _assign_pos_user(n, conn_positions)

    # Separación mínima entre nodos del mismo tipo para evitar solapamientos
    def _repel_pass(node_ids: List[str], min_dist: float = 0.12, iterations: int = 8):
        for _ in range(iterations):
            for i in range(len(node_ids)):
                for j in range(i + 1, len(node_ids)):
                    ia, ib_ = node_ids[i], node_ids[j]
                    if ia not in pos_map or ib_ not in pos_map:
                        continue
                    xa, ya = pos_map[ia]
                    xb, yb = pos_map[ib_]
                    dx, dy = xb - xa, yb - ya
                    d = math.sqrt(dx*dx + dy*dy) + 1e-9
                    if d < min_dist:
                        push = (min_dist - d) / 2
                        nx  = dx / d * push
                        ny  = dy / d * push * 0.6
                        pos_map[ia] = (
                            max(-0.92, min(0.92, xa - nx)),
                            max(0.05,  min(0.95, ya - ny)),
                        )
                        pos_map[ib_] = (
                            max(-0.92, min(0.92, xb + nx)),
                            max(0.05,  min(0.95, yb + ny)),
                        )

    _repel_pass([n["id"] for n in topicos_sel],  min_dist=0.16)
    _repel_pass([n["id"] for n in usuarios_sel], min_dist=0.08)

    # ── Escalados de tamaño ───────────────────────────────────────────────────
    st_max = max((n.get("St", 0) for n in topicos_sel),  default=1) or 1
    su_max = max((n.get("Su", 0) for n in usuarios_sel), default=1) or 1
    wu_max = max((e.get("Wu_t", 0) for e in aristas_plot), default=1) or 1

    def _topic_radius(n):
        t = math.sqrt(n.get("St", 0) / st_max)
        return 120 + t * 1800   # scatter s (área en puntos²)

    def _user_radius(n):
        t = math.sqrt(n.get("Su", 0) / su_max)
        return 30 + t * 250

    def _edge_lw(e):
        wn = e.get("Wu_t", 0) / wu_max
        return 0.5 + wn * 4.0   # grosor 0.5 – 4.5 px

    # ── Figura ────────────────────────────────────────────────────────────────
    fig_w, fig_h = 13, 11 # ancho x alto en pulgadas
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor="white")

    # Fondos semitransparentes por zona
    ax.axvspan(-1.05, 0,    alpha=0.025, color=_COL_NEG, zorder=0)
    ax.axvspan(0, 1.05,     alpha=0.025, color=_COL_FAV, zorder=0)

    # ── Aristas ───────────────────────────────────────────────────────────────
    for e in aristas_plot:
        src_id = e.get("source")
        tgt_id = e.get("target")
        if src_id not in pos_map or tgt_id not in pos_map:
            continue
        x_src, y_src = pos_map[src_id]
        x_tgt, y_tgt = pos_map[tgt_id]

        cu_t  = float(e.get("Cu_t", 0.0))
        ib_e  = float(e.get("Ib_e", 0.5))
        lw    = _edge_lw(e)
        col   = _pos_color(cu_t)

        ax.plot(
            [x_src, x_tgt], [y_src, y_tgt],
            color=col,
            alpha=max(0.08, min(0.65, ib_e * 0.75)),
            linewidth=lw,
            zorder=1,
            solid_capstyle="round",
        )

    # ── Nodos usuario (círculos punteados, fondo) ─────────────────────────────
    for n in usuarios_sel:
        if n["id"] not in pos_map:
            continue
        x, y   = pos_map[n["id"]]
        cu     = float(n.get("Cu", 0.0))
        ib_u   = float(n.get("Ib_u", 0.6))
        s      = _user_radius(n)
        col    = _pos_color(cu)

        # Relleno muy tenue
        ax.scatter(x, y, s=s,
                   color=col, alpha=max(0.10, ib_u * 0.25),
                   edgecolors=col, linewidths=1.0,
                   linestyles="dashed",
                   zorder=2)

    # ── Nodos tópico (círculos sólidos, primer plano) ─────────────────────────
    for n in topicos_sel:
        if n["id"] not in pos_map:
            continue
        x, y   = pos_map[n["id"]]
        ct     = float(n.get("Ct", 0.0))
        ib_t   = float(n.get("Ib_t", 0.75))
        s      = _topic_radius(n)
        col    = _pos_color(ct)

        ax.scatter(x, y, s=s,
                   color=col, alpha=max(0.30, ib_t * 0.88),
                   edgecolors="white", linewidths=1.8,
                   zorder=3)

        # Etiqueta del tópico: wrapping en 2 líneas si es largo
        label_raw = str(n.get("label", "")).upper()
        # Partir en máx 2 líneas de 16 chars
        if len(label_raw) > 16:
            words = label_raw.split()
            mid   = max(1, len(words) // 2)
            label = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])
        else:
            label = label_raw

        # Offset: alternar arriba/abajo según índice para reducir solapamientos
        idx_t  = topicos_sel.index(n)
        offset = 11 if idx_t % 2 == 0 else -13
        va     = "bottom" if offset > 0 else "top"

        ax.annotate(
            label,
            xy=(x, y),
            xytext=(0, offset),
            textcoords="offset points",
            ha="center",
            va=va,
            fontsize=6.0,
            fontweight="bold",
            color="#1B3A6B",
            zorder=5,
            multialignment="center",
            bbox=dict(
                facecolor="white",
                alpha=0.82,
                edgecolor="#D0D9EC",
                linewidth=0.5,
                pad=1.8,
                boxstyle="round,pad=0.3",
            ),
        )

    # ── Ejes y decoración ────────────────────────────────────────────────────
    ax.axvline(0, color="#D0D9EC", linewidth=0.9, linestyle="--", zorder=0)
    ax.axhline(0.5, color="#D0D9EC", linewidth=0.5, linestyle=":", zorder=0)

    ax.set_xlim(-1.05, 1.05)
    ax.set_ylim(-0.02, 1.05)

    ax.set_xlabel(
        "← CRÍTICA / RECHAZO                        POSTURA                        APOYO / FAVOR →",
        fontsize=7.5, fontweight="bold", color="#3D3D5C",
    )
    ax.set_ylabel(
        "← POLARIZACIÓN / DISONANCIA          CONSENSO / COHERENCIA →",
        fontsize=7.5, fontweight="bold", color="#3D3D5C",
    )

    # Spines
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_color("#D0D9EC")
    ax.spines["bottom"].set_color("#D0D9EC")
    ax.tick_params(colors="#9aa5b1", labelsize=7)

    # ── Leyenda ───────────────────────────────────────────────────────────────
    from matplotlib.lines import Line2D

    legend_elems = [
        mpatches.Patch(facecolor=_COL_FAV, alpha=0.80, label="Favorable"),
        mpatches.Patch(facecolor=_COL_NEU, alpha=0.80, label="Neutro"),
        mpatches.Patch(facecolor=_COL_NEG, alpha=0.80, label="Crítico"),
        Line2D([0], [0], marker="o", color="none",
               markerfacecolor="#4A7CC1", markeredgecolor="white",
               markersize=9, label="Tópico"),
        Line2D([0], [0], marker="o", color="none",
               markerfacecolor="#4A7CC1", alpha=0.4,
               markeredgecolor="#4A7CC1", markeredgewidth=1.2,
               linestyle="--", markersize=6, label="Usuario"),
    ]
    ax.legend(
        handles=legend_elems,
        loc="upper right",
        fontsize=7,
        frameon=True,
        framealpha=0.90,
        facecolor="white",
        edgecolor="#dee2e6",
        ncol=2,
        handlelength=1.0,
        borderpad=0.7,
    )

    # Estadísticas
    ax.text(
        0.01, 0.01,
        f"{len(topicos_sel)} tópicos · {len(usuarios_sel)} usuarios · {len(aristas_plot)} conexiones",
        transform=ax.transAxes,
        ha="left", va="bottom",
        fontsize=6, color="#9aa5b1", fontstyle="italic",
    )

    fig.tight_layout(pad=0.5)
    return _fig_to_bytes(fig)


# ─────────────────────────────────────────────────────────────────────────────
# MOTORES DE APOYO / RECHAZO — helpers autosuficientes
# ─────────────────────────────────────────────────────────────────────────────
_MP_POST_TIPOS    = {'post', 'video', 'tweet', 'publicación', 'publicacion'}
_MP_COMMENT_TIPOS = {'comentario', 'comment', 'reply', 'respuesta'}
_MP_ANCHOR_COLS   = ['id_raiz', 'id_video', 'uri', 'parent_id', 'post_id']
_MP_CONTENT_COLS  = ['contenido_post', 'titulo_video', 'contenido', 'title', 'text']
_MP_USER_COLS     = ['usuario', 'autor', 'author', 'username', 'canal']
_MP_DATE_COLS     = ['fecha', 'fecha_post', 'fecha_publicacion', 'created_at', 'date']
_MP_URI_COLS      = ['uri', 'url', 'permalink', 'link', 'id_video']
_MP_PILARES       = ['legitimacion', 'efectividad', 'justicia_equidad', 'confianza_institucional']
_MP_REAC_COLS     = ['likes']
_MP_COMP_COLS     = ['reposts', 'shares']
_MP_COMM_COLS     = ['comments', 'replies', 'num_comentarios']


def _mp_first(row, cols, default=""):
    for c in cols:
        v = row.get(c) if isinstance(row, dict) else getattr(row, c, None)
        if v is not None and str(v).strip() not in ("", "nan", "None"):
            return str(v).strip()
    return default


def _mp_safe_int(val):
    try:
        v = float(val)
        return int(v) if not (np.isnan(v) or np.isinf(v)) else 0
    except Exception:
        return 0


def _mp_find_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _mp_find_col_valid(df, candidates):
    """Como _mp_find_col, pero exige que la columna tenga datos reales
    para este subconjunto (evita columnas 'prestadas' por pd.concat)."""
    for c in candidates:
        if c in df.columns and df[c].notna().any():
            return c
    return _mp_find_col(df, candidates)  # fallback último recurso

def _mp_pesos(df):
    col_r = _mp_find_col(df, _MP_REAC_COLS)
    col_s = _mp_find_col(df, _MP_COMP_COLS)
    col_c = _mp_find_col(df, _MP_COMM_COLS)

    R = pd.to_numeric(df[col_r], errors='coerce').fillna(0).sum() if col_r else 0.0
    S = pd.to_numeric(df[col_s], errors='coerce').fillna(0).sum() if col_s else 0.0
    C = pd.to_numeric(df[col_c], errors='coerce').fillna(0).sum() if col_c else 0.0

    TSE = R + S + C
    M   = sum(1 for x in [R, S, C] if x > 0)
    if M == 0 or TSE == 0:
        return 1.0, 1.0, 1.0, col_r, col_s, col_c

    w_r = (TSE / M) / R if R > 0 else 0.0
    w_s = (TSE / M) / S if S > 0 else 0.0
    w_c = (TSE / M) / C if C > 0 else 0.0
    return w_r, w_s, w_c, col_r, col_s, col_c


def _mp_impacto(df, w_r, w_s, w_c, col_r, col_s, col_c):
    r = pd.to_numeric(df[col_r], errors='coerce').fillna(0) if col_r else pd.Series(0.0, index=df.index)
    s = pd.to_numeric(df[col_s], errors='coerce').fillna(0) if col_s else pd.Series(0.0, index=df.index)
    c = pd.to_numeric(df[col_c], errors='coerce').fillna(0) if col_c else pd.Series(0.0, index=df.index)
    return 1.0 + (r * w_r + s * w_s + c * w_c)


def _mp_factor(df):
    factores = pd.Series(1.0, index=df.index)
    if 'tipo' in df.columns:
        es_post = df['tipo'].fillna('').str.strip().str.lower().isin(_MP_POST_TIPOS)
    else:
        es_post = pd.Series(True, index=df.index)
    if 'plataforma' not in df.columns:
        return factores

    plat = df['plataforma'].fillna('').str.lower()

    mask_yt = es_post & plat.str.contains('youtube', na=False)
    if mask_yt.any():
        df_yt  = df[mask_yt]
        V      = pd.to_numeric(df_yt.get('vistas', 0),       errors='coerce').fillna(0)
        S      = pd.to_numeric(df_yt.get('suscriptores', 0), errors='coerce').fillna(0)
        Vt, St = V.sum(), S.sum()
        fv = (1 + np.log1p(V / Vt)) if Vt > 0 else pd.Series(1.0, index=df_yt.index)
        fs = (1 + np.log1p(S / St)) if St > 0 else pd.Series(1.0, index=df_yt.index)
        factores[mask_yt] = (fv * fs).values

    mask_bs = es_post & plat.str.contains('bluesky', na=False)
    if mask_bs.any():
        df_bs = df[mask_bs]
        F_seg = pd.to_numeric(df_bs.get('seguidores', 0), errors='coerce').fillna(0)
        Ft    = F_seg.sum()
        if Ft > 0:
            factores[mask_bs] = (1 + np.log1p(F_seg / Ft)).values

    return factores


def _mp_threads_pilar(df, scores, active, es_post, es_comment, anchor_col):
    threads = []
    posts_df = df[es_post & active]

    comments_df     = df[es_comment]
    comments_active = comments_df[scores[comments_df.index].isin([-1, 0, 1])]
    com_by_anchor   = (
        comments_active.groupby(anchor_col)
        if anchor_col and anchor_col in comments_active.columns and not comments_active.empty
        else None
    )

    for idx, post_row in posts_df.iterrows():
        anchor_val = post_row.get(anchor_col) if anchor_col else None
        stance_p   = int(scores[idx])
        I_eff_p    = float(post_row['_I_eff'])

        sum_com_raw = sum_com_sup = 0.0
        n_coms_thread = 0
        if anchor_val is not None and com_by_anchor is not None:
            try:
                coms        = com_by_anchor.get_group(anchor_val)
                sum_com_raw = float((scores[coms.index] * coms['_I']).sum())
                sum_com_sup = float(coms['_I'].sum())
                n_coms_thread = len(coms)
            except KeyError:
                pass

        thread_raw = 0.4 * (stance_p * I_eff_p) + 0.6 * sum_com_raw
        thread_sup = 0.4 * I_eff_p               + 0.6 * sum_com_sup
        thread_norm = thread_raw / thread_sup if thread_sup > 0 else 0.0
        thread_pct  = (thread_norm + 1) / 2 * 100

        plat = str(post_row.get('plataforma', '')).lower()
        canal_val = 0
        if 'youtube' in plat:
            likes       = _mp_safe_int(post_row.get('vistas', 0))
            extra_label = "Suscriptores"
            extra_val   = _mp_safe_int(post_row.get('suscriptores', 0))
        elif 'bluesky' in plat:
            likes       = _mp_safe_int(post_row.get('likes', 0))
            extra_label = "Seguidores"
            extra_val   = _mp_safe_int(post_row.get('seguidores', 0))

        elif 'telegram' in plat:
            likes       = _mp_safe_int(post_row.get('vistas', 0))
            extra_label = "Reacciones"
            extra_val   = _mp_safe_int(post_row.get('reacciones_total', 0))    
            canal_val   = _mp_safe_int(post_row.get('seguidores', 0))  # suscriptores del canal
        else:
            likes = extra_val = 0
            extra_label = ""

        threads.append({
            "thread_id":   str(anchor_val) if anchor_val is not None else str(idx),
            "raw":         round(thread_raw, 4),
            "sup":         round(thread_sup, 4),
            "score_pct":   round(thread_pct, 2),
            "stance_post": stance_p,
            "contenido":   str(_mp_first(post_row, _MP_CONTENT_COLS)).replace("\n", " ").strip(),
            #textwrap.shorten(_mp_first(post_row, _MP_CONTENT_COLS),width=300, placeholder="…"),
            "fecha":       _mp_first(post_row, _MP_DATE_COLS),
            "likes":       likes,
            "extra_label": extra_label,
            "extra_val":   extra_val,
            "canal_val":   canal_val,
            "comentarios": n_coms_thread if n_coms_thread else _mp_safe_int(post_row.get('num_comentarios', 0)),#_mp_safe_int(post_row.get('num_comentarios', 0)),
            "uri":         _mp_first(post_row, _MP_URI_COLS),
            "plataforma":  str(post_row.get('plataforma', '')),
        })

    return threads


def _calcular_motores_desde_pilares(analysis_meta: dict, top_n: int = 5) -> dict:
    folder_raw = Path(analysis_meta.get("output_folder", ""))
    if not folder_raw.is_absolute():
        try:
            from logica import BASE_DIR_1
            folder = (BASE_DIR_1 / folder_raw).resolve()
        except Exception:
            folder = Path.cwd() / folder_raw
    else:
        folder = folder_raw

    archivos = list(folder.glob("*_pilares.csv"))
    if not archivos:
        return {}

    dfs = []
    for arch in archivos:
        try:
            with open(arch, 'r', encoding='utf-8') as f:
                sep = ';' if ';' in f.readline() else ','
            df_t = pd.read_csv(arch, sep=sep, encoding='utf-8', on_bad_lines='skip')
            if 'plataforma' not in df_t.columns:
                nombre = arch.name.lower()
                if   'youtube' in nombre: df_t['plataforma'] = 'youtube'
                elif 'reddit'  in nombre: df_t['plataforma'] = 'reddit'
                elif 'bluesky' in nombre: df_t['plataforma'] = 'bluesky'
                elif 'telegram' in nombre: df_t['plataforma'] = 'telegram'
                else:                     df_t['plataforma'] = 'otros'
            dfs.append(df_t)
        except Exception as e:
            print(f"  ⚠️ [motores] Error leyendo {arch.name}: {e}")

    if not dfs:
        return {}

    df_total = pd.concat(dfs, ignore_index=True)

    resultado = {}
    redes = (
        {str(r): df_total[df_total['plataforma'] == r].copy()
         for r in df_total['plataforma'].dropna().unique()}
        if 'plataforma' in df_total.columns
        else {'dataset': df_total.copy()}
    )

    for red, df_red in redes.items():
        if df_red.empty:
            continue

        w_r, w_s, w_c, col_r, col_s, col_c = _mp_pesos(df_red)
        df_red = df_red.copy()
        df_red['_I']     = _mp_impacto(df_red, w_r, w_s, w_c, col_r, col_s, col_c)
        df_red['_F']     = _mp_factor(df_red)
        df_red['_I_eff'] = df_red['_I'] * df_red['_F']

        if 'tipo' in df_red.columns:
            tipo_lower = df_red['tipo'].fillna('').str.strip().str.lower()
            es_post    = tipo_lower.isin(_MP_POST_TIPOS)
            es_comment = tipo_lower.isin(_MP_COMMENT_TIPOS)
        else:
            es_post    = pd.Series(True,  index=df_red.index)
            es_comment = pd.Series(False, index=df_red.index)

        # Soporta esquemas con parent_uri (Bluesky/Telegram) — verificar que la
        # columna esté REALMENTE poblada para esta red, no solo presente por
        # efecto del pd.concat con otras plataformas (que añade columnas NaN
        # "prestadas" de otros CSV con esquema distinto).
        tiene_esquema_uri = (
            'parent_uri' in df_red.columns and 'uri' in df_red.columns and
            df_red['parent_uri'].notna().any() and df_red['uri'].notna().any()
        )
        if tiene_esquema_uri:
            df_red['_anchor'] = df_red['uri'].where(es_post, df_red['parent_uri'])
            anchor_col = '_anchor'
        else:
            anchor_col = _mp_find_col_valid(df_red, _MP_ANCHOR_COLS)

        resultado_red = {}

        for pilar in _MP_PILARES:
            if pilar not in df_red.columns:
                resultado_red[pilar] = {"motores_apoyo": [], "motores_rechazo": []}
                continue

            scores = pd.to_numeric(df_red[pilar], errors='coerce').fillna(2)
            active = scores.isin([-1, 0, 1])

            if not (es_post & active).any():
                resultado_red[pilar] = {"motores_apoyo": [], "motores_rechazo": []}
                continue

            if anchor_col:
                threads = _mp_threads_pilar(
                    df_red, scores, active, es_post, es_comment, anchor_col
                )
            else:
                threads = []
                for idx in df_red[es_post & active].index:
                    row      = df_red.loc[idx]
                    stance_p = int(scores[idx])
                    I_eff_p  = float(row['_I_eff'])
                    plat     = str(row.get('plataforma', '')).lower()
                    canal_v = 0
                    if 'youtube' in plat:
                        likes_v = _mp_safe_int(row.get('vistas', 0))
                        el, ev  = "Suscriptores", _mp_safe_int(row.get('suscriptores', 0))
                    elif 'bluesky' in plat:
                        likes_v = _mp_safe_int(row.get('likes', 0))
                        el, ev  = "Seguidores", _mp_safe_int(row.get('seguidores', 0))
                    elif 'telegram' in plat:
                        likes_v = _mp_safe_int(row.get('vistas', 0))
                        el, ev  = "Reacciones", _mp_safe_int(row.get('reacciones_total', 0))    
                        canal_v = _mp_safe_int(row.get('seguidores', 0))
                    else:
                        likes_v, el, ev = 0, "", 0
                    threads.append({
                        "thread_id":   str(idx),
                        "raw":         round(stance_p * I_eff_p, 4),
                        "sup":         round(I_eff_p, 4),
                        "stance_post": stance_p,
                        # "contenido":   str(_mp_first(row, _MP_CONTENT_COLS)).replace("\n", " ").strip(),
                        "contenido": textwrap.shorten(_mp_first(row, _MP_CONTENT_COLS),width=400, placeholder="…"),
                        "fecha":       _mp_first(row, _MP_DATE_COLS),
                        "likes":       likes_v,
                        "extra_label": el,
                        "extra_val":   ev,
                        "comentarios": _mp_safe_int(row.get('num_comentarios', 0)),
                        "uri":         _mp_first(row, _MP_URI_COLS),
                        "plataforma":  str(row.get('plataforma', '')),
                    })

            apoyo   = sorted([t for t in threads if t['raw'] > 0],
                             key=lambda x: x['raw'], reverse=True)[:top_n]
            rechazo = sorted([t for t in threads if t['raw'] < 0],
                             key=lambda x: x['raw'])[:top_n]

            for t in apoyo + rechazo:
                t['score'] = round(t.pop('raw'), 4)

            resultado_red[pilar] = {
                "motores_apoyo":   apoyo,
                "motores_rechazo": rechazo,
            }

        df_red.drop(columns=['_I', '_F', '_I_eff', '_anchor'], inplace=True, errors='ignore')
        resultado[red] = resultado_red

    return resultado

pdfmetrics.registerFont(
    TTFont("DejaVu", "fonts/DejaVuSans.ttf")
)

pdfmetrics.registerFont(
    TTFont("DejaVu-Bold", "fonts/DejaVuSans-Bold.ttf")
)

pdfmetrics.registerFont(
    TTFont("DejaVu-Oblique", "fonts/DejaVuSans-Oblique.ttf")
)
# ─────────────────────────────────────────────────────────────────────────────
# ESTILOS REPORTLAB
# ─────────────────────────────────────────────────────────────────────────────
def _build_styles():
    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        "cover_title": S("cover_title",
            fontName="Helvetica-Bold", fontSize=28,
            textColor=C_WHITE, alignment=TA_LEFT, leading=34),

        "cover_sub": S("cover_sub",
            fontName="Helvetica", fontSize=13,
            textColor=colors.HexColor("#c8d4ee"), alignment=TA_LEFT, leading=18),

        "cover_meta": S("cover_meta",
            fontName="Helvetica", fontSize=9,
            textColor=colors.HexColor("#8faad0"), alignment=TA_LEFT, leading=14),

        "cover_label": S("cover_label",
            fontName="Helvetica-Bold", fontSize=9,
            textColor=C_ACCENT, alignment=TA_LEFT, leading=12, spaceBefore=2),

        "section_title": S("section_title",
            fontName="Helvetica-Bold", fontSize=14,
            textColor=C_PRIMARY, spaceBefore=14, spaceAfter=4, leading=18),

        "subsection": S("subsection",
            fontName="Helvetica-Bold", fontSize=11,
            textColor=C_SECONDARY, spaceBefore=10, spaceAfter=4, leading=14),

        "body": S("body",
            fontName="Helvetica", fontSize=9,
            textColor=C_TEXT_MID, leading=13, spaceAfter=4, alignment=TA_JUSTIFY),

        "body_left": S("body_left",
            fontName="Helvetica", fontSize=9,
            textColor=C_TEXT_MID, leading=13, spaceAfter=4, alignment=TA_LEFT),

        "caption": S("caption",
            fontName="Helvetica-Oblique", fontSize=7.5,
            textColor=C_TEXT_LIGHT, alignment=TA_CENTER, spaceAfter=6),

        "box_title": S("box_title",
            fontName="Helvetica-Bold", fontSize=9,
            textColor=C_PRIMARY, leading=12, spaceAfter=2),

        "kpi_value": S("kpi_value",
            fontName="Helvetica-Bold", fontSize=22,
            textColor=C_PRIMARY, alignment=TA_CENTER, leading=26),

        "kpi_label": S("kpi_label",
            fontName="Helvetica", fontSize=7.5,
            textColor=C_TEXT_LIGHT, alignment=TA_CENTER, leading=10, spaceAfter=2),

        "table_header": S("table_header",
            fontName="Helvetica-Bold", fontSize=8,
            textColor=C_WHITE, alignment=TA_CENTER),

        "table_cell": S("table_cell",
            fontName="Helvetica", fontSize=7.5,
            textColor=C_TEXT_DARK, alignment=TA_LEFT, leading=10),

        "table_cell_unicode": S("table_cell_unicode",
            fontName="DejaVu",
            fontSize=7.5,
            textColor=C_TEXT_DARK,
            alignment=TA_LEFT,
            leading=10),    

        "table_cell_c": S("table_cell_c",
            fontName="Helvetica", fontSize=7.5,
            textColor=C_TEXT_DARK, alignment=TA_CENTER, leading=10),

        "footer": S("footer",
            fontName="Helvetica", fontSize=7,
            textColor=C_TEXT_LIGHT, alignment=TA_CENTER),

        "interpretation": S("interpretation",
            fontName="Helvetica-Bold", fontSize=11,
            textColor=C_PRIMARY, alignment=TA_CENTER, leading=15),

        "note": S("note",
            fontName="Helvetica-Oblique", fontSize=8,
            textColor=C_TEXT_LIGHT, leading=11, spaceAfter=3, alignment=TA_LEFT),

        "formula": S("formula",
            fontName="Courier", fontSize=8,
            textColor=C_TEXT_DARK, leading=11, spaceAfter=3,
            leftIndent=12, backColor=colors.HexColor("#F4F6FA")),

    }


# ─────────────────────────────────────────────────────────────────────────────
# FLOWABLES DECORATIVOS
# ─────────────────────────────────────────────────────────────────────────────
class ColorBar(Flowable):
    def __init__(self, width, height=3, color=None):
        super().__init__()
        self.width  = width
        self.height = height
        self.color  = color or C_ACCENT

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)

    def wrap(self, *args):
        return self.width, self.height


class KpiBox(Flowable):
    def __init__(self, value: str, label: str, width: float, height: float = 2.2*cm,
                 color=None, text_color=None, accent_color=None):
        super().__init__()
        self.value        = value
        self.label        = label
        self.width        = width
        self.height       = height
        self.bg_color     = color or C_LIGHT_BG
        self.text_color   = text_color or C_PRIMARY
        self.accent_color = accent_color or C_ACCENT

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg_color)
        c.roundRect(0, 0, self.width, self.height, radius=4, fill=1, stroke=0)
        c.setFillColor(self.accent_color)
        c.rect(0, self.height - 3, self.width, 3, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 17)
        c.setFillColor(self.text_color)
        c.drawCentredString(self.width / 2, self.height / 2 + 4, self.value)
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#7A7A9A"))
        label = self.label.replace("\n", " ")
        c.drawCentredString(self.width / 2, self.height / 2 - 10, label[:38])

    def wrap(self, *args):
        return self.width, self.height


class InfoBox(Flowable):
    def __init__(self, text: str, width: float, height: float,
                 border_color=None, bg_color=None):
        super().__init__()
        self.text         = text
        self.width        = width
        self.height       = height
        self.border_color = border_color or C_ACCENT
        self.bg_color     = bg_color or C_LIGHT_BG

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg_color)
        c.roundRect(4, 0, self.width - 4, self.height, radius=3, fill=1, stroke=0)
        c.setFillColor(self.border_color)
        c.rect(0, 0, 4, self.height, fill=1, stroke=0)

    def wrap(self, *args):
        return self.width, self.height


# ─────────────────────────────────────────────────────────────────────────────
# PLANTILLAS DE PÁGINA
# ─────────────────────────────────────────────────────────────────────────────
PW, PH = A4
M       = 1.8 * cm
CW      = PW - 2 * M


def _add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(M, 1.4 * cm, PW - M, 1.4 * cm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(C_TEXT_LIGHT)
    canvas.drawString(M, 0.9 * cm, "Análisis de opinión en redes sociales · DS4M Mediterráneo")
    canvas.drawRightString(PW - M, 0.9 * cm, f"Página {doc.page}")
    canvas.restoreState()


def _cover_page_bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(C_PRIMARY)
    canvas.rect(0, 0, PW, PH, fill=1, stroke=0)
    canvas.setFillColor(C_ACCENT)
    canvas.rect(0, 0, PW, 0.6 * cm, fill=1, stroke=0)
    canvas.setFillColor(C_SECONDARY)
    canvas.rect(PW - 1.0 * cm, 0, 1.0 * cm, PH, fill=1, stroke=0)
    canvas.setFillColor(C_ACCENT)
    canvas.rect(PW - 1.0 * cm, PH - 5 * cm, 1.0 * cm, 5 * cm, fill=1, stroke=0)
    canvas.restoreState()


def _inner_page_template(canvas, doc):
    _add_page_number(canvas, doc)
    canvas.saveState()
    canvas.setFillColor(C_ACCENT)
    canvas.rect(0, 0, 3, PH, fill=1, stroke=0)
    canvas.restoreState()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS DE TABLAS
# ─────────────────────────────────────────────────────────────────────────────
_TBLSTYLE_BASE = [
    ("BACKGROUND",    (0, 0), (-1, 0),  C_PRIMARY),
    ("TEXTCOLOR",     (0, 0), (-1, 0),  C_WHITE),
    ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_LIGHT_BG]),
    ("GRID",          (0, 0), (-1, -1), 0.3, C_BORDER),
    ("TOPPADDING",    (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ("VALIGN",        (0, 0), (-1, -1), "TOP"),
]


def _pos_color_pct(pct: float) -> colors.Color:
    if pct >= 57: return C_VERY_POS
    if pct >= 43: return C_NEU
    return C_VERY_NEG


def _scoreop_text_label(pct: float) -> str:
    label, _ = _scoreop_cat(pct)
    return f"{pct:.2f}% — {label}"


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
def build_analysis_pdf(
    dashboard_data: dict,
    analysis_meta:  dict,
    aceptacion_data: dict | None = None,
) -> bytes:
    """
    Genera el PDF completo del informe de análisis de opinión en RRSS.

    Parámetros
    ----------
    dashboard_data  : dict devuelto por el endpoint /dashboard
    analysis_meta   : dict del registro en analysis_db.json
    aceptacion_data : dict de aceptacion_global.json (opcional)

    Devuelve
    --------
    bytes del PDF listo para descarga.
    """
    buf = io.BytesIO()
    ST  = _build_styles()
    FIG_NUM = 1
    # ── Extraer datos ────────────────────────────────────────────────────────
    kpis         = dashboard_data.get("kpis", {})
    scoreop      = dashboard_data.get("scoreop", {})
    topics       = dashboard_data.get("topics", [])
    nubes        = dashboard_data.get("nubes", {})
    nube_v2      = dashboard_data.get("nube_unificada_v2", [])
    grafo_v2     = dashboard_data.get("grafo_bipartito_v2", {})
    vol_por_red  = dashboard_data.get("volumen_por_red", {})
    tend_global  = dashboard_data.get("tendencia_global", {})
    tend_por_red = dashboard_data.get("tendencia_por_red", {})
    platform_order = sorted(vol_por_red.keys(), key=lambda p: -vol_por_red.get(p, 0))

    s_stats      = scoreop.get("stats", {})
    s_dist       = scoreop.get("distribution", {})
    s_dist_plat  = scoreop.get("dist_por_plataforma", {})
    s_top        = scoreop.get("top_posts", [])[:5]
    s_bot        = scoreop.get("bottom_posts", [])[:5]

    project_name = analysis_meta.get("project_name", "—")
    tema         = analysis_meta.get("tema", "—")
    desc_tema    = analysis_meta.get("desc_tema") or dashboard_data.get("desc_tema", "—")
    fuentes      = analysis_meta.get("sources", [])
    fuentes = sorted(
        fuentes,
        key=lambda f: -vol_por_red.get(str(f).lower(), 0)
    )
    sources_desc = _build_sources_description(fuentes)
    sources_desc_short = _build_sources_desc_short(fuentes)
    idiomas      = analysis_meta.get("languages", [])
    start_date   = _fmt_date(analysis_meta.get("start_date", "—"))
    end_date     = _fmt_date(analysis_meta.get("end_date", "—"))
    created_at   = analysis_meta.get("created_at", "—")
    username     = analysis_meta.get("username", "—")

    posts        = dashboard_data.get("raw_data", [])

    # Keywords
    raw_kw = analysis_meta.get("keywords", [])
    if isinstance(raw_kw, str):
        try:
            raw_kw = json.loads(raw_kw)
        except Exception:
            raw_kw = [raw_kw]

    kw_set = set()
    if isinstance(raw_kw, list):
        for item in raw_kw:
            if isinstance(item, dict):
                kw = item.get("keyword", "")
            else:
                kw = str(item)
            kw = kw.strip()
            if kw:
                kw_set.add(kw)

    kw_list = sorted(kw_set)
    kw_str  = " · ".join(kw_list) if kw_list else "—"

    try:
        created_str = datetime.fromisoformat(created_at).strftime("%d/%m/%Y %H:%M")
    except Exception:
        created_str = str(created_at)

    # ── Doc setup ────────────────────────────────────────────────────────────
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=M, rightMargin=M,
        topMargin=1.5 * cm, bottomMargin=1.8 * cm,
        title=f"Informe — {project_name}",
        author="Sistema de análisis de opinión · DS4M Mediterráneo",
    )

    cover_frame = Frame(M, 2.2 * cm, CW, PH - 4 * cm, id="cover")
    cover_tpl   = PageTemplate(id="cover", frames=[cover_frame], onPage=_cover_page_bg)
    inner_frame = Frame(M, 1.8 * cm, CW, PH - 3.5 * cm, id="inner")
    inner_tpl   = PageTemplate(id="inner", frames=[inner_frame], onPage=_inner_page_template)
    doc.addPageTemplates([cover_tpl, inner_tpl])

    story: list = []

    # ══════════════════════════════════════════════════════════════════════════
    # PORTADA
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Spacer(1, 3.5 * cm))
    story.append(Paragraph(
        '<font color="#F5A623">INFORME DE ANÁLISIS DE OPINIÓN</font>',
        ParagraphStyle("cover_sup", fontName="Helvetica-Bold", fontSize=10,
                       textColor=C_ACCENT, alignment=TA_LEFT, leading=14)
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Redes sociales", ST["cover_title"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        f'<font color="#e8f0fe"><b>{tema.upper()}</b></font>',
        ParagraphStyle("cover_tema", fontName="Helvetica-Bold", fontSize=16,
                       textColor=colors.HexColor("#e8f0fe"), leading=22, alignment=TA_LEFT)
    ))
    story.append(Spacer(1, 0.5 * cm))
    story.append(ColorBar(CW * 0.30, height=3, color=C_ACCENT))
    story.append(Spacer(1, 0.8 * cm))

    if desc_tema and desc_tema != "—":
        short_desc = "<br/>".join(textwrap.wrap(str(desc_tema).replace("\n", " ").strip(), width=55)) 
        #str(desc_tema).replace("\n", " ").strip()#textwrap.shorten(desc_tema, width=240, placeholder="…")
        story.append(Paragraph(short_desc, ST["cover_sub"]))
        story.append(Spacer(1, 0.7 * cm))

    meta_fields = [
        ("Proyecto",           project_name),
        ("Periodo analizado",  f"{start_date} — {end_date}"),
        ("Fuentes",            ", ".join([f.capitalize() for f in fuentes]) or "—"),
        ("Idiomas",            ", ".join(idiomas) or "—"),
        ("Generado",           f"{created_str}  ·  Analista: {username}"),
    ]
    for label, value in meta_fields:
        story.append(Paragraph(
            f'<font color="#F5A623"><b>{label}:</b></font>  '
            f'<font color="#8faad0">{value}</font>',
            ST["cover_meta"]
        ))
    story.append(Spacer(1, 1.0 * cm))

    total_posts = kpis.get("total", 0)
    s_pct_media = scoreop.get("scoreop_pct_global", 0)
    n_topics    = len(topics)
    aceptacion_global = None
    score_color = _pos_color_pct(s_pct_media)
    if aceptacion_data and isinstance(aceptacion_data, dict):
        global_acp_tmp = aceptacion_data.get("global", {})
        if global_acp_tmp:
            aceptacion_global = global_acp_tmp.get("PillarOP_pct_medio")
    # ── KPIs portada dinámicos ──────────────────────────────────────
    kpis_cover = [
        KpiBox(
            f"{_fmt_int(total_posts)}",
            "Publicaciones analizadas",
            CW / 4 - 0.25*cm,
            color=colors.HexColor("#162e56"),
            text_color=C_WHITE,
            accent_color=C_ACCENT
        ),

        KpiBox(
            f"{s_pct_media:.2f}%" if s_pct_media else "—",
            "ECHO global",
            CW / 4 - 0.25*cm,
            color=colors.HexColor("#162e56"),
            text_color=_pos_color_pct(s_pct_media),
            accent_color=score_color
        ),
    ]

    # KPI opcional
    if aceptacion_global is not None:

        acp_color = _pos_color_pct(aceptacion_global)

        kpis_cover.append(
            KpiBox(
                f"{aceptacion_global:.2f}%",
                "Aceptación global",
                CW / 4 - 0.25*cm,
                color=colors.HexColor("#162e56"),
                text_color=acp_color,
                accent_color=acp_color
            )
        )
    

    # KPI temas
    kpis_cover.append(
        KpiBox(
            f"{_fmt_int(n_topics)}",
            "Temas detectados",
            CW / 4 - 0.25*cm,
            color=colors.HexColor("#162e56"),
            text_color=C_WHITE,
            accent_color=C_ACCENT
        )
    )

    n_boxes = len(kpis_cover)

    kpi_tbl = Table(
        [kpis_cover],
        colWidths=[CW / n_boxes] * n_boxes
    )

    kpi_tbl.setStyle(TableStyle([
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(kpi_tbl)

    story.append(NextPageTemplate("inner"))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # SECCIÓN 1 — RESUMEN EJECUTIVO
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Paragraph("1. Resumen ejecutivo", ST["section_title"]))
    story.append(ColorBar(CW, height=2, color=C_ACCENT))
    story.append(Spacer(1, 0.3 * cm))

    total_com = kpis.get("total_comentarios", 0)
    # exec_text = (
    #     f"El presente informe recoge los resultados del sistema de análisis automatizado de opinión pública "
    #     f"sobre el tema <b>{tema}</b>, correspondiente al periodo {start_date} — {end_date}. "
    #     f"Se han procesado <b>{_fmt_int(total_posts)} publicaciones originales</b> "
    #     f"(publicaciones en Reddit y Bluesky, así como vídeos publicados en YouTube) y <b>{_fmt_int(total_com)} comentarios</b> asociados, "
    #     f"procedentes de {len(fuentes)} fuente(s): "
    #     f"{', '.join([f.capitalize() for f in fuentes])}."
    # )
    exec_text = (
        f"El presente informe recoge los resultados del sistema de análisis automatizado de opinión pública "
        f"sobre el tema <b>{tema}</b>, correspondiente al periodo {start_date} — {end_date}. "
        f"Se han procesado <b>{_fmt_int(total_posts)} publicaciones originales</b> "
        f"({sources_desc}) y <b>{_fmt_int(total_com)} comentarios</b> asociados, "
        f"procedentes de {len(fuentes)} fuente(s): "
        f"{', '.join([f.capitalize() for f in fuentes])}."
    )
    story.append(Paragraph(exec_text, ST["body"]))

    if desc_tema and desc_tema != "—":
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph("<b>Contexto del análisis:</b> " + desc_tema, ST["body"]))

    story.append(Spacer(1, 0.25*cm))
    kw_display = kw_str#[:300] + ("…" if len(kw_str) > 300 else "")
    story.append(Paragraph(
        f"<b>Términos de búsqueda utilizados:</b> {kw_display}", ST["body"]
    ))
    story.append(Spacer(1, 0.3 * cm))

    # ── Tabla de métricas clave ──────────────────────────────────────────────
    scoreop_platform = scoreop.get("por_plataforma", {})

    scoreop_pct_max = scoreop_platform.get("ScoreOP_pct_max", {})
    scoreop_pct_min = scoreop_platform.get("ScoreOP_pct_min", {})
    s_med      = s_stats.get("pct_mediana", s_stats.get("mediana", 0))
    s_global   = scoreop.get("scoreop_pct_global", s_pct_media or 0)

    n_topics_post = len([t for t in topics if t.get("volumen", 0) > 0])

    max_values = [v for v in scoreop_pct_max.values() if isinstance(v, (int, float))]
    min_values = [v for v in scoreop_pct_min.values() if isinstance(v, (int, float))]

    s_max = max(max_values) if max_values else None
    value_s_min = min(min_values) if min_values else None
    s_min = 0.0 if value_s_min is not None and abs(value_s_min) < 1e-10 else value_s_min

    kpi_data = [
        [Paragraph("<b>Indicador</b>",    ST["table_header"]),
         Paragraph("<b>Valor</b>",        ST["table_header"]),
         Paragraph("<b>Descripción</b>",  ST["table_header"])],

        [Paragraph("Publicaciones totales",  ST["table_cell"]),
         Paragraph(f"{_fmt_int(total_posts)}",       ST["table_cell"]),
        #  Paragraph("Publicaciones de Reddit o Bluesky, y vídeos de YouTube originales con análisis de polaridad completado. "
        #            "Cada publicación es tratada como la 'voz del autor'.", ST["table_cell"])],
         Paragraph(f"{sources_desc_short.capitalize()} originales con análisis de polaridad completado. "
         "Cada publicación es tratada como la 'voz del autor'.", ST["table_cell"])],
        [Paragraph("Comentarios totales",    ST["table_cell"]),
         Paragraph(f"{_fmt_int(total_com)}",         ST["table_cell"]),
         Paragraph("Respuestas de la comunidad incluidas en el cálculo de los indicadores de polaridad ponderada por esfuerzo social, influencia y alcance "
                    #"(ponderan el 60 % "
                   "de la puntuación de cada publicación. No se contabilizan como publicaciones independientes.",
                   ST["table_cell"])],

        [Paragraph("Temas identificados",    ST["table_cell"]),
         Paragraph(f"{_fmt_int(n_topics_post)}",       ST["table_cell"]),
         Paragraph("Principales argumentos y enfoques detectados automáticamente en las publicaciones analizadas. "
                   "Cada contenido se asocia a un tópico representativo de la polaridad expresada." 
                   "El sistema prioriza la reutilización de categorías existentes para reducir duplicidades y mantener coherencia analítica.",
                   ST["table_cell"])],

        [Paragraph("ECHO global",     ST["table_cell"]),
         Paragraph(f"{s_global:.2f}%",       ST["table_cell"]),
         Paragraph("Síntesis agregada que cuantifica la hegemonía de la polaridad en el debate global. Representa el centro de gravedad de la " \
         "opinión pública, integrando la carga emocional de los argumentos ponderada por su tracción social efectiva (esfuerzo y alcance). " \
         "El indicador final se consolida mediante la masa discursiva de cada red, priorizando los ecosistemas con mayor densidad de participación " \
         "real para reflejar la posición neta que domina la agenda pública.",
        #  "Índice global de posicionamiento calculado mediante agregación "
        #             "ponderada del índice de posicionamiento por plataforma según el volumen total de "
        #             "interacciones analizadas (publicaciones + comentarios). "
        #             "Rango [0%, 100%]: 50% = equilibrio o neutralidad; "
        #             ">60% = posicionamiento mayoritariamente favorable; "
        #             "<40% = posicionamiento mayoritariamente desfavorable.",
                   ST["table_cell"])]
    ]               
    if aceptacion_global is not None:
        kpi_data.append([
            Paragraph("Aceptación global", ST["table_cell"]),
            Paragraph(f"{aceptacion_global:.2f}%", ST["table_cell"]),
            Paragraph(
                    "Indicador de aceptación social calculado a partir de la media de los cuatro pilares "
                    "(legitimación, efectividad, justicia y confianza institucional). "
                    "Primero se calcula la aceptación media de cada red social, considerando únicamente "
                    "publicaciones y comentarios con clasificación válida. "
                    "Después, el resultado global se obtiene como una media ponderada, donde cada red "
                    "contribuye en función del volumen de contenido analizado en esa red. "
                    "El indicador refleja el nivel general de aceptación de la opinión pública en el periodo analizado.",
                ST["table_cell"]
            ),
        ])
    kpi_data.append([
        Paragraph("Convergencia de Polaridad Favorable Máxima", ST["table_cell"]),
         Paragraph(f"{s_max:.2f}%" if s_max else "—", ST["table_cell"]),
         Paragraph("Publicación con ECHO score más alto.",
                   ST["table_cell"]
        ),
    ])

    kpi_data.append([Paragraph("Convergencia de Polaridad Crítica Máxima ", ST["table_cell"]),
         Paragraph(f"{s_min:.2f}%" if s_min is not None else "—", ST["table_cell"]),
         Paragraph("Publicación con ECHO score más bajo.",
                   ST["table_cell"]
        ),
    ])

    kpi_tbl2 = Table(kpi_data, colWidths=[CW*0.28, CW*0.14, CW*0.58])
    kpi_tbl2.setStyle(TableStyle(_TBLSTYLE_BASE + [
        ("ALIGN",     (1, 1), (1, -1), "CENTER"),
        ("FONTNAME",  (1, 1), (1, -1), "Helvetica-Bold"),
    ]))
    story.append(kpi_tbl2)
    story.append(Spacer(1, 0.3 * cm))

    # ══════════════════════════════════════════════════════════════════════════
    # SECCIÓN 2 — VOLUMEN Y DISTRIBUCIÓN DE PUBLICACIONES
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("2. Volumen y distribución de publicaciones y evolución temporal", ST["section_title"]))
    story.append(ColorBar(CW, height=2, color=C_ACCENT))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph(
        "Esta sección analiza la distribución de publicaciones por plataforma y la evolución temporal "
        "de la actividad durante el periodo de estudio. Se distingue entre <b>publicaciones originales</b> "
        f"({sources_desc_short})" " y <b>comentarios</b>, que son las respuestas de la comunidad. "
        "Ambas tipologías contribuyen al cálculo de los indicadores.",#, pero con roles distintos: "
        #"las publicaciones aportan el 40% del peso de su hilo, los comentarios el 60%.",
        ST["body"]
    ))
    story.append(Spacer(1, 0.3 * cm))

    if vol_por_red:
        donut_bytes = _chart_donut_platforms(vol_por_red, platform_order)
        donut_img   = _img_from_bytes(donut_bytes, CW * 0.48)

        vol_rows = [[
            Paragraph("<b>Plataforma</b>",   ST["table_header"]),
            Paragraph("<b>Publicaciones</b>", ST["table_header"]),
            Paragraph("<b>Comentarios</b>",   ST["table_header"]),
        ]]
        por_plat    = scoreop.get("por_plataforma", {})
        comment_key = "num_comentarios_sum"
        for plat, cnt in sorted(vol_por_red.items(), key=lambda x: -x[1]):
            n_com = int(por_plat.get(comment_key, {}).get(plat, 0)) if comment_key else "—"
            vol_rows.append([
                Paragraph(plat.capitalize(), ST["table_cell"]),
                Paragraph(f"{_fmt_int(cnt)}",         ST["table_cell_c"]),
                Paragraph(f"{_fmt_int(n_com)}" if isinstance(n_com, int) else n_com, ST["table_cell_c"]),
            ])
        vol_tbl = Table(vol_rows, colWidths=[CW*0.14, CW*0.14, CW*0.14])
        vol_tbl.setStyle(TableStyle(_TBLSTYLE_BASE + [
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ]))

        combo = Table([[donut_img, vol_tbl]], colWidths=[CW * 0.52, CW * 0.48])
        combo.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(combo)
        story.append(Paragraph(
            f"Figura {FIG_NUM}. Distribución de publicaciones originales por plataforma y tabla resumen. "
            f"La columna 'Comentarios' muestra el total de respuestas procesadas de cada red.",
            ST["caption"]
        ))
        story.append(Spacer(1, 0.4 * cm))
        FIG_NUM += 1

    def _ylabel_for_platform(red: str) -> str:
        red = red.lower()
        if red == "youtube":  return "Vídeos"
        if red == "reddit":   return "Publicaciones"
        if red == "bluesky":  return "Publicaciones"
        return "Publicaciones"

    def _chart_trend_single(tendencia_global, tendencia_red, red, color="#2E5FA3"):
        fechas_all = set(tendencia_global.keys())
        fechas_all.update((tendencia_red.get("total") or {}).keys())
        fechas = sorted(fechas_all)
        if not fechas:
            fig, ax = plt.subplots(figsize=(8, 2.5), facecolor="white")
            ax.text(0.5, 0.5, "Sin datos de tendencia", ha="center", va="center", color="#7A7A9A")
            return _fig_to_bytes(fig)
        fig, ax = plt.subplots(figsize=(8.5, 2.4), facecolor="white")
        global_vals = [tendencia_global.get(f, 0) for f in fechas]
        ax.fill_between(range(len(fechas)), global_vals, alpha=0.10, color="#C9D3E6", zorder=1)
        ax.plot(range(len(fechas)), global_vals, color="#B8C4D9", linewidth=2.2, label="Global", zorder=2)
        total = tendencia_red.get("total", {})
        vals  = [total.get(f, 0) for f in fechas]
        ax.plot(range(len(fechas)), vals, color=color, linewidth=2.5, zorder=4, label=red.capitalize())
        ax.fill_between(range(len(fechas)), vals, alpha=0.18, color=color, zorder=3)
        step = max(1, len(fechas) // 10)
        ax.set_xticks(range(0, len(fechas), step))
        ax.set_xticklabels(
            [_fmt_date(fechas[i]) for i in range(0, len(fechas), step)],
            rotation=35, ha="right", fontsize=7
        )
        ax.set_ylabel(_ylabel_for_platform(red), fontsize=8)
        ax.set_title(f"Evolución temporal · {red.capitalize()}", fontsize=10, fontweight="bold", color="#1B3A6B")
        ax.legend(fontsize=8, frameon=False, loc="upper left")
        _apply_ds4m_style(ax)
        fig.tight_layout()
        return _fig_to_bytes(fig)

    if tend_global:
        for i, red in enumerate([r for r in platform_order if r in tend_por_red]):
            data = tend_por_red[red]
            story.append(Spacer(1, 8))
            single_bytes = _chart_trend_single(tend_global, data, red, color=_plat_color(red, i))
            single_img   = _img_from_bytes(single_bytes, CW)
            story.append(single_img)
            story.append(Paragraph(
                f"Figura {FIG_NUM}. Evolución diaria del número de publicaciones originales de la red {red.capitalize()}."
                " La tendencia global se muestra en segundo plano para referencia."
                " Los picos de actividad pueden correlacionarse con eventos noticiosos o acciones de comunicación específicas.",
                ST["caption"]
            ))
            FIG_NUM += 1

    # ══════════════════════════════════════════════════════════════════════════
    # SECCIÓN 3 — ANÁLISIS DE IMPACTO: SCOREOP
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("3. Análisis del ECHO score (Esfuerzo, Conversación y Huella de Opinión)", ST["section_title"]))
    story.append(ColorBar(CW, height=2, color=C_ACCENT))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("3.1 Metodología: modelo ECHO score", ST["subsection"]))

    story.append(Paragraph(
        "El indicador de polaridad ponderada por esfuerzo social, y alcance,  denominado <b>ECHO score</b>, cuantifica la <b>tracción social de la carga argumental</b> "
        "en la conversación digital. A diferencia de los modelos basados en frecuencia simple de menciones positivas o negativas, "
        "este modelo evalúa el peso específico de cada intervención mediante la integración de la intensidad de interacción (esfuerzo), la audiencia potencial (alcance) " \
        "y la validación colectiva de la comunidad (auditoría discursiva).", 
        # "incorporando factores asociados al nivel de interacción generado, al alcance potencial del emisor y a la respuesta de la comunidad " \
        # "frente al contenido publicado.",
        ST["body"]))
    story.append(Spacer(1, 0.2*cm))

    dim_data = [
        [Paragraph("<b>Componente</b>", ST["table_header"]),
         Paragraph("<b>Qué es y cómo se calcula</b>", ST["table_header"]),
         Paragraph("<b>Por qué importa</b>", ST["table_header"])],

        [Paragraph("Polaridad del autor y de los comentarios", ST["table_cell"]),
         Paragraph("El análisis automatizado asigna a cada post y comentario un valor de polaridad respecto al tema de estudio introducido: "
             "+1 = a favor / apoyo, 0 = neutro / informativo / equilibrado, -1 = en contra / crítico. "
             "Los contenidos clasificados como 2 (no relacionados con el tema) "
             "se excluyen completamente del cálculo",# — no aportan ni numerador ni denominador.",
             ST["table_cell"]),
         Paragraph(
             "Garantiza que solo el contenido genuinamente relacionado con el tema "
             "influya en la métrica, eliminando ruido y spam.",
             ST["table_cell"])],

        [Paragraph("Impacto por esfuerzo\nsocial", ST["table_cell"]), #I(x)
         Paragraph("El sistema estima el impacto real de cada publicación considerando el nivel de interacción "
            "que genera en la comunidad. No todas las interacciones tienen el mismo significado. "#: compartir "
            #"contenido o participar activamente en la conversación requiere un mayor nivel de implicación que una " \
            # "reacción rápida. " \
            "El análisis se adapta automáticamente al comportamiento característico de cada plataforma, " \
            "evitando comparaciones directas entre dinámicas sociales distintas.",
            #  "I(x) = R * W_reac + S * W_comp + C * W_comm <br/>"
            #  "Donde R = reacciones (likes), S = compartidos (shares/reposts), <br/>"
            #  "C = número de comentarios del elemento analizado.<br/>"
            #  "Los pesos W se calculan dinamicamente para toda la red filtrada:<br/>"
            #  "  TSE = R_total + S_total + C_total  (participación total de la red)<br/>"
            #  "  M   = número de tipos de métrica con datos > 0 en esa red<br/>"
            #  "  W_reac = (TSE / M) / R_total   si R_total > 0, sino 0<br/>"
            #  "  W_comp = (TSE / M) / S_total   si S_total > 0, sino 0<br/>"
            #  "  W_comm = (TSE / M) / C_total   si C_total > 0, sino 0<br/>"
            #  "Efecto: la métrica más escasa en esa red recibe el peso más alto.<br/>"
            #  "M varía según la red:<br/>"
            #  "  Bluesky (M = 3): Me gusta, republicaciones/citas y comentarios.<br/>"
            #  "  YouTube (M = 2): Me gusta y comentarios.<br/>"
            #  "  Reddit (M = 1): Exclusivamente comentarios (se excluyen Upvotes por su naturaleza de puntuación neta).",
             ST["table_cell"]
             ),
         Paragraph(
             "Un comentario en Reddit (donde comentar es habitual) no equivale a uno "
             "en Bluesky (donde el ratio es menor). El modelo se autocalibra por red: "
             "si una plataforma casi no tiene likes pero sí muchos comentarios, "
             "los comentarios valen proporcionalmente menos que en una red donde son raros.",
             ST["table_cell"])],

        [Paragraph("Factor de influencia y alcance (solo publicaciones originales)", ST["table_cell"]),
         Paragraph(
            "Las publicaciones con mayor capacidad de difusión reciben una ponderación adicional en el análisis. " 
            "Para ello se consideran variables de alcance potencial, como visualizaciones, seguidores o tamaño de audiencia, según la plataforma. " 
            "El objetivo no es premiar popularidad superficial, sino estimar la capacidad real de una publicación para influir en la conversación pública.",
            #  "Amplia el impacto de la publicación según el alcance potencial del autor:<br/>"
            #  "  YouTube:  F = (1 + ln(V/V_total)) * (1 + ln(S/S_total))<br/>"
            #  "            V = vistas del video, S = suscriptores del canal.<br/>"
            #  "  Bluesky:  F = 1 + ln(seguidores / seguidores_total_red)<br/>"
            #  "  Reddit:   F = 1  (sin factor adicional, debido a la ausencia de variable estructural de alcance observable)<br/>"
            # "La transformación logarítmica ayuda a estabilizar la varianza y a reducir el impacto de cuentas con seguidores inflados artificialmente o por crecimiento histórico no relacionado con el tema.",
             ST["table_cell"]),
         Paragraph(
             "Un video con 1M de vistas en YouTube tiene mayor capacidad de instalar "
             "una opinion en la agenda que uno con 100 vistas, incluso si ambos vehiculan argumentos con la misma polaridad. " \
             "El factor de influencia y alcance actúa como un amplificador de la carga argumental, determinando que la huella " \
             "de opinión del primer vídeo sea estructuralmente más relevante en el cálculo del indicador global, aunque sin un incremento estrictamente lineal.",
             ST["table_cell"])],
        # [
        #     Paragraph("Representatividad de usuarios", ST["table_cell"]),
        #     Paragraph(
        #         "El sistema incorpora mecanismos de equilibrio destinados a evitar que "
        #         "un pequeño grupo de usuarios extremadamente activos domine artificialmente "
        #         "la conversación analizada. De esta manera, se favorece una representación "
        #         "más proporcional de la diversidad de participantes presentes en el debate.",
        #         ST["table_cell"]
        #     ),
        #     Paragraph(
        #         "Reduce el impacto de comportamientos repetitivos o campañas de alta actividad, "
        #         "permitiendo identificar tendencias de opinión más representativas del conjunto "
        #         "de participantes.",
        #         ST["table_cell"]
        #     )
        #     ],
        [Paragraph("Regla 40/60:\nautor vs. comunidad", ST["table_cell"]),
         Paragraph(
             "El indicador final (<b>ECHO score de la publicación</b>) ntegra la polaridad de la carga argumental del autor " \
             "con la respuesta emocional agregada de la comunidad. Este enfoque trasciende la mera monitorización de la emisión " \
             "para evaluar la validación social del discurso. Mediante esta arquitectura, el sistema identifica dinámicas de convergencia "
             "(cuando la comunidad amplifica la polaridad original) o de disonancia "
             "(cuando la respuesta colectiva neutraliza o invierte el sentido del mensaje inicial).",
            #  "El indicador de posición ponderado por esfuerzo social y alcance de cada hilo de publicación se construye combinando:\n"
            #  "  40% = contribución de la publicación original\n"
            #  "  60% = contribución agregada de sus comentarios\n"
            #  "Esto implica que si el autor adopta una posición favorable (+1), pero la comunidad expresa una respuesta mayoritariamente contradictoria o en dirección opuesta, el indicador resultante puede descender por debajo del 50%, indicando una inversión de la narrativa predominante respecto al contenido original.",
             ST["table_cell"]),
         Paragraph(
             "Captura fenómenos dcomo el 'ratio' (donde una tracción crítica masiva invalida la narrativa del autor) "
             "o el de 'consenso por refuerzo' (cuando los comentarios amplifican la posición "
             "de la publicación original), garantizando que una publicación viral con argumentos críticos obtenga una " \
             "huella de opinión radicalmente distinta a una publicación con el mismo contenido pero sin interacción disonante.",
             ST["table_cell"])],
    ]
    dim_tbl = Table(dim_data, colWidths=[CW*0.17, CW*0.44, CW*0.37])
    dim_tbl.setStyle(TableStyle(_TBLSTYLE_BASE))
    story.append(dim_tbl)
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph(
    "El sistema calcula el ECHO score de cada conversación (publicación original y comentarios asociados) integrando múltiples dimensiones de interacción social: intensidad de participación, " \
    "alcance potencial de la publicación y respuesta generada en la comunidad. " \
    "Posteriormente, los resultados se normalizan para permitir comparaciones consistentes entre plataformas y periodos temporales distintos.",
    ST["body"]
))

    # story.append(Paragraph("<b>Secuencia de cálculo completa para cada publicación original:</b>",
    #                        ST["body_left"]))
    # story.append(Spacer(1, 0.1*cm))

    # formulas = [
    #     "PASO 1 — Impacto individual:",
    #     "  I(post)  = 1.0 + (R_post * W_reac + S_post * W_comp + C_post * W_comm"),
    #     "  I(com_k) = 1.0 + (R_com_k * W_reac + S_com_k * W_comp + C_com_k * W_comm"),
    #     "",
    #     "PASO 2 — Acumulación bruta del hilo (Impacto del hilo):",
    #     "  raw = 0.4 * (Posición_post * I(post) * F_post) + 0.6 * SUM_k( Posición_com_k * I(com_k) )",
    #     "",
    #     "PASO 3 — Máximo teórico posible:",
    #     "  sup = 0.4 * I(post) * F_post  +  0.6 * SUM_k( I(com_k) )",
    #     "  (escenario contrafactual de máxima alineación en el que todas las opiniones están perfectamente alineadas en sentido positivo (+1))",
    #     "",
    #     "PASO 4 — Normalización al intervalo [-1, +1]:",
    #     "  norm = raw / sup           (si sup > 0, en caso contrario = 0.0)",
    #     "",
    #     "PASO 5 — Conversión a escala porcentual [0%, 100%]:",
    #     "  Indicador_pct  = (norm + 1) / 2 * 100",
    #     "  (0% = alineación completamente negativa, 50% = neutralidad estructural, ",
    #     "  100% = alineación completamente positiva)"
    # ]
    # for line in formulas:
    #     if line == "":
    #         story.append(Spacer(1, 0.05*cm))
    #     else:
    #         story.append(Paragraph(line, ST["formula"]))
    # story.append(Spacer(1, 0.2*cm))

    # story.append(Paragraph(
    #     "<b>Casos límite ilustrativos:</b>  "
    #     "Si un post tiene posición +1 y todos sus comentarios también (+1), "
    #     "norm = 1.0 y indicador_pct = 100%.  "
    #     "Si el post es +1 pero todos los comentarios son -1 y tienen el mismo peso que el post, "
    #     "raw = 0.4*I - 0.6*I_com: el resultado puede ser negativo y dar un indicador_pct &lt; 50%.  "
    #     "Si sup = 0 (el post no tiene interacción activa medible y no tiene comentarios), "
    #     "norm = 0.0 e indicador_pct = 50% (posición neutral por defecto).",
    #     ST["note"]
    # ))
    # story.append(Spacer(1, 0.2*cm))

    # story.append(Paragraph("<b>Agregación por red y cálculo del KPI global:</b>", ST["body_left"]))
    # story.append(Spacer(1, 0.1*cm))
    # agg_formulas = [
    #     "Indicador_pct_red = (SUM_posts(raw) / SUM_posts(sup) + 1) / 2 * 100",
    #     "  → ratio de raw acumulado sobre sup acumulado de todos los posts de la red.",
    #     "",
    #     "N_r (peso de la red) = n_posts_activos_red + n_comentarios_activos_red",
    #     "  → 'activos' = con posición != 2 (relacionados con el tema).",
    #     "",
    #     "Indicador_pct_global = SUM_r( Indicador_pct_red * N_r ) / SUM_r( N_r )",
    #     "  → media ponderada por volumen de participación: las redes con más",
    #     "    contenido activo tienen más peso en el KPI global.",
    # ]
    # for line in agg_formulas:
    #     if line == "":
    #         story.append(Spacer(1, 0.05*cm))
    #     else:
    #         story.append(Paragraph(line, ST["formula"]))
    # story.append(Spacer(1, 0.2*cm))

    # interp_data = [
    #     [Paragraph("<b>Rango indicador</b>", ST["table_header"]),
    #      Paragraph("<b>Categoría</b>",            ST["table_header"]),
    #      Paragraph("<b>Significado sustantivo</b>", ST["table_header"])],
    #     [Paragraph("&gt; 80%",   ST["table_cell_c"]),
    #      Paragraph("Convergencia positiva alta",     ST["table_cell"]),
    #      Paragraph("El conjunto de la comunidad expresa una polaridad positiva activa y mayoritaria, "
    #                "con interacciones que amplifican la polaridad positiva.", ST["table_cell"])],
    #     [Paragraph("60% – 80%", ST["table_cell_c"]),
    #      Paragraph("Predominancia positiva",         ST["table_cell"]),
    #      Paragraph("Predomina la polaridad positiva, aunque existe debate visible. "
    #                "La tracción positiva supera claramente a la negativa.", ST["table_cell"])],
    #     [Paragraph("40% – 60%", ST["table_cell_c"]),
    #      Paragraph("Equilibrio / Polarización", ST["table_cell"]),
    #      Paragraph("Las polaridades positivas y negativas se compensan, "
    #                "o bien el contenido es mayoritariamente neutro. "
    #                "50% exacto = equilibrio perfecto o engagement nulo.", ST["table_cell"])],
    #     [Paragraph("20% – 40%", ST["table_cell_c"]),
    #      Paragraph("Predominancia negativa",      ST["table_cell"]),
    #      Paragraph("Predomina la polaridad negativa. "
    #                "La comunidad contradice activamente a los autores con polaridad positiva.", ST["table_cell"])],
    #     [Paragraph("&lt; 20%",  ST["table_cell_c"]),
    #      Paragraph("Convergencia negativa alta",  ST["table_cell"]),
    #      Paragraph("Rechazo mayoritario e intenso. Posible efecto 'ratio': "
    #                "los posts con polaridad positiva generan oleadas de argumentos negativos en los comentarios.", ST["table_cell"])],
    # ]
    
    interp_data = [
    [Paragraph("<b>Rango indicador</b>", ST["table_header"]),
     Paragraph("<b>Categoría técnica</b>", ST["table_header"]),
     Paragraph("<b>Significado sociométrico</b>", ST["table_header"])],
    
    [Paragraph("&gt; 80%", ST["table_cell_c"]),
     Paragraph("Convergencia Favorable alta", ST["table_cell"]),
     Paragraph("<b>Consenso hegemónico:</b> la práctica totalidad de la energía social (alcance + interacción) valida los argumentos de apoyo. Los <b>Picos de ECHO score</b> en este rango indican una sintonía absoluta entre emisor y comunidad.", ST["table_cell"])],
    
    [Paragraph("60% – 80%", ST["table_cell_c"]),
     Paragraph("Predominancia favorable", ST["table_cell"]),
     Paragraph("<b>Validación mayoritaria:</b> los argumentos favorables dominan la agenda y capitalizan la interacción, aunque coexisten con voces críticas que mantienen capacidad de respuesta.", ST["table_cell"])],
    
    [Paragraph("40% – 60%", ST["table_cell_c"]),
     Paragraph("Equilibrio / Polarización", ST["table_cell"]),
     Paragraph("<b>Punto de neutralización:</b> las fuerzas de apoyo y rechazo tienen magnitudes similares y se cancelan recíprocamente, o bien el discurso es puramente informativo sin tracción emocional.", ST["table_cell"])],
    
    [Paragraph("20% – 40%", ST["table_cell_c"]),
     Paragraph("Predominancia crítica", ST["table_cell"]),
     Paragraph("<b>Tracción de rechazo:</b> la narrativa crítica lidera el debate. La comunidad contradice activamente los argumentos favorables, desplazando el centro de gravedad hacia el descontento.", ST["table_cell"])],
    
    [Paragraph("&lt; 20%", ST["table_cell_c"]),
     Paragraph("Convergencia crítica alta", ST["table_cell"]),
     Paragraph("<b>Rechazo estructural:</b> clima de hostilidad unívoca. Los <b>Picos de ECHO score</b> en este rango señalan 'ratios' masivos donde la respuesta social invalida por completo la narrativa del autor.", ST["table_cell"])],
]
    interp_tbl = Table(interp_data, colWidths=[CW*0.18, CW*0.20, CW*0.62])
    interp_tbl_style = TableStyle(_TBLSTYLE_BASE[:])
    interp_tbl_style.add("BACKGROUND", (0,1), (-1,1), colors.HexColor("#e8f5e9"))
    interp_tbl_style.add("BACKGROUND", (0,2), (-1,2), colors.HexColor("#f1f8e9"))
    interp_tbl_style.add("BACKGROUND", (0,3), (-1,3), colors.HexColor("#f5f5f5"))
    interp_tbl_style.add("BACKGROUND", (0,4), (-1,4), colors.HexColor("#fff3e0"))
    interp_tbl_style.add("BACKGROUND", (0,5), (-1,5), colors.HexColor("#ffebee"))
    interp_tbl_style.add("ALIGN",      (0,1), (0,-1), "CENTER")
    interp_tbl_style.add("FONTNAME",   (0,1), (0,-1), "Helvetica-Bold")
    interp_tbl.setStyle(interp_tbl_style)
    story.append(interp_tbl)
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        "Nota: El indicador ECHO global no es un promedio de los ECHO score de cada publicación. "
        "Se define como el ratio entre la <b>energía neta acumulada</b> y el <b>soporte máximo potencial</b> del conjunto analizado." \
        "Esta arquitectura permite que el indicador sea sensible a la <b>asimetría de impacto</b>: "
        "dos escenarios con idéntico número de publicaciones favorables y críticas arrojarán resultados "
        "divergentes si la tracción social (interacción y alcance) está concentrada en una de las dos polaridades.",
        ST["note"]
    ))
    story.append(Spacer(1, 0.3*cm))

    if scoreop.get("disponible"):
        story.append(Paragraph("3.2 Resultados globales", ST["subsection"]))

        pct_global   = scoreop.get("scoreop_pct_global", s_pct_media or 50)
        pct_label, pct_hex = _scoreop_cat(pct_global)
        s_pct_media  = s_stats.get("pct_media")

        sk_data = [[
            KpiBox(f"{pct_global:.2f}%",  "ECHO Global",    CW/4-0.2*cm,
                   color=colors.HexColor("#dff0e8"), text_color=colors.HexColor(pct_hex),
                   accent_color=colors.HexColor(pct_hex)),
            KpiBox(f"{s_pct_media:.2f}%"  if s_pct_media  else "—",
                   "ECHO Promedio",                                   CW/4-0.2*cm),
            KpiBox(f"{s_max:.2f}%"        if s_max        else "—",
                   "Pico de ECHO score (max)",                                   CW/4-0.2*cm,
                   color=colors.HexColor("#e8f5e9"), text_color=C_VERY_POS,
                   accent_color=C_VERY_POS),
            KpiBox(f"{s_min:.2f}%"        if s_min is not None else "—",
                   "Pico de ECHO score (min)",                                 CW/4-0.2*cm,
                   color=colors.HexColor("#ffebee"), text_color=C_VERY_NEG,
                   accent_color=C_VERY_NEG),
        ]]
        sk_tbl = Table(sk_data, colWidths=[CW/4]*4)
        sk_tbl.setStyle(TableStyle([
            ("LEFTPADDING",  (0,0), (-1,-1), 3),
            ("RIGHTPADDING", (0,0), (-1,-1), 3),
        ]))
        story.append(sk_tbl)
        story.append(Spacer(1, 0.15*cm))
        story.append(Paragraph(
            f"<b>Interpretación del ECHO score global ({pct_global:.2f}%):</b> {_interp_scoreop(pct_global)}<br/>"
            f"La media por post no está ponderada y puede diferir debido a desbalances de volumen entre plataformas.",
            ST["body"]
        ))
        story.append(Spacer(1, 0.3*cm))

        pct_por_red = scoreop.get("scoreop_pct_por_red", {})
        if pct_por_red:
            story.append(Paragraph("3.3 Polaridad ponderada por esfuerzo social, y alcance por plataforma", ST["subsection"]))
            story.append(Paragraph(
                "La polaridad de cada red (Indicador ECHO score de la red) se calcula como la media ponderada del impacto de todos sus posts, "
                "manteniendo coherencia metodológica entre plataformas y volúmenes de interacción.",
                #"usando el denominador acumulado (sup) para mantener coherencia con el modelo.",
                ST["body"]
            ))
            story.append(Spacer(1, 0.15*cm))

            plat_rows = [[
                Paragraph("<b>Plataforma</b>",      ST["table_header"]),
                Paragraph("<b>ECHO score de la red</b>", ST["table_header"]),
                Paragraph("<b>Categoría</b>",        ST["table_header"]),
                Paragraph("<b>Motores (+)</b>",      ST["table_header"]),
                Paragraph("<b>Neutros</b>",          ST["table_header"]),
                Paragraph("<b>Motores (-)</b>",      ST["table_header"]),
            ]]
            for plat, pct_r in sorted(pct_por_red.items(), key=lambda x: -x[1]):
                lbl, hx = _scoreop_cat(pct_r)
                d     = s_dist_plat.get(plat, {})
                n_pos = (d.get("muy_positivo", 0) + d.get("positivo", 0))
                n_neu = d.get("neutro", 0)
                n_neg = (d.get("negativo", 0) + d.get("muy_negativo", 0))
                total = n_pos + n_neu + n_neg or 1
                plat_rows.append([
                    Paragraph(plat.capitalize(),                            ST["table_cell"]),
                    Paragraph(f"{pct_r:.2f}%",                             ST["table_cell_c"]),
                    Paragraph(lbl,                                          ST["table_cell_c"]),
                    Paragraph(f"{n_pos} ({n_pos/total*100:.2f}%)",         ST["table_cell_c"]),
                    Paragraph(f"{n_neu} ({n_neu/total*100:.2f}%)",         ST["table_cell_c"]),
                    Paragraph(f"{n_neg} ({n_neg/total*100:.2f}%)",         ST["table_cell_c"]),
                ])
            plat_tbl = Table(plat_rows, colWidths=[CW*0.12, CW*0.20, CW*0.20, CW*0.12, CW*0.12, CW*0.12])
            plat_tbl.setStyle(TableStyle(_TBLSTYLE_BASE + [
                ("ALIGN",   (1,1), (-1,-1), "CENTER"),
                ("FONTNAME",(1,1), (1,-1),  "Helvetica-Bold"),
            ]))
            story.append(plat_tbl)
            story.append(Spacer(1, 0.15*cm))
            story.append(Paragraph(
                "Motores (+): publicaciones originales con ECHO score > 60% (tracción favorable). "
                "Neutros: indicador 40-60%. Motores (-): indicador < 40% (tracción de rechazo).",
                ST["note"]
            ))
            story.append(Spacer(1, 0.3*cm))

        charts = _chart_scoreop_trend_by_red(scoreop, platform_order)
        if charts:
            story.append(Paragraph(
                "3.5 Trayectoria temporal de la polaridad por plataforma",
                ST["subsection"]
            ))
            # story.append(Paragraph(
            #     "Cada gráfico monitoriza el promedio diario de los ECHO score de la publicaciones. "
            #     "La línea continua representa el promedio ECHO score del día, "
            #     "mientras que la línea discontinua representa el 'sesgo acumulado', definido como la suma progresiva de las desviaciones diarias respecto al punto neutro (50%). "
            #     #"sesgo_t = Σ (Indicador_pct_día - 50), "
            #     "Este valor no es un promedio, sino la acumulación de capital social o malestar crónico a lo largo de todo el periodo: <br/>"
            #     "- Valores positivos indican predominio sostenido de apoyo en el tiempo<br/>"
            #     "- Valores negativos indican acumulación persistente de rechazo<br/>"
            #     "- Valores cercanos a 0 indican equilibrio estable en el largo plazo.",
            #     ST["body"]
            # ))
            story.append(Paragraph(
                "Cada gráfico monitoriza la evolución cronológica de la polaridad mediante el promedio diario de los valores <b>ECHO score</b>. "
                "La línea continua representa la <b>Polaridad Media Diaria</b>, identificando la respuesta inmediata de la opinión pública ante hitos o eventos específicos. "
                "Por otro lado, la línea discontinua representa el <b>Balance Neto Acumulado</b> (Inercia del Clima Social), definido como el sumatorio progresivo de las desviaciones diarias respecto al punto de equilibrio (50%). "
                "Este indicador no constituye un promedio, sino una métrica de memoria del sistema que revela la acumulación de capital social o la cronificación del malestar a lo largo de todo el periodo analizado: <br/><br/>"
                "• <b>Valores positivos:</b> indican una consolidación sostenida de la validación de los argumentos en el tiempo.<br/>"
                "• <b>Valores negativos:</b> revelan una acumulación persistente de rechazo estructural o malestar crónico.<br/>"
                "• <b>Valores cercanos a 0:</b> señalan un estado de equilibrio estable o una neutralización recíproca de fuerzas en el largo plazo.",
                ST["body"]
            ))
            for red, img in charts.items():
                story.append(Spacer(1, 0.25*cm))
                story.append(_img_from_bytes(img, CW))
                story.append(Paragraph(
                    f"Figura {FIG_NUM}. Dinámica de polaridad y balance neto del debate · {red.capitalize()}. "
                    "La línea continua muestra el ECHO score promedio diario; la línea discontinua muestra el balance neto del sesgo.",
                    ST["caption"]
                ))
                FIG_NUM += 1
            story.append(Spacer(1, 0.3*cm))

        story.append(Paragraph("3.6 Tabla de distribución global", ST["subsection"]))
        dist_data = [
            [Paragraph("<b>Categoría</b>",            ST["table_header"]),
             Paragraph("<b>Rango indicador </b>",  ST["table_header"]),
             Paragraph("<b>N.° publicaciones (%)</b>", ST["table_header"]),
             Paragraph("<b>Qué indica</b>",            ST["table_header"])],
        ]
        cat_info = [
            ("muy_positivo",  "> 80%",    "#e8f5e9", "Amplio consenso positivo con alta interacción."),
            ("positivo",      "60 – 80%", "#f1f8e9", "Posición favorable predominante."),
            ("neutro",        "40 – 60%", "#f5f5f5", "Debate equilibrado o contenido con posición neutra."),
            ("negativo",      "20 – 40%", "#fff3e0", "Posición de rechazo predominante."),
            ("muy_negativo",  "< 20%",    "#ffebee", "Fuerte rechazo activo o controversia marcada."),
        ]
        total_dist = sum(s_dist.get(c[0], 0) for c in cat_info) or 1
        for cat, rango, bg, desc in cat_info:
            n = s_dist.get(cat, 0)
            dist_data.append([
                Paragraph(cat.replace("_", " ").capitalize(), ST["table_cell"]),
                Paragraph(rango,                              ST["table_cell_c"]),
                Paragraph(f"{_fmt_int(n)} ({n/total_dist*100:.2f}%)", ST["table_cell_c"]),
                Paragraph(desc,                               ST["table_cell"]),
            ])

        dist_tbl = Table(dist_data, colWidths=[CW*0.16, CW*0.14, CW*0.14, CW*0.44])
        style_dist = TableStyle(_TBLSTYLE_BASE[:])
        for i, (_, _, bg, _) in enumerate(cat_info, start=1):
            style_dist.add("BACKGROUND", (0, i), (-1, i), colors.HexColor(bg))
        dist_tbl.setStyle(style_dist)
        story.append(dist_tbl)
        story.append(Spacer(1, 0.4*cm))

        story.append(Paragraph("3.7 Publicaciones representativas", ST["subsection"]))
        story.append(Paragraph(
            "Se muestran hasta 5 publicaciones con mayor tracción positiva (<b>motores positivos</b>) "
            "y hasta 5 con mayor tracción negativa (<b>motores negativos</b>). "
            "El ECHO score de cada publicación indica qué porcentaje del máximo potencial positivo "
            "obtuvo, considerando su impacto individual y la respuesta de sus comentarios.",
            ST["body"]
        ))
        story.append(Spacer(1, 0.15*cm))

        def _posts_table(posts, title, bg_header, color_text):
            if not posts:
                return
            story.append(Paragraph(f"<b>{title}</b>", ST["body_left"]))
            rows = [[
                Paragraph("<b>Plataforma</b>",         ST["table_header"]),
                Paragraph("<b>Fecha</b>",              ST["table_header"]),
                Paragraph("<b>ECHO pct</b>",      ST["table_header"]),
                Paragraph("<b>Polaridad autor</b>",     ST["table_header"]),
                Paragraph("<b>Comentarios</b>",        ST["table_header"]),
                Paragraph("<b>Extracto del contenido</b>", ST["table_header"]),
            ]]
            for post in posts:
                # content = str(post.get("contenido_post", "")).replace("\n", " ").strip() #textwrap.shorten(str(post.get("contenido_post", ""), width=110, placeholder="…")
                content = limpiar_texto_pdf(str(post.get("contenido_post", "") or ""))
                content = textwrap.shorten(content, width=400, placeholder="…")
                pct_s   = post.get("ScoreOP_pct", 0)
                pct     = 0.0 if pct_s is not None and abs(pct_s) < 1e-10 else pct_s
                stance  = {1: "Positiva", 0: "Neutra", -1: "Negativa"}.get(
                    post.get("stance_post"), str(post.get("stance_post", "—")))
                n_com   = post.get("num_comentarios", 0)
                fecha_raw = str(post.get("FECHA", ""))
                fecha_str = _fmt_date(fecha_raw) if fecha_raw not in ("", "—", "nan") else "—"
                rows.append([
                    Paragraph((post.get("plataforma") or "—").capitalize(), ST["table_cell"]),
                    Paragraph(fecha_str,                                     ST["table_cell"]),
                    Paragraph(f"{pct:.2f}%" if pct is not None else "—",   ST["table_cell_c"]),
                    Paragraph(stance,                                        ST["table_cell_c"]),
                    Paragraph(str(n_com),                                   ST["table_cell_c"]),
                    Paragraph(limpiar_texto_pdf(content),    ST["table_cell_unicode"]),
                ])
            tbl = Table(rows, colWidths=[CW*0.11, CW*0.11, CW*0.12, CW*0.12, CW*0.13, CW*0.38])
            tbl.setStyle(TableStyle(_TBLSTYLE_BASE + [
                ("BACKGROUND", (0,0), (-1,0), bg_header),
                ("ALIGN",      (1,0), (3,-1), "CENTER"),
                ("FONTNAME",   (1,1), (1,-1), "Helvetica-Bold"),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 0.25*cm))

        _posts_table(s_top, "Motores de apoyo (Indicador > 60%)",
                     colors.HexColor("#1b5e20"), "#0a7c4a")
        _posts_table(s_bot, "Motores de rechazo (Indicador < 40%)",
                     colors.HexColor("#b71c1c"), "#d8535f")

    else:
        story.append(Paragraph(
            "Los datos de indicadores no están disponibles para este análisis. "
            "Puede que el cálculo esté en curso o que no existan publicaciones con comentarios suficientes.",
            ST["body"]
        ))

    # ── 3.8 Publicaciones con mayor impacto por red ──────────────────────────
    sup_by_red = defaultdict(float)
    for p in posts:
        sup_by_red[p.get("plataforma")] += float(p.get("ScoreOP_sup", 0) or 0)

    for p in posts:
        red_p = p.get("plataforma")
        sup   = float(p.get("ScoreOP_sup", 0) or 0)
        total = sup_by_red.get(red_p, 1)
        p["impacto_red"] = sup / total if total > 0 else 0

    top_by_red = defaultdict(list)
    for p in posts:
        top_by_red[p["plataforma"]].append(p)
    for red_p in top_by_red:
        top_by_red[red_p] = sorted(
            top_by_red[red_p],
            key=lambda x: x.get("impacto_red", 0),
            reverse=True
        )[:3]

    story.append(Paragraph("3.8 Publicaciones con mayor impacto por red", ST["subsection"]))
    story.append(Paragraph(
        "Se muestran las publicaciones con mayor capacidad de influencia estructural dentro de cada plataforma. "
        "El impacto relativo indica cuánto peso tiene cada publicación en la conversación total de la red a la que pertenece, " \
        "considerando el volumen de interacción, alcance y participación que genera. "
        # "Este valor representa un escenario contrafactual de máxima alineación positiva, es decir, "
        # " el volumen máximo de tracción que una publicación podría aportar al sistema si todas las interacciones "
        # "estuvieran perfectamente alineadas en sentido favorable (+1). "
        # " A diferencia de indicador_pct, esta métrica no evalúa si la conversación es favorable o desfavorable, "
        # "sino cuánto 'mueve la aguja' cada publicación original dentro de la dinámica total de su plataforma. "
        # "Una publicación con alto impacto relativo concentra una fracción significativa de la atención, interacción y "
        # "capacidad de arrastre del debate en esa comunidad.",
        "A diferencia del ECHO score, esta métrica no evalúa si se consolidan los argumentos positivos o negativos, "
        "sino el nivel de visibilidad, alcance e influencia estructural que tiene cada publicación dentro de la red. "
        "Las publicaciones con mayor impacto relativo tienden a concentrar una parte significativa de la atención y participación de la comunidad.",
        ST["body"]
    ))
    story.append(Spacer(1, 0.15*cm))

    # ── CORRECCIÓN DEL BUG: idx_red y red_name se pasan como parámetros ─────
    def _impact_table_red(posts_red, red_name, idx_red_num):
        if not posts_red:
            return

        story.append(Paragraph(
            f"3.8.{idx_red_num + 1} {red_name.capitalize()} · publicaciones dominantes",
            ST["subsection"]
        ))
        story.append(ColorBar(CW * 0.25, height=2,
                              color=colors.HexColor(_plat_color(red_name))))
        story.append(Spacer(1, 0.15 * cm))

        rows = [[
            Paragraph("<b>Energía en la red</b>", ST["table_header"]),
            Paragraph("<b>Fecha</b>",            ST["table_header"]),
            Paragraph("<b>Indicador</b>",      ST["table_header"]),
            Paragraph("<b>Polaridad</b>",            ST["table_header"]),
            Paragraph("<b>Métricas del post</b>",  ST["table_header"]),
            Paragraph("<b>Contenido</b>",           ST["table_header"]),
        ]]

        def safe_float(x):
            try:
                if x is None or x == "":
                    return None
                v = float(x)
                return 0.0 if abs(v) < 1e-10 else v
            except Exception:
                return None

        for p in posts_red:
            content = limpiar_texto_pdf(str(p.get("contenido_post", "") or ""))
            content = textwrap.shorten(content, width=400, placeholder="…")
            pct     = safe_float(p.get("ScoreOP_pct")) or 0.0
            fecha_raw = str(p.get("fecha", ""))
            fecha_str = _fmt_date(fecha_raw) if fecha_raw not in ("", "—", "nan") else "—"
            impact  = safe_float(p.get("impacto_red")) or 0.0
            stance  = {1: "Favorable", 0: "Neutra", -1: "En contra"}.get(
                p.get("stance_post"), str(p.get("stance_post", "—")))

            if red_name.lower() == "youtube":
                vistas   = safe_float(p.get("vistas"))
                subs     = safe_float(p.get("suscriptores"))
                comments = safe_float(p.get("num_comentarios"))
                metricas = (
                    f"Vistas: {_fmt_int(vistas) if vistas is not None else '—'}<br/>  "
                    f"Suscriptores: {_fmt_int(subs) if subs is not None else '—'}<br/>  "
                    f"Comentarios: {_fmt_int(comments) if comments is not None else '—'}"
                )
            elif red_name.lower() == "bluesky":
                followers = safe_float(p.get("seguidores"))
                comments  = safe_float(p.get("num_comentarios"))
                metricas  = (
                    f"Seguidores: {_fmt_int(followers) if followers is not None else '—'}<br/>"
                    f"Comentarios: {_fmt_int(comments) if comments is not None else '—'}"
                )
            elif red_name.lower() == "reddit":
                comments = safe_float(p.get("num_comentarios"))
                metricas = f"Comentarios: {_fmt_int(comments) if comments is not None else '—'}"

            elif red_name.lower() == "telegram":
                vistas      = safe_float(p.get("vistas"))
                reacciones  = safe_float(p.get("reacciones_total"))
                suscript    = safe_float(p.get("seguidores"))
                comments    = safe_float(p.get("num_comentarios"))
                metricas = (
                    f"Vistas: {_fmt_int(vistas) if vistas is not None else '—'}<br/>"
                    f"Reacciones: {_fmt_int(reacciones) if reacciones is not None else '—'}<br/>"
                    f"Comentarios: {_fmt_int(comments) if comments is not None else '—'}<br/>"
                    f"Suscriptores canal: {_fmt_int(suscript) if suscript is not None else '—'}"
                )    
            else:
                sup      = safe_float(p.get("ScoreOP_sup"))
                metricas = f"sup {sup:.2f}" if sup is not None else "—"

            rows.append([
                Paragraph(f"{impact*100:.2f}%", ST["table_cell_c"]),
                Paragraph(fecha_str,            ST["table_cell_c"]),
                Paragraph(f"{pct:.2f}%",         ST["table_cell_c"]),
                Paragraph(stance,                ST["table_cell_c"]),
                Paragraph(metricas,              ST["table_cell_c"]),
                Paragraph(limpiar_texto_pdf(content),    ST["table_cell_unicode"]),
            ])

        tbl = Table(
            rows,
            colWidths=[CW*0.1, CW*0.11, CW*0.10, CW*0.10, CW*0.22, CW*0.35],
            repeatRows=1,
            splitByRow=1,
        )
        tbl.setStyle(TableStyle(_TBLSTYLE_BASE + [
            ("ALIGN",         (0,1), (3,-1), "CENTER"),
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("GRID",          (0,0), (-1,-1), 0.35, colors.HexColor("#d9d9d9")),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT_BG]),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.3*cm))

    # Llamada con índice explícito — resuelve el bug idx_red
    for idx_red_num, red_name in enumerate([r for r in platform_order if r in top_by_red]):
        posts_red = top_by_red[red_name]
        _impact_table_red(posts_red[:5], red_name, idx_red_num)

    # ══════════════════════════════════════════════════════════════════════════
    # SECCIÓN 4 — TEMAS Y ANÁLISIS DE CONTENIDO
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("4. Temas detectados y análisis de contenido", ST["section_title"]))
    story.append(ColorBar(CW, height=2, color=C_ACCENT))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph(
        "El sistema emplea un modelo ajustado específicamente "
        "para el análisis automatizado de conversaciones digitales, permitiendo identificar la polaridad del argumento expresado en publicaciones y comentarios, " \
        "así como los principales argumentos asociados a cada polaridad. "
        "A cada contenido analizado se le asigna una categoría de postura y un tópico argumental representativo, entendido como el motivo principal "
        "que explica la posición expresada respecto al tema de estudio. De este modo, el análisis permite identificar no solo la orientación general de la "
        "conversación, sino también los argumentos más frecuentes que estructuran el debate público digital. "
        "Las señales obtenidas se integran posteriormente en el cálculo del indicador de posición de cada conversación analizada.",
        # "para la detección de postura y la extracción de tópicos argumentales restringidos, "
        # "bajo un esquema de normalización semántica y reutilización controlada de etiquetas. "
        # "A cada unidad de contenido analizada (publicaciones y comentarios) se le asigna una postura "
        # "y un tópico argumental único, que representa el motivo o ángulo semántico que fundamenta dicha postura respecto al tema de análisis. "
        # "El tópico no describe el tema general, sino la razón específica detrás del posicionamiento expresado. "
        # "Posteriormente, las señales de postura de las publicaciones y sus comentarios se agregan al cálculo del indicador_pct de la publicación original a la que pertenecen, "
        # "permitiendo modelar la dinámica de opinión de forma jerárquica (nivel comentario → nivel publicación).",
        ST["body"]
    ))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph(
        "<b>Cómo leer la tabla:</b> "
        "<i>Menciones</i> = número de publicaciones con ese tema. "
        "<i>Favorables</i> = publicaciones con indicador > 60%. "
        "<i>Neutros</i> = indicador 40-60%. "
        "<i>En contra</i> = indicador < 40%. ",
        ST["note"]
    ))
    story.append(Spacer(1, 0.2*cm))

    by_topic = defaultdict(lambda: defaultdict(int))
    for p in dashboard_data.get("raw_data", []):
        topic = p.get("topic")
        red   = p.get("plataforma")
        if topic and red:
            by_topic[topic][red] += 1

    if topics:
        top_topics  = sorted(topics, key=lambda t: t.get("volumen", 0), reverse=True)
        total_pubs  = sum(t.get("volumen", 0) for t in topics) or 1
        redes = sorted({p.get("plataforma", "—") for p in dashboard_data.get("raw_data", [])})

        topic_rows = [[
            Paragraph("<b>Tema</b>",        ST["table_header"]),
            Paragraph("<b>Menciones</b>",   ST["table_header"]),
            Paragraph("<b>% del total</b>", ST["table_header"]),
        ]]
        for red in redes:
            topic_rows[0].append(Paragraph(f"<b>{red.capitalize()}</b><br/><b>(%)</b>", ST["table_header"]))
        topic_rows[0].extend([
            Paragraph("<b>Motores positivos</b>", ST["table_header"]),
            Paragraph("<b>Motores neutrales / polarizados</b>",    ST["table_header"]),
            Paragraph("<b>Motores negativos</b>",  ST["table_header"]),
        ])

        for t in top_topics:
            topic = t.get("TOPIC", "—")
            vol   = t.get("volumen", 0) or 1
            pos   = t.get("pos", 0)
            neu   = t.get("neu", 0)
            neg   = t.get("neg", 0)

            row = [
                Paragraph(str(topic)[:38].capitalize(), ST["table_cell"]),
                Paragraph(f"{_fmt_int(vol)}",                   ST["table_cell_c"]),
                Paragraph(f"{vol/total_pubs*100:.2f}%", ST["table_cell_c"]),
            ]
            topic_dist = by_topic.get(topic, {})
            for red in redes:
                count = topic_dist.get(red, 0)
                pct   = (count / vol * 100) if vol else 0
                row.append(Paragraph(f"{pct:.1f}%", ST["table_cell_c"]))
            row.extend([
                Paragraph(f"{_fmt_int(pos)}", ST["table_cell_c"]),
                Paragraph(f"{_fmt_int(neu)}", ST["table_cell_c"]),
                Paragraph(f"{_fmt_int(neg)}", ST["table_cell_c"]),
            ])
            topic_rows.append(row)

        n_redes = max(1, len(redes))

        # Ancho mínimo por columna de plataforma para que "Telegram"/"Youtube"
        # quepan en una sola línea con fuente reducida (ver punto 2).
        plat_col_min = 1.6* cm
        plat_block_w = max(CW * 0.30, plat_col_min * n_redes)

        # Columnas fijas (Tema, Menciones, % del total, Motores +/Neutros/-)
        # se reducen proporcionalmente si el bloque de plataformas creció.
        fixed_w = CW - plat_block_w
        fixed_props = [0.20, 0.18, 0.16, 0.16, 0.16, 0.16]  # deben sumar 1.0
        tema_w, menc_w, pct_w, mpos_w, mneu_w, mneg_w = [fixed_w * p for p in fixed_props]

        topic_tbl = Table(
            topic_rows,
            colWidths=[
                tema_w,
                menc_w,
                pct_w,
                *([plat_block_w / n_redes] * n_redes),
                mpos_w,
                mneu_w,
                mneg_w,
            ],
        )

        topic_tbl.setStyle(TableStyle(_TBLSTYLE_BASE + [
            ("ALIGN", (1,0), (-1,-1), "CENTER"),
        ]))
        story.append(topic_tbl)
        story.append(Spacer(1, 0.4*cm))
    else:
        story.append(Paragraph("No se dispone de información sobre temas para este análisis.", ST["body"]))

    # VERSIÓN 2.0: Sección de nubes de palabras deshabilitada temporalmente
    # if nubes:
    #     story.append(Paragraph("4.1 Nubes de palabras", ST["subsection"]))
    #     story.append(Paragraph(
    #         "Las nubes de palabras representan visualmente los términos más frecuentes en cada plataforma. "
    #         "El <b>tamaño</b> de cada palabra es proporcional a su frecuencia de aparición en el corpus. "
    #         "El <b>color</b> refleja la posición media de las publicaciones que contienen ese término: "
    #         "verde = término asociado a posts favorables; rojo = término asociado a posts de rechazo; "
    #         "gris = término neutro o polarizado. "
    #         "Los términos de búsqueda utilizados para la recolección de datos se excluyen automáticamente. "
    #         "Cuando existen, se generan dos nubes por plataforma: una de los posts (voz de los autores) "
    #         "y otra de los comentarios (voz de la comunidad).",
    #         ST["body"]
    #     ))
    #     story.append(Spacer(1, 0.2*cm))

    #     plataformas = defaultdict(dict)
    #     for nombre, b64str in nubes.items():
    #         label = nombre.replace("nube_", "")
    #         if label.endswith("_posts"):
    #             plataformas[label.replace("_posts", "")]["posts"] = b64str
    #         elif label.endswith("_comentarios"):
    #             plataformas[label.replace("_comentarios", "")]["comentarios"] = b64str

    #     for red, imgs in plataformas.items():
    #         row_imgs = []
    #         row_caps = []

    #         posts_b64 = imgs.get("posts")
    #         if posts_b64:
    #             row_imgs.append(_b64_to_img(posts_b64, CW * 0.46))
    #         else:
    #             row_imgs.append(Spacer(1, 1))
    #         row_caps.append(Paragraph(f"{red.upper()} — Autores (posts)", ST["caption"]))

    #         com_b64 = imgs.get("comentarios")
    #         if com_b64:
    #             row_imgs.append(_b64_to_img(com_b64, CW * 0.46))
    #         else:
    #             row_imgs.append(Spacer(1, 1))
    #         row_caps.append(Paragraph(f"{red.upper()} — Comunidad (comentarios)", ST["caption"]))

    #         img_tbl = Table([row_imgs], colWidths=[CW*0.5, CW*0.5])
    #         img_tbl.setStyle(TableStyle([
    #             ("ALIGN",  (0,0), (-1,-1), "CENTER"),
    #             ("VALIGN", (0,0), (-1,-1), "TOP"),
    #         ]))
    #         story.append(img_tbl)

    #         cap_tbl = Table([row_caps], colWidths=[CW*0.5, CW*0.5])
    #         cap_tbl.setStyle(TableStyle([("ALIGN", (0,0), (-1,-1), "CENTER")]))
    #         story.append(cap_tbl)
    #         story.append(Spacer(1, 0.35*cm))
    # --- SECCIÓN 4.1: NUBE ---
    if nube_v2:
        story.append(Paragraph("4.1 Nube de términos", ST["subsection"]))
        story.append(Paragraph(
            "Esta nube organiza las palabras y frases según su capacidad de movilización. El <b>tamaño</b> "
            "indica el impacto real (alcance del autor más la reacción generada en comentarios). El <b>color</b> "
            "refleja el tono del argumento (verde para mensajes amables, rojo para mensajes críticos). La <b>opacidad</b> "
            "mide la coherencia: los términos más nítidos indican que el tono del mensaje coincide con la postura "
            "política del autor, mientras que los traslúcidos señalan usos irónicos, matizaciones o contradicciones.",
            ST["body"]
        ))
        story.append(Spacer(1, 0.2*cm))

        nube_img_bytes = _chart_nube_unificada_v2(nube_v2)
        if nube_img_bytes:
            story.append(_img_from_bytes(nube_img_bytes, CW * 0.95))
            story.append(Paragraph(
                f"Figura {FIG_NUM}. Nube unificada de palabras y bigramas, ponderada por impacto social acumulado.",
                ST["caption"]
            ))
            FIG_NUM += 1
        story.append(Spacer(1, 0.3*cm))

    # --- SECCIÓN 4.2: MAPA ---
    if grafo_v2 and grafo_v2.get("nodes"):
        story.append(Paragraph("4.2 Mapa de narrativas: temas y usuarios", ST["subsection"]))
        story.append(Paragraph(
            "Este mapa proyecta la red de temas y usuarios en un plano analítico de postura y coherencia. "
            "Los <b>círculos con borde sólido</b> representan los temas principales, mientras que los "
            "<b>círculos con borde punteado</b> representan a los usuarios. Ambos conservan un tamaño "
            "proporcional a su peso en la conversación. El eje horizontal sitúa a la izquierda las posturas "
            "críticas y a la derecha las de apoyo. El eje vertical indica la nitidez del discurso: los elementos "
            "en la parte superior son mensajes directos, mientras que los inferiores reflejan mayor ambigüedad "
            "o polarización interna.",
            ST["body"]
        ))
        story.append(Spacer(1, 0.2*cm))

        grafo_img_bytes = _chart_mapa_narrativas_v2(grafo_v2)
        if grafo_img_bytes:
            story.append(_img_from_bytes(grafo_img_bytes, CW * 0.95))
            story.append(Paragraph(
                f"Figura {FIG_NUM}. Mapa de narrativas: temas (círculos) y usuarios (puntos), "
                "posicionados por postura y coherencia interna.",
                ST["caption"]
            ))
            FIG_NUM += 1
        story.append(Spacer(1, 0.2*cm))

    # ══════════════════════════════════════════════════════════════════════════
    # SECCIÓN 5 — INDICADOR DE ACEPTACIÓN (PillarOP)
    # ══════════════════════════════════════════════════════════════════════════
    if aceptacion_data and isinstance(aceptacion_data, dict):
        global_acp  = aceptacion_data.get("global", {})
        por_red_acp = aceptacion_data.get("por_red", {})
        interp      = aceptacion_data.get("interpretacion", "")

        if global_acp:
            story.append(PageBreak())
            story.append(Paragraph(
                "5. Indicador de aceptación social de medidas o políticas públicas",
                ST["section_title"]
            ))
            story.append(ColorBar(CW, height=2, color=C_ACCENT))
            story.append(Spacer(1, 0.3*cm))

            story.append(Paragraph("5.1 Metodología: modelo de aceptación social", ST["subsection"]))
            story.append(Paragraph(
                "El modelo de aceptación social de medidas o políticas públicas extiende la lógica del indicador de polaridad ponderada por esfuerzo social, y alcance (ECHO) hacia "
                "un análisis multidimensional de la opinión. "
                "Para ello, el sistema identifica y clasifica opiniones expresadas en publicaciones y comentarios a partir de cuatro dimensiones complementarias:  "
                "<b>legitimación sociopolítica</b>, <b>efectividad percibida</b>, <b>justicia y equidad percibida</b> y "
                "<b>confianza y legitimidad institucional</b>. ",
                ST["body"]
            ))
            story.append(Spacer(1, 0.2*cm))

            pilar_def_data = [
                [Paragraph("<b>Pilar</b>", ST["table_header"]),
                 Paragraph("<b>Que evalúa</b>", ST["table_header"]),
                 Paragraph("<b>Ejemplo de interpretacion favorable</b>", ST["table_header"])],
                [Paragraph("Legitimación sociopolítica", ST["table_cell"]),
                 Paragraph("Evalúa si la medida se percibe como legítima, válida, legal o socialmente aceptable. "
                            "Incluye percepciones relacionadas con conformidad normativa, ajuste a la ley, razonabilidad "
                            "o derecho de las instituciones a aplicar la medida.", ST["table_cell"]),
                 Paragraph("\"La medida está justificada y tiene base legal suficiente.\"", ST["table_cell"])],
                [Paragraph("Efectividad percibida", ST["table_cell"]),
                 Paragraph("Evalúa cómo se percibe la utilidad y capacidad real de la medida para "
                            "resolver el problema que pretende abordar. Analiza expectativas de funcionamiento, "
                            "impacto o resultados observables.", ST["table_cell"]),
                 Paragraph("\"Las restricciones han reducido claramente los accidentes y mejorado la movilidad.\"", ST["table_cell"])],
                [Paragraph("Justicia y equidad percibida", ST["table_cell"]),
                 Paragraph("Evalúa cómo se percibe la distribución de beneficios, costes o perjuicios entre grupos "
                            "sociales. Incorpora opiniones vinculadas con desigualdad, discriminación, trato injusto "
                            "o reparto equilibrado del impacto de la medida.", ST["table_cell"]),
                 Paragraph("\"La medida afecta por igual a todos los sectores y no perjudica a ningún colectivo.\"", ST["table_cell"])],
                [Paragraph("Confianza  y legitimidad institucional", ST["table_cell"]),
                 Paragraph("Evalúa el nivel de confianza depositado en los actores responsables de implementar la medida "
                            "(gobiernos, administraciones, organismos o responsables políticos). Incluye percepciones "
                            "de competencia, transparencia, honestidad o intereses ocultos.", ST["table_cell"]),
                 Paragraph("\"Las instituciones están gestionando el programa de forma transparente y responsable.\"", ST["table_cell"])],
            ]
            pilar_def_tbl = Table(pilar_def_data, colWidths=[CW*0.18, CW*0.40, CW*0.40])
            pilar_def_tbl.setStyle(TableStyle(_TBLSTYLE_BASE))
            story.append(pilar_def_tbl)
            story.append(Spacer(1, 0.2*cm))

            story.append(Paragraph("5.2 Proceso de cálculo de los indicadores", ST["subsection"]))
            story.append(Paragraph(
                "Cada publicación original o comentario se analiza de forma individual y recibe una clasificación específica para cada una de las dimensiones evaluadas: "
                "favorable (1), neutra (0), en contra (-1) o sin evidencia interpretable (2). "
                "El sistema excluye automáticamente contenido ajeno al objeto de estudio. "
                #"El sistema aplica previamente un filtro de exclusión semántica y geográfica para eliminar ruido, spam, textos puramente informativos o contenido ajeno al objeto de análisis. "
                # "Posteriormente, el LLM identifica juicios explícitos e implícitos asociados a cada dimensión, incluyendo evaluaciones sobre legalidad, eficacia, impacto social o confianza en actores institucionales. "
                # "Los valores marcados como <i>sin relación</i> (2) se excluyen del cálculo del pilar correspondiente, de modo que cada indicador refleja únicamente opiniones donde existe evidencia semántica suficiente sobre esa dimensión concreta. "
                # "Finalmente, las clasificaciones obtenidas para publicaciones y comentarios se agregan jerárquicamente mediante el mismo esquema matemático utilizado para la construcción del indicador de posición, permitiendo la estimación de métricas de aceptación social en distintos niveles de agregación (publicación, red social y global), tanto a nivel de pilar como en forma de síntesis general.",
                "Posteriormente, las señales obtenidas de publicaciones y comentarios se integran en el cálculo de los distintos indicadores " \
                "de aceptación social, permitiendo analizar tanto la posición expresada en cada conversación como las reacciones generadas dentro de la comunidad digital.",
                ST["body"]
            ))
            story.append(Spacer(1, 0.3*cm))

            story.append(Paragraph("5.3 Niveles de agregación del modelo de aceptación social", ST["subsection"]))
            story.append(Paragraph(
                # "El modelo opera mediante una estructura jerárquica de agregación que permite "
                # "analizar la aceptación social desde distintos niveles de granularidad. "
                # "En el nivel más desagregado, cada publicación y su hilo de comentarios generan indicadores post × pilar, donde se estima la postura respecto a cada una de las cuatro dimensiones analíticas. "
                # "Paralelamente, cada hilo puede sintetizarse en un indicador post global, que refleja la aceptación general del contenido sin descomposición por dimensión. "
                # "En un nivel intermedio, los resultados se agregan por red social, produciendo indicadores red × pilar (comparación de plataformas en cada dimensión) y red global (síntesis global de cada plataforma). "
                # "En el nivel agregado superior, se construyen indicadores global × pilar, que reflejan el consenso multidimensional entre todas las redes sociales analizadas. "
                # "Finalmente, el sistema calcula un índice global de aceptación social, obtenido mediante la agregación ponderada de todos los pilares y redes sociales, utilizando como peso el volumen de publicaciones y comentarios con posición activa.",
                "El modelo permite analizar la aceptación social en distintos niveles de lectura. "
                "En primer lugar, se evalúa cada publicación y su conversación asociada para identificar cómo se posiciona respecto a cada una de las dimensiones analizadas. "
                "Posteriormente, los resultados se consolidan por plataforma, permitiendo comparar tendencias entre redes sociales y observar diferencias en los patrones de conversación. "
                "Finalmente, el sistema construye indicadores agregados que sintetizan la percepción general observada en el conjunto de plataformas analizadas.",
                ST["body"]
            ))
            story.append(Spacer(1, 0.3*cm))

            story.append(Paragraph("5.4 Interpretación de la escala", ST["subsection"]))
            story.append(Paragraph(
                "<b>Escala de interpretación de los indicadores:</b>  "
                "&gt;60% = aceptación neta ·  40-60% = neutralidad / polarización ·  "
                "&lt;40% = rechazo neto. "
                "El valor de 50% representa neutralidad perfecta, es decir, equilibrio estructural entre apoyo y rechazo dentro del pilar analizado. "
                "Cada indicador de pilar se calcula aplicando la misma arquitectura matemática del indicador de posición ponderada, "
                # "pero sustituyendo la posición general del contenido por la posición específica respecto a cada dimensión de aceptación pública "
                "adaptada a cada una de las dimensiones de aceptación pública evaluadas "
                "(legitimación, efectividad, justicia y confianza institucional). "
                # "El cálculo se realiza a nivel de hilo de publicación (post + comentarios), combinando un 40% del posicionamiento de la publicación original "
                # "y un 60% de la respuesta agregada de la comunidad. "
                # "Las publicaciones y comentarios clasificados como '2' (sin relación con el pilar) se excluyen completamente del cálculo, "
                # "de modo que cada indicador refleja únicamente opiniones explícitas sobre ese eje concreto. "
                # "El resultado final se normaliza en una escala continua de 0% a 100%, donde "
                # "0% representa oposición máxima o alineación predominantemente desfavorable respecto al pilar analizado; "
                # "50% representa neutralidad estructural o equilibrio entre posiciones favorables y desfavorables; "
                # "y 100% representa aceptación máxima o alineación predominantemente favorable. "
                # "Los valores intermedios reflejan distintos grados de apoyo, rechazo o polarización en la conversación analizada. "
                # "El indicador global de aceptación se obtiene mediante agregación ponderada de los cuatro pilares y de cada red social, "
                # "utilizando como peso el volumen de publicaciones y comentarios con posición activa.", integrando tanto la postura de la publicación original 
                "El cálculo se realiza a nivel de hilo conversacional, integrando tanto la postura de la publicación original "
                "como la respuesta agregada de la comunidad, con el objetivo de estimar la orientación predominante del debate en cada dimensión. "
                "Las unidades de contenido sin evidencia semántica suficiente sobre un pilar concreto se excluyen del cálculo de dicha dimensión, "
                "de modo que cada indicador refleja únicamente opiniones explícitamente vinculadas al eje analizado. "
                "El resultado final se expresa en una escala continua de 0% a 100%, donde los valores extremos representan escenarios de alineación "
                "predominantemente favorable o desfavorable, y los valores intermedios reflejan distintos grados de aceptación, rechazo o polarización social. "
                "El indicador global de aceptación se obtiene mediante la agregación ponderada de los distintos pilares y plataformas analizadas, "
                "considerando el volumen relativo de publicaciones e interacciones asociadas a cada dimensión.",
                ST["body"]
            ))
            story.append(Spacer(1, 0.3*cm))

            story.append(Paragraph("5.5 Desglose por pilar y plataforma", ST["subsection"]))
            pct_medio    = global_acp.get("PillarOP_pct_medio", 50)
            interp_color = C_VERY_POS if pct_medio >= 60 else (C_TEXT_MID if pct_medio >= 40 else C_VERY_NEG)
            story.append(Paragraph(
                "La tabla presenta una estructura matricial de doble entrada en la que las filas representan los distintos pilares "
                "evaluados mientras que las columnas representan las redes sociales analizadas, "
                "incorporando además una columna y una fila de agregación global. "
                # "Cada celda contiene el indicador red × pilar, calculado como la posición ponderada media de las publicaciones "
                # "con postura explícita en ese pilar dentro de cada plataforma, junto con el número de menciones asociadas."
                "Cada celda muestra el nivel relativo de aceptación asociado a un pilar específico dentro de una plataforma concreta, "
                "junto con el volumen de menciones consideradas en el cálculo. "
                "La columna 'Resultado global' sintetiza el comportamiento agregado del conjunto de plataformas para cada dimensión, "#refleja la agregación transversal de todas las plataformas para cada pilar, ponderada por el volumen de menciones con posición activa, mientras que la fila 'Aceptación total' "
                # "resume la media de los cuatro pilares por plataforma. "
                # "Las celdas en verde indican aceptación neta; en rojo, rechazo; en gris, neutralidad.",
                "ponderando los resultados según el volumen de publicaciones e interacciones con posicionamiento activo. "
                "Por su parte, la fila de 'Aceptación total' resume la tendencia general observada en cada plataforma a partir de la agregación de los distintos pilares analizados. "
                "La codificación cromática facilita la interpretación visual de los resultados: los tonos verdes indican niveles relativamente altos de aceptación, "
                "los tonos rojos reflejan predominio de rechazo y los tonos neutros representan situaciones de equilibrio o polarización.",
                ST["body"]
            ))
            story.append(Spacer(1, 0.15*cm))

            PILARES  = ["legitimacion", "efectividad", "justicia_equidad", "confianza_institucional"]
            LABELS_P = ["Legitimación sociopolítica", "Efectividad percibida", "Justicia y equidad percibida", "Confianza y legitimidad institucional"]
            redes    = platform_order #list(por_red_acp.keys())

            header_row = [Paragraph("<b>Pilar</b>", ST["table_header"])]
            for red in redes:
                header_row.append(Paragraph(f"<b>{red.capitalize()}</b>", ST["table_header"]))
            header_row.append(Paragraph("<b>Global</b>", ST["table_header"]))

            pillar_rows_tbl = [header_row]
            for p, lbl in zip(PILARES, LABELS_P):
                row = [Paragraph(f"<b>{lbl}</b>", ST["table_cell"])]
                for red in redes:
                    rd  = por_red_acp.get(red, {})
                    val = rd.get(f"PillarOP_pct_{p}", 50)
                    men = rd.get(f"menciones_{p}", 0)
                    row.append(Paragraph(f"{val:.2f}%\n({men} men.)", ST["table_cell_c"]))
                g_val = global_acp.get(f"PillarOP_pct_{p}", 50)
                g_men = global_acp.get(f"menciones_{p}", 0)
                row.append(Paragraph(f"<b>{g_val:.2f}%</b>\n({g_men} men.)", ST["table_cell_c"]))
                pillar_rows_tbl.append(row)

            total_row = [Paragraph("<b>Aceptacion total</b>", ST["table_cell"])]
            for red in redes:
                rd   = por_red_acp.get(red, {})
                rm   = rd.get("PillarOP_pct_medio", 50)
                rmen = rd.get("total_menciones", 0)
                total_row.append(Paragraph(f"<b>{rm:.2f}%</b>\n({rmen} men.)", ST["table_cell_c"]))
            g_pm = global_acp.get("PillarOP_pct_medio", pct_medio)
            g_tm = global_acp.get("total_menciones", 0)
            total_row.append(Paragraph(f"<b>{g_pm:.2f}%</b>\n({g_tm} men.)", ST["table_cell_c"]))
            pillar_rows_tbl.append(total_row)

            n_cols = 1 + len(redes) + 1
            col_w  = CW / n_cols
            col_widths_pillar = [CW * 0.26] + [col_w * 0.74] * (n_cols - 1)

            pillar_tbl = Table(pillar_rows_tbl, colWidths=col_widths_pillar)
            tbl_style_pillar = list(_TBLSTYLE_BASE)
            tbl_style_pillar += [
                ("BACKGROUND", (0, len(PILARES)+1), (-1, len(PILARES)+1), colors.HexColor("#E8F0FE")),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ]
            for row_i, p in enumerate(PILARES, start=1):
                for col_i, red in enumerate(redes, start=1):
                    rd_val  = por_red_acp.get(red, {}).get(f"PillarOP_pct_{p}", 50)
                    cell_bg = (colors.HexColor("#e8f5e9") if rd_val >= 57
                               else colors.HexColor("#ffebee") if rd_val < 43
                               else colors.HexColor("#f5f5f5"))
                    tbl_style_pillar.append(("BACKGROUND", (col_i, row_i), (col_i, row_i), cell_bg))
                g_v = global_acp.get(f"PillarOP_pct_{p}", 50)
                cell_bg_g = (colors.HexColor("#e8f5e9") if g_v >= 57
                             else colors.HexColor("#ffebee") if g_v < 43
                             else colors.HexColor("#f5f5f5"))
                tbl_style_pillar.append(("BACKGROUND", (-1, row_i), (-1, row_i), cell_bg_g))
            pillar_tbl.setStyle(TableStyle(tbl_style_pillar))
            story.append(pillar_tbl)
            story.append(Spacer(1, 0.3*cm))

            story.append(Paragraph("5.6 Resultado global", ST["subsection"]))
            pct_medio    = global_acp.get("PillarOP_pct_medio", 50)
            interp_color = C_VERY_POS if pct_medio >= 57 else (C_TEXT_MID if pct_medio >= 43 else C_VERY_NEG)
            pct_box = KpiBox(
                f"{pct_medio:.2f}%", "Aceptación global",
                CW * 0.38, height=2.8*cm,
                color=colors.HexColor("#e8f5e9") if pct_medio >= 50 else colors.HexColor("#ffebee"),
                text_color=interp_color,
                accent_color=interp_color,
            )
            interp_par = Paragraph(interp or "—", ST["interpretation"])
            combo_kpi = Table([[pct_box], [interp_par]], colWidths=[CW*0.40])
            combo_kpi.setStyle(TableStyle([
                ("VALIGN",      (0,0), (-1,-1), "TOP"),
                ("TOPPADDING",  (0,0), (-1,0),  6),
                ("TOPPADDING",  (0,1), (-1,1),  2),
            ]))
            story.append(combo_kpi)
            story.append(Spacer(1, 0.4*cm))

            story.append(Paragraph("5.7 Distribución de posiciones por pilar", ST["subsection"]))
            story.append(Paragraph(
                "La siguiente tabla muestra, para cada pilar, cuántas publicaciones tomaron posición "
                "a favor, de forma neutra o en contra. Solo se contabilizan publicaciones que mencionan "
                "explícitamente ese pilar (publicaciones con valor 2 = sin relación se excluyen).",
                ST["body"]
            ))
            story.append(Spacer(1, 0.15*cm))

            dist_pilar_data = [
                [Paragraph("<b>Pilar</b>",          ST["table_header"]),
                 Paragraph("<b>A favor</b>",         ST["table_header"]),
                 Paragraph("<b>Neutro</b>",          ST["table_header"]),
                 Paragraph("<b>En contra</b>",       ST["table_header"]),
                 Paragraph("<b>Total menciones</b>", ST["table_header"]),
                 Paragraph("<b>Indicador</b>",       ST["table_header"])],
            ]
            for p, lbl in zip(PILARES, LABELS_P):
                pos  = global_acp.get(f"pos_{p}", 0)
                neu  = global_acp.get(f"neu_{p}", 0)
                neg  = global_acp.get(f"neg_{p}", 0)
                men  = global_acp.get(f"menciones_{p}", 0)
                pv   = global_acp.get(f"PillarOP_pct_{p}", 50)
                total_men = pos + neu + neg or 1
                dist_pilar_data.append([
                    Paragraph(lbl,                                    ST["table_cell"]),
                    Paragraph(f"{pos} ({pos/total_men*100:.0f}%)",   ST["table_cell_c"]),
                    Paragraph(f"{neu} ({neu/total_men*100:.0f}%)",   ST["table_cell_c"]),
                    Paragraph(f"{neg} ({neg/total_men*100:.0f}%)",   ST["table_cell_c"]),
                    Paragraph(str(men),                               ST["table_cell_c"]),
                    Paragraph(f"<b>{pv:.2f}%</b>",                  ST["table_cell_c"]),
                ])
            dist_pilar_tbl = Table(
                dist_pilar_data,
                colWidths=[CW*0.28, CW*0.14, CW*0.14, CW*0.14, CW*0.15, CW*0.15]
            )
            dist_pilar_tbl.setStyle(TableStyle(_TBLSTYLE_BASE + [
                ("ALIGN", (1,0), (-1,-1), "CENTER"),
            ]))
            story.append(dist_pilar_tbl)

    # ══════════════════════════════════════════════════════════════════════════
    # SECCIÓN 6 — MOTORES DE APOYO Y RECHAZO POR PILAR
    # ══════════════════════════════════════════════════════════════════════════
    motores_data = _calcular_motores_desde_pilares(analysis_meta, top_n=5)

    if motores_data:

        story.append(PageBreak())
        story.append(Paragraph(
            "6. Motores de apoyo y rechazo por pilar y plataforma",
            ST["section_title"]
        ))
        story.append(ColorBar(CW, height=2, color=C_ACCENT))
        story.append(Spacer(1, 0.3 * cm))

        story.append(Paragraph(
            "Esta sección identifica los contenidos que ejercen mayor tracción "
            "sobre cada dimensión de aceptación social analizada. "
            "Se consideran <b>motores de apoyo</b> aquellos hilos de conversación (publicación original y comentarios asociados) "
            "cuya contribución agregada al indicador del pilar es favorable, "
            "es decir, aquellos en los que tanto el posicionamiento inicial como la respuesta de la comunidad tienden a reforzar " \
            "la aceptación de la medida o política pública. Por el contrario, los <b>motores de rechazo</b> corresponden a hilos cuya " \
            "contribución agregada desplaza el indicador en sentido desfavorable, reflejando dinámicas de oposición o cuestionamiento dentro de la conversación digital.",
            # "del autor y la respuesta de la comunidad empujan el pilar en sentido favorable. "
            # "Un <b>motor de rechazo</b> es el caso contrario: la suma ponderada 40/60 resulta "
            # "negativa, indicando que ese hilo arrastra el indicador hacia el rechazo.",
            ST["body"]
        ))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph(
            "<b>Cómo se calcula el indicador de cada motor:</b>  "
            # "indicador = 0.4 × (posición_post × I_eff_post) + 0.6 × Σ(posición_com × I_com). "
            # "Un valor positivo indica apoyo neto al pilar; un valor negativo indica rechazo neto. "
            # "El valor absoluto refleja la magnitud: a mayor |score|, mayor capacidad "
            # "de ese hilo para mover el indicador global del pilar.",
            "cada hilo de conversación genera una contribución específica al indicador del pilar analizado, "
            "combinando el posicionamiento de la publicación original y la respuesta agregada de la comunidad. "
            "El modelo asigna un 40% del peso al contenido inicial y un 60% a los comentarios asociados, "
            "integrando además factores de interacción, alcance y esfuerzo social. "
            "Los valores positivos reflejan dinámicas de apoyo o legitimación del pilar, mientras que los valores negativos "
            "indican dinámicas de rechazo o cuestionamiento. "
            "La magnitud absoluta del indicador representa la capacidad relativa de ese hilo para influir en el resultado global "
            "del pilar dentro de la conversación analizada.",
            ST["note"]
        ))
        story.append(Spacer(1, 0.3 * cm))

        PILAR_LABELS = {
            "legitimacion":            "Legitimación sociopolítica",
            "efectividad":             "Efectividad percibida",
            "justicia_equidad":        "Justicia y equidad percibida",
            "confianza_institucional": "Confianza y legitimidad institucional",
        }
        PILARES_ORDER = [
            "legitimacion", "efectividad",
            "justicia_equidad", "confianza_institucional",
        ]

        # ── Tabla de motores: 5 columnas alineadas con sección 3.8 ──────────
        # Columnas: Impacto pilar | Posición | Fecha | Métricas del post | Extracto
        def _motores_table(motores, es_apoyo):
            if not motores:
                return None
            hdr_color = colors.HexColor("#1b5e20") if es_apoyo else colors.HexColor("#b71c1c")

            rows = [[
                Paragraph("<b>Impacto pilar</b>",    ST["table_header"]),
                Paragraph("<b>Posición</b>",          ST["table_header"]),
                Paragraph("<b>Fecha</b>",             ST["table_header"]),
                Paragraph("<b>Métricas del post</b>", ST["table_header"]),
                Paragraph("<b>Extracto del contenido</b>", ST["table_header"]),
            ]]

            stance_map = {1: "Favorable", 0: "Neutra", -1: "En contra"}

            for m in motores:
                score     = m.get("score_pct", 0)
                stance    = stance_map.get(m.get("stance_post"), "—")
                fecha_raw = str(m.get("fecha", ""))
                fecha_str = _fmt_date(fecha_raw) if fecha_raw not in ("", "—", "nan") else "—"
                comms     = m.get("comentarios", 0)

                # Métricas unificadas igual que en 3.8
                plat = str(m.get("plataforma", "")).lower()
                lk   = m.get("likes", 0)
                ev   = m.get("extra_val", 0)
                if "youtube" in plat:
                    metricas = (
                        f"Vistas: {_fmt_int(lk)}<br/>"
                        f"Suscriptores: {_fmt_int(ev)}<br/>"
                        f"Comentarios: {_fmt_int(comms)}"
                    )
                elif "bluesky" in plat:
                    metricas = (
                        f"Likes: {_fmt_int(lk)}<br/>"
                        f"Seguidores: {_fmt_int(ev)}<br/>"
                        f"Comentarios: {_fmt_int(comms)}"
                    )
                elif "telegram" in plat:
                    canal_val = m.get("canal_val", 0)
                    metricas = (
                        f"Vistas: {_fmt_int(lk)}<br/>"
                        f"Reacciones: {_fmt_int(ev)}<br/>"
                        f"Comentarios: {_fmt_int(comms)}<br/>"
                        f"Suscriptores canal: {_fmt_int(canal_val)}"
                    )    
                else:  # reddit
                    metricas = f"Comentarios: {_fmt_int(comms)}" if comms else "—"
                score_str = f"{score:.2f}%"
                # contenido = str(m.get("contenido", "")).replace("\n", " ").strip() #textwrap.shorten(str(m.get("contenido", "")), width=120, placeholder="…")
                contenido = limpiar_texto_pdf(str(m.get("contenido", "") or ""))
                contenido = textwrap.shorten(contenido, width=400, placeholder="…")
                rows.append([
                    Paragraph(f"<b>{score_str}</b>" if es_apoyo else score_str, ST["table_cell_c"]),
                    Paragraph(stance,    ST["table_cell_c"]),
                    Paragraph(fecha_str, ST["table_cell_c"]),
                    Paragraph(metricas,  ST["table_cell_c"]),
                    Paragraph(limpiar_texto_pdf(contenido),    ST["table_cell_unicode"]),
                ])

            # 5 columnas, anchos alineados con _impact_table_red de la sección 3.8
            tbl = Table(
                rows,
                colWidths=[CW*0.12, CW*0.12, CW*0.10, CW*0.22, CW*0.44],
                repeatRows=1,
            )
            tbl.setStyle(TableStyle(_TBLSTYLE_BASE + [
                ("BACKGROUND",    (0, 0), (-1, 0),  hdr_color),
                ("ALIGN",         (0, 1), (3, -1),  "CENTER"),
                ("FONTNAME",      (0, 1), (0, -1),  "Helvetica-Bold"),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("GRID",          (0, 0), (-1, -1), 0.35, colors.HexColor("#d9d9d9")),
            ]))
            return tbl

        redes_ordenadas = sorted(motores_data.keys())

        for idx_red, red in enumerate(redes_ordenadas):
            datos_red = motores_data.get(red, {})
            if not datos_red:
                continue

            story.append(Spacer(1, 0.2 * cm))
            story.append(Paragraph(
                f"6.{idx_red + 1} Plataforma: {red.capitalize()}",
                ST["subsection"]
            ))
            story.append(ColorBar(CW * 0.25, height=2,
                                  color=colors.HexColor(_plat_color(red))))
            story.append(Spacer(1, 0.15 * cm))

            hay_datos_red = False

            for pilar in PILARES_ORDER:
                datos_pilar = datos_red.get(pilar, {})
                apoyo   = datos_pilar.get("motores_apoyo",   [])
                rechazo = datos_pilar.get("motores_rechazo", [])
                if not apoyo and not rechazo:
                    continue

                hay_datos_red = True

                story.append(Paragraph(
                    f"<b>{PILAR_LABELS.get(pilar, pilar)}</b>",
                    ST["body_left"]
                ))
                story.append(Spacer(1, 0.06 * cm))

                if apoyo:
                    story.append(Paragraph(
                        f"Motores de apoyo — {len(apoyo)} publicaciones con mayor tracción positiva",
                        ParagraphStyle("_ms_apoyo", fontName="Helvetica-Bold", fontSize=8,
                                       textColor=colors.HexColor("#1b5e20"),
                                       spaceBefore=3, spaceAfter=2, leading=10)
                    ))
                    t = _motores_table(apoyo, es_apoyo=True)
                    if t:
                        story.append(t)
                    story.append(Spacer(1, 0.12 * cm))

                if rechazo:
                    story.append(Paragraph(
                        f"Motores de rechazo — {len(rechazo)} publicaciones con mayor tracción negativa",
                        ParagraphStyle("_ms_rechazo", fontName="Helvetica-Bold", fontSize=8,
                                       textColor=colors.HexColor("#b71c1c"),
                                       spaceBefore=3, spaceAfter=2, leading=10)
                    ))
                    t = _motores_table(rechazo, es_apoyo=False)
                    if t:
                        story.append(t)
                    story.append(Spacer(1, 0.18 * cm))

            if not hay_datos_red:
                story.append(Paragraph(
                    "No se identificaron motores significativos para esta plataforma.",
                    ST["body"]
                ))

        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            "Nota: se muestran hasta 5 motores de apoyo y 5 de rechazo por pilar y plataforma. "
            "Un mismo hilo puede ser motor positivo en un pilar y negativo en otro "
            "si la comunidad responde de forma diferente a cada dimensión de aceptación.",
            ST["note"]
        ))

    # ══════════════════════════════════════════════════════════════════════════
    # SECCIÓN FINAL — FICHA TÉCNICA Y METODOLOGÍA
    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("Anexo: ficha técnica y metodología", ST["section_title"]))
    story.append(ColorBar(CW, height=2, color=C_ACCENT))
    story.append(Spacer(1, 0.3*cm))

    ficha = [
        ["Parámetro",            "Valor"],
        ["Proyecto",             project_name],
        ["Tema analizado",       tema],
        ["Periodo de búsqueda",  f"{start_date} — {end_date}"],
        ["Fecha del informe",    created_str],
        ["Fuentes de datos",     ", ".join([f.capitalize() for f in fuentes]) or "—"],
        ["Idiomas analizados",   ", ".join(idiomas) or "—"],
        ["Términos de búsqueda", kw_str],#[:250] + ("…" if len(kw_str) > 250 else "")],
        ["Analista",             username],
        # ["Motor de análisis",    "—"],
    ]
    ficha_data = [
        [
            Paragraph(f"<b>{row[0]}</b>" if i == 0 else row[0],
                      ST["table_header"] if i == 0 else ST["table_cell"]),
            Paragraph(f"<b>{row[1]}</b>" if i == 0 else row[1],
                      ST["table_header"] if i == 0 else ST["table_cell"]),
        ]
        for i, row in enumerate(ficha)
    ]
    ficha_tbl = Table(ficha_data, colWidths=[CW*0.35, CW*0.65])
    ficha_tbl.setStyle(TableStyle(_TBLSTYLE_BASE + [
        ("BACKGROUND", (0,0), (-1,0),  C_SECONDARY),
        ("FONTNAME",   (0,1), (0,-1),  "Helvetica-Bold"),
    ]))
    story.append(ficha_tbl)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("Nota metodológica", ST["subsection"]))
    story.append(Paragraph(
        "Este informe ha sido generado automáticamente por el <b>Sistema de análisis de opinión en redes sociales</b> "
        "basado en los modelos de indicador de polaridad y de aceptación ponderados por esfuerzo y alcance, " \
        "El sistema ha sido desarrollado en el marco de iniciativas de investigación orientadas al análisis de " \
        "conversación pública y dinámicas de aceptación social en entornos digitales. "
        # "desarrollados en el marco del proyecto <b>DS4M Mediterráneo – Data Space for Mobility</b>, "
        # "iniciativa liderada por el <b>INTRAS – Universitat de València</b>, con la colaboración del <b>IRTIC</b> y el apoyo de <b>ITS España</b>, financiada por el <b>Ministerio para la Transformación Digital y de la Función Pública</b> y la <b>Unión Europea – Next Generation EU</b>. "
        "El análisis de polaridad y la asignación temática se realizan mediante modelos de lenguaje de gran tamaño (LLM) "
        "ejecutados sobre infraestructura <b>vLLM</b>. "
        "La adquisición de datos se realiza exclusivamente sobre contenido público disponible en plataformas digitales, "
        "mediante interfaces oficiales de programación (API) y protocolos autorizados de acceso interoperable "
        "proporcionados por YouTube, Reddit y Bluesky. "
        "Los resultados deben interpretarse en función del contexto temporal, las plataformas analizadas y el volumen de información disponible en cada caso. La representatividad de los indicadores depende de la diversidad, cobertura y nivel de participación existente en las publicaciones recopiladas, por lo que los resultados no constituyen encuestas demoscópicas ni mediciones estadísticas representativas de la población general. "
        "Las métricas se expresan en una escala normalizada de 0% a 100%, donde el 50% representa una situación de neutralidad o equilibrio estructural entre polaridades positivas y negativas; los valores superiores indican una mayor alineación positiva y los inferiores una mayor presencia de negatividad en la conversación analizada. "
        "Los resultados, interpretaciones y métricas generadas tienen carácter exclusivamente analítico e informativo. Los responsables del sistema no se hacen responsables de las decisiones, conclusiones o actuaciones adoptadas por terceros a partir de la utilización, interpretación o extrapolación de los resultados contenidos en este informe.",
        ST["body"]
    ))

    # ── Build ────────────────────────────────────────────────────────────────
    doc.build(story)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS DE INTERPRETACIÓN
# ─────────────────────────────────────────────────────────────────────────────

def _interp_scoreop(pct: float) -> str:
    if pct > 80:
        return "Existe un amplio consenso positivo hacia la medida o el tema analizado."
    if pct > 60:
        return "Predomina el apoyo, aunque existe debate visible. La tracción positiva supera claramente a la negativa."
    if pct > 40:
        return ("Las posiciones favorables y desfavorables se compensan o coexisten de forma equilibrada, "
                "indicando un entorno de polarización o neutralidad estructural.")
    if pct == 40 or pct == 50 or pct == 60:
        return "Zona de transición: equilibrio entre apoyo y rechazo con baja dominancia clara."
    if pct > 20:
        return "Predomina el rechazo o la crítica hacia la medida o el tema analizado."
    return "Existe un fuerte rechazo activo en la conversación analizada."

# ────────────────────────────────────────────────────────────────────────────
# OTRAS FUNCIONES AUXILIARES
# ────────────────────────────────────────────────────────────────────────────  
def _fmt_int(n):
    try:
        v = float(n)

        if np.isnan(v) or np.isinf(v):
            return "0"

        return f"{int(v):,}".replace(",", " ")

    except Exception:
        return "0"