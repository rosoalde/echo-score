import os
import csv
import json
import hashlib
import requests
import re
import sys
import base64
from pathlib import Path
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
from io import BytesIO
import asyncio

# Configuración de rutas relativas
ROOT_PATH = Path(__file__).resolve().parents[2]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

import clean_project.config.settings as config

from clean_project.vllm.model_config import MODELO_ACTIVO, VISION_HABILITADA
MODELO_VLM = MODELO_ACTIVO

# Cliente vLLM
client = OpenAI(base_url="http://host.docker.internal:8001/v1", api_key="local-token")
#MODELO_VLM = "Qwen/Qwen2.5-14B-Instruct-AWQ"#"Qwen/Qwen2.5-VL-7B-Instruct"

# =====================================================
# 1. GESTIÓN DE API KEYS (ROTACIÓN)
# =====================================================

api_keys = [
    config.CREDENTIALS["youtube"]["API_KEY_YOUTUBE"],
    config.CREDENTIALS["youtube"]["API_KEY_YOUTUBE2"],
    config.CREDENTIALS["youtube"]["API_KEY_YOUTUBE3"]
]
# La cuota de YouTube Data API v3 es de 10.000 unidades/día por PROYECTO (3 cuentas diferentes)

current_api_key_index = 0
api_keys_exceeded = [False] * len(api_keys)

def get_youtube_service():
    """Construye el servicio de YouTube con la clave actual."""
    return build("youtube", "v3", developerKey=api_keys[current_api_key_index])

# Inicialización global del servicio
youtube = get_youtube_service()

def switch_api_key():
    """Cambia a la siguiente API Key si la actual se agota."""
    global current_api_key_index, youtube, api_keys_exceeded
    api_keys_exceeded[current_api_key_index] = True
    current_api_key_index += 1
    
    if current_api_key_index >= len(api_keys):
        print("❌ TODAS las API Keys de YouTube han agotado su cuota.")
        return False
        
    print(f"🔑 Cuota agotada. Cambiando a la API Key {current_api_key_index + 1}...")
    youtube = get_youtube_service()
    return True

# =====================================================
# 1. UTILIDADES DE APOYO
# =====================================================

def generar_id_anonimo(username):
    if not username: return "UNKNOWN"
    return hashlib.sha256(username.encode()).hexdigest()[:16].upper()

def download_and_base64(url):
    try:
        response = requests.get(url)
        return base64.b64encode(response.content).decode('utf-8')
    except:
        return None

def get_video_transcript(video_id):
    try:
        ytt_api = YouTubeTranscriptApi()
        t_list = ytt_api.list(video_id)

        try:
            transcript = t_list.find_transcript(["es", "es-ES"])
        except Exception:
            transcript = next(iter(t_list)).translate("es")

        return " ".join(t.text for t in transcript.fetch())

    except Exception as e:
        print(e)
        return ""

# =====================================================
# 2. EL PORTERO (GATEKEEPER) MULTIMODAL MEJORADO
# =====================================================

def verificar_relevancia_vlm(detalles, transcripcion, b64_image, u_conf):

    geo_instruction = ""
    if "GLOBAL" in u_conf.population_scope.upper():
        geo_instruction = "2. GEOGRAFÍA:\n"
        geo_instruction += " Filtro desactivado. Acepta comentarios de cualquier ubicación geográfica."
    else:
        geo_instruction = f"2. GEOGRAFÍA:\n"
        geo_instruction =  f" Considerar RELEVANTE solo si el autor, el contenido o el contexto menciona o permite inferir claramente una ubicación específica dentro de {u_conf.population_scope}:"
        geo_instruction += f" Nombre de barrio, distrito, calle, plaza, institución local, o gentilicio local en {u_conf.population_scope}."
        geo_instruction += f" Referencia a un servicio/organismo que opera exclusivamente en {u_conf.population_scope}"
        geo_instruction += f" El autor indica estar en {u_conf.population_scope} (perfil, contexto, etc.)"
        geo_instruction += f" DESCARTAR si:"
        geo_instruction += f" - El post no contiene ninguna referencia geográfica verificable"
        geo_instruction += f" - La referencia geográfica apunta claramente a otra ciudad/región no relacionada con {u_conf.population_scope}"
        geo_instruction += f" - El contenido podría ser de cualquier ciudad (sin anclaje local)"
        geo_instruction += f" EN CASO DE DUDA: marcar como NO relevante para temas hiperlocales."
        geo_instruction += f" (Para temas hiperlocales la precisión importa más que el recall.)"
        geo_instruction += f"(ej: r/uruguay y buscas España), marca NO RELEVANTE."
    keywords_str = ", ".join(u_conf.general["keywords"])
    """
    IA con jerarquía de evidencia: El texto manda sobre la imagen.
    """
    prompt = f"""
    TAREA:
    Determinar si este contenido es RELEVANTE para el tema.

    TEMA OBJETIVO:
    {u_conf.tema}

    CONTEXTO DEL TEMA:
    {u_conf.desc_tema}

    PALABRAS CLAVE RELACIONADAS:
    {keywords_str}

    ÁMBITO GEOGRÁFICO (REFERENCIA, NO RESTRICTIVO):
    {u_conf.population_scope}

    -------------------------
    REGLAS DE DECISIÓN
    -------------------------

    1. PRIORIDAD ABSOLUTA: SEMÁNTICA
    Si el título contiene términos clave del TEMA OBJETIVO → RELEVANTE.
    Si el contenido describe términos cercanos o relacionados semánticamente → RELEVANTE.

    {geo_instruction}

    3. LA IMAGEN ES SECUNDARIA
    - SOLO usarla si el texto es ambiguo
    - NO descartar contenido textual relevante por imagen genérica

    4. PRINCIPIO DE INCLUSIÓN
    - Si hay duda → RELEVANTE

    5. CASOS DE DESCARTE
    Solo marcar NO relevante si:
    - trata de otro tema completamente distinto
    - o de otra ubicación sin relación clara

    -------------------------
    DATOS
    -------------------------
    Título: {detalles['titulo']}
    Descripción: {detalles['descripcion'][:1000]}
    Transcripción: {transcripcion[:1000]}

    -------------------------
    RESPUESTA (JSON)
    -------------------------
    {{
    "relevante": true/false,
    "razon": "Explica brevemente por qué es relevante (máx 2 líneas)"
    "idioma": Idioma detectado del contenido analizado, 
    "idioma_justificacion": "Explica la razón de la asignación del idioma"
    }}
    """

    content = [{"type": "text", "text": prompt}]
    if VISION_HABILITADA and b64_image:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}})

    try:
        response = client.chat.completions.create(
            model=MODELO_VLM,
            messages=[{"role": "user", "content": content}],
            temperature=0,
            max_tokens=200
        )
        raw = response.choices[0].message.content
        clean_raw = re.sub(r"```json|```", "", raw, flags=re.IGNORECASE).strip()
        res = json.loads(clean_raw)
        return res.get("relevante", False), res.get("razon", "No se proporcionó razón"), res.get("idioma", "Desconocido"), res.get("idioma_justificacion", "N/A")
    except Exception as e:
        return True, f"Error en Gatekeeper: {str(e)}", "Desconocido", "N/A" # En caso de duda, no descartamos

# =====================================================
# 3. SCRAPER CORE
# =====================================================

async def run_youtube(u_conf):
    global youtube
    print(f"🚀 YouTube Scraper (Filtro IA + Fechas) para: {u_conf.tema}")
    
    output_folder = Path(u_conf.general["output_folder"])
    output_folder.mkdir(parents=True, exist_ok=True) 
    media_folder = output_folder / "media"
    media_folder.mkdir(parents=True, exist_ok=True)
    
    youtube = build("youtube", "v3", developerKey=config.CREDENTIALS["youtube"]["API_KEY_YOUTUBE"])
    
    # Formatear fechas para la API
    rfc_start = f"{u_conf.general['start_date']}T00:00:00Z"
    rfc_end = f"{u_conf.general['end_date']}T23:59:59Z"

    csv_path = output_folder / "youtube_global_dataset.csv"
    seen_ids = set()

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow([
            "tipo", "id_video", "fecha", "usuario", "id_anonimo", "contenido", 
            "titulo_video", "transcripcion", "likes", "comments", "vistas", 
            "canal", "thumbnail_path", "idioma_ia", "idioma_ia_just", "relevancia_ia", "relevancia_just", "suscriptores"
        ])

        for kw in u_conf.general["keywords"]:
            print(f"🔍 Buscando: {kw} (Periodo: {u_conf.general['start_date']} al {u_conf.general['end_date']})")
            # search.list tiene un tope documentado de ~500 resultados totales
            # por keyword/periodo (se pagine o no). No troceamos por fechas para
            # cubrirlo: con un periodo ~1 año la cuota (100 unidades/página,
            # compartida por proyecto) se agotaría antes de terminar. Asumimos
            # ~500/keyword como techo de cobertura conocido y documentado.
            next_page_token_search = None

            while True:
                try:
                    search_res = youtube.search().list(
                        q=f'"{kw}"', 
                        part="snippet", 
                        type="video", 
                        maxResults=50, 
                        regionCode="ES",
                        publishedAfter=rfc_start,
                        publishedBefore=rfc_end,
                        pageToken=next_page_token_search
                    ).execute()

                except HttpError as e:
                    if e.resp.status == 403 and switch_api_key():
                        # Reintentar con la nueva llave
                        # next_page_token_search no cambia: reintenta la MISMA
                        # página con la nueva key en vez de perder la keyword
                        continue
                    break
                    
                for item in search_res.get("items", []):
                    vid_id = item["id"]["videoId"]
                    if vid_id in seen_ids: continue
                    seen_ids.add(vid_id)

                    try:
                        v_stats_res = youtube.videos().list(part="statistics,snippet", id=vid_id).execute()
                        if not v_stats_res["items"]: continue
                        v_stats = v_stats_res["items"][0]

                        canal_id = v_stats["snippet"]["channelId"]
                        channel_res = youtube.channels().list(
                            part="statistics",
                            id=canal_id
                        ).execute()

                        suscriptores = 0
                        if channel_res.get("items"):
                            suscriptores = int(
                                channel_res["items"][0]["statistics"].get("subscriberCount", 0)
                            )
                        
                        detalles = {
                            "titulo": v_stats["snippet"]["title"],
                            "descripcion": v_stats["snippet"]["description"],
                            "canal_publica": v_stats["snippet"]["channelTitle"],
                            "thumb_url": v_stats["snippet"]["thumbnails"]["high"]["url"]
                        }
                        
                        transcripcion = get_video_transcript(vid_id)
                        b64_img = download_and_base64(detalles["thumb_url"])

                        es_relevante, razon_ia, idioma, idioma_justificacion = verificar_relevancia_vlm(detalles, transcripcion, b64_img, u_conf)

                        if not es_relevante:
                            # IMPRIMIMOS LA RAZÓN EN LA TERMINAL
                            print(f"⏩ SALTADO: {detalles['titulo']}")
                            print(f"   └─ ❌ RAZÓN IA: {razon_ia}") 
                            continue

                        # Guardar imagen
                        img_path = media_folder / f"{vid_id}.jpg"
                        if b64_img:
                            with open(img_path, "wb") as img_f:
                                img_f.write(base64.b64decode(b64_img))

                        # Fila Video
                        writer.writerow([
                            "VIDEO", vid_id, v_stats["snippet"]["publishedAt"], 
                            detalles["canal_publica"], generar_id_anonimo(detalles["canal_publica"]),
                            detalles["descripcion"], detalles["titulo"], transcripcion,
                            v_stats["statistics"].get("likeCount", 0), v_stats["statistics"].get("commentCount", 0),
                            v_stats["statistics"].get("viewCount", 0), detalles["canal_publica"],
                            f"media/{vid_id}.jpg", idioma, idioma_justificacion,"SI", razon_ia, suscriptores  
                        ]) 

                        # --- DESCARGAR TODOS LOS COMENTARIOS (PAGINACIÓN) ---
                        print(f"📥 Descargando comentarios para: {vid_id}")
                        next_page_token = None
                        while True:
                            try:
                                comments_res = youtube.commentThreads().list(
                                    part="snippet", 
                                    videoId=vid_id, 
                                    maxResults=100, 
                                    textFormat="plainText",
                                    pageToken=next_page_token
                                ).execute()

                                for c_item in comments_res.get("items", []):
                                    c = c_item["snippet"]["topLevelComment"]["snippet"]
                                    writer.writerow([
                                        "COMENTARIO", vid_id, c["publishedAt"], c["authorDisplayName"],
                                        generar_id_anonimo(c["authorDisplayName"]), c["textDisplay"],
                                        detalles["titulo"], "", c["likeCount"], 
                                        c_item["snippet"]["totalReplyCount"], 0, detalles["canal_publica"], "", "", "", "SI", "", ""
                                    ]) 

                                next_page_token = comments_res.get("nextPageToken")
                                if not next_page_token: break
                            except HttpError as e:
                                if e.resp.status in [403, 404]: break
                                raise e
                    except Exception as e:
                        print(f"⚠️ Error procesando video {vid_id}: {e}")
                # Cada página nueva cuesta 100 unidades igual que la primera.
                # El bucle termina solo: o bien se acaban los resultados reales,
                # o bien YouTube deja de devolver nextPageToken al llegar al
                # tope de ~500 (ver nota de arriba).
                next_page_token_search = search_res.get("nextPageToken")
                if not next_page_token_search:
                    break
    print(f"✅ Proceso finalizado. Datos en: {csv_path}")

if __name__ == "__main__":
    from types import SimpleNamespace
    mock_conf = SimpleNamespace(
        tema="Pantalán de Sagunto",
        desc_tema="Infraestructura portuaria renovada como espacio turístico y cultural con vistas al Mediterráneo.",
        population_scope="Sagunto, España",
        general={
            "output_folder": "./debug_test",
            "keywords": ["pantalán sagunto", "paseo marítimo sagunto", "renovación pantalán sagunto"],
            "start_date": "2024-08-20",
            "end_date": "2025-03-01"
        }
    )
    asyncio.run(run_youtube(mock_conf))