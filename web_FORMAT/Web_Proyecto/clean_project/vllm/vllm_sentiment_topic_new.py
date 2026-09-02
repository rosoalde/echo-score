import pandas as pd
from pathlib import Path
import time
import re
import json
import concurrent.futures
from openai import OpenAI
from types import SimpleNamespace
import os
import base64
from collections import Counter
import numpy as np


## DESCOMENTAR 
# import sys
# ROOT_PATH = Path("/home/romina/RRSS_FORTMAT/web_FORMAT/Web_Proyecto")
# sys.path.insert(0, str(ROOT_PATH))
# import clean_project.config.settings as config
##

from clean_project.vllm.model_config import MODELO_ACTIVO, VISION_HABILITADA
MODEL_NAME = MODELO_ACTIVO

# =====================================================
# CONFIGURACIÓN vLLM
# =====================================================

client = OpenAI(
    base_url="http://host.docker.internal:8001/v1",
    api_key="local-token",
    timeout=60.0
)

# # MODELO MULTIMODAL para análisis con imágenes
# MODELO_VISION = "Qwen/Qwen2.5-14B-Instruct-AWQ"#"Qwen/Qwen2.5-VL-7B-Instruct"
# # MODELO TEXTO para análisis rápido sin imágenes
# MODELO_TEXTO = "Qwen/Qwen2.5-14B-Instruct-AWQ"#"Qwen/Qwen2.5-VL-7B-Instruct"

MICRO_BATCH_SIZE = 100  # Reducido para análisis multimodal
MAX_RETRIES = 2
NUM_CTX = 30000

# Memoria Global de Tópicos (con consolidación)
TOPIC_MEMORY = {}  # {topic_normalizado: count}
MAX_TOPICS = 30  # Límite máximo de topics únicos

# =====================================================
# UTILIDADES DE IMÁGENES
# =====================================================

def encode_image_base64(image_path):
    """Codifica imagen a base64 para el modelo"""
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        print(f"⚠️ Error codificando imagen {image_path}: {e}")
        return None

def load_image_from_path(media_path):
    """
    Carga imágenes desde media_path.
    Formato esperado: JSON array ["path1.jpg", "path2.png"]
    """
    if not media_path or pd.isna(media_path) or str(media_path).strip() in ["", "[]", "nan"]:
        return []
    
    try:
        paths = json.loads(media_path)
        if isinstance(paths, list):
            return [p for p in paths if p and os.path.exists(p)]
        elif isinstance(paths, str) and os.path.exists(paths):
            return [paths]
    except:
        # Si no es JSON, asumimos que es un path directo
        if os.path.exists(str(media_path)):
            return [str(media_path)]
    
    return []

def load_transcript(transcript_path):
    """Carga transcripción desde JSON"""
    if not transcript_path or pd.isna(transcript_path) or not os.path.exists(str(transcript_path)):
        return ""
    
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Formato: [{"text": "...", "start": ..., "duration": ...}, ...]
            if isinstance(data, list):
                return " ".join([segment.get("text", "") for segment in data])
            elif isinstance(data, str):
                return data
    except:
        pass
    
    return ""

# =====================================================
# EXTRACTOR JSON ROBUSTO
# =====================================================

# Orden fijo de columnas de análisis, usado tanto al parsear como al
# escribir en el DataFrame/CSV. La clave es el nombre final en el CSV
# (compatible con el modelo `records` del sistema de anotación); el
# comentario indica la clave del JSON del LLM de la que procede.
COLUMNAS_ANALISIS = [
    "pertinencia",          # <- relevante/irrelevante
    "justif_pertinencia",    # <- justificación pertinencia
    "lang",                # <- idioma (primer código)
    "justif_lang",          # <- idioma_just
    "world_continent",      # <- continente (primer código)
    "justif_continente",    # <- continente_just
    "world_country",        # <- pais (primer código)
    "justif_pais",           # <- pais_just
    "world_region",          # <- region
    "justif_region",          # <- region_just
    "world_city",              # <- ciudad
    "justif_ciudad",            # <- ciudad_just
    "posicion",                  # <- posicion
    "justif_posicion",            # <- posicion_just
    "topic_llm",                   # <- subtopic
    "justif_topic",                 # <- subtopic_just
    "sentiment_llm",                 # <- sent_subtopic
    "justif_sentimiento",             # <- sent_subtopic_just
]

def _primero_o_vacio(valor):
    """Colapsa una lista de códigos (idioma/continente/pais) al primer
    elemento para la columna escalar del CSV. Admite también un string
    suelto por si el LLM no respeta el formato de lista."""
    if isinstance(valor, list):
        return str(valor[0]).strip() if valor else ""
    if valor is None:
        return ""
    return str(valor).strip()

def _entero_seguro(valor, permitidos, default=2):
    """Convierte a int si es uno de los valores permitidos; si no, default."""
    try:
        v = int(valor)
        return v if v in permitidos else default
    except (TypeError, ValueError):
        return default

def _fila_vacia(motivo=""):
    """Fila de fallback cuando no se puede parsear el JSON del modelo."""
    return {
        "pertinencia": "irrelevante", "justif_pertinencia": motivo,
        "lang": "", "justif_lang": "",
        "world_continent": "", "justif_continente": "",
        "world_country": "", "justif_pais": "",
        "world_region": "", "justif_region": "",
        "world_city": "", "justif_ciudad": "",
        "posicion": 2, "justif_posicion": motivo,
        "topic_llm": "error", "justif_topic": motivo,
        "sentiment_llm": 2, "justif_sentimiento": motivo,
    }

def validar_json(data):
    """Valida y mapea el JSON del modelo (claves 'idioma', 'pais', 'subtopic',
    etc.) a las columnas finales del CSV (claves 'lang', 'world_country',
    'topic_llm', etc. — ver COLUMNAS_ANALISIS)."""
    if not isinstance(data, dict):
        return _fila_vacia("JSON no es un diccionario")

    resultado = {
        "pertinencia":        str(data.get("pertinencia", "irrelevante")).strip().lower(),
        "justif_pertinencia": str(data.get("justif_pertinencia", "") or "").strip(),
        "lang":               _primero_o_vacio(data.get("idioma")),
        "justif_lang":        str(data.get("idioma_just", "") or "").strip(),
        "world_continent":    _primero_o_vacio(data.get("continente")),
        "justif_continente":  str(data.get("continente_just", "") or "").strip(),
        "world_country":      _primero_o_vacio(data.get("pais")),
        "justif_pais":        str(data.get("pais_just", "") or "").strip(),
        "world_region":       str(data.get("region", "") or "").strip(),
        "justif_region":      str(data.get("region_just", "") or "").strip(),
        "world_city":         str(data.get("ciudad", "") or "").strip(),
        "justif_ciudad":      str(data.get("ciudad_just", "") or "").strip(),
        "posicion":           _entero_seguro(data.get("posicion"), {-1, 0, 1, 2}, default=2),
        "justif_posicion":    str(data.get("posicion_just", "") or "").strip(),
        "topic_llm":          str(data.get("subtopic", "") or "no relacionado").strip(),
        "justif_topic":       str(data.get("subtopic_just", "") or "").strip(),
        "sentiment_llm":      _entero_seguro(data.get("sent_subtopic"), {-1, 0, 1, 2}, default=2),
        "justif_sentimiento": str(data.get("sent_subtopic_just", "") or "").strip(),
    }

    if resultado["pertinencia"] not in ("relevante", "irrelevante"):
        resultado["pertinencia"] = "irrelevante"

    return resultado   

def extraer_json_clasificacion(raw):
    """Extrae la clasificación completa (16 campos) del JSON del modelo,
    con los mismos 3 niveles de tolerancia que la versión anterior
    (JSON directo, sin markdown, mayor bloque {...} válido)."""
    if not raw or not isinstance(raw, str):
        return _fila_vacia("respuesta vacía")
    
    raw = raw.strip()
    
    # Intento 1: JSON directo
    try:
        data = json.loads(raw)
        return validar_json(data)
    except Exception:
        pass
    
    # Intento 2: Limpiar markdown
    raw_clean = re.sub(r"```json|```", "", raw, flags=re.IGNORECASE).strip()
    try:
        data = json.loads(raw_clean)
        return validar_json(data)
    except Exception:
        pass
    
    # Intento 3: Extraer el JSON más grande
    def extract_largest_json(text):
        stack = []
        start_index = None
        candidates = []
        for i, char in enumerate(text):
            if char == "{":
                if not stack:
                    start_index = i
                stack.append(char)
            elif char == "}":
                if stack:
                    stack.pop()
                    if not stack and start_index is not None:
                        candidates.append(text[start_index:i+1])
        return max(candidates, key=len) if candidates else None
    
    bloque = extract_largest_json(raw_clean)
    if bloque:
        try:
            bloque = re.sub(r',\s*}', '}', bloque)
            bloque = re.sub(r',\s*]', ']', bloque)
            data = json.loads(bloque)
            return validar_json(data)
        except Exception:
            pass

    #=========================================
    # A diferencia de la versión anterior, NO hay regex de emergencia campo
    # a campo: con 18 claves no es fiable y añade más ruido del que evita.
    # response_format={"type": "json_object"} en la llamada a vLLM ya obliga
    # a JSON sintácticamente válido, así que este camino debería ser raro.
    return _fila_vacia("no se pudo parsear JSON")
    # # Intento 4: Regex de emergencia
    # try:
    #     sent_match = re.search(r'"?sentimiento"?\s*:\s*"?(-?1|0|2)"?', raw, re.IGNORECASE)
    #     topic_match = re.search(r'"?topic"?\s*:\s*"([^"]+)"', raw, re.IGNORECASE)
    #     lang_match = re.search(r'"?Idioma_Real"?\s*:\s*"([^"]+)"', raw, re.IGNORECASE)
        
    #     sentimiento = int(sent_match.group(1)) if sent_match else 2
    #     topic = topic_match.group(1).strip() if topic_match else "error"
    #     idioma = lang_match.group(1).strip() if lang_match else None
        
    #     return sentimiento, topic, idioma, 0
    # except:
    #     pass
    
    # return 2, "error", None, 0
    #=========================================

def validar_json(data):
    """Valida y extrae datos del JSON"""
    if not isinstance(data, dict):
        return 2, "no relacionado", "Desconocido", 0
    
    filtro = data.get("Verificacion_Filtro", {})
    idioma_detectado = str(filtro.get("Idioma_Real") or "Desconocido")
    pasa = str(filtro.get("Pasa_el_filtro", "")).upper()
    
    if "NO" in pasa:
        return 2, "no relacionado", idioma_detectado, 0
    
    if "Topics" in data and isinstance(data["Topics"], list) and data["Topics"]:
        item = data["Topics"][0]
        topic = item.get("Topic", "no relacionado")
        sentimiento = item.get("Sentimiento", 2)
        posicion = item.get("Posicion", 0)
        
        try:
            sentimiento = int(sentimiento)
        except:
            sentimiento = 2
        try:
            posicion = int(posicion)
            if posicion not in [-1, 0, 1]:
                posicion = 0
        except:
            posicion = 0    
        
        if sentimiento not in [1, -1, 0, 2]:
            sentimiento = 2
        
        return sentimiento, str(topic).strip(), idioma_detectado, posicion
    
    return 2, "no relacionado", idioma_detectado, 0

# =====================================================
# PREPARACIÓN DE CONTEXTO SEGÚN NUEVO ESQUEMA
# =====================================================

def preparar_contexto_multimodal(row, df_completo, red_social):
    """
    Prepara contexto completo incluyendo:
    - Texto del comentario
    - Contexto del post/video padre
    - Imágenes (si hay)
    - Transcripción (si hay)
    
    Returns:
        {
            "texto": str,
            "imagenes": [base64_strings],
            "tiene_media": bool
        }
    """
    
    def safe_text(val):
        if val is None or pd.isna(val) or str(val).strip().lower() in ["nan", "", "none"]:
            return ""
        return str(val).strip()
    
    # Textos basura
    contenido = safe_text(row.get("contenido"))
    if contenido.lower() in ["[removed]", "[deleted]", "nan", "", "none"]:
        return {"texto": "BORRADO", "imagenes": [], "tiene_media": False}
    
    tipo = safe_text(row.get("tipo"))
    es_comentario = tipo.lower() in ["comentario", "comment", "reply"]
    
    # ========================================
    # CONSTRUCCIÓN DE TEXTO
    # ========================================
    
    texto_partes = []
    
    # 1. CONTENIDO PRINCIPAL
    texto_partes.append(f"[CONTENIDO]\n{contenido}")

    # 1b. TEXTO CITADO: aplica tanto si esta fila es un POST/CITA con su
    # propio texto_citado, como más abajo si es un COMENTARIO cuyo padre
    # citaba algo (row.get() es seguro aunque el CSV no tenga la columna).
    texto_citado_propio = safe_text(row.get("texto_citado"))

    if texto_citado_propio:
        texto_partes.append(f"[POST CITADO]\n{texto_citado_propio[:500]}")
    
    # 2. CONTEXTO DEL PADRE (para comentarios)
    if es_comentario:
        if red_social == "reddit":
            # Buscar post padre por id_raiz
            id_raiz = safe_text(row.get("id_raiz"))
            if id_raiz:
                post_padre = df_completo[
                    (df_completo["tipo"] == "POST") & 
                    (df_completo["id_raiz"] == id_raiz)
                ]
                if not post_padre.empty:
                    padre_contenido = safe_text(post_padre.iloc[0].get("contenido"))
                    padre_fuente = safe_text(post_padre.iloc[0].get("fuente"))
                    
                    if padre_fuente:
                        texto_partes.insert(0, f"[SUBREDDIT]\n{padre_fuente}")
                    if padre_contenido:
                        texto_partes.insert(1, f"[POST PADRE]\n{padre_contenido[:500]}")
        
        elif red_social == "youtube":
            # Para YouTube, todos los comentarios comparten id_video
            id_video = safe_text(row.get("id_video"))
            titulo_video = safe_text(row.get("titulo_video"))
            
            if titulo_video:
                texto_partes.insert(0, f"[TÍTULO VIDEO]\n{titulo_video}")
            
            # Buscar transcripción del video
            transcripcion_path = safe_text(row.get("transcripcion"))
            if transcripcion_path:
                transcript_text = load_transcript(transcripcion_path)
                if transcript_text:
                    # Limitar transcripción a 1000 caracteres
                    texto_partes.insert(1, f"[TRANSCRIPCIÓN (extracto)]\n{transcript_text[:1000]}")
        
        elif red_social in ("bluesky", "telegram"):
            # Buscar post padre por parent_uri.
            # En POST/CITA, parent_uri == uri (self-reference, sin padre real);
            # solo aplica cuando esta fila es un comentario auténtico.
            parent_uri = safe_text(row.get("parent_uri"))
            propio_uri = safe_text(row.get("uri"))
            if parent_uri and parent_uri != propio_uri:
                post_padre = df_completo[
                    (df_completo["tipo"].str.lower() == "post") & 
                    (df_completo["uri"] == parent_uri)
                ]
                if not post_padre.empty:
                    fila_padre = post_padre.iloc[0]
                    padre_contenido = safe_text(fila_padre.get("contenido"))
                    if padre_contenido:
                        texto_partes.insert(0, f"[POST PADRE]\n{padre_contenido[:500]}")
                    # .get() es seguro aunque el CSV viejo no tenga la columna texto_citado
                    padre_texto_citado = safe_text(fila_padre.get("texto_citado"))
                    if padre_texto_citado:
                        texto_partes.insert(1, f"[TEXTO CITADO POR EL POST PADRE]\n{padre_texto_citado[:500]}")
            # [CANAL]: contexto del canal de Telegram, igual que [SUBREDDIT] en Reddit.
            # Se toma directamente de la propia fila (columna "canal"), sin
            # necesidad de buscar el post padre, porque cada fila del CSV
            # de Telegram ya trae su canal de origen.            
            if red_social == "telegram":
                canal = safe_text(row.get("canal"))
                if canal:
                    texto_partes.insert(0, f"[CANAL]\n{canal}")            

    
    # 3. Para posts de YouTube, añadir transcripción completa
    elif red_social == "youtube" and tipo.lower() == "video":
        transcripcion_path = safe_text(row.get("transcripcion"))
        titulo_video = safe_text(row.get("titulo_video"))
        parent_id = safe_text(row.get("id_video"))
        if parent_id:
            video_padre = df_completo[
                (df_completo["tipo"] == "video") &
                (df_completo["id_video"] == parent_id)
            ]
            if not video_padre.empty:
                padre_contenido = safe_text(video_padre.iloc[0].get("contenido"))
                if padre_contenido:
                    texto_partes.insert(1, f"[DESCRIPCIÓN VIDEO]\n{padre_contenido[:500]}")

        
        if titulo_video:
            texto_partes.insert(0, f"[TÍTULO]\n{titulo_video}")

        
        if transcripcion_path:
            transcript_text = load_transcript(transcripcion_path)
            if transcript_text:
                # Para videos (no comentarios), usar más transcripción
                texto_partes.append(f"[TRANSCRIPCIÓN]\n{transcript_text[:2000]}")
    
    texto_final = "\n\n".join(texto_partes)
    
    # ========================================
    # CARGA DE IMÁGENES
    # ========================================
    
    imagenes_base64 = []
    media_path = row.get("media_path")
    
    if media_path and not pd.isna(media_path):
        image_paths = load_image_from_path(media_path)
        
        # Limitar a 3 imágenes por eficiencia
        for img_path in image_paths[:3]:
            b64 = encode_image_base64(img_path)
            if b64:
                imagenes_base64.append(b64)
    
    return {
        "texto": texto_final,
        "imagenes": imagenes_base64,
        "tiene_media": len(imagenes_base64) > 0
    }

# =====================================================
# GESTIÓN DE TOPICS (CON CONSOLIDACIÓN)
# =====================================================

import unicodedata
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def normalizar_topic(t):
    """Normaliza topic para consolidación"""
    if not t:
        return "error"
    
    t = str(t).strip().lower()
    t = re.sub(r'[^\w\s]', '', t).replace('_', ' ')
    t = re.sub(r'\s+', ' ', t)
    
    # Quitar acentos
    t = ''.join(c for c in unicodedata.normalize('NFD', t) 
                if unicodedata.category(c) != 'Mn')
    
    return t

def consolidar_topic(nuevo_topic):
    """
    Consolida topics similares usando similitud semántica.
    Si el nuevo topic es muy similar a uno existente, usa el existente.
    """
    if not TOPIC_MEMORY:
        TOPIC_MEMORY[nuevo_topic] = 1
        return nuevo_topic
    
    # Vectorizar topics existentes + nuevo
    topics_existentes = list(TOPIC_MEMORY.keys())
    todos_topics = topics_existentes + [nuevo_topic]
    
    try:
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(todos_topics)
        
        # Calcular similitud del nuevo con todos los existentes
        similarities = cosine_similarity(
            tfidf_matrix[-1:],  # nuevo topic
            tfidf_matrix[:-1]   # existentes
        )[0]
        
        # Si hay similitud > 0.85, usar el existente más popular
        max_sim = max(similarities) if len(similarities) > 0 else 0
        
        if max_sim > 0.85:
            # Encontrar el más similar
            idx_similar = similarities.argmax()
            topic_similar = topics_existentes[idx_similar]
            
            # Incrementar contador
            TOPIC_MEMORY[topic_similar] += 1
            return topic_similar
        else:
            # Es suficientemente diferente, añadir como nuevo
            TOPIC_MEMORY[nuevo_topic] = 1
            
            # Si superamos el límite, eliminar el menos frecuente
            if len(TOPIC_MEMORY) > MAX_TOPICS:
                topic_menos_comun = min(TOPIC_MEMORY, key=TOPIC_MEMORY.get)
                del TOPIC_MEMORY[topic_menos_comun]
            
            return nuevo_topic
            
    except Exception as e:
        # Si falla la consolidación, añadir directamente
        TOPIC_MEMORY[nuevo_topic] = TOPIC_MEMORY.get(nuevo_topic, 0) + 1
        return nuevo_topic

def construir_contexto_topics():
    """Crea bloque de topics para el prompt"""
    if not TOPIC_MEMORY:
        return "\n(Aún no se han detectado tópicos. Crea el primero basado en el argumento).\n"
    
    # Ordenar por frecuencia (más comunes primero)
    topics_ordenados = sorted(
        TOPIC_MEMORY.items(),
        key=lambda x: x[1],
        reverse=True
    )[:15]  # Top 15
    
    topics_str = ", ".join([t[0] for t in topics_ordenados])
    
    return f"""
=== TÓPICOS MÁS COMUNES (Úsalos si el argumento coincide) ===
{topics_str}

⚠️ REGLA CRÍTICA: Si el argumento del comentario es muy similar a uno de estos,
USA EXACTAMENTE el tópico existente. No crees variantes.
"""


# =====================================================
# CATÁLOGO DE IDIOMAS / PAÍSES / CONTINENTES (Talkwalker)
# =====================================================
# PENDIENTE: sustituir por el contenido real de talkwalker_languages.json /
# talkwalker_countries.json en cuanto Romina los comparta. Si los ficheros
# existen junto a este script, se cargan automáticamente; si no, se usa una
# instrucción ISO genérica para que el pipeline no se quede bloqueado.

def _instruccion_lista_idiomas():
    ruta = Path(__file__).parent / "talkwalker_languages.json"
    if ruta.exists():
        with open(ruta, "r", encoding="utf-8") as f:
            catalogo = json.load(f)
        codigos = sorted(catalogo.keys()) if isinstance(catalogo, dict) else sorted(catalogo)
        return f"Usa EXCLUSIVAMENTE uno de estos códigos: {', '.join(codigos)}."
    return "Usa el código ISO 639-1 de 2 letras (ej: es, ca, eu, en, fr, pt).  # provisional, sin talkwalker_languages.json"


def _instruccion_lista_paises():
    ruta = Path(__file__).parent / "talkwalker_countries.json"
    if ruta.exists():
        with open(ruta, "r", encoding="utf-8") as f:
            catalogo = json.load(f)
        codigos = sorted(catalogo.keys()) if isinstance(catalogo, dict) else sorted(catalogo)
        return f"Usa EXCLUSIVAMENTE uno de estos códigos de país: {', '.join(codigos)}."
    return "Usa el código ISO 3166-1 alpha-2 (ej: ES, MX, AR, FR).  # provisional, sin talkwalker_countries.json"


def _instruccion_lista_continentes():
    return "Usa uno de: AF, AN, AS, EU, NA, OC, SA.  # provisional, sin catálogo Talkwalker de continentes"

# =====================================================
# PROMPTS
# =====================================================

def build_prompts(tema, desc_tema, keywords_list, population_scope, languages):
    keywords_str = ", ".join(keywords_list)
    langs = ", ".join(languages) if languages else "Cualquiera"
    geo_instruction = ""
    if "GLOBAL" in population_scope.upper():
        geo_instruction = "2. GEOGRAFÍA (pertinencia):\n"
        geo_instruction += " Filtro desactivado. Acepta comentarios de cualquier ubicación geográfica."
    else:
        geo_instruction = f"2. GEOGRAFÍA (pertinencia):\n"
        geo_instruction +=  f" Considerar RELEVANTE solo si el autor, el contenido o el contexto menciona o permite inferir claramente una ubicación específica dentro de {population_scope}:"
        geo_instruction += f" Nombre de barrio, distrito, calle, plaza, institución local, o gentilicio local en {population_scope}."
        geo_instruction += f" Referencia a un servicio/organismo que opera exclusivamente en {population_scope}"
        geo_instruction += f" El autor indica estar en {population_scope} (perfil, contexto, etc.)"
        geo_instruction += f" DESCARTAR si:"
        geo_instruction += f" - El post no contiene ninguna referencia geográfica verificable"
        geo_instruction += f" - La referencia geográfica apunta claramente a otra ciudad/región no relacionada con {population_scope}"
        geo_instruction += f" - El contenido podría ser de cualquier ciudad (sin anclaje local)"
        geo_instruction += f" EN CASO DE DUDA: marcar como NO relevante para temas hiperlocales."
        geo_instruction += f" (Para temas hiperlocales la precisión importa más que el recall.)"
        geo_instruction += f"(ej: contexto geográfico no relacionado: r/uruguay y Geografía interés es: España), marca NO RELEVANTE."
    
    system = (
        "Eres un auditor de datos para social listening. "
        "Tu prioridad es ELIMINAR ruido antes de clasificar. "
        "Todo el texto libre en 'Topic' deben estar en CASTELLANO. "
        "Salida: JSON exclusivamente, con TODAS las claves del formato pedido, sin excepción."
    )
    
    user_template = f"""
--- MARCO DE CONTROL ---
- Tema central de análisis: {tema}
- Descripción técnica: {desc_tema}
- Idiomas permitidos: {langs}
- Ubicación permitida: {population_scope}

--- INSTRUCCIONES GENERALES  ---
1. ANALIZA SOLO el bloque [CONTENIDO] para pertinencia, idioma, postura y subtopic, sentimiento, region, pais, ciudad.
2. Usa [TÍTULO POST], [POST PADRE], [TRANSCRIPCIÓN], etc. SOLO como contexto auxiliar.
2. Determina si el [CONTENIDO] es pertinente.
5. El topic explica el ARGUMENTO principal del [CONTENIDO], NO repite el tema general.


🚨 PASO 0: PERTINENCIA 🚨
Marca "pertinencia":"irrelevante" si:
1. IDIOMA: el [CONTENIDO] no está en {langs}.
{geo_instruction}
3. SPAM/PUBLICIDAD: mensajes sin texto coherente o que promueven productos/servicios sin relación con "{tema}".
4. AJENO: "{tema}" NO es el foco del [CONTENIDO], aunque se mencione de forma secundaria o contextual.

⚠️ NO excluyas noticias/citas relevantes al tema.
Si "pertinencia":"irrelevante" → aun así completa "idioma" (Paso 1) y la ubicación del autor (Paso 2); usa "posicion":2, "subtopic":"no relacionado", "sent_subtopic":2, y explica en cada "_just" que no aplica por no ser pertinente.


--- PASO 1: IDIOMA DEL CONTENIDO ---
Identifica el idioma del bloque [CONTENIDO] (ignora el idioma de [TÍTULO]/[POST PADRE]/etc.).
{_instruccion_lista_idiomas()}
Devuelve normalmente UN único código en la lista "idioma". 

--- PASO 2: UBICACIÓN DEL AUTOR (NO la del contenido) ---

⚠️ DISTINCIÓN CRÍTICA:
Debes inferir dónde está / de dónde es el AUTOR del [CONTENIDO], NO el lugar del que el autor está hablando.
Ejemplo: si el autor escribe "el ayuntamiento de Valencia ha vuelto a fallar", eso NO implica que el autor esté en Valencia — podría estar comentando desde fuera.

Señales VÁLIDAS para inferir la ubicación del autor:
- Referencias en primera persona: "aquí en...", "mi ciudad", "nosotros los [gentilicio]".
- Declaración explícita de residencia o nacionalidad.
- Marcas dialectales/léxicas claras y consistentes (vocabulario, expresiones) propias de una región concreta.

Señales que NO debes usar POR SÍ SOLAS (no son el autor, son el tema):
- El lugar del que trata el [CONTENIDO] o el [POST PADRE].
- El nombre del subreddit/canal/fuente — salvo que el propio [CONTENIDO] confirme pertenencia ("vivo aquí", "somos de aquí").

Si no hay NINGUNA señal fiable sobre el AUTOR → usa listas vacías [] en "continente"/"pais" y "" en "region"/"ciudad", y dilo explícitamente en el "_just" (no inventes ubicación por descarte).
{_instruccion_lista_paises()}
{_instruccion_lista_continentes()}
"region" y "ciudad" son texto libre (o "" si no se puede inferir). No puede haber más de un código en "continente"/"pais" si hay ambigüedad real entre opciones concretas (p. ej. un rasgo dialectal compartido por varios países).



--- PASO 3: POSTURA/POSICIÓN/OPINIÓN SOBRE "{tema}" (a nivel de TODA la publicación, no por subtopic) ---
Determina la POSTURA O POSICIÓN O OPINIÓN del autor —explícita O implícita— sobre "{tema}" EN SÍ MISMO (no sobre su contexto, gestión puntual o servicios relacionados):
- "1": apoya, defiende o se posiciona u opina a favor de "{tema}", explícita o implícitamente.
- "-1": rechaza, critica o se posiciona u opina en contra de "{tema}" en sí mismo, explícita o implícitamente.
- "0": el autor SÍ toma postura sobre "{tema}", pero es neutral/equilibrada (pros y contras, sin inclinarse claramente).
- "2": el [CONTENIDO] no expresa NINGUNA postura, posición u opinión sobre "{tema}" —ni explícita ni implícita— aunque sea pertinente (p. ej. información pura, pregunta, dato objetivo sin valoración).

⚠️ "0" y "2" NO son lo mismo: "0" es una postura posición u opinión neutral EXPRESADA; "2" es AUSENCIA de postura posición u opinión.


REGLAS:
- Criticar algo RELACIONADO con "{tema}" ≠ estar en contra de "{tema}". Ejemplo: Si el tema de análisis es el "bikesharing", el contenido: "el alcalde quitó los carriles bici" → posicion=2 (no es postura posición u opinión sobre el tema (bikesharing) en sí).
- Señalar un fallo puntual de un servicio ≠ rechazarlo. Ejemplo: "bicing siempre falla" → posicion=2 (usuario que señala un problema puntual, no rechaza el concepto).
- Solo marcar -1 si hay rechazo (explícito o implícito) al concepto, medida o servicio en sí. Ejemplo: "el bikesharing destruye el comercio" → posicion=-1.
- Si "pertinencia" es "irrelevante", usa directamente posicion=2.

--- PASO 4: SUBTOPIC (aspecto/argumento del comentario) + SU SENTIMIENTO ---

🚨 REGLAS:
1. PROHIBIDO usar palabras de "{tema}" ni "{keywords_str}" en el subtopic.
2. El subtopic es el aspecto/argumento CONCRETO del tema sobre el que el autor opina — no tiene por qué ser el tema principal; puede ser explícito o implícito.
3. La ausencia de postura, opinión o posición sobre "{tema}" (posicion=2) IMPIDE identificar un subtopic si el autor opina sobre algo no relacionado con el tema.
4. REUTILIZACIÓN OBLIGATORIA: revisa los SUBTOPICS EXISTENTES abajo; si el argumento coincide total o parcialmente, reutiliza EXACTAMENTE ese mismo texto. Solo crea uno nuevo si no existe ninguno similar.
5. Longitud 2-4 palabras, castellano correcto, sin sinónimos si ya existe un subtopic equivalente.
6. "sent_subtopic": polaridad hacia ESE subtopic (no hacia "{tema}" en general): "1" positiva, "0" neutra, "-1" negativa.
7. Si "pertinencia" es "irrelevante" o no hay ningún aspecto con opinión identificable, usa "subtopic":"no relacionado" y "sent_subtopic":2.


Ejemplos de construcción del subtopic:
- Apoyo/positivo: "Mejora de [aspecto]", "Eficiencia en [aspecto]", "Necesidad de [aspecto]"; o apoyando el tema al criticar un obstáculo: "Crítica a [problema/entidad]", "Rechazo a [lo que impide el tema]".
- Crítica/negativo: "Riesgo de [consecuencia]", "Impacto negativo en [aspecto]", "Falta de [recurso]", "Coste excesivo", "Mala gestión de [aspecto]", "Injusticia en [aspecto]".
- Neutral: "Información sobre [aspecto]", "Consulta técnica", "Procedimiento de [tema]".


__TOPICS_EXISTENTES__


--- CONTENIDO A ANALIZAR ---
__CONTENIDO_ANALIZAR__

--- FORMATO JSON (TODAS las claves son obligatorias, sin excepción) ---
{{
  "pertinencia": "relevante|irrelevante",
  "justif_pertinencia": "...",
  "idioma": ["<código>"],
  "idioma_just": "...",
  "continente": ["<código>"],
  "continente_just": "...",
  "pais": ["<código>"],
  "pais_just": "...",
  "region": "...",
  "region_just": "...",
  "ciudad": "...",
  "ciudad_just": "...",
  "posicion": <-1|0|1|2>,
  "posicion_just": "...",
  "subtopic": "...",
  "subtopic_just": "...",
  "sent_subtopic": <-1|0|1>,
  "sent_subtopic_just": "..."
}}
"""
    
    return system, user_template

# =====================================================
# TRABAJADOR vLLM
# =====================================================

def call_vllm_worker(contexto, system_prompt, user_template):
    """
    Llama al modelo vLLM con o sin imágenes.
    
    Args:
        contexto: dict con {texto, imagenes, tiene_media}
        system_prompt: prompt del sistema
        user_template: template del usuario
    """
    
    if contexto["texto"] == "BORRADO":
        return _fila_vacia("borrado")
    
    # Construir contexto de topics
    contexto_topics = construir_contexto_topics()
    
    # Inyectar en prompt
    prompt_final = user_template.replace("__TOPICS_EXISTENTES__", contexto_topics)
    prompt_final = prompt_final.replace("__CONTENIDO_ANALIZAR__", contexto["texto"])
    
    # Decidir modelo
    modelo = MODEL_NAME #if usar_vision and contexto["tiene_media"] else MODELO_TEXTO
    
    # Construir mensajes
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    # Si hay imágenes, añadirlas al contenido
    if VISION_HABILITADA and contexto["tiene_media"]:
        user_content = [
            {"type": "text", "text": prompt_final}
        ]
        
        # Añadir imágenes (máx 3)
        for img_b64 in contexto["imagenes"][:3]:
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}"
                }
            })
        
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": prompt_final})
    
    # Llamar al modelo
    for intento in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=modelo,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
                max_tokens=4000 # subido de 3000: ahora hay ~8 campos de justificación en texto libre
            )
            
            raw = response.choices[0].message.content
            resultado  = extraer_json_clasificacion(raw)
            
            # Normalizar y consolidar el subtopic (misma lógica de siempre)
            topic_norm = normalizar_topic(resultado["topic_llm"])
            
            if topic_norm not in ["error", "no relacionado", "comercializacion"]:
                resultado["topic_llm"] = consolidar_topic(topic_norm)
            else:
                resultado["topic_llm"] = topic_norm
            
            if resultado["posicion"] in (1, -1, 0):
                print(f"✅ Pertinencia={resultado['pertinencia']} | Postura={resultado['posicion']} | "
                      f"Subtopic='{resultado['topic_llm']}' | Lang='{resultado['lang']}' | País='{resultado['world_country']}'")
            
            return resultado
            
        except Exception as e:
            print(f"⚠️ Error en intento {intento + 1}: {e}")
            time.sleep(1)
    
    return _fila_vacia("fallo tras reintentos")

# =====================================================
# PIPELINE PRINCIPAL
# =====================================================

def llm_analysis(u_conf):
    """
    Análisis principal con soporte multimodal opcional.
    
    Args:
        u_conf: configuración
    """
    
    print("\n🚀 ANÁLISIS DE SENTIMIENTO + STANCE (vLLM)")
    
    data_folder = Path(u_conf.general["output_folder"])
    
    # Cargar memoria de topics
    memory_file = data_folder / "learned_topics.json"
    if memory_file.exists():
        with open(memory_file, "r", encoding="utf-8") as f:
            topics_previos = json.load(f)
            for t in topics_previos:
                TOPIC_MEMORY[t] = TOPIC_MEMORY.get(t, 0) + 1
    
    # Construir prompts
    system_p, user_t = build_prompts(
        u_conf.tema,
        u_conf.desc_tema,
        u_conf.general["keywords"],
        u_conf.population_scope,
        u_conf.languages
    )
    
    # Buscar archivos de datos
    archivos = list(data_folder.glob("*_global_dataset.csv"))
    
    for archivo in archivos:
        # Detectar red social
        nombre = archivo.stem.lower()
        if "reddit" in nombre:
            red_social = "reddit"
        elif "youtube" in nombre:
            red_social = "youtube"
        elif "bluesky" in nombre:
            red_social = "bluesky"
        elif "telegram" in nombre:
            red_social = "telegram"    
        else:
            continue
        
        print(f"\n=== Procesando: {archivo.name} ({red_social}) ===")
        
        # Cargar DataFrame
        try:
            with open(archivo, 'r', encoding='utf-8') as f:
                sep = ';' if ';' in f.readline() else ','
            
            df = pd.read_csv(archivo, sep=sep, encoding='utf-8', 
                           engine='python', on_bad_lines='skip')
            
            # Limpiar filas vacías
            if 'contenido' in df.columns:
                df = df.dropna(subset=['contenido'])
                df = df[df['contenido'].astype(str).str.strip() != ""]
                df = df.reset_index(drop=True)
            
            if df.empty:
                continue
                
        except Exception as e:
            print(f"❌ Error cargando: {e}")
            continue
        
        # Añadir columnas de análisis si no existen
        for col in COLUMNAS_ANALISIS:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].fillna("").astype(str).str.strip()
        
        # Identificar pendientes
        mask_pendiente = (
            (df["topic_llm"] == "") | (df["topic_llm"] == "nan") |
            (df["posicion"] == "") | (df["posicion"] == "nan") |
            (df["pertinencia"] == "") | (df["pertinencia"] == "nan")
        )
        
        # FILTRO ADICIONAL: Solo analizar contenido RELEVANTE según LLM previo
        if "relevancia_ia" in df.columns:
            mask_pendiente = mask_pendiente & (df["relevancia_ia"] == "SI")
        
        indices_pendientes = df[mask_pendiente].index.tolist()
        total = len(df)
        pendientes = len(indices_pendientes)
        
        if pendientes == 0:
            print(f"✅ Ya analizado al 100%")
            continue
        
        print(f"📊 Pendientes: {pendientes} / {total}")
        
        # Procesar por lotes
        analizado_path = archivo.with_name(archivo.stem + "_analizado.csv")
        
        for i in range(0, pendientes, MICRO_BATCH_SIZE):
            batch_indices = indices_pendientes[i : i + MICRO_BATCH_SIZE]
            
            print(f"\n  Lote {i//MICRO_BATCH_SIZE + 1} ({len(batch_indices)} items)...")
            
            # Preparar contextos multimodales
            contextos = {}
            for idx in batch_indices:
                contextos[idx] = preparar_contexto_multimodal(
                    df.loc[idx],
                    df,  # DataFrame completo para buscar padres
                    red_social
                )
            
            # Procesar en paralelo
            with concurrent.futures.ThreadPoolExecutor(max_workers=MICRO_BATCH_SIZE) as executor:
                futures = {
                    executor.submit(
                        call_vllm_worker,
                        contextos[idx],
                        system_p,
                        user_t
                    ): idx
                    for idx in batch_indices
                }
                
                for future in concurrent.futures.as_completed(futures):
                    idx = futures[future]
                    try:
                        resultado = future.result()
                        for col in COLUMNAS_ANALISIS:
                            df.loc[idx, col] = str(resultado[col])
                    except Exception as e:
                        print(f"❌ Error en fila {idx}: {e}")
            
            # Guardar progreso
            df.to_csv(analizado_path, index=False, sep=';', encoding='utf-8')
            print(f"  💾 Guardado")
        
        print(f"\n✅ {archivo.name} completado")
    
    # Guardar memoria de topics
    with open(memory_file, "w", encoding="utf-8") as f:
        json.dump(list(TOPIC_MEMORY.keys()), f, ensure_ascii=False, indent=2)
    
    # Mostrar estadísticas de topics
    print(f"\n📊 TOPICS DETECTADOS ({len(TOPIC_MEMORY)}):")
    for topic, count in sorted(TOPIC_MEMORY.items(), key=lambda x: x[1], reverse=True)[:15]:
        print(f"  • {topic}: {count}")
    
    print(f"\n✨ Análisis finalizado")

# =====================================================
# EJECUCIÓN
# =====================================================

if __name__ == "__main__":
    #PARA DEBUGEAR AISLADO CAMBIAR http://host.docker.internal:8001/v1 POR http://localhost:8001/v1
    # y descomentar ## DESCOMENTAR 
    # Configuración de prueba
    u_conf = SimpleNamespace(
        tema="venus", #"Regularización de inmigrantes",#"LUX TOUR",#"Transporte público Valencia",
        desc_tema="planeta del sistema solar", #"Proceso legal que permite a personas migrantes regular su situación legal en España. Incluye requisitos específicos y derechos laborales temporales.",#"La cuarta gira de conciertos de la cantante española Rosalía, promoviendo su álbum 'Lux', comenzará el 16 de marzo de 2026 en Lyon, Francia, y finalizará el 3 de septiembre de 2026 en San Juan, Puerto Rico.",
        population_scope="GLOBAL",#"España",#"GLOBAL",
        languages=["Castellano", "Catalan","Euskera"],
        general={
            "output_folder": "/home/romina/pruebas_telegram",#"/home/rrss/proyecto_web/RRSS_version_stance/project_web/Web_Proyecto/datos/admin/regularización_inmigrantes",
            "keywords": ["venus"],#['cear migratuak', 'cear regularización', 'inmigrantes legales', 'cear regularització', 'amnistía inmigrantes', 'proceso regularización', 'trámites regularización', 'regularizazio migratuak', 'legalización inmigrantes', 'regularización migrantes', 'regularització immigrats', 'regularizazioa migratuak', 'migratuak regularizazioa', 'regularización migratoria', 'requisitos regularización', 'beneficios regularización', 'regularització immigració', 'regularització immigrants', 'regularización inmigrantes', 'real decret regularització', 'real decreto regularización', 'real decreto regularizazioa', 'derechos laborales migrantes', 'regularización extraordinaria', 'regularización personas migrantes']#["Rosalía LUX 2026", "conciertos rosalía 2026", "lux tour rosalía", "rosalía en gira 2026"]
        }
    )
    
    # Ejecutar con o sin visión
    USAR_VISION = False  # Cambiar a True para análisis con imágenes
    
    llm_analysis(u_conf)