import csv
import asyncio
import aiohttp
import json
import hashlib
import re
import os
import sys
import base64
from pathlib import Path
from datetime import datetime
from openai import AsyncOpenAI


# Si es True: se recogen POST (ORIGINAL/AUTENTICO), CITA, COMENTARIO_A_POST y COMENTARIO_A_COMENTARIO.
# Si es False: solo se recogen POST (ORIGINAL/AUTENTICO) y CITA (no se bajan hilos de comentarios).
INCLUIR_COMENTARIOS = False

# Configuración de rutas relativas
ROOT_PATH = Path(__file__).resolve().parents[2]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

import clean_project.config.settings as config

from clean_project.vllm.model_config import (
    MODELO_ACTIVO, VISION_HABILITADA, EXTRA_BODY_LLM, MAX_TOKENS_GATEKEEPER,
)
MODELO_VLM = MODELO_ACTIVO

# Cliente vLLM
# PARA DEBUGEAR AISLADO CAMBIAR http://host.docker.internal:8001/v1 POR http://localhost:8001/v1
client = AsyncOpenAI(base_url="http://host.docker.internal:8001/v1", api_key="local-token")
# MODELO_VLM = "Qwen/Qwen2.5-14B-Instruct-AWQ"#"Qwen/Qwen2.5-VL-7B-Instruct"

# Semáforo para no saturar la red
SEM = asyncio.Semaphore(10)

ERROR_LOG_PATH = None  # se fija en run_bluesky() según la carpeta de salida
# =====================================================
# 1. UTILIDADES DE APOYO
# =====================================================

def generar_id_anonimo(username):
    if not username: return "UNKNOWN"
    return hashlib.sha256(username.encode()).hexdigest()[:16].upper()

async def download_image_b64(session, url):
    if not url: return None
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                content = await resp.read()
                return base64.b64encode(content).decode('utf-8')
    except:
        return None

def parse_bluesky_date(fecha_iso):
    try:
        # Manejo más robusto de fechas ISO de Bluesky
        clean_date = fecha_iso.split('.')[0].replace("Z", "")
        return datetime.fromisoformat(clean_date)
    except:
        return None
    
async def get_author_followers(session, did: str, headers: dict):
    """Nº de seguidores, o None si no se pudo saber (para no confundir 'error' con '0 seguidores')."""
    url = "https://bsky.social/xrpc/app.bsky.actor.getProfile"
    data, error = await peticion_con_reintentos(session, "GET", url, headers=headers, params={"actor": did})
    if error:
        registrar_error(keyword="", etapa="get_author_followers", motivo=error, uri=did)
        return data.get("followersCount", 0)    
    return data.get("followersCount", 0)    

async def peticion_con_reintentos(session, metodo, url, max_reintentos=5, backoff_base=2, **kwargs):
    """
    Ejecuta una petición HTTP con reintentos y backoff exponencial (espera = backoff_base ** intento).
    Devuelve (json, None) si tiene éxito, o (None, motivo) si se agotan los reintentos —
    así el llamador puede distinguir "sin resultados" de "no se pudo saber".
    """
    kwargs.setdefault("timeout", aiohttp.ClientTimeout(total=15))
    ultimo_error = "desconocido"

    for intento in range(max_reintentos):
        try:
            async with SEM:
                async with session.request(metodo, url, **kwargs) as resp:
                    if resp.status == 429:
                        try:
                            espera = float(resp.headers.get("Retry-After", backoff_base ** intento))
                        except (TypeError, ValueError):
                            espera = backoff_base ** intento
                        await asyncio.sleep(espera)
                        continue
                    if resp.status >= 500:
                        ultimo_error = f"HTTP {resp.status}"
                        await asyncio.sleep(backoff_base ** intento)
                        continue
                    if resp.status != 200:
                        return None, f"HTTP {resp.status}"  # error 4xx real: reintentar no sirve de nada
                    return await resp.json(), None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            ultimo_error = str(e)
            await asyncio.sleep(backoff_base ** intento)

    return None, f"reintentos agotados ({max_reintentos}): {ultimo_error}"

def registrar_error(**campos):
    """Deja constancia de cada fallo para poder auditar después qué se perdió y por qué."""
    campos["timestamp"] = datetime.now().isoformat()
    fieldnames = ["timestamp", "keyword", "etapa", "motivo", "uri", "hasta"]
    existe = ERROR_LOG_PATH.exists()
    with open(ERROR_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
        if not existe:
            writer.writeheader()
        writer.writerow({k: campos.get(k, "") for k in fieldnames})

def clasificar_tipo_post(p):
    """
    Clasifica un post de Bluesky según su naturaleza real:
    - POST: post auténtico, sin reply, sin cita.
    - CITA: post que cita a otro post (embed tipo record o recordWithMedia).
    - COMENTARIO_A_POST: respuesta directa a un post original (parent == root).
    - COMENTARIO_A_COMENTARIO: respuesta a otro comentario (parent != root).
    """
    record = p.get("record", {})
    reply = record.get("reply")
    embed_view = p.get("embed", {})
    embed_type = embed_view.get("$type", "")

    es_cita = embed_type in ("app.bsky.embed.record#view", "app.bsky.embed.recordWithMedia#view")

    if reply:
        root_uri = reply.get("root", {}).get("uri")
        parent_uri = reply.get("parent", {}).get("uri")
        if root_uri and parent_uri and root_uri == parent_uri:
            return "COMENTARIO_A_POST"
        return "COMENTARIO_A_COMENTARIO"

    if es_cita:
        # return "CITA"
        return "POST"

    return "POST"

def extraer_texto_citado(p):
    """
    Si el post es una cita (embed tipo record/recordWithMedia), extrae el texto
    del post original citado. Devuelve "" si no aplica o no se puede extraer.
    """
    embed_view = p.get("embed", {})
    embed_type = embed_view.get("$type", "")

    record_view = None
    if embed_type == "app.bsky.embed.record#view":
        record_view = embed_view.get("record", {})
    elif embed_type == "app.bsky.embed.recordWithMedia#view":
        record_view = embed_view.get("record", {}).get("record", {})

    if not record_view:
        return ""

    return record_view.get("value", {}).get("text", "")

# =====================================================
# 2. EL PORTERO (GATEKEEPER) MULTIMODAL
# =====================================================

async def verificar_relevancia_vlm(post_data, b64_image, u_conf):
    """
    Analiza si el post de Bluesky es relevante antes de bajar el hilo.
    """
    keywords_str = ", ".join(u_conf.general["keywords"])
    text = post_data.get("record", {}).get("text", "")
    author = post_data.get("author", {}).get("displayName", "Usuario")

    geo_instruction = ""
    if "GLOBAL" in u_conf.population_scope.upper():
        geo_instruction = " Filtro desactivado. Acepta comentarios de cualquier ubicación geográfica."
    else:
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

    prompt = f"""
    TAREA: Determinar si este post de Bluesky es RELEVANTE.
    TEMA: {u_conf.tema}
    CONTEXTO PARA CONTEXTUALIZAR EL TEMA: {u_conf.desc_tema}
    KEYWORDS RELACIONADAS CON EL TEMA: {keywords_str}
    UBICACIÓN OBJETIVO: {u_conf.population_scope}

    DATOS DEL POST:
    - Autor: {author}
    - Texto: {text}

    REGLAS:
    1. Prioridad semántica: Si el texto trata sobre el tema o tiene términos relacionados con el tema o el contexto o las keywords relacionadas -> RELEVANTE.
    2. Imagen: Úsala solo si el texto es ambiguo.
    3. Geografía: {geo_instruction}
    4. Si no se puede inferir ubicación marcar como RELEVANTE, no descartar por defecto.
    5. En caso de duda, marcar como RELEVANTE para no perder datos potenciales.

    Responde en JSON: {{"relevante": true/false, "razon_relevancia": "...", "idioma": "...", "idioma_justificacion": "..."}}
    """

    content = [{"type": "text", "text": prompt}]
    if VISION_HABILITADA and b64_image:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}})

    raw, response = None, None
    try:
        response = await client.chat.completions.create(
            model=MODELO_VLM,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=MAX_TOKENS_GATEKEEPER,
            extra_body=EXTRA_BODY_LLM,
        )
        raw = response.choices[0].message.content
        res, _ = json.JSONDecoder().raw_decode(raw)
        return res.get("relevante", False), res.get("razon_relevancia", "N/A"), res.get("idioma", "Desconocido"), res.get("idioma_justificacion", "N/A")
    except Exception as e:
        fr = response.choices[0].finish_reason if response else None
        print(f"⚠️ Raw LLM (fallo parseo, finish_reason={fr}): {raw!r} | {e}")
        return True, "Error en validación, se mantiene por precaución", "Desconocido", "N/A"

# =====================================================
# 3. FUNCIONES DE COMUNICACIÓN BLUESKY
# =====================================================

async def fetch_posts(session, keyword, headers, start_date, end_date):
    url = "https://bsky.social/xrpc/app.bsky.feed.searchPosts"
    todos_los_posts = []
    limite_superior = end_date

    while True:
        query_string = f"{keyword} since:{start_date} until:{limite_superior}"
        params = {"q": query_string, "limit": 100, "sort": "latest"}

        data, error = await peticion_con_reintentos(session, "GET", url, headers=headers, params=params)

        if error:
            registrar_error(keyword=keyword, etapa="fetch_posts", motivo=error, hasta=limite_superior)
            break  # se detiene la paginación; el hueco queda registrado, no oculto

        posts_pagina = data.get("posts", [])
        if not posts_pagina:
            break

        todos_los_posts.extend(posts_pagina)
        # Los duplicados que puedan solaparse en el límite de página ya los filtra
        # 'seen_uris' en run_bluesky — no hace falta dedup aquí también.

        if len(posts_pagina) < 100:
            break  # última página: menos resultados que el límite = no queda nada más

        limite_superior = min(p["record"]["createdAt"] for p in posts_pagina)

    return todos_los_posts

async def fetch_thread(session, uri, headers):
    url = "https://bsky.social/xrpc/app.bsky.feed.getPostThread"
    data, error = await peticion_con_reintentos(session, "GET", url, headers=headers, params={"uri": uri, "depth": 1})
    if error:
        registrar_error(keyword="", etapa="fetch_thread", motivo=error, uri=uri)
        return {}
    return data.get("thread", {})

# =====================================================
# 4. LÓGICA PRINCIPAL
# =====================================================

async def run_bluesky(u_conf):
    print(f"🚀 Bluesky Scraper Multimodal para: {u_conf.tema}")
    
    output_folder = Path(u_conf.general["output_folder"])
    output_folder.mkdir(parents=True, exist_ok=True)
    media_folder = output_folder / "media"
    media_folder.mkdir(exist_ok=True)

    global ERROR_LOG_PATH
    ERROR_LOG_PATH = output_folder / "errores_recoleccion.csv"

    csv_path = output_folder / "bluesky_global_dataset.csv"
    
    username = config.CREDENTIALS["bluesky"]["USERNAME_bluesky"]
    password = config.CREDENTIALS["bluesky"]["PASSWORD_bluesky"]

    async with aiohttp.ClientSession() as session:
        # Auth
        async with session.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                                json={"identifier": username, "password": password}) as resp:
            auth = await resp.json()
            headers = {"Authorization": f"Bearer {auth['accessJwt']}"}

        seen_uris = set()
        count_total = 0
        
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow([
                "tipo", "uri", "parent_uri", "fecha", "usuario", "id_anonimo", "contenido", 
                "likes", "reposts", "replies", "media_path", "idioma_ia", "idioma_ia_just", "relevancia_ia", "relevancia_just",
                "seguidores", "texto_citado" 
            ])

            for kw in u_conf.general["keywords"]:
                print(f"🔍 Buscando en Bluesky: {kw}")
                posts = await fetch_posts(session, kw, headers, u_conf.general["start_date"], u_conf.general["end_date"])
                print(f"   -> Encontrados {len(posts)} posts brutos.")

                for p in posts:
                    uri = p["uri"]
                    if uri in seen_uris: continue
                    seen_uris.add(uri)
                    tipo_real = clasificar_tipo_post(p)
                    print(tipo_real)

                    if not INCLUIR_COMENTARIOS and tipo_real in ("COMENTARIO_A_POST", "COMENTARIO_A_COMENTARIO"):
                        continue

                    texto_citado = extraer_texto_citado(p) # if tipo_real == "CITA" else ""
                    print(texto_citado)


                    # Extraer imagen
                    img_url = None
                    embed = p.get("embed", {})
                    if embed.get("$type") == "app.bsky.embed.images":
                        img_url = embed["images"][0]["fullsize"]
                    
                    b64_img = await download_image_b64(session, img_url)

                    # --- PASO PORTERO ---
                    es_relevante, razon, idioma, idioma_justificacion = await verificar_relevancia_vlm(p, b64_img, u_conf)
                    
                    if not es_relevante:
                        print(f"   ⏩ SALTADO: {p['record'].get('text', '')[:40]}... | Razón: {razon}")
                        continue

                    # Guardar imagen
                    local_img_path = ""
                    if b64_img:
                        filename = f"bsky_{generar_id_anonimo(uri)}.jpg"
                        with open(media_folder / filename, "wb") as img_f:
                            img_f.write(base64.b64decode(b64_img))
                        local_img_path = f"media/{filename}"

                    author_did = p["author"]["did"]
                    seguidores = await get_author_followers(session, author_did, headers)

                    # Guardar Post
                    writer.writerow([
                        tipo_real, uri, uri, p["record"]["createdAt"], p["author"]["handle"],
                        generar_id_anonimo(p["author"]["handle"]), p["record"]["text"],
                        p.get("likeCount", 0), p.get("repostCount", 0), p.get("replyCount", 0),
                        local_img_path, idioma, idioma_justificacion, "SI", razon, seguidores, texto_citado
                    ])
                    count_total += 1

                    # Comentarios
                    if p.get("replyCount", 0) > 0:
                        thread = await fetch_thread(session, uri, headers)
                        for reply in thread.get("replies", []):
                            rep_post = reply.get("post", {})
                            if not rep_post: continue
                            
                            writer.writerow([
                                "COMENTARIO", rep_post["uri"], uri, rep_post["record"]["createdAt"],
                                rep_post["author"]["handle"], generar_id_anonimo(rep_post["author"]["handle"]),
                                rep_post["record"]["text"], rep_post.get("likeCount", 0),
                                rep_post.get("repostCount", 0), rep_post.get("replyCount", 0),
                                "", idioma, "", "SI", "", "", ""
                            ])
                            count_total += 1

    print(f"✅ Bluesky finalizado. Total registros guardados: {count_total}")


# =====================================================
# DEBUG AISLADO
# =====================================================
if __name__ == "__main__":
    from types import SimpleNamespace
    mock_conf = SimpleNamespace(
        tema="ROSALIA",# LUX TOUR",#"Pantalán de Sagunto",
        desc_tema="Rosalia es una cantante española",#"La cuarta gira de conciertos de la cantante española Rosalía, promoviendo su álbum 'Lux', comenzará el 16 de marzo de 2026 en Lyon, Francia, y finalizará el 3 de septiembre de 2026 en San Juan, Puerto Rico.",#"Infraestructura portuaria renovada en Sagunto, Valencia.",
        population_scope="GLOBAL",#"España",
        general={
            "output_folder": "./debug_bsky",
            "keywords": ["ROSALIA"], #"Rosalía LUX 2026", "conciertos rosalía 2026", "lux tour rosalía", "rosalía en gira 2026"],#["pantalán sagunto", "puerto sagunto"],
            "start_date": "2026-04-22",#"2026-03-01",#"2025-02-01",
            "end_date": "2026-04-24",#"2026-04-21"
        }
    )
    asyncio.run(run_bluesky(mock_conf))