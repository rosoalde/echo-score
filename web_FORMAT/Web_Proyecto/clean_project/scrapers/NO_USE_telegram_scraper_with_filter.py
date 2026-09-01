"""
TELEGRAM SCRAPER
================
Recopila mensajes y comentarios de canales públicos y grupos de Telegram.

REQUISITOS:
pip install telethon --break-system-packages

CREDENCIALES (GRATUITAS — 5 minutos):
1. Ve a https://my.telegram.org/auth
2. Inicia sesión con tu número de teléfono de Telegram
3. Haz clic en "API development tools"
4. Crea una nueva aplicación (nombre y plataforma cualquiera)
5. Copia API_ID (número) y API_HASH (string)
6. Rellena las variables abajo

IMPORTANTE SOBRE SESIONES:
La primera vez que ejecutes el scraper te pedirá:
- Tu número de teléfono (con prefijo país, ej: +34XXXXXXXXX)
- El código de verificación que Telegram te envía
- Opcionalmente la contraseña 2FA si la tienes activada
Esto crea un fichero .session local que reutiliza la autenticación en ejecuciones posteriores.
Guarda ese fichero en un lugar seguro y NO lo subas a git.

QUÉ PUEDE SCRAPEAR:
- Canales públicos: mensajes completos con historial
- Grupos de discusión vinculados a canales: comentarios
- Grupos públicos: mensajes (debes ser miembro o ser público)
- Mensajes privados: NO (requeriría ser miembro e implica problemas éticos)
"""

import asyncio
import csv
import hashlib
import json
import sys
import re
from pathlib import Path
from datetime import datetime, timezone
from openai import OpenAI
from types import SimpleNamespace

ROOT_PATH = Path(__file__).resolve().parents[2]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
import clean_project.config.settings as config

ROOT_PATH = Path(__file__).resolve().parents[2]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))


    
from clean_project.vllm.model_config import MODELO_ACTIVO, VISION_HABILITADA
MODELO_VLM = MODELO_ACTIVO
client = OpenAI(base_url="http://localhost:8001/v1", api_key="local-token")

# ─────────────────────────────────────────────────────────────────────────────
# ⚠️  CLAVES A COMPLETAR — https://my.telegram.org/auth
# ─────────────────────────────────────────────────────────────────────────────
TELEGRAM_API_ID = config.CREDENTIALS["telegram"]["TELEGRAM_API_ID"]
TELEGRAM_API_HASH = config.CREDENTIALS["telegram"]["TELEGRAM_API_HASH"]
TELEGRAM_SESSION_NAME = "social_insight_session"  # Nombre del fichero .session
SESSION_DIR = Path(__file__).resolve().parent  # ← añadir aquí
CACHE_SUBS_PATH = SESSION_DIR / "canal_subs_cache.json"
# ─────────────────────────────────────────────────────────────────────────────
try:
    subs_cache = json.loads(CACHE_SUBS_PATH.read_text())
except Exception:
    subs_cache = {}
# Canales/grupos públicos de Telegram a monitorizar por defecto.
# Formato: "@nombre_canal" o "https://t.me/nombre_canal"
# El usuario puede sobrescribir esto en u_conf.general["telegram_channels"]

from clean_project.scrapers.canales import CANALES_DEFAULT 
def generar_id_anonimo(username: str) -> str:
    if not username:
        return "UNKNOWN"
    return hashlib.sha256(username.encode()).hexdigest()[:16].upper()


def limpiar_texto(texto: str) -> str:
    if not texto:
        return ""
    # Eliminar entidades HTML y caracteres de control
    texto = re.sub(r"&[a-zA-Z]+;", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()

def extraer_reacciones(mensaje) -> dict:
    """
    Devuelve dict con total de reacciones y desglose por emoji.
    Ej: {"total": 23, "detalle": "👍:14,🤔:7,❤:2"}
    """
    if not mensaje.reactions or not mensaje.reactions.results:
        return {"total": 0, "detalle": ""}
    
    total = 0
    partes = []
    for rc in mensaje.reactions.results:
        emoticon = getattr(rc.reaction, "emoticon", "?")
        count = rc.count or 0
        total += count
        partes.append(f"{emoticon}:{count}")
    
    return {"total": total, "detalle": ",".join(partes)}


async def verificar_relevancia(texto, canal_nombre, u_conf):
    if not texto or len(texto.strip()) < 10:
        return False, "Texto demasiado corto", "Desconocido"

    keywords_str = ", ".join(u_conf.general["keywords"])
    geo = (
        "Sin restricción geográfica."
        if "GLOBAL" in u_conf.population_scope.upper()
        else f"Solo si menciona o permite inferir {u_conf.population_scope}."
    )
    prompt = f"""
    Determina si este mensaje de Telegram es RELEVANTE.
    TEMA: {u_conf.tema}
    CONTEXTO: {u_conf.desc_tema}
    KEYWORDS: {keywords_str}
    GEOGRAFÍA: {geo}
    CANAL: {canal_nombre}

    Mensaje: {texto[:500]}

    Responde en JSON: {{"relevante": true/false, "razon": "...", "idioma": "..."}}
    """
    try:
        response = client.chat.completions.create(
            model=MODELO_VLM,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        res = json.loads(response.choices[0].message.content)
        return res.get("relevante", False), res.get("razon", "N/A"), res.get("idioma", "Desconocido")
    except Exception:
        return True, "Error en validación", "Desconocido"

async def verificar_relevancia_batch(mensajes_batch: list[dict], u_conf) -> list[dict]:
    """
    Analiza un batch de mensajes en UNA sola llamada al LLM.
    
    mensajes_batch: lista de dicts con {"id": str, "texto": str, "canal": str}
    Devuelve: lista de dicts con {"id": str, "relevante": bool, "idioma": str, "razon": str}
    """
    keywords_str = ", ".join(u_conf.general["keywords"])
    geo = (
        "Sin restricción geográfica."
        if "GLOBAL" in u_conf.population_scope.upper()
        else f"Solo si menciona o permite inferir {u_conf.population_scope}."
    )

    # Construir la lista de mensajes para el prompt
    items_str = ""
    for i, m in enumerate(mensajes_batch):
        items_str += f'\n  {{"index": {i}, "canal": "{m["canal"]}", "texto": "{m["texto"][:300].replace(chr(34), chr(39))}"}}'

    prompt = f"""
Analiza estos {len(mensajes_batch)} mensajes de Telegram y determina si cada uno es RELEVANTE.

TEMA: {u_conf.tema}
CONTEXTO: {u_conf.desc_tema}
KEYWORDS: {keywords_str}
GEOGRAFÍA: {geo}

MENSAJES:
[{items_str}
]

Para cada mensaje devuelve si es relevante, el idioma detectado y una razón breve.

Responde ÚNICAMENTE con este JSON (sin texto adicional):
{{
  "resultados": [
    {{"index": 0, "relevante": true/false, "idioma": "...", "razon": "..."}},
    {{"index": 1, "relevante": true/false, "idioma": "...", "razon": "..."}},
    ...
  ]
}}
"""
    try:
        response = client.chat.completions.create(
            model=MODELO_VLM,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=2000,
        )
        res = json.loads(response.choices[0].message.content)
        resultados = res.get("resultados", [])
        
        # Indexar por "index" para recuperar fácilmente
        mapa = {r["index"]: r for r in resultados}
        
        # Devolver en el mismo orden que la entrada
        salida = []
        for i, m in enumerate(mensajes_batch):
            r = mapa.get(i, {})
            salida.append({
                "id": m["id"],
                "relevante": r.get("relevante", True),  # en caso de duda, relevante
                "idioma": r.get("idioma", "Desconocido"),
                "razon": r.get("razon", "N/A"),
            })
        return salida

    except Exception as e:
        print(f"   ⚠️ Error en batch LLM: {e}")
        # Fallback: todos relevantes para no perder datos
        return [{"id": m["id"], "relevante": True, "idioma": "Desconocido", "razon": "Error batch"} 
                for m in mensajes_batch]
async def run_telegram(u_conf):
    """
    Scraper principal de Telegram.
    Recorre los canales indicados en u_conf.general["telegram_channels"]
    y extrae mensajes + comentarios dentro del rango de fechas.
    """
    if TELEGRAM_API_ID == 0 or TELEGRAM_API_HASH.startswith("XXX"):
        print("⚠️ Telegram: sin credenciales configuradas.")
        print("   → Ve a https://my.telegram.org/auth y rellena TELEGRAM_API_ID y TELEGRAM_API_HASH")
        return

    try:
        from telethon import TelegramClient
        from telethon.tl.types import (
            MessageMediaPhoto, MessageMediaDocument,
            PeerChannel, InputMessagesFilterEmpty
        )
        from telethon.errors import ChannelPrivateError
    except ImportError:
        print("⚠️ Instala Telethon: pip install telethon --break-system-packages")
        return

    print(f"📱 Telegram Scraper para: {u_conf.tema}")

    output_folder = Path(u_conf.general["output_folder"])
    output_folder.mkdir(parents=True, exist_ok=True)
    csv_path = output_folder / "telegram_global_dataset.csv"

    start_dt = datetime.strptime(u_conf.general["start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(u_conf.general["end_date"], "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )

    # Canales a rastrear: los del usuario + los default
    # canales = u_conf.general.get("telegram_channels", []) + CANALES_DEFAULT
    if u_conf.general.get("telegram_channels") is not None:
        canales = u_conf.general.get("telegram_channels")
    else:
        canales = CANALES_DEFAULT
    print(f"Canales default: {CANALES_DEFAULT[0:10]}")
    print(f"Todos los canales: {canales[0:10]}")
    if not canales:
        print("⚠️ Telegram: no hay canales configurados.")
        print("   → Añade canales en u_conf.general['telegram_channels'] = ['@micanal', ...]")
        return

    seen_ids = set()
    count = 0

    # Guardar sesión en la carpeta de output para no perderla. Ruta fija, siempre el mismo fichero
    SESSION_DIR = Path(__file__).resolve().parent  # misma carpeta que el scraper
    session_path = str(SESSION_DIR / TELEGRAM_SESSION_NAME)
    # ── Logging con minutos ───────────────────────────────────────────────
    import logging

    class _FloodFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            if 'Sleeping for' in msg:
                try:
                    segundos = int(msg.split('Sleeping for')[1].split('s')[0].strip())
                    record.msg = f"⏳ FloodWait: esperando {segundos}s ({segundos//60}min {segundos%60}s)..."
                    record.args = ()
                except Exception:
                    pass
            return True

    logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.WARNING)
    logging.getLogger('telethon').addFilter(_FloodFilter())
    # ─────────────────────────────────────────────────────────────────────
    async with TelegramClient(session_path, TELEGRAM_API_ID, TELEGRAM_API_HASH, flood_sleep_threshold=24*60*60) as tg:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                "tipo", "id", "suscriptores", "parent_id", "fecha", "usuario", "id_anonimo",
                "contenido", "views", "forwards", "replies",
                "reacciones_total", "reacciones_detalle",
                "tiene_media", "canal", "idioma_ia", "relevancia_ia",
            ])
            from telethon.errors import ChannelPrivateError
            for canal_ref in canales:
                canal_ref = canal_ref.strip()
                print(f"\n   📢 Canal: {canal_ref}")
                from telethon.tl.functions.channels import GetFullChannelRequest
                try:

                    try:
                        entidad = await tg.get_input_entity(canal_ref)
                    except ValueError:
                        # No está en caché, hay que resolverlo - aquí sí puede haber FloodWait
                        entidad = await tg.get_entity(canal_ref)
                    canal_nombre = getattr(entidad, "title", canal_ref)
                    canal_username = getattr(entidad, "username", canal_ref)

                    # ── Número de suscriptores ─────────────────────────
                    if canal_ref in subs_cache:
                        suscriptores = subs_cache[canal_ref]
                    else:
                        full_info = await tg(GetFullChannelRequest(channel=entidad))
                        suscriptores = full_info.full_chat.participants_count
                        subs_cache[canal_ref] = suscriptores
                        CACHE_SUBS_PATH.write_text(json.dumps(subs_cache))
                    print(f"   👥 Suscriptores: {suscriptores:,}")

                except ChannelPrivateError:
                    print(f"   ❌ Canal privado: {canal_ref}")
                    continue
                except Exception as e:
                    print(f"   ❌ {canal_ref}: {e}")
                    continue
                
                await asyncio.sleep(1.5)  # delay preventivo entre canales
                
                
                # ── Mensajes del canal ────────────────────────────────────────
                # ── Mensajes del canal ────────────────────────────────────────
                msg_count = 0
                BATCH_SIZE = 20

                for kw in u_conf.general["keywords"]:

                    # Buffer para acumular antes de llamar al LLM
                    buffer_meta    = []   # dicts con {"id", "texto", "canal"}
                    buffer_objetos = []   # objetos Message de Telethon

                    async def vaciar_buffer():
                        """Clasifica el buffer con el LLM y escribe los relevantes al CSV."""
                        nonlocal count, msg_count
                        if not buffer_meta:
                            return

                        print(f"   🧠 Batch LLM: {len(buffer_meta)} mensajes…")
                        resultados = await verificar_relevancia_batch(buffer_meta, u_conf)

                        for res, mensaje in zip(resultados, buffer_objetos):
                            if not res["relevante"]:
                                print(f"      ⏩ SALTADO: {res['razon'][:60]}")
                                continue

                            idioma = res["idioma"]
                            texto  = limpiar_texto(mensaje.text or mensaje.message or "")
                            reacs  = extraer_reacciones(mensaje)

                            sender = await mensaje.get_sender()
                            nombre_sender = (
                                getattr(sender, "username", None)
                                or getattr(sender, "first_name", "")
                                or canal_username
                            ) if sender else canal_username

                            tiene_media = "SI" if mensaje.media else "NO"

                            writer.writerow([
                                "POST", str(mensaje.id), suscriptores, "",
                                mensaje.date.strftime("%Y-%m-%d %H:%M"),
                                nombre_sender,
                                generar_id_anonimo(nombre_sender),
                                texto,
                                getattr(mensaje, "views", 0) or 0,
                                getattr(mensaje, "forwards", 0) or 0,
                                getattr(getattr(mensaje, "replies", None), "replies", 0) or 0,
                                reacs["total"],
                                reacs["detalle"],
                                tiene_media, canal_nombre, idioma, "SI",
                            ])
                            count += 1
                            msg_count += 1

                            # ── Comentarios del post relevante ──────────────────
                            if getattr(mensaje, "replies", None) and mensaje.replies.replies > 0:
                                try:
                                    async for reply in tg.iter_messages(
                                        entidad,
                                        reply_to=mensaje.id,
                                        limit=100,
                                    ):
                                        rid = f"{mensaje.id}_r{reply.id}"
                                        if rid in seen_ids:
                                            continue
                                        seen_ids.add(rid)

                                        texto_reply = limpiar_texto(reply.text or reply.message or "")
                                        if not texto_reply:
                                            continue

                                        views_reply    = getattr(reply, "views", 0) or 0
                                        forwards_reply = getattr(reply, "forwards", 0) or 0
                                        replies_reply  = getattr(getattr(reply, "replies", None), "replies", 0) or 0
                                        reacs_reply    = extraer_reacciones(reply)

                                        reply_sender = await reply.get_sender()
                                        nombre_reply = (
                                            getattr(reply_sender, "username", None)
                                            or getattr(reply_sender, "first_name", "")
                                            or "usuario"
                                        ) if reply_sender else "usuario"

                                        writer.writerow([
                                            "COMENTARIO", str(reply.id), suscriptores, str(mensaje.id),
                                            reply.date.strftime("%Y-%m-%d %H:%M"),
                                            nombre_reply,
                                            generar_id_anonimo(nombre_reply),
                                            texto_reply,
                                            views_reply,
                                            forwards_reply,
                                            replies_reply,
                                            reacs_reply["total"],
                                            reacs_reply["detalle"],
                                            "NO", canal_nombre, idioma, "SI",
                                        ])
                                        count += 1

                                except Exception:
                                    pass

                        buffer_meta.clear()
                        buffer_objetos.clear()

                    # ── Bucle de scraping: acumula en buffer ──────────────────
                    async for mensaje in tg.iter_messages(
                        entidad,
                        search=kw,
                        limit=None,
                    ):
                        if mensaje.date < start_dt:
                            break
                        if mensaje.date > end_dt:
                            continue

                        mid = str(mensaje.id)
                        if mid in seen_ids:
                            continue
                        seen_ids.add(mid)

                        texto = limpiar_texto(mensaje.text or mensaje.message or "")
                        if not texto and not mensaje.media:
                            continue

                        print(f"      📥 Acumulando: {texto[:50]}…")

                        buffer_meta.append({"id": mid, "texto": texto, "canal": canal_nombre})
                        buffer_objetos.append(mensaje)

                        # Cuando el buffer llega a BATCH_SIZE, llamar al LLM
                        if len(buffer_meta) >= BATCH_SIZE:
                            await vaciar_buffer()

                        await asyncio.sleep(0.05)

                    # Procesar lo que quede al terminar el canal/keyword
                    await vaciar_buffer()

                    print(f"   → {msg_count} mensajes relevantes de {canal_nombre}")

    print(f"\n✅ Telegram finalizado. {count} registros guardados en {csv_path.name}")
    print(f"   💾 Sesión guardada en: {session_path}.session (reutilizable)")


# ─────────────────────────────────────────────────────────────────────────────
# MODO SIN AUTENTICACIÓN: scraping web del preview público de t.me/s/canal
# Útil si no quieres configurar credenciales. Limitado a ~100 mensajes recientes.
# ─────────────────────────────────────────────────────────────────────────────
async def run_telegram_web_preview(u_conf):
    """
    Alternativa sin credenciales. Scraping del preview público de Telegram.
    Limitaciones: ~100 mensajes por canal, sin comentarios, sin historial.
    No requiere registro ni instalación adicional.
    """
    import aiohttp
    from bs4 import BeautifulSoup

    print(f"📱 Telegram Web Preview Scraper (sin auth) para: {u_conf.tema}")

    output_folder = Path(u_conf.general["output_folder"])
    output_folder.mkdir(parents=True, exist_ok=True)
    csv_path = output_folder / "telegram_global_dataset.csv"

    start_dt = datetime.strptime(u_conf.general["start_date"], "%Y-%m-%d")
    end_dt = datetime.strptime(u_conf.general["end_date"], "%Y-%m-%d").replace(
        hour=23, minute=59, second=59
    )

    #canales = u_conf.general.get("telegram_channels", []) + CANALES_DEFAULT
    if u_conf.general.get("telegram_channels") is not None:
        canales = u_conf.general.get("telegram_channels")
    else:
        canales = CANALES_DEFAULT
    if not canales:
        print("⚠️ No hay canales configurados en telegram_channels")
        return

    seen_ids = set()
    count = 0

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
    }

    async with aiohttp.ClientSession() as session:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                "tipo", "id", "suscriptores", "parent_id", "fecha", "usuario", "id_anonimo",
                "contenido", "views", "forwards", "replies",
                "reacciones_total", "reacciones_detalle", 
                "tiene_media", "canal", "idioma_ia", "relevancia_ia",
            ])

            for canal_ref in canales:
                # Normalizar nombre de canal
                canal_username = canal_ref.strip().lstrip("@").split("/")[-1]
                url_preview = f"https://t.me/s/{canal_username}"

                print(f"   📢 Scrapeando preview: {url_preview}")

                try:
                    async with session.get(url_preview, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        if resp.status != 200:
                            print(f"   ⚠️ No accesible (status {resp.status}): {url_preview}")
                            continue
                        html = await resp.text()
                except Exception as e:
                    print(f"   ⚠️ Error: {e}")
                    continue

                soup = BeautifulSoup(html, "html.parser")
                canal_nombre = soup.select_one(".tgme_channel_info_header_title")
                canal_nombre = canal_nombre.get_text() if canal_nombre else canal_username

                mensajes = soup.select(".tgme_widget_message")
                print(f"   → {len(mensajes)} mensajes en el preview")

                for msg in mensajes:
                    # ID del mensaje
                    mid = msg.get("data-post", "")
                    if not mid or mid in seen_ids:
                        continue

                    # Texto
                    texto_el = msg.select_one(".tgme_widget_message_text")
                    texto = limpiar_texto(texto_el.get_text() if texto_el else "")
                    if not texto:
                        continue

                    # Filtro por keyword
                    if not any(kw.lower() in texto.lower() for kw in u_conf.general["keywords"]):
                        continue

                    # Fecha
                    time_el = msg.select_one("time")
                    fecha_str = time_el.get("datetime", "") if time_el else ""
                    try:
                        fecha_p = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        fecha_p = datetime.now()

                    if not (start_dt <= fecha_p <= end_dt):
                        continue

                    seen_ids.add(mid)

                    # Views
                    views_el = msg.select_one(".tgme_widget_message_views")
                    views = views_el.get_text().strip() if views_el else "0"

                    tiene_media = "SI" if msg.select_one(".tgme_widget_message_photo, .tgme_widget_message_video") else "NO"

                    es_rel, razon, idioma = await verificar_relevancia(texto, canal_nombre, u_conf)
                    if not es_rel:
                        print(f"      ⏩ SALTADO: {texto[:50]}…")
                        continue

                    writer.writerow([
                        "POST", mid, suscriptores, "",
                        fecha_p.strftime("%Y-%m-%d %H:%M"),
                        canal_nombre,
                        generar_id_anonimo(canal_nombre),
                        texto,
                        views, 0, 0,
                        tiene_media, canal_nombre, idioma, "SI",
                    ])
                    count += 1

                await asyncio.sleep(2)

    print(f"\n✅ Telegram Web Preview finalizado. {count} mensajes guardados.")


if __name__ == "__main__":
    mock_conf = SimpleNamespace(
        # tema="Transporte público",
        # desc_tema="Debate sobre el transporte público en Valencia.",
        # population_scope="Valencia, España",
        tema="Transporte público",#Donald Trump y política de Estados Unidos",
        desc_tema="El sistema de transporte público de la ciudad de Valencia, España, que incluye autobuses y otros medios de transporte.",#"Noticias sobre Donald Trump, su actividad política, campañas electorales, decisiones judiciales, declaraciones públicas y acontecimientos relacionados con la política estadounidense.",
        population_scope="Valencia, España",
        general={
            "output_folder": "./debug_telegram",
            "keywords": ["transporte"],#["UCO"],#["metro Valencia", "EMT Valencia", "Metrovalencia"],
            "start_date": "2026-05-01",
            "end_date": "2026-06-04",
        #     # Lista de canales públicos de Telegram a monitorizar:
        #     # Puedes poner el @username o la URL completa t.me/...
            #"telegram_channels": ["UNoticias"],#"@eldiarioes", "@noticias_20minutos",
                # "@canal_ejemplo",
                # "https://t.me/otro_canal",
                # Añade aquí los canales relevantes para tu tema
        },
    )

    # Modo 1: Con credenciales Telethon (acceso completo, historial ilimitado)
    if TELEGRAM_API_ID != 0:
        asyncio.run(run_telegram(mock_conf))
    else:
        # Modo 2: Sin credenciales (solo preview público, ~100 mensajes)
        print("⚠️ Sin credenciales → usando modo web preview (limitado)")
        asyncio.run(run_telegram_web_preview(mock_conf))