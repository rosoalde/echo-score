"""
telegram_scraper_with_filter.py
Filtra el archivo YA DESCARGADO por telegram_raw_downloader.py según las
keywords/fechas/geo de UN proyecto concreto, aplica el mismo portero LLM
que usan Bluesky/Reddit/YouTube, y escribe telegram_global_dataset.csv
en el output_folder del proyecto — mismo esquema que los demás scrapers.

A diferencia de los otros scrapers, este NO llama a la API de Telegram:
lee de home/romina/Datos_APIs_RRSS/Datos_telegram/telegram/raw, que se mantiene
actualizado por el downloader + scheduler de forma independiente.
"""

import csv
import json
import sys
from pathlib import Path
from datetime import datetime, date
from openai import OpenAI
import requests
import asyncio

ROOT_PATH = Path(__file__).resolve().parents[2]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from clean_project.scrapers.canales import CANALES_DEFAULT
from clean_project.vllm.model_config import MODELO_ACTIVO

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN — mismo origen de datos que telegram_raw_downloader.py
# ═══════════════════════════════════════════════════════════════

import os
TELEGRAM_RAW_ROOT = Path(os.environ.get("TELEGRAM_RAW_ROOT", "/home/romina/Datos_APIs_RRSS/Datos_telegram/telegram/raw"))

print(f"🔎 TELEGRAM_RAW_ROOT = {TELEGRAM_RAW_ROOT}")
print(f"🔎 ¿Existe la ruta? {TELEGRAM_RAW_ROOT.exists()}")
if TELEGRAM_RAW_ROOT.exists():
    print(f"🔎 Contenido: {list(TELEGRAM_RAW_ROOT.iterdir())[:10]}")
else:
    print("🔎 Directorio padre /home/romina existe?:", Path('/home/romina').exists())


print(MODELO_ACTIVO)

client =  OpenAI(base_url="http://host.docker.internal:8001/v1", api_key="local-token")

# Numéro de llamadas al portero que viajan en simultáneo. vLLM las agrupa
# internamente — subir esto es lo que de verdad acelera el análisis,
# no el acceso a los datos locales.
CONCURRENCIA_LLM_TELEGRAM = 16
SEM_TELEGRAM = asyncio.Semaphore(CONCURRENCIA_LLM_TELEGRAM)


print("\n =====models=====")
# a=requests.get("http://localhost:8001/v1/models").json()
# print(a["data"][0]['id'])
print("=====models=====")



MODELO_VLM = MODELO_ACTIVO



# ═══════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════

def _parse_fecha(fecha_str: str):
    """created_at viene en ISO ('2023-11-20T08:34:23+00:00')."""
    if not fecha_str:
        return None
    try:
        return datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).date()
    except Exception:
        return None


def _en_rango(fecha_str: str, start_date: str, end_date: str) -> bool:
    f = _parse_fecha(fecha_str)
    if not f:
        return False
    try:
        d_start = datetime.strptime(start_date, "%Y-%m-%d").date()
        d_end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        return True  # sin fechas válidas en u_conf, no filtramos
    return d_start <= f <= d_end


def _match_keyword(contenido: str, keywords: list) -> bool:
    """Pre-filtro barato ANTES de gastar tokens de LLM."""
    if not contenido:
        return False
    contenido_low = contenido.lower()
    return any(kw.lower() in contenido_low for kw in keywords)


def _sumar_reacciones(mensaje: dict) -> int:
    """
    Suma el total de reacciones (ej: {'🔥': 5, '😱': 3} -> 8).
    En Telegram, 'likes' viene siempre en 0 — el engagement real
    de aprobación está en 'reactions', no en 'likes'.
    """
    reactions = mensaje.get("reactions") or {}
    return sum(reactions.values())


def _contar_respuestas_anidadas(comment_id: str, mensajes_del_post: list) -> int:
    """
    El campo 'replies' de la API de Telegram viene siempre en 0 para
    COMENTARIOS (solo lo rellena para POSTS) — aunque el comentario tenga
    respuestas anidadas debajo. Sin este conteo, el engagement real de un
    comentario (usado como impacto en ScoreOP) siempre quedaría en 0.

    Cuenta, de forma transitiva, cuántos comentarios (directos + anidados
    de más niveles) cuelgan de comment_id dentro del mismo post.
    """
    hijos_directos = [
        m for m in mensajes_del_post
        if m.get("parent_comment_id") == comment_id
    ]
    total = len(hijos_directos)
    for hijo in hijos_directos:
        total += _contar_respuestas_anidadas(hijo["external_id"], mensajes_del_post)
    return total

def _cargar_canal(canal: str) -> tuple[list, dict]:
    """Carga messages.json + metadata.json de un canal."""
    canal_dir = TELEGRAM_RAW_ROOT / canal
    messages_file = canal_dir / "messages.json"
    print(f"   📂 Buscando: {messages_file} | existe={messages_file.exists()}")
    metadata_file = canal_dir / "metadata.json"

    if not messages_file.exists():
        return [], {}

    with open(messages_file, "r", encoding="utf-8") as f:
        mensajes = json.load(f)

    metadata = {}
    if metadata_file.exists():
        with open(metadata_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

    return mensajes, metadata


# ═══════════════════════════════════════════════════════════════
# PORTERO LLM — mismo criterio que verificar_relevancia_vlm de Bluesky,
# pero solo texto (el downloader raw no descarga imágenes)
# ═══════════════════════════════════════════════════════════════

async def verificar_relevancia_telegram(contenido: str, canal: str, u_conf) -> tuple[bool, str, str]:
    keywords_str = ", ".join(u_conf.general["keywords"])

    geo_instruction = ""
    if "GLOBAL" in u_conf.population_scope.upper():
        geo_instruction = "Filtro desactivado. Acepta contenido de cualquier ubicación."
    else:
        geo_instruction = (
            f"Considerar RELEVANTE solo si el contenido menciona o permite inferir "
            f"claramente una ubicación dentro de {u_conf.population_scope}. "
            f"EN CASO DE DUDA: marcar como NO relevante para temas hiperlocales."
        )

    prompt = f"""
TAREA: Determinar si este mensaje de Telegram es RELEVANTE.
TEMA: {u_conf.tema}
CONTEXTO: {getattr(u_conf, "desc_tema", "")}
KEYWORDS RELACIONADAS: {keywords_str}
UBICACIÓN OBJETIVO: {u_conf.population_scope}

DATOS DEL MENSAJE:
- Canal: {canal}
- Texto: {contenido[:800]}

REGLAS:
1. Prioridad semántica: si el texto trata sobre el tema o las keywords -> RELEVANTE.
2. Geografía: {geo_instruction}
3. Si no se puede inferir ubicación, marcar como RELEVANTE (no descartar por defecto).
4. En caso de duda, marcar como RELEVANTE para no perder datos potenciales.

Responde en JSON: {{"relevante": true/false, "razon": "...", "idioma": "..."}}
"""

    try:
        async with SEM_TELEGRAM:
            response = await client.chat.completions.create(
                model=MODELO_VLM,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
        res = json.loads(response.choices[0].message.content)
        # print(f"{'=' * 60}")
        # print(res)
        # print(f"{'=' * 60}")
        return res.get("relevante", False), res.get("razon", "N/A"), res.get("idioma", "Desconocido")
    except Exception as e:
        print(f"⚠️ Error llamando al LLM: {e}")
        return True, "Error en validación, se mantiene por precaución", "Desconocido"


# ═══════════════════════════════════════════════════════════════
# LÓGICA PRINCIPAL
# ═══════════════════════════════════════════════════════════════

async def run_telegram(u_conf):
    print(f"🚀 Telegram (archivo local) para: {u_conf.tema}")
    from clean_project.scrapers.telegram_API import prueba
    
    prueba()    #imprime todos los comentarios que tengan la keyword.
    output_folder = Path(u_conf.general["output_folder"])
    output_folder.mkdir(parents=True, exist_ok=True)
    csv_path = output_folder / "telegram_global_dataset.csv"

    keywords = u_conf.general.get("keywords", [])
    start_date = u_conf.general.get("start_date")
    end_date = u_conf.general.get("end_date")

    if not keywords:
        print("⚠️ Sin keywords, no se puede filtrar Telegram.")
        return

    canales = CANALES_DEFAULT
    count_total = 0

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "tipo", "uri", "parent_uri", "fecha", "usuario", "id_anonimo", "contenido",
            "likes", "reposts", "replies", "media_path", "idioma_ia", "relevancia_ia",
            "seguidores", "texto_citado", "canal", "vistas", "reacciones_total",
        ])

        for canal_ref in canales:
            canal_ref = canal_ref.strip().lstrip("@")
            mensajes, metadata = _cargar_canal(canal_ref)
            if not mensajes:
                print(f"⚠️ No se encontraron mensajes para el canal: {canal_ref}")
                continue

            suscriptores = metadata.get("suscriptores", 0)
            print(f"📢 {canal_ref}: revisando {len(mensajes)} registros...")

            # Indexar posts por external_id para poder añadir sus comentarios
            posts_por_id = {m["external_id"]: m for m in mensajes if m.get("tipo") == "POST"}
            comentarios_por_post = {}
            for m in mensajes:
                if m.get("tipo") == "COMENTARIO":
                    comentarios_por_post.setdefault(m["reply_to_message_id"], []).append(m)

            # 1. Pre-filtro barato: fecha + keyword (rápido, no llama al LLM)
            candidatos = []
            for post in posts_por_id.values():
                contenido = post.get("content", "") or ""
                if start_date and end_date and not _en_rango(post.get("created_at"), start_date, end_date):
                    continue
                if not _match_keyword(contenido, keywords):
                    continue
                candidatos.append((post, contenido))

            if not candidatos:
                continue

            print(f"   🧠 {len(candidatos)} candidatos, consultando LLM en paralelo (máx {CONCURRENCIA_LLM_TELEGRAM} a la vez)...")

            # 2. Portero LLM: se lanzan TODAS las llamadas del canal a la vez.
            #    SEM_TELEGRAM limita cuántas viajan en simultáneo; vLLM agrupa
            #    internamente las que llegan juntas, en vez de una por una.
            resultados = await asyncio.gather(*[
                verificar_relevancia_telegram(contenido, canal_ref, u_conf)
                for _, contenido in candidatos
            ])

            # 3. Escribir al CSV solo lo que pasó el portero
            for (post, contenido), (es_relevante, razon, idioma) in zip(candidatos, resultados):
                if not es_relevante:
                    print(f"   ⏩ SALTADO: {contenido[:40]}... | {razon}")
                    continue
                print(f"   ✅ GUARDADO: {contenido[:40]}... | {razon}")

                uri = f"tg:{canal_ref}:{post['external_id']}"
                writer.writerow([
                    "POST", uri, uri, post.get("created_at"), post.get("sender_username"),
                    post.get("sender_id_hash"), contenido,
                    post.get("likes", 0), post.get("forwards", 0), post.get("replies", 0),
                    post.get("media_types") or "", idioma, "SI", suscriptores, "", canal_ref, post.get("views", 0), _sumar_reacciones(post),
                ])
                count_total += 1

                comentarios_del_post = comentarios_por_post.get(post["external_id"], [])
                for com in comentarios_del_post:
                    if com.get("tipo_comentario") == "anidado":
                        continue
                    com_uri = f"tg:{canal_ref}:{com['external_id']}"
                    num_respuestas = _contar_respuestas_anidadas(
                        com["external_id"], comentarios_del_post
                    )
                    writer.writerow([
                        "COMENTARIO", com_uri, uri, com.get("created_at"),
                        com.get("sender_username"), com.get("sender_id_hash"),
                        com.get("content", ""), com.get("likes", 0), com.get("forwards", 0),
                        num_respuestas, com.get("media_types") or "",
                        idioma, "SI", "", "", canal_ref, com.get("views", 0), _sumar_reacciones(com),
                    ])
                    count_total += 1
    print(f"✅ Telegram finalizado. Total registros guardados: {count_total}")

# =====================================================
# DEBUG AISLADO
# =====================================================
# if __name__ == "__main__":
#     import asyncio
#     from types import SimpleNamespace
#     PARA DEBUGEAR AISLADO CAMBIAR http://host.docker.internal:8001/v1 POR http://localhost:8001/v1
#     mock_conf = SimpleNamespace(
#         tema="venus", #"ABEJAS", #"bikesharing",
#         desc_tema="planeta", #"NIDO ABEJAS", #"Servicio de transporte público de bicicletas",
#         population_scope="GLOBAL",
#         general={
#             "output_folder": "/home/romina/debug_telegram",
#             "keywords": ["venus no tiene estaciones"],#["abejas aniden"],#["bicing"],
#             "start_date": "2026-07-09",#"2025-06-11",#"2026-07-01",
#             "end_date": "2026-07-11",#"2025-06-12",#"2026-07-28",
#         },
#     )
#     asyncio.run(run_telegram(mock_conf))    