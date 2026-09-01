"""
MASTODON SCRAPER
================
"""

import asyncio
import aiohttp
import csv
import hashlib
import json
import sys
import re
from pathlib import Path
from datetime import datetime
from openai import OpenAI
from types import SimpleNamespace

ROOT_PATH = Path(__file__).resolve().parents[2]
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

import clean_project.config.settings as config    

from clean_project.vllm.model_config import MODELO_ACTIVO, VISION_HABILITADA
MODELO_VLM = MODELO_ACTIVO

client = OpenAI(base_url="http://localhost:8001/v1", api_key="local-token")

# Rede social descentralizada con muchas instancias públicas. https://instances.social permite buscar en todas las instancias, pero es lento y no devuelve texto completo. Mejor hacer búsquedas individuales por instancia usando su API (si no requiere token) o registrando una app para obtener token de solo lectura (si lo requiere).
MASTODON_INSTANCES = [
    "mastodon.social",       # la más grande, mezcla de idiomas
#     "mas.to",                # general, mucho español
#     "mastodon.online",       # general
#     "social.coop",           # cooperativista, español presente
#     "kolektiva.social",      # activismo, mucho español de LATAM
#     "todon.nl",              # progresista, español presente
#     "social.quodverum.com",  # política española
#     "mastodon.eus",          # País Vasco / euskera + castellano
#     "mastodont.cat",         # Cataluña / catalán + castellano
#     "masto.es",              # Hispanohablante, general
#     "sociale.network",       # Italia pero acepta español
#     "social.politicaconciencia.org",  # política
#     "xarxa.cloud",
#     "mstdn.social",
#     "todon.eu",
#     "mastodon.jalgi.eus",
#     "masto.pt",
#     "colorid.es",
#     "ciberlandia.pt",
#     "mastodon.uno",
#     "bologna.one",
#     "oc.todon.fr",
 ]


SEM = asyncio.Semaphore(5)

# ── Caché de tokens ───────────────────────────────────────────────────────────
TOKENS_PATH = Path(__file__).resolve().parent / "mastodon_tokens.json"
try:
    tokens_cache = json.loads(TOKENS_PATH.read_text())
except Exception:
    tokens_cache = {}


mastodon_token  = config.CREDENTIALS["mastodon"]["token"]
if mastodon_token:  # si existe y no es None
    tokens_cache["mastodon.social"] = mastodon_token
    # Guardamos la caché actualizada
    TOKENS_PATH.write_text(json.dumps(tokens_cache, indent=2))
# ─────────────────────────────────────────────────────────────────────────────


def generar_id_anonimo(username: str) -> str:
    if not username:
        return "UNKNOWN"
    return hashlib.sha256(username.encode()).hexdigest()[:16].upper()


def limpiar_html(texto: str) -> str:
    texto = re.sub(r"<br\s*/?>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", "", texto)
    return texto.strip()


async def obtener_token(session, instance):
    """Registra una app y obtiene token de solo lectura automáticamente."""
    try:
        async with session.post(
            f"https://{instance}/api/v1/apps",
            data={
                "client_name": "research_scraper",
                "redirect_uris": "urn:ietf:wg:oauth:2.0:oob",
                "scopes": "read",
            },
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                return None
            app = await resp.json()

        async with session.post(
            f"https://{instance}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": app["client_id"],
                "client_secret": app["client_secret"],
                "scope": "read",
            },
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                return None
            return (await resp.json()).get("access_token")
    except Exception as e:
        print(f"   ⚠️ No se pudo obtener token de {instance}: {e}")
        return None
    
async def obtener_respuestas(session, instance, post_id, token=None):
    """Obtiene todos los comentarios (descendants) de un post específico."""
    url = f"https://{instance}/api/v1/statuses/{post_id}/context"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with SEM:
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                print(f"         context API status: {resp.status}")
                if resp.status == 200:
                    datos = await resp.json()
                    # 'descendants' son las respuestas (comentarios)
                    print(f"         ancestors: {len(datos.get('ancestors', []))}, descendants: {len(datos.get('descendants', []))}")
                    return datos.get("descendants", [])
                return []
        except Exception as e:
            print(f"         ❌ Error context: {e}")
            return []

async def search_mastodon(session, instance, keyword, token=None, limit=40, max_id=None):
    url = f"https://{instance}/api/v2/search"
    params = {"q": keyword, "type": "statuses", "limit": limit, "resolve": "false"}
    if max_id:
        params["max_id"] = max_id        # ← paginación correcta
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with SEM:
        try:
            async with session.get(url, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    print(f"   ⚠️ {instance} devolvió {resp.status}")
                    return []
                return (await resp.json()).get("statuses", [])
        except Exception as e:
            print(f"   ⚠️ Error en {instance}: {e}")
            return []


async def verificar_relevancia(post_text, author, u_conf):
    keywords_str = ", ".join(u_conf.general["keywords"])
    geo_instruction = (
        "Filtro desactivado. Acepta cualquier ubicación geográfica."
        if "GLOBAL" in u_conf.population_scope.upper()
        else f"Solo relevante si menciona o permite inferir {u_conf.population_scope}."
    )
    prompt = f"""
    Determina si este post de Mastodon es RELEVANTE.
    TEMA: {u_conf.tema}
    CONTEXTO: {u_conf.desc_tema}
    KEYWORDS: {keywords_str}
    GEOGRAFÍA: {geo_instruction}

    Autor: {author}
    Texto: {post_text[:500]}

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


async def run_mastodon(u_conf):
    print(f"🐘 Mastodon Scraper para: {u_conf.tema}")

    output_folder = Path(u_conf.general["output_folder"])
    output_folder.mkdir(parents=True, exist_ok=True)
    csv_path = output_folder / "mastodon_global_dataset.csv"

    start_dt = datetime.strptime(u_conf.general["start_date"], "%Y-%m-%d")
    end_dt = datetime.strptime(u_conf.general["end_date"], "%Y-%m-%d").replace(
        hour=23, minute=59, second=59
    )

    seen_ids = set()
    count = 0

    async with aiohttp.ClientSession() as session:

        # ── Obtener tokens para todas las instancias ──────────────────────────
        for instance in MASTODON_INSTANCES:
            if instance not in tokens_cache:
                print(f"   🔑 Registrando app en {instance}...")
                token = await obtener_token(session, instance)
                if token:
                    tokens_cache[instance] = token
                    TOKENS_PATH.write_text(json.dumps(tokens_cache))
                    print(f"   ✅ Token guardado para {instance}")
                else:
                    print(f"   ❌ Sin token para {instance} — búsqueda limitada")
            else:
                print(f"   ✅ Token cargado para {instance}")
        # ─────────────────────────────────────────────────────────────────────

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL)
            writer.writerow([
                "tipo", "id", "url", "fecha", "edited_at", "usuario", "id_anonimo",
                "contenido", "likes", "reposts", "quotes", "replies",
                "idioma_declarado", "visibility", "sensitive", "tiene_media",
                "es_reblog", "in_reply_to_id", "hashtags", "followers",
                "bot", "instancia", "idioma_ia", "relevancia_ia",
            ])

            for kw in u_conf.general["keywords"]:
                for instance in MASTODON_INSTANCES:
                    print(f"\n   🔍 [{instance}] Buscando: {kw}")
                    token = tokens_cache.get(instance)


                    max_id = None
                    while True:
                        posts = await search_mastodon(session, instance, kw,
                                                    token=token, limit=40, max_id=max_id)
                        if not posts:
                            break
                        max_id = posts[-1]["id"]    
                        for p in posts:
                            # [p.get("content", "")[:50] for p in posts]  # debug contenido
                            pid = p.get("id", "")
                            if pid in seen_ids:
                                continue

                            created_raw = p.get("created_at", "")
                            try:
                                fecha_p = datetime.fromisoformat(
                                    created_raw.replace("Z", "+00:00")
                                ).replace(tzinfo=None)
                            except Exception:
                                continue

                            if not (start_dt <= fecha_p <= end_dt):
                                print(f"      ❌ POST RECHAZADO POR FECHA: {fecha_p}") # <--- AÑADE ESTO
                                continue

                            seen_ids.add(pid)

                            texto = limpiar_html(p.get("content", ""))
                            autor = p.get("account", {}).get("acct", "")
                            dirección_url = p.get("url", "")
                            print(f"   ➡️ Evaluando post {pid} de {autor} {dirección_url} en {instance}...")

                            es_rel, razon, idioma = await verificar_relevancia(texto, autor, u_conf)
                            if not es_rel:
                                print(f"      ⏩ SALTADO: {texto[:50]}… | {razon}")
                                continue

                            print(f"      ✅ GUARDADO: {texto}…")

                            hashtags = ",".join(t["name"] for t in p.get("tags", []))

                            writer.writerow([
                                "POST",
                                pid,
                                p.get("url", ""),
                                fecha_p.strftime("%Y-%m-%d %H:%M"),
                                p.get("edited_at", "") or "",
                                autor,
                                generar_id_anonimo(autor),
                                texto,
                                p.get("favourites_count", 0),
                                p.get("reblogs_count", 0),
                                p.get("quotes_count", 0),
                                p.get("replies_count", 0),
                                p.get("language", "") or "",
                                p.get("visibility", "public"),
                                "SI" if p.get("sensitive") else "NO",
                                "SI" if p.get("media_attachments") else "NO",
                                "SI" if p.get("reblog") else "NO",
                                p.get("in_reply_to_id", "") or "",
                                hashtags,
                                p.get("account", {}).get("followers_count", 0),
                                "SI" if p.get("account", {}).get("bot") else "NO",
                                instance,
                                idioma,
                                "SI",
                            ])
                            count += 1
                            print(f"      💬 replies_count={p.get('replies_count', 0)} para post {pid}")
                            if p.get("replies_count", 0) > 0:
                                print(f"      💬 Obteniendo {p.get('replies_count')} respuestas...")
                                comentarios = await obtener_respuestas(session, instance, pid, token=token)
                                print(f"      💬 {len(comentarios)} respuestas recibidas")
    
                                for c in comentarios:
                                    cid = c.get("id", "")
                                    if not cid or cid in seen_ids:
                                        continue
                                    seen_ids.add(cid)
                                    
                                    texto_c  = limpiar_html(c.get("content", ""))
                                    autor_c  = c.get("account", {}).get("acct", "")
                                    fecha_c_raw = c.get("created_at", "")
                                    
                                    try:
                                        fecha_c = datetime.fromisoformat(
                                            fecha_c_raw.replace("Z", "+00:00")
                                        ).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")
                                    except Exception:
                                        fecha_c = fecha_c_raw
                                    
                                    hashtags_c = ",".join(t["name"] for t in c.get("tags", []))
                                    
                                    writer.writerow([
                                        "COMENTARIO",
                                        cid,
                                        c.get("url", ""),
                                        fecha_c,
                                        c.get("edited_at", "") or "",
                                        autor_c,
                                        generar_id_anonimo(autor_c),
                                        texto_c,
                                        c.get("favourites_count", 0),   # likes del comentario
                                        c.get("reblogs_count", 0),       # reposts del comentario
                                        c.get("quotes_count", 0),        # quotes
                                        c.get("replies_count", 0),       # respuestas anidadas
                                        c.get("language", "") or "",
                                        c.get("visibility", "public"),
                                        "SI" if c.get("sensitive") else "NO",
                                        "SI" if c.get("media_attachments") else "NO",
                                        "SI" if c.get("reblog") else "NO",
                                        pid,                             # parent = post original
                                        hashtags_c,
                                        c.get("account", {}).get("followers_count", 0),
                                        "SI" if c.get("account", {}).get("bot") else "NO",
                                        instance,
                                        idioma,                          # hereda idioma del post padre
                                        "HEREDADA",
                                    ])
                                    count += 1
                                    print(f"         💬 Comentario de @{autor_c}: {texto_c[:50]}…")
                                    print(f"         💬 Comentario de {autor_c} guardado.")    

                        
                        if len(posts) < 40:
                            break
                        await asyncio.sleep(1)

                    print(f"   → {count} posts guardados hasta ahora")

    print(f"\n✅ Mastodon finalizado. {count} posts guardados en {csv_path}")


if __name__ == "__main__":
    mock_conf = SimpleNamespace(
        tema="Visita Papa León XIV a España",
        desc_tema="visita del Papa León XIV a España en junio de 2026",
        population_scope="GLOBAL",
        general={
            "output_folder": "./debug_mastodon",
            "keywords": ["papa leon xiv", "papa", "leon xiv"],
            "start_date": "2026-04-01",
            "end_date": "2026-06-09",
        },
    )
    asyncio.run(run_mastodon(mock_conf))