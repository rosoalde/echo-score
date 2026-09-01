import pandas as pd
from pathlib import Path
import ollama
import time
import re
import json

# =====================================================
# CONFIGURACIÓN
# =====================================================
MODEL_NAME = "qwen2.5:1.5b"#"gemma3:4b" #"qwen2.5:1.5b" #"llama3:latest" #  "qwen2.5:1.5b"#
BATCH_SIZE = 4
MAX_RETRIES = 2
NUM_CTX = 4096

# =====================================================
# EXTRACTOR JSON ULTRA ROBUSTO
# =====================================================
def extraer_json_clasificacion(raw):

    if not raw or not isinstance(raw, str):
        return 2, "error"

    print("\n------ RAW MODEL OUTPUT ------")
    print(raw)
    print("------------------------------\n")

    raw = raw.strip()

    # -------------------------------------------------
    # 1️⃣ Intentar carga directa
    # -------------------------------------------------
    try:
        data = json.loads(raw)
        return validar_json(data)
    except:
        pass

    # -------------------------------------------------
    # 2️⃣ Limpiar markdown ```json ```
    # -------------------------------------------------
    raw_clean = re.sub(r"```json|```", "", raw, flags=re.IGNORECASE).strip()

    try:
        data = json.loads(raw_clean)
        return validar_json(data)
    except:
        pass

    # -------------------------------------------------
    # 3️⃣ Extraer bloque JSON más grande posible
    #    usando balanceo de llaves (NO regex simple)
    # -------------------------------------------------
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

        # devolver el bloque más largo
        if candidates:
            return max(candidates, key=len)

        return None

    bloque = extract_largest_json(raw_clean)

    if bloque:
        try:
            bloque = re.sub(r',\s*}', '}', bloque)
            bloque = re.sub(r',\s*]', ']', bloque)
            data = json.loads(bloque)
            return validar_json(data)
        except:
            pass

    # -------------------------------------------------
    # 4️⃣ Fallback regex inteligente (case insensitive)
    # -------------------------------------------------
    try:
        sent_match = re.search(
            r'"?sentimiento"?\s*:\s*"?(-?1|0|2)"?',
            raw,
            re.IGNORECASE
        )

        topic_match = re.search(
            r'"?topic"?\s*:\s*"([^"]+)"',
            raw,
            re.IGNORECASE
        )

        sentimiento = int(sent_match.group(1)) if sent_match else 2
        topic = topic_match.group(1).strip() if topic_match else "error"

        return sentimiento, topic

    except:
        pass

    # -------------------------------------------------
    # 5️⃣ Último fallback absoluto
    # -------------------------------------------------
    return 2, "error"

def validar_json(data):

    if not isinstance(data, dict):
        return 2, "error"

    # 🔥 Caso correcto esperado
    if "Topics" in data and isinstance(data["Topics"], list) and data["Topics"]:
        item = data["Topics"][0]

        topic = item.get("Topic", "error")
        sentimiento = item.get("Sentimiento", 2)

        try:
            sentimiento = int(sentimiento)
        except:
            sentimiento = 2

        if sentimiento not in [1, -1, 0, 2]:
            sentimiento = 2

        if not isinstance(topic, str) or not topic.strip():
            topic = "error"

        return sentimiento, topic.strip()

    # fallback viejo
    sentimiento = data.get("sentimiento", 2)
    topic = data.get("topic", "error")

    try:
        sentimiento = int(sentimiento)
    except:
        sentimiento = 2

    if sentimiento not in [1, -1, 0, 2]:
        sentimiento = 2

    if not isinstance(topic, str) or not topic.strip():
        topic = "error"

    return sentimiento, topic.strip()
# =====================================================
# PREPARACIÓN TEXTO
# =====================================================
def preparar_texto(row, num_ctx=NUM_CTX):
    def count_tokens(texto):
        return len(texto) // 4 if texto else 0

    def safe_text(val):
        """Convierte None/NaN/'nan' a string vacío y hace strip"""
        if val is None or pd.isna(val) or str(val).strip().lower() == "nan":
            return ""
        return str(val).strip()

    comentario = safe_text(row.get("contenido"))
    if not comentario:
        return None

    titulo = safe_text(row.get("post_title"))
    cuerpo = safe_text(row.get("post_selftext"))
    titulo_video = safe_text(row.get("titulo_video"))
    descripcion = safe_text(row.get("descripcion_video"))
    tweet_previo = safe_text(row.get("BeforeContenido"))

    # Texto base
    texto_final = f"[COMENTARIO]\n{comentario}"
    total_tokens = count_tokens(comentario)

    # Reddit
    if titulo or cuerpo:
        if titulo and total_tokens + count_tokens(titulo) <= num_ctx:
            texto_final = f"[TÍTULO POST]\n{titulo}\n" + texto_final
            total_tokens += count_tokens(titulo)
        if cuerpo and total_tokens + count_tokens(cuerpo) <= num_ctx:
            texto_final = f"[CUERPO POST]\n{cuerpo}\n" + texto_final
            total_tokens += count_tokens(cuerpo)

    # YouTube
    elif titulo_video or descripcion:
        if titulo_video and total_tokens + count_tokens(titulo_video) <= num_ctx:
            texto_final = f"[TÍTULO VIDEO]\n{titulo_video}\n" + texto_final
            total_tokens += count_tokens(titulo_video)
        if descripcion and total_tokens + count_tokens(descripcion) <= num_ctx:
            texto_final = f"[DESCRIPCIÓN VIDEO]\n{descripcion}\n" + texto_final
            total_tokens += count_tokens(descripcion)

    # Twitter hilo
    elif tweet_previo:
        if total_tokens + count_tokens(tweet_previo) <= num_ctx:
            texto_final = f"[TWEET ANTERIOR]\n{tweet_previo}\n" + texto_final

    return texto_final
# =====================================================
# PROMPTS (SIN .format())
# =====================================================
#Población objetivo: {population_scope} (si está vacía, asumir 'público general')

def build_prompts(tema, keywords_list, languages): #, population_scope
    keywords_str = ", ".join(keywords_list)
    # if not population_scope:
    #     population_scope = "General"
    # elif isinstance(population_scope, list):
    #     population_scope = ", ".join(population_scope)
    langs = ", ".join(languages) if languages else "Cualquiera"

    system = """
Eres un analista experto en social listening.
Responde ÚNICAMENTE con un JSON válido.
No agregues texto adicional.
"""

    user_template = f"""
--- DATOS DE ENTRADA ---
Tema general: {tema} 
Listado de términos de búsqueda: [{keywords_str}]
Idiomas permitidos: {langs} 

--- COMENTARIO A ANALIZAR ---
__COMENTARIO__

🚨 **PASO 0: FILTRO DE EXCLUSIÓN TOTAL** 🚨
Eres un filtro de elegibilidad. Tu única tarea es decidir si un COMENTARIO es una OPINIÓN relevante sobre el tema del proyecto o si debe EXCLUIRSE.

INSTRUCCIONES:
1) Si se cumple CUALQUIERA de los criterios de exclusión, responde inmediatamente con:
   topic="No relacionado", sentimiento="2", excluded=true.
2) Si NO se cumple ningún criterio de exclusión, responde excluded=false y NO pongas topic="No relacionado".
3) No inventes contexto. Usa solo el comentario.

CRITERIOS DE EXCLUSIÓN TOTAL:
A) IDIOMA: el comentario está principalmente en un idioma NO permitido.

C) TIPO DE TEXTO (NO OPINIÓN):
   C1 NOTICIA/INFORMATIVO: El texto debe excluirse SOLO si se limita a informar, reproducir o resumir
una noticia, comunicado oficial o hecho objetivo, SIN expresar ningún tipo
de valoración personal.

Se considera NOTICIA/INFORMATIVO excluible cuando:
- Reproduce titulares, avisos o comunicados (p.ej., "Última hora", "según...",
  "comunicado oficial", "BOE", "decreto", "se aprueba", "entra en vigor").
- Describe hechos de forma neutra o institucional.
- No contiene juicio, opinión, reacción personal ni lenguaje evaluativo.

NO debe excluirse si el texto:
- Comenta, reacciona o valora una noticia, aunque la mencione explícitamente.
- Expresa crítica, apoyo, ironía, sarcasmo, burla, desconfianza o indignación.
- Incluye lenguaje coloquial, emocional o interpretativo del autor.
   C2 PUBLICIDAD/VENTA: intención comercial (precio, oferta, comprar, link en bio, promoción).
   C3 DESCRIPCIÓN NEUTRA: El texto debe excluirse SOLO si se limita a describir o explicar
una situación, medida o hecho SIN expresar valoración personal.

Se considera descripción neutra excluible cuando:
- Describe hechos, contextos o situaciones de forma objetiva o explicativa.
- No muestra apoyo, rechazo, crítica ni preocupación.
- No incluye ironía, sarcasmo, burla, desconfianza ni lenguaje emocional.
- Podría ser leído como una explicación impersonal sin cambiar el sentido.

NO debe excluirse si el texto:
- Incluye interpretación personal, aunque sea implícita.
- Sugiere evaluación mediante tono, elección de palabras o contexto.
- Utiliza ironía, exageración o lenguaje coloquial con carga valorativa.

D) FALSO POSITIVO: aparece un termino de búsqueda pero no se refiere al objeto de opinión del tema de investigación.

**PASO 1: Extracción de Topic y Sentimiento (Solo si pasa el filtro)**

Si hay una **OPINIÓN PERSONAL EXPLÍCITA**:
1. **Topic**: Identifica el MOTIVO o ASPECTO concreto evaluado (ej: "precio", "seguridad", "ruido", "rescate", "regulación"). 
No uses los posibles términos de búsqueda del "Listado de términos de búsqueda" ni el "Tema general" ni sus posibles variantes semánticas para establecer el topic.  
El Topic debe ser una etiqueta corta (1–3 palabras máximo). No usar frases. 
2. **Sentimiento**: Asigna SOLO el número:
   - "1": Elogio, apoyo, valoración positiva explícita.
   - "-1": Queja, crítica, rechazo, preocupación explícita, valoración negativa explícita.
   - "0": Mención neutra u opinión ambivalente sin carga clara, el comentario solo reporta o cita opiniones de terceros sin expresar una valoración propia clara.
   - "2": (Irrelevante) Si no hay juicio de valor claro, no esta relacionado, noticia.

⚠️ INSTRUCCIÓN CRÍTICA:
- Analiza EXCLUSIVAMENTE el bloque "COMENTARIO".
- El bloque "CONTEXTO" solo sirve para entender referencias implícitas, relación con ámbito geográfico, o relación con Tema general de análisis.
- NO evalúes el título ni el cuerpo.
- Si el comentario es una opinión aunque el contexto sea noticia, NO excluir.
   
**Formato de respuesta JSON ESTRICTO**:
- El campo "Sentimiento" debe contener SOLO el número en formato string, NADA de texto adicional.
- Si es excluido, devuelve: {{ "Topics": [{{ "Topic": "No relacionado", "Sentimiento": "2" }}]}}

{{
  "Topics": [
    {{ "Topic": "<aspecto concreto o 'No relacionado'>", "Sentimiento": "<1|-1|0|2>" }}
  ]
}}
"""

    return system, user_template


def construir_contexto_topics(topic_memory):
    """
    Genera bloque de contexto con los topics ya descubiertos
    para forzar coherencia terminológica.
    """

    if not topic_memory:
        return ""

    lista = "\n".join(f"- {t}" for t in sorted(topic_memory))

    return f"""
=== ÁNGULOS DE OPINIÓN YA DETECTADOS ===
Estos NO son el tema del estudio.
Son los argumentos usados por las personas.

Reutilízalos si el comentario expresa el mismo argumento.

Ángulos existentes:
{lista}

Si aparece un argumento distinto, crea uno nuevo breve (1–3 palabras).
========================================
"""

def normalizar_topic(t):
    t = str(t).strip().lower()
    t = re.sub(r"\s+", " ", t)  # colapsar espacios
    return t
# =====================================================
# LLM BATCH 
# =====================================================
def call_llm_batch(textos, system_prompt, user_template, topic_memory):

    resultados = []
    print(f"\n📞 Conectando con {MODEL_NAME}...")
    print()

    for i, texto in enumerate(textos):

        if not texto:
            resultados.append((2, "error"))
            continue

        contexto_topics = construir_contexto_topics(topic_memory)
        prompt = contexto_topics + "\n" + user_template.replace("__COMENTARIO__", texto)
        print(f"\n------ PROMPT ENVIADO ({i+1}) ------")

        print("\n[SYSTEM]")
        print(system_prompt)

        print("\n[USER]")
        print(prompt)

        print("------------------------------------")
        val = (2, "error")

        for intento in range(MAX_RETRIES):
            try:
                response = ollama.chat(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    options={
                        "temperature": 0.0,
                        "num_ctx": NUM_CTX,
                        "format": "json"
                    }
                )

                # 🔥 Extracción correcta del contenido
                try:
                    raw = response["message"]["content"]
                except:
                    try:
                        raw = response.message.content
                    except:
                        raw = str(response)

                sentimiento, topic = extraer_json_clasificacion(raw)
                val = (sentimiento, topic)
                

                topic_limpio = normalizar_topic(topic)
                if topic_limpio and topic_limpio.lower() not in ["error", "no relacionado"]:
                    topic_memory.add(topic_limpio)
                break

            except Exception as e:
                print(f"❌ Error intento {intento+1}: {e}")
                time.sleep(1)

        print(f"✅ Resultado fila {i+1}: {val}")
        resultados.append(val)

    return resultados
# =====================================================
# PIPELINE PRINCIPAL
# =====================================================
def llm_analysis(u_conf):
    topic_memory = set()
    import json
    from types import SimpleNamespace

    ''' Para ver claramente toda la configuración recibida en u_conf 

    def to_dict(obj):
        """Convierte recursivamente un SimpleNamespace en dict"""
        if isinstance(obj, SimpleNamespace):
            return {k: to_dict(v) for k, v in vars(obj).items()}
        elif isinstance(obj, dict):
            return {k: to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [to_dict(v) for v in obj]
        else:
            return obj

    # ---- Imprimir u_conf completo ----
    print("\n📦 DEBUG: u_conf completo")
    print(json.dumps(to_dict(u_conf), indent=2, ensure_ascii=False))

    '''

    print("\n" + "="*50)
    print("🚀 INICIANDO ANÁLISIS SENTIMIENTO + TOPIC")
    print("="*50)

    data_folder = Path(u_conf.general["output_folder"])
    TEMA = u_conf.tema
    KEYWORDS = u_conf.general["keywords"]
    # POPULATION = u_conf.population_scope
    LANGS = u_conf.languages
    print(f"data_folder: {data_folder}")
    print(f"TEMA: {TEMA} en first_analysis.py")
    print(f" Keywords: {KEYWORDS} en first_analysis.py")
    # print(f" POBLACIÓN: {POPULATION} en first_analysis.py")
    print(f" LANGS: {LANGS} en first_analysis.py")

    SYSTEM_PROMPT, USER_TEMPLATE = build_prompts(TEMA, KEYWORDS, LANGS) #POPULATION, 

    archivos = list(data_folder.glob("*_global_dataset.csv"))

    if not archivos:
        print("❌ No se encontraron archivos *_global_dataset.csv")
        return

    for archivo in archivos:

        print(f"\n=== Procesando {archivo.name} ===")
        start_time = time.perf_counter()

        try:
            with open(archivo, 'r', encoding='utf-8') as f:
                sep = ';' if ';' in f.readline() else ','

            df = pd.read_csv(archivo, sep=sep, encoding='utf-8', engine='python')
        except Exception as e:
            print(f"❌ Error leyendo: {e}")
            continue

        if "sentimiento" not in df.columns:
            df["sentimiento"] = ""

        if "topic" not in df.columns:
            df["topic"] = ""

        pendientes = []
        indices = []

        for idx, row in df.iterrows():

            val = str(row["sentimiento"]).strip()
            if val and val.lower() != "nan":
                continue

            texto = preparar_texto(row)

            if not texto:
                df.at[idx, "sentimiento"] = 2
                df.at[idx, "topic"] = "error"
                continue

            pendientes.append(texto)
            indices.append(idx)

            if len(pendientes) >= BATCH_SIZE:

                resultados = call_llm_batch(
                    pendientes,
                    SYSTEM_PROMPT,
                    USER_TEMPLATE, topic_memory
                )

                for i, (sent, topic) in zip(indices, resultados):
                    df.at[i, "sentimiento"] = sent
                    df.at[i, "topic"] = topic
                    

                pendientes, indices = [], []

                # Guardado intermedio
                output = archivo.with_name(
                    archivo.stem + "_analizado.csv"
                )
                df.to_csv(output, index=False, sep=sep, encoding='utf-8')

        # Procesar resto
        if pendientes:

            resultados = call_llm_batch(
                pendientes,
                SYSTEM_PROMPT,
                USER_TEMPLATE, topic_memory
            )

            for i, (sent, topic) in zip(indices, resultados):
                df.at[i, "sentimiento"] = sent
                df.at[i, "topic"] = topic
                

        elapsed = time.perf_counter() - start_time

        output = archivo.with_name(
            archivo.stem + "_analizado.csv"
        )

        df.to_csv(output, index=False, sep=sep, encoding='utf-8')

        print(f"✅ Finalizado: {output.name}")
        print(f"⏱️ Tiempo: {elapsed:.2f}s")

# '''-------------EJECUCIÓN DIRECTA DE PRUEBA-------------'''  
# if __name__ == "__main__":
#     #     from types import SimpleNamespace
#     from pathlib import Path

#     data_folder = Path(r"C:\Users\DATS004\Dropbox\14. DS4M - Social Media Research\git\project_web\Web_Proyecto\datos\admin\prohibición_burka (2)")

#     # Ruta donde está tu CSV
#     # Crear objeto configuración mínimo
#     u_conf = SimpleNamespace()

#     u_conf.tema = "prohibición burka en espacios públicos"

#     u_conf.general = {
#         "output_folder": data_folder,
#         "keywords": [
#             "prohibición burka espacios públicos",
#             "burka libertad de expresión",
#             "burka derechos humanos",
#             "burka discriminación género",
#             "burka Francia prohibición",
#             "burka libertad religiosa",
#             "prohibición burka controversia"
#         ]
#     }

#     u_conf.population_scope = ["Público General"]
#     u_conf.languages = ["Castellano"]

#     # Ejecutar análisis
#     llm_analysis(u_conf)