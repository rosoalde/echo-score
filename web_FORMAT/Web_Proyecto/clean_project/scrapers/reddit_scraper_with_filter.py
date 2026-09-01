import asyncio
import csv
import json
import hashlib
import requests
import re
import os
import sys
import base64
from pathlib import Path
from datetime import datetime
import asyncpraw
from openai import OpenAI
from types import SimpleNamespace

# Configuración de rutas
ROOT_PATH = Path(__file__).resolve().parents[2]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

import clean_project.config.settings as config
from clean_project.vllm.model_config import MODELO_ACTIVO, VISION_HABILITADA
MODELO_VLM = MODELO_ACTIVO

client = OpenAI(base_url="http://localhost:8001/v1", api_key="local-token")

# =====================================================
# 1. UTILIDADES
# =====================================================

def generar_id_anonimo(username):
    if not username: return "UNKNOWN"
    return hashlib.sha256(username.encode()).hexdigest()[:16].upper()

def download_to_base64(url):
    if not url: return None
    try:
        headers = {'User-Agent': 'SocialInsight/2.0'}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            return base64.b64encode(res.content).decode('utf-8')
    except: return None
    return None

def extraer_urls_imagenes(obj):
    """Extrae URLs de imágenes/GIFs de un post o comentario de Reddit."""
    urls = []
    if hasattr(obj, 'url'):
        if any(obj.url.lower().endswith(ext) for ext in ['.jpg', '.png', '.jpeg', '.gif']):
            urls.append(obj.url)
    if hasattr(obj, 'media_metadata') and obj.media_metadata:
        for item in obj.media_metadata.values():
            if 's' in item and 'u' in item['s']:
                urls.append(item['s']['u'])
    return list(set(urls))

async def _get_karma(author) -> int:
    if not author:
        return 0
    try:
        await author.load()
        return author.total_karma
    except Exception:
        return 0
# =====================================================
# 2. EL PORTERO (GATEKEEPER) REDDIT
# =====================================================

async def verificar_relevancia_vlm_reddit(post, b64_images, u_conf):
    keywords_str = ", ".join(u_conf.general["keywords"])
    subreddit_name = post.subreddit.display_name

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

    prompt = f"""
    TAREA: Determinar si este contenido de Reddit es RELEVANTE.
    TEMA: {u_conf.tema}
    CONTEXTO: {u_conf.desc_tema}
    KEYWORDS: {keywords_str}

    DATOS DE ENTRADA:
    - Subreddit: r/{subreddit_name}
    - Título: {post.title}
    - Texto: {post.selftext[:500]}

    REGLAS:
    1. Herencia de Contexto: Si el subreddit es conocido por tratar temas relacionados con {u_conf.tema} o el contexto, eso sugiere relevancia.
    2. Prioridad semántica: Si trata sobre el tema o términos relacionados -> RELEVANTE.
    3. Imagen: Úsala para confirmar el contexto si el texto es breve.
    4. Geografía: {geo_instruction}
    5. Si no se puede inferir ubicación marcar como RELEVANTE, no descartar por defecto.
    6. En caso de duda, marcar como RELEVANTE para no perder datos potenciales.

    Responde en JSON: {{"relevante": true/false, "razon": "...", "idioma": "..."}}
    """

    content = [{"type": "text", "text": prompt}]
    if VISION_HABILITADA:
        for b64 in b64_images[:2]:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    try:
        response = client.chat.completions.create(
            model=MODELO_VLM,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0
        )
        res = json.loads(response.choices[0].message.content)
        return res.get("relevante", False), res.get("razon", "N/A"), res.get("idioma", "Desconocido")
    except:
        return True, "Error en validación", "Desconocido"

# =====================================================
# 3. SCRAPER PRINCIPAL
# =====================================================

# Cabecera del CSV — se define una vez para consistencia
FIELDNAMES = [
    "tipo", "id_raiz", "id_propio", "fecha", "usuario", "karma", "id_anonimo",
    "contenido", "likes", "comments", "media_path", "fuente",
    "idioma_ia", "relevancia_ia"
]

async def run_reddit(u_conf):
    print(f"🚀 Reddit Scraper Multimodal para: {u_conf.tema}")

    output_folder = Path(u_conf.general["output_folder"])
    output_folder.mkdir(parents=True, exist_ok=True)
    media_folder = output_folder / "media" / "reddit"
    media_folder.mkdir(parents=True, exist_ok=True)

    csv_path = output_folder / "reddit_global_dataset.csv"

    # ── Abrir el CSV en modo append desde el inicio ──────────────────────
    # Esto garantiza que cada fila se persiste inmediatamente,
    # evitando pérdida de datos si el proceso se interrumpe.
    csv_file_handle = open(csv_path, 'w', newline='', encoding='utf-8')
    writer = csv.DictWriter(csv_file_handle, fieldnames=FIELDNAMES, delimiter=';')
    writer.writeheader()
    csv_file_handle.flush()

    rows_written = 0

    try:
        async with asyncpraw.Reddit(
            client_id=config.CREDENTIALS["reddit"]["reddit_client_id"],
            client_secret=config.CREDENTIALS["reddit"]["reddit_client_secret"],
            user_agent="SocialInsight/2.0"
        ) as reddit:

            seen_ids = set()
            start_dt = datetime.strptime(u_conf.general["start_date"], "%Y-%m-%d")
            end_dt   = datetime.strptime(u_conf.general["end_date"],   "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )

            for kw in u_conf.general["keywords"]:
                print(f"🔍 Buscando: {kw}")
                subreddit_all  = await reddit.subreddit("all")
                for orden in ("relevance", "new", "top"):
                    try:
                        search_results = subreddit_all.search(kw, sort=orden, syntax="plain", limit=1000) 
                        #subreddit_all.search({kw}, sort=orden)

                        async for post in search_results:
                            # ── Filtros básicos ──────────────────────────────
                            if post.id in seen_ids:
                                continue
                            fecha_p = datetime.fromtimestamp(post.created_utc)
                            # if not (start_dt <= fecha_p <= end_dt):
                            #     continue
                            if fecha_p > end_dt:
                                continue           # aún no llegamos a la ventana
                            if fecha_p < start_dt:
                                if orden == "new":
                                    break
                                continue

                            await post.load()
                            seen_ids.add(post.id)

                            # ── Media del post ───────────────────────────────
                            img_urls = extraer_urls_imagenes(post)
                            b64_imgs = [download_to_base64(u) for u in img_urls]
                            b64_imgs = [img for img in b64_imgs if img]

                            # ── Gatekeeper ───────────────────────────────────
                            es_relevante, razon, idioma = await verificar_relevancia_vlm_reddit(
                                post, b64_imgs, u_conf
                            )
                            if not es_relevante:
                                print(f"  ⏩ SALTADO: {post.title[:50]}... (Razón: {razon})")
                                continue

                            # ── Guardar imágenes localmente ──────────────────
                            local_paths = []
                            for i, b64 in enumerate(b64_imgs):
                                filename = f"red_{post.id}_{i}.jpg"
                                try:
                                    with open(media_folder / filename, "wb") as f:
                                        f.write(base64.b64decode(b64))
                                    local_paths.append(f"media/reddit/{filename}")
                                except Exception as e:
                                    print(f"⚠️ Error guardando imagen {filename}: {e}")

                            # ── Escribir fila POST inmediatamente ────────────
                            post_row = {
                                "tipo":         "POST",
                                "id_raiz":      post.id,
                                "id_propio":    post.id,
                                "fecha":        fecha_p.strftime("%Y-%m-%d %H:%M"),
                                "usuario":      post.author.name if post.author else "[deleted]",
                                "karma":        await _get_karma(post.author),
                                "id_anonimo":   generar_id_anonimo(post.author.name if post.author else "deleted"),
                                "contenido":    post.selftext if post.selftext else post.title,
                                "likes":        post.score,
                                "comments":     post.num_comments,
                                "media_path":   "|".join(local_paths),
                                "fuente":       f"r/{post.subreddit.display_name}",
                                "idioma_ia":    idioma,
                                "relevancia_ia":"SI"
                            }
                            writer.writerow(post_row)
                            csv_file_handle.flush()      # flush inmediato
                            rows_written += 1

                            # ── Comentarios directos ─────────────────────────
                            try:
                                await post.comments.replace_more(limit=0)
                                for comment in post.comments:
                                    c_urls     = extraer_urls_imagenes(comment)
                                    c_b64      = download_to_base64(c_urls[0]) if c_urls else None
                                    c_local_path = ""
                                    if c_b64:
                                        c_filename = f"red_comm_{comment.id}.jpg"
                                        try:
                                            with open(media_folder / c_filename, "wb") as f:
                                                f.write(base64.b64decode(c_b64))
                                            c_local_path = f"media/reddit/{c_filename}"
                                        except Exception as e:
                                            print(f"⚠️ Error guardando imagen comentario: {e}")

                                    comment_row = {
                                        "tipo":         "COMENTARIO",
                                        "id_raiz":      post.id,
                                        "id_propio":    comment.id,
                                        "fecha":        datetime.fromtimestamp(comment.created_utc).strftime("%Y-%m-%d %H:%M"),
                                        "usuario":      comment.author.name if comment.author else "[deleted]",
                                        "karma":        await _get_karma(comment.author),
                                        "id_anonimo":   generar_id_anonimo(comment.author.name if comment.author else "deleted"),
                                        "contenido":    comment.body,
                                        "likes":        comment.score,
                                        "comments":     len(comment.replies),
                                        "media_path":   c_local_path,
                                        "fuente":       f"r/{post.subreddit.display_name}",
                                        "idioma_ia":    idioma,
                                        "relevancia_ia":"SI"
                                    }
                                    writer.writerow(comment_row)
                                    rows_written += 1

                                # Flush cada post completo (post + sus comentarios)
                                csv_file_handle.flush()

                            except Exception as e:
                                print(f"⚠️ Error procesando comentarios del post {post.id}: {e}")
                                csv_file_handle.flush()   # asegurar lo que ya se escribió

                    except asyncio.CancelledError:
                        print(f"⚠️ Búsqueda cancelada para keyword: {kw}")
                        raise   # re-raise para que el caller lo gestione

                    except Exception as e:
                        print(f"⚠️ Error procesando keyword '{kw}'/ sort={orden}: {e}")
                    csv_file_handle.flush()   # guardar lo que haya hasta ahora
                    continue                  # pasar a la siguiente keyword

    finally:
        # Garantizado: siempre cerramos el archivo aunque haya excepción
        csv_file_handle.close()
        if rows_written == 0:
            print("⚠️ No se encontraron posts relevantes para Reddit. El CSV quedará vacío (solo cabecera).")
        else:
            print(f"✅ Reddit: {rows_written} filas guardadas en {csv_path.name}")


# =====================================================
# DEBUG AISLADO
# =====================================================
if __name__ == "__main__":
    mock_conf = SimpleNamespace(
        tema="ROSALIA",#"Pantalán de Sagunto",
        desc_tema="Rosalia es una cantante española",#"Renovación de la infraestructura portuaria en Sagunto.",
        population_scope="GLOBAL",#"España",
        #languages=["es"],
        general={
            "output_folder": "./debug_reddit",
            "keywords": ["ROSALIA"], #["pantalán sagunto", "puerto sagunto"],
            "start_date": "2026-04-01",#"2025-02-01",
            "end_date": "2026-04-30",#"2026-04-21"
        },
        scraping={"reddit": {"limit": None}}
    )
    asyncio.run(run_reddit(mock_conf))