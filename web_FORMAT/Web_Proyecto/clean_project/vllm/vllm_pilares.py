import os
import json
import base64
import pandas as pd
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from tqdm import tqdm
from types import SimpleNamespace
from clean_project.vllm.model_config import MODELO_ACTIVO, VISION_HABILITADA
MODEL_NAME = MODELO_ACTIVO
import concurrent.futures
# Cargar variables de entorno
load_dotenv()

client = OpenAI(
    base_url="http://host.docker.internal:8001/v1",
    api_key="local-token",
    timeout=600.0
)
#MODEL_NAME = "Qwen/Qwen2.5-14B-Instruct-AWQ"#"Qwen/Qwen2.5-VL-7B-Instruct" # Qwen3-VL-8B-Instruct pasar a la versión 3 cuando esté disponible y estable
NUM_CTX = 30000  # Límite de tokens aproximado para el contexto
PILARES_BATCH_SIZE = 100  # Peticiones en paralelo al servidor vLLM
def get_prompt_pilares(tema, desc_tema, keywords_list, population_scope, languages):
    keywords_str = ", ".join(keywords_list) if isinstance(keywords_list, list) else str(keywords_list)
    langs = ", ".join(languages) if languages else "Cualquiera"

    system = (f"Eres un experto en análisis de opiniones y comunicación política. "
              f"Tu tarea es identificar juicios de valor subjetivos sobre el tema: {tema} (descripción: {desc_tema}). "
              "Tu salida debe ser exclusivamente JSON.")

    user_template = f"""
--- MARCO DE CONTROL DEL PROYECTO ---
- Tema central de análisis: {tema}
- Descripción técnica: {desc_tema}
- Idiomas permitidos: {langs}
- Ubicación permitida: {population_scope}

--- INSTRUCCIONES DE EVALUACIÓN ---
Analiza el [COMENTARIO] y utiliza su contexto ([ENLACE/FUENTE], [TÍTULO POST] , [CUERPO POST], [TÍTULO VIDEO] , [DESCRIPCIÓN], [TWEET ANTERIOR], etc) 
para comprender yasignar una postura (stance) al [COMENTARIO] para cada uno de los 4 pilares.

🚨 PASO 0: FILTRO DE EXCLUSIÓN TOTAL (Gatekeeper) 🚨
Eres un filtro de elegibilidad. Tu única tarea en este paso es decidir si el texto es una OPINIÓN válida (relevante para {population_scope}) o si debe EXCLUIRSE.

✅ PRINCIPIO CLAVE (anti-falsos excluidos):
- Si tienes DUDA razonable entre excluir o no, elige excluded=false y pasa al PASO 1.
- Solo usa excluded=true cuando el criterio de exclusión sea CLARO e INEQUÍVOCO.
- NO excluyas por “falta de contexto”: usa solo el texto.

REGLAS:
1) Si se cumple de forma CLARA e INEQUÍVOCA CUALQUIERA de los criterios de exclusión, responde con excluded=true, motivo_exclusion y asigna "2" a TODOS los pilares. DETENTE.
2) Si NO se cumple de forma clara ningún criterio, responde excluded=false y pasa al PASO 1.
3) No inventes contexto. Usa solo el texto.

CRITERIOS DE EXCLUSIÓN TOTAL (aplicar SOLO si es evidente):

A) IDIOMA:
EXCLUIR solo si el texto del COMENTARIO está principalmente en un idioma NO permitido.
Idiomas permitidos: {languages}.

B) GEOGRAFÍA AJENA (REGLA DE HERENCIA): 
EXCLUIR si el TEXTO del CONTEXTO proporcionado o el texto del COMENTARIO indican un lugar (barrio, ciudad o país) que NO forman parte del contexto geográfico objetivo: {population_scope}. 


C) TIPO DE TEXTO (TEXTO PURO, NO OPINIÓN):

C1 NOTICIA/INFORMATIVO (EXCLUIR SOLO SI ES TEXTO PURO):
Excluir SOLO si el texto se limita a informar/reproducir/resumir una noticia, titular o comunicado (p.ej. "BOE", "decreto", "comunicado", "según", "última hora") SIN expresar valoración personal.
Si hay CUALQUIER indicio de valoración (crítica, apoyo, indignación, ironía, burla, desconfianza, tono evaluativo, emojis de juicio), NO excluir.

C2 PUBLICIDAD/VENTA:
Excluir solo si hay intención comercial clara (precio, oferta, comprar, promo, enlace, venta) o es spam.

C3 DESCRIPCIÓN NEUTRA/TÉCNICA (EXCLUIR SOLO SI ES TEXTO PURO):
Excluir SOLO si el texto se limita a describir/explicar de forma impersonal (funcionamiento, datos, contexto) SIN evaluación personal, SIN emoción, SIN ironía/sarcasmo, SIN apoyo/queja.
Si hay cualquier juicio, queja, apoyo o crítica (aunque sea sutil o implícita), NO excluir.

D) FALSO POSITIVO:
Excluir solo si NO se refiere al objeto de opinión del tema: {tema} con descripción: {desc_tema}.
Si hay duda, NO excluir.

⚠️ INSTRUCCIÓN CRÍTICA:
- Analiza EXCLUSIVAMENTE el bloque "COMENTARIO".
- El bloque "CONTEXTO" solo sirve para entender referencias implícitas, relación con ámbito geográfico, o relación con tema de análisis.
- NO evalúes el título ni el cuerpo.
- Si el texto del COMENTARIO es una opinión aunque el CONTEXTO sea noticia, NO excluir.

FORMATO DE SALIDA SI excluded=true:
Devuelve SOLO este JSON (sin texto extra), usando motivo_exclusion como justificación de los 4 pilares:
{{
  "Legitimación_sociopolítica": "2",
  "Efectividad_percibida": "2",
  "Justicia_y_equidad_percibida": "2",
  "Confianza_y_legitimidad_institucional": "2",
  "legitimacion_just": "<motivo_exclusion>",
  "efectividad_just": "<motivo_exclusion>",
  "justicia_eq_just": "<motivo_exclusion>",
  "confianza_just": "<motivo_exclusion>"
}}

🚨 PASO 1: SOLO si excluded=false 🚨
Bloque de reglas generales:
REGLAS GENERALES DE ANÁLISIS (OBLIGATORIAS)
1) Analiza únicamente el texto del COMENTARIO.
- No evalúes el título ni el CONTEXTO como si fueran la opinión.
- El CONTEXTO solo sirve para entender mejor el COMENTARIO.
2) Detecta juicios de valor, no información.
- Analiza opiniones, valoraciones o interpretaciones.
- No analices descripciones neutras o información factual.
3) Cada pilar mide una dimensión diferente.
- Evalúa cada pilar de forma independiente.
- Un mismo COMENTARIO puede activar varios pilares a la vez.
- No asumas ningún pilar por defecto. Cada pilar debe activarse solo si hay evidencia específica.
4) Prioriza el significado implícito.
- Ten en cuenta ironía, sarcasmo y tono.
- Interpreta la intención real del COMENTARIO.
5) No infieras más allá del texto.
- No inventes intención si no hay indicios.
- Si el significado es ambiguo, usa "0" (neutro).
6) Diferencia entre "0" y "2":
- "0" → hay referencia al pilar pero es ambigua o sin orientación clara.
- "2" → no hay ninguna referencia interpretable a ese pilar.
- En caso de duda leve, usa "0" en lugar de "2".
7) Si hay evidencia, clasifica (evita el "2").
- Usa "2" solo si NO hay absolutamente ninguna evidencia.

REGLAS DE DESAMBIGUACIÓN GLOBAL (MUY IMPORTANTES)
Cada pilar representa un tipo distinto de juicio.
Un mismo COMENTARIO puede contener varios juicios a la vez.
Evalúa cada pilar de forma independiente.
Un COMENTARIO puede activar varios pilares simultáneamente.
No elijas un único pilar dominante si hay varios juicios distintos.
--------------------------------------------------
IDENTIFICACIÓN POR TIPO DE JUICIO:
1) LEGITIMIDAD / LEGALIDAD / AJUSTE A NORMAS → Legitimacion
- ¿La medida se percibe como legal, legítima, válida o acorde a normas, ley, justicia o razón?
2) RESULTADO de la medida → Efectividad percibida
- ¿Funciona? ¿Sirve? ¿Tiene impacto real?
3) IMPACTO sobre las personas → Justicia y equidad percibida
- ¿Es justo o injusto? ¿A quién beneficia o perjudica?
4) ACTORES o responsables → Confianza institucional
- ¿Se critica o valora al gobierno, políticos o instituciones?
--------------------------------------------------
REGLA DE RESOLUCIÓN DE AMBIGÜEDAD:
Si una misma expresión puede pertenecer a varios pilares:
- Identifica el tipo de juicio principal de esa expresión concreta (legitimidad, resultado, impacto o actor)
- Esto NO impide que el comentario active varios pilares si contiene varios juicios distintos
--------------------------------------------------
REGLAS CLAVE DE SEPARACIÓN:
- Hablar de legalidad, legitimidad o ajuste con normas → Legitimacion
- Evaluar resultados → Efectividad
- Hablar de impacto en personas → Justicia
- Criticar actores → Confianza institucional
--------------------------------------------------
CASOS FRECUENTES:
- “esto es ilegal” → Legitimacion (-1)
- “no sirve para nada” → Efectividad (-1)
- “es injusto” → Justicia (-1)
- “solo quieren recaudar” → Confianza (-1)
--------------------------------------------------
CASOS AMBIGUOS:
Palabras como “aceptable”, “válido”, “correcto”, “ilegítimo”:
- Si se refieren a conformidad con ley, normas o legitimidad → Legitimacion
- Si se refieren al impacto en personas o reparto → Justicia
--------------------------------------------------
REGLA FINAL:
Si hay duda:
- Identifica primero el tipo de juicio
- NO uses "2" si hay cualquier indicio interpretable
Bloque de los pilares:
1) LEGITIMACION
--------------------------------------------------
Se refiere a si el comentario evalúa la medida en términos de legalidad, legitimidad o ajuste con las normas.
Legitimar significa convertir algo en legítimo, lícito o conforme a la ley, justicia o razón.
Pregunta clave:
¿El comentario sugiere que la medida es legal, legítima, válida o acorde con la ley, la justicia, las normas o la razón?
--------------------------------------------------
QUÉ INCLUYE:
- Si la medida es legal o ilegal
- Si la medida se percibe como legítima o ilegítima
- Si se ajusta o no a la ley, a las normas o a principios considerados válidos
- Si se presenta como aceptable o inaceptable por razones normativas o legales
- Juicios sobre si “debería poder hacerse” o “no deberían poder hacer esto”
--------------------------------------------------
EVIDENCIA POSITIVA (1):
Se asigna cuando el comentario expresa o sugiere que la medida es legal,
legítima, válida o conforme con las normas, la ley, la justicia o la razón.
Esto incluye:
- percepción de conformidad legal
- aceptación de la medida como válida o legítima
- valoración positiva de su ajuste con normas o principios
Ejemplos:
- “es legal”
- “es legítimo”
- “es válido”
- “es correcto”
- “cumple la ley”
También implícito:
- “tiene base legal”
- “no veo problema en que lo hagan”
- “es una medida aceptable”
- “está dentro de lo normal”
--------------------------------------------------
EVIDENCIA NEGATIVA (-1):
Se asigna cuando el comentario expresa o sugiere que la medida es ilegal,
ilegítima, inválida o contraria a normas, ley, justicia o razón.
Esto incluye:
- percepción de ilegalidad o ilegitimidad
- rechazo por falta de base normativa o legal
- juicio de que la medida “no debería permitirse”
Ejemplos:
- “es ilegal”
- “es ilegítimo”
- “va contra la ley”
- “no deberían poder hacer esto”
- “esto no es válido”
También implícito:
- “esto no tiene base legal”
- “no es aceptable”
- “se están saltando las normas”
- “esto no debería permitirse”
--------------------------------------------------
EVIDENCIA NEUTRA (0):
Se asigna cuando el comentario hace referencia a la legalidad o legitimidad de la medida,
pero NO expresa una valoración clara (ni positiva ni negativa).
Esto incluye:
- duda o incertidumbre sobre si es legal o legítima
- evaluaciones ambiguas o poco definidas
- menciones a normas o ley sin juicio claro
Ejemplos:
- “no sé si es legal”
- “habría que ver si esto cumple la ley”
- “no tengo claro si esto es legítimo”
- “no sé hasta qué punto se ajusta a la norma”
--------------------------------------------------
NO INCLUYE:
- Resultados → Efectividad
- Impacto social → Justicia
- Actores → Confianza
--------------------------------------------------
REGLA FINAL:
Si hay cualquier evaluación sobre legalidad, legitimidad o ajuste con normas → NO uses "2"
2) EFECTIVIDAD PERCIBIDA
--------------------------------------------------
Se refiere a si el comentario evalúa los RESULTADOS o la UTILIDAD de la medida.
Pregunta clave:
¿El comentario sugiere que la medida funciona, no funciona o tendrá impacto?
--------------------------------------------------
QUÉ INCLUYE:
- Si funciona o no funciona
- Si sirve o no sirve
- Si tendrá efectos reales
- Si mejorará o empeorará la situación
- Expectativas de impacto (aunque sean subjetivas)
--------------------------------------------------
EVIDENCIA POSITIVA (1):
Se asigna cuando el comentario expresa o sugiere que la medida es eficaz,
útil o tendrá un impacto positivo en la realidad.
Esto incluye:
- creencias de que la medida funciona o funcionará
- expectativas de mejora o solución de un problema
- valoración positiva del impacto o resultados de la medida
Ejemplos:
- “funciona”
- “sirve”
- “va a mejorar”
- “es útil”
- “tendrá efecto”
También implícito:
- “esto ayudará”
- “puede solucionar el problema”
- “esto sí que arregla las cosas”
- “puede funcionar bien”
--------------------------------------------------
EVIDENCIA NEGATIVA (-1):
Se asigna cuando el comentario expresa o sugiere que la medida es ineficaz,
inútil o no tendrá impacto real (o incluso empeorará la situación).
Esto incluye:
- negación de eficacia o utilidad
- expectativas de fracaso o ausencia de resultados
- creencias de que la medida no cambiará nada o tendrá efectos negativos
Ejemplos:
- “no sirve para nada”
- “es inútil”
- “no va a cambiar nada”
- “no funcionará”
- “es un fracaso”
También implícito:
- “esto no arregla nada”
- “no tiene ningún efecto”
- “esto no sirve”
- “no soluciona el problema”
- “esto va a empeorar las cosas”
--------------------------------------------------
EVIDENCIA NEUTRA (0):
Se asigna cuando el comentario hace referencia a la posible eficacia de la medida,
pero NO expresa una valoración clara (ni positiva ni negativa).
Esto incluye:
- duda o incertidumbre sobre si funcionará
- evaluaciones ambiguas o poco definidas
- comentarios que reconocen la posibilidad de distintos resultados sin posicionarse
Ejemplos:
- “no sé si funcionará”
- “puede que sí o puede que no”
- “habrá que ver si funciona”
- “no está claro si tendrá efecto”
--------------------------------------------------
NO INCLUYE:
- Legitimacion → Legitimacion
- Justicia → Justicia
- Críticas a actores → Confianza
--------------------------------------------------
REGLA FINAL:
Si hay cualquier evaluación sobre resultados o impacto → NO uses "2"
3) JUSTICIA Y EQUIDAD PERCIBIDA
--------------------------------------------------
Se refiere a si la medida se percibe como justa o injusta en cómo afecta a las personas.
Pregunta clave:
¿El COMENTARIO evalúa si la medida trata a las personas de forma justa?
--------------------------------------------------
QUÉ INCLUYE:
- Quién gana y quién pierde
- Reparto de costes y beneficios
- Desigualdad o discriminación
- Impacto en grupos sociales
- Justicia del proceso de decisión
--------------------------------------------------
EVIDENCIA POSITIVA (1):
Se asigna cuando el comentario expresa o sugiere que la medida es justa,
equitativa o distribuye de forma adecuada sus efectos entre las personas.
Esto incluye:
- percepción de reparto equilibrado de costes y beneficios
- trato igualitario entre individuos o grupos
- valoración positiva del impacto social de la medida
Ejemplos:
- “es justo”
- “es equitativo”
- “beneficia a todos”
También implícito:
- “es equilibrado”
- “reparte bien el impacto”
- “afecta a todos por igual”
- “no perjudica a nadie en particular”
--------------------------------------------------
EVIDENCIA NEGATIVA (-1):
Se asigna cuando el comentario expresa o sugiere que la medida es injusta,
desigual o afecta de forma negativa o desproporcionada a ciertos grupos.
Esto incluye:
- percepción de desigualdad o discriminación
- reparto injusto de costes o beneficios
- impacto negativo en personas o colectivos de forma no equitativa
Ejemplos:
- “es injusto”
- “discrimina”
- “perjudica a la gente”
- “siempre pagan los mismos”
También implícito:
- “esto castiga a la mayoría”
- “beneficia a unos y perjudica a otros”
- “los de siempre salen perdiendo”
- “esto afecta sobre todo a la gente normal”
--------------------------------------------------
EVIDENCIA NEUTRA (0):
Se asigna cuando el comentario hace referencia a la justicia o al impacto social,
pero NO expresa una valoración clara (ni positiva ni negativa).
Esto incluye:
- duda o ambivalencia sobre si es justo
- evaluaciones poco definidas o sin posicionamiento claro
- menciones al impacto social sin juicio explícito
Ejemplos:
- “no sé si es justo”
- “puede ser justo o no”
- “habría que ver si es equitativo”
--------------------------------------------------
NO INCLUYE:
- Legitimidad o legalidad → Legitimacion
- Resultados → Efectividad
- Actores → Confianza
--------------------------------------------------
REGLA FINAL:
Si hay referencia al impacto social → NO uses "2"
4) CONFIANZA INSTITUCIONAL
--------------------------------------------------
Se refiere a la confianza o desconfianza hacia los actores responsables.
Pregunta clave:
¿El COMENTARIO evalúa a los responsables de la medida?
--------------------------------------------------
QUÉ INCLUYE:
- Intenciones (honestas vs interesadas)
- Competencia (capaces vs incompetentes)
- Corrupción o intereses ocultos
--------------------------------------------------
EVIDENCIA POSITIVA (1):
Se asigna cuando el comentario expresa o sugiere que los actores responsables 
(gobierno, políticos o instituciones) son confiables, competentes o actúan con buenas intenciones.
Esto incluye:
- confianza en su capacidad para gestionar la medida
- percepción de profesionalidad o competencia
- atribución de intenciones honestas o responsables
Ejemplos:
- “confío en que lo harán bien”
- “son competentes”
También implícito:
- “están haciendo lo correcto”
- “parece que saben lo que hacen”
- “lo están gestionando bien”
--------------------------------------------------
EVIDENCIA NEGATIVA (-1):
Se asigna cuando el comentario expresa o sugiere desconfianza hacia los actores responsables,
atribuyéndoles incompetencia, malas intenciones o intereses propios.
Esto incluye:
- sospecha de intereses ocultos (dinero, política, beneficio propio)
- percepción de corrupción o manipulación
- percepción de incompetencia o mala gestión
Ejemplos:
- “solo quieren recaudar”
- “son corruptos”
- “no tienen ni idea”
También implícito:
- “no me fío de ellos”
- “lo hacen por su beneficio”
- “esto es puro interés político”
- “solo miran por ellos mismos”
--------------------------------------------------
EVIDENCIA NEUTRA (0):
Se asigna cuando el comentario menciona o implica a los actores responsables,
pero NO expresa una valoración clara (ni positiva ni negativa) sobre ellos.
Esto incluye:
- duda o ambivalencia
- evaluaciones débiles o poco definidas
- menciones sin juicio claro
Ejemplos:
- “no sé si lo hacen bien”
- “puede que tengan buenas intenciones”
- “el gobierno ha propuesto esto” (sin valoración)
--------------------------------------------------
REGLA CLAVE:
Debe haber referencia a actores (gobierno, políticos, instituciones).
--------------------------------------------------
NO INCLUYE:
- Legitimidad o legalidad → Legitimacion
- Resultados → Efectividad
- Impacto → Justicia
--------------------------------------------------
CASOS LÍMITE:
- “esto es ilegal porque el gobierno se ha pasado” → Legitimacion (-1) + Confianza (-1)
- “no me fío del gobierno aunque quizá funcione” → Confianza (-1) + Efectividad (0 o 1/-1 según el resto del comentario)
--------------------------------------------------
REGLA FINAL:
Si se evalúan actores → NO uses "2"
--------------------------------------------------
REGLAS DE FORMATO:
- Responde SOLO en JSON, sin texto adicional.
- Los 4 valores numéricos deben ser SOLO el número en formato string.
- Los 4 campos "_just" son texto libre breve (1 frase) justificando el valor de su pilar correspondiente.


--- COMENTARIO A ANALIZAR ---
__COMENTARIO__


FORMATO DE SALIDA SI excluded=false:

{{
  "Legitimacion_sociopolítica": "<1|-1|0|2>",
  "Efectividad_percibida": "<1|-1|0|2>",
  "Justicia_y_equidad_percibida": "<1|-1|0|2>",
  "Confianza_y_legitimidad_institucional": "<1|-1|0|2>",
  "legitimacion_just": "...",
  "efectividad_just": "...",
  "justicia_eq_just": "...",
  "confianza_just": "..."
}}
"""
    return system, user_template

def preparar_texto_pilares_seguro(row, df_completo=None, red_social="", num_ctx=NUM_CTX):
    def count_tokens(texto): return len(texto) // 4 if texto else 0
    def safe_text(val):
        if pd.isna(val) or str(val).strip().lower() in ["nan", "none", ""]: return ""
        return str(val).strip()

    # 1. Extraer el texto principal (columna 'contenido')
    comentario = safe_text(row.get("contenido"))
    
    textos_basura = ["[removed]", "[deleted]"]
    if not comentario or comentario.lower() in textos_basura:
        return "BORRADO"

    # 2. Extraer contexto adicional por plataforma
    texto_citado = safe_text(row.get("texto_citado"))
    titulo_video = safe_text(row.get("titulo_video"))
    transcripcion = safe_text(row.get("transcripcion"))
    fuente = safe_text(row.get("fuente"))  # subreddit en Reddit

    tipo_lower = safe_text(row.get("tipo")).lower()
    es_comentario = tipo_lower in ["comentario", "comment", "reply"] or tipo_lower.startswith("comentario")

    texto_final = f"[COMENTARIO/POST]\n{comentario}\n"
    total_tokens = count_tokens(comentario)

    if texto_citado and total_tokens + count_tokens(texto_citado) < num_ctx:
        texto_final += f"\n[POST CITADO]\n{texto_citado}\n"
        total_tokens += count_tokens(texto_citado)

    # 2b. Contexto del post padre (para comentarios de Bluesky y Reddit)
    if es_comentario and df_completo is not None:
        padre_contenido = ""
        padre_texto_citado = ""

        if red_social == "bluesky" and "uri" in df_completo.columns:
            parent_uri = safe_text(row.get("parent_uri"))
            uri_propio = safe_text(row.get("uri"))
            if parent_uri and parent_uri != uri_propio:
                padre_rows = df_completo[df_completo["uri"] == parent_uri]
                if not padre_rows.empty:
                    padre_contenido = safe_text(padre_rows.iloc[0].get("contenido"))
                    padre_texto_citado = safe_text(padre_rows.iloc[0].get("texto_citado"))

        elif red_social == "reddit" and "id_propio" in df_completo.columns:
            id_raiz = safe_text(row.get("id_raiz"))
            if id_raiz:
                padre_rows = df_completo[
                    (df_completo["tipo"].astype(str).str.upper() == "POST") &
                    (df_completo["id_propio"].astype(str) == id_raiz)
                ]
                if not padre_rows.empty:
                    padre_contenido = safe_text(padre_rows.iloc[0].get("contenido"))

        if padre_contenido and total_tokens + count_tokens(padre_contenido) < num_ctx:
            texto_final += f"\n[POST PADRE]\n{padre_contenido[:500]}\n"
            total_tokens += count_tokens(padre_contenido[:500])

        if padre_texto_citado and total_tokens + count_tokens(padre_texto_citado) < num_ctx:
            texto_final += f"\n[TEXTO CITADO POR EL POST PADRE]\n{padre_texto_citado[:500]}\n"
            total_tokens += count_tokens(padre_texto_citado[:500])

    # 2c. Fuente / subreddit (Reddit)
    if fuente and total_tokens + count_tokens(fuente) < num_ctx:
        texto_final = f"[FUENTE]\n{fuente}\n" + texto_final

    if transcripcion and total_tokens + count_tokens(transcripcion) < num_ctx:
        texto_final += f"\n[TRANSCRIPCIÓN/CONTEXTO VISUAL]\n{transcripcion}\n"
        total_tokens += count_tokens(transcripcion)

    if titulo_video and total_tokens + count_tokens(titulo_video) < num_ctx:
        texto_final = f"[TÍTULO VIDEO]\n{titulo_video}\n" + texto_final

    return texto_final

def encode_image(image_path):
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception:
        return None

def extraer_valor(json_dict, pilar):
    for clave in KEY_MAP[pilar]:
        if clave in json_dict:
            return json_dict[clave]
    return None
 
def parsear_stance(valor_raw):
    if valor_raw is None:
        return None
    try:
        v = int(str(valor_raw).strip())
        if v in (-1, 0, 1, 2):
            return v
        return None
    except (ValueError, TypeError):
        return None
import re # <--- AÑADE ESTO ARRIBA DEL TODO EN TU ARCHIVO
KEY_MAP = {
    'legitimacion': [
        'legitimacion',
        'Legitimacion_sociopolitica',
        'Legitimación_sociopolítica',
        'Legitimacion_sociopolítica',
        'Legitimación_sociopolitica',
        'legitimacion_sociopolítica',
        'Legitmacion',
    ],
    'efectividad': [
        'efectividad',
        'Efectividad_percibida',
    ],
    'justicia_equidad': [
        'justicia_equidad',
        'Justicia_y_equidad_percibida',
    ],
    'confianza_institucional': [
        'confianza_institucional',
        'Confianza_y_legitimidad_institucional',
    ],
    'legitimacion_just': ['legitimacion_just'],
    'efectividad_just': ['efectividad_just'],
    'justicia_equidad_just': ['justicia_eq_just', 'justicia_equidad_just'],
    'confianza_institucional_just': ['confianza_just', 'confianza_institucional_just'],
}
def analizar_pilares_vllm(system_prompt, user_prompt, image_path=None):
    user_content = [{"type": "text", "text": user_prompt}]
    
    if VISION_HABILITADA and image_path and os.path.exists(image_path):
        base64_image = encode_image(image_path)
        if base64_image:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
            })

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.0, # Subimos un pelín para que no sea tan robótico
            max_tokens=300
        )
        
        respuesta_raw = response.choices[0].message.content.strip()
        
        # DEBUG: Imprimir lo que dice el modelo realmente
        print(f"\n[RAW LLM] -> {respuesta_raw}")
        
        # Extractor infalible de JSON usando Regex
        match = re.search(r'\{.*\}', respuesta_raw, re.DOTALL)
        if match:
            json_str = match.group(0)
            return json.loads(json_str)
        else:
            print(f"⚠️ No se encontró JSON en la respuesta: {respuesta_raw}")
            return {}
            
    except Exception as e:
        print(f"❌ Error en LLM: {e}")
        return {}

def _worker_pilares(idx, texto_preparado, user_template, system_prompt, img_path):
    """
    Worker ejecutado en paralelo por ThreadPoolExecutor.
    Devuelve (idx, resultado_dict) o (idx, None) en caso de error.
    """
    if texto_preparado == "BORRADO":
        return idx, None
 
    user_prompt = user_template.replace("__COMENTARIO__", texto_preparado)
 
    user_content = [{"type": "text", "text": user_prompt}]
    if VISION_HABILITADA and img_path and os.path.exists(img_path):
        base64_image = encode_image(img_path)
        if base64_image:
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
            })
 
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content}
            ],
            temperature=0.0,
            max_tokens=300
        )
        respuesta_raw = response.choices[0].message.content.strip()
        print(f"\n[RAW LLM idx={idx}] -> {respuesta_raw}")
 
        match = re.search(r'\{.*\}', respuesta_raw, re.DOTALL)
        if match:
            resultado_json = json.loads(match.group(0))
        else:
            print(f"⚠️ No se encontró JSON (idx={idx}): {respuesta_raw}")
            return idx, None
 
    except Exception as e:
        print(f"❌ Error LLM (idx={idx}): {e}")
        return idx, None
 
    # Parsear los 4 pilares
    leg = parsear_stance(extraer_valor(resultado_json, 'legitimacion'))
    efe = parsear_stance(extraer_valor(resultado_json, 'efectividad'))
    jus = parsear_stance(extraer_valor(resultado_json, 'justicia_equidad'))
    con = parsear_stance(extraer_valor(resultado_json, 'confianza_institucional'))

    # Justificaciones (texto libre, sin conversión numérica)
    leg_j = extraer_valor(resultado_json, 'legitimacion_just') or ""
    efe_j = extraer_valor(resultado_json, 'efectividad_just') or ""
    jus_j = extraer_valor(resultado_json, 'justicia_equidad_just') or ""
    con_j = extraer_valor(resultado_json, 'confianza_institucional_just') or ""
 
    print(f"  ✅ idx={idx} | leg={leg}, efe={efe}, jus={jus}, con={con} | claves={list(resultado_json.keys())}")
 
    return idx, {"leg": leg, "efe": efe, "jus": jus, "con": con, "leg_j": leg_j, "efe_j": efe_j, "jus_j": jus_j, "con_j": con_j}

def procesar_pilares_directorio(u_conf, archivos=None):
    folder = Path(u_conf.general["output_folder"])
 
    if archivos is None:
        archivos = list(folder.glob("*_analizado.csv"))
 
    if not archivos:
        print(f"⚠️ No hay archivos *_analizado.csv pendientes en {folder}")
        return
 
    tema      = u_conf.tema
    desc_tema = u_conf.desc_tema
    keywords  = u_conf.general["keywords"]
    population = u_conf.population_scope
    langs      = u_conf.languages
 
    system_prompt, user_template = get_prompt_pilares(tema, desc_tema, keywords, population, langs)
 
    for arch in archivos:
        print(f"\n🚀 Procesando pilares para: {arch.name}")
 
        nombre = arch.stem.lower()
        if "bluesky" in nombre:
            red_social = "bluesky"
        elif "reddit" in nombre:
            red_social = "reddit"
        elif "youtube" in nombre:
            red_social = "youtube"
        else:
            red_social = ""
 
        with open(arch, 'r', encoding='utf-8') as f:
            sep = ';' if ';' in f.readline() else ','
 
        df = pd.read_csv(arch, sep=sep, encoding='utf-8', on_bad_lines='skip')
 
        # 1. Filtrar descartados# Con el nuevo vllm_sentiment_topic_new.py el CSV ya no trae 'sentimiento'
        # (se sustituyó por 'pertinencia'); se mantiene el camino antiguo por si
        # se procesa un *_analizado.csv generado con el esquema previo.
        if 'pertinencia' in df.columns:
            df_filtrado = df[df['pertinencia'].astype(str).str.strip().str.lower() == 'relevante'].copy()
        elif 'sentimiento' in df.columns:
            df['sentimiento'] = pd.to_numeric(df['sentimiento'], errors='coerce')
            df_filtrado = df[df['sentimiento'] != 2].copy()
        else:
            df_filtrado = df.copy()
 
        print(f"Filas totales: {len(df)} | A analizar (sin descartados): {len(df_filtrado)}")
 
        if df_filtrado.empty:
            continue
 
        # Inicializar columnas de pilares
        cols_pilares = ['legitimacion', 'efectividad', 'justicia_equidad', 'confianza_institucional']
        for p in cols_pilares:
            if p not in df_filtrado.columns:
                df_filtrado[p] = 0

        cols_pilares_just = ['justif_legitimacion', 'justif_efectividad', 'justif_justicia_equidad', 'justif_confianza_institucional']
        for pj in cols_pilares_just:
            if pj not in df_filtrado.columns:
                df_filtrado[pj] = ""

        # Construir lista de índices a procesar
        indices = df_filtrado.index.tolist()
        total   = len(indices)
 
        # ── PROCESAR EN LOTES PARALELOS ──────────────────────────
        for batch_start in tqdm(range(0, total, PILARES_BATCH_SIZE), desc="Lotes pilares"):
            batch_indices = indices[batch_start : batch_start + PILARES_BATCH_SIZE]
 
            # Preparar argumentos del lote fuera del executor (sin I/O pesado)
            tareas = []
            for idx in batch_indices:
                row = df_filtrado.loc[idx]
                texto_preparado = preparar_texto_pilares_seguro(row, df_completo=df_filtrado, red_social=red_social)
 
                img_path = row.get('media_path')
                if pd.isna(img_path) or str(img_path).strip().lower() in ['nan', 'none', '']:
                    img_path = row.get('thumbnail_path')
                if pd.isna(img_path) or str(img_path).strip().lower() in ['nan', 'none', '']:
                    img_path = None
                else:
                    img_path = str(img_path).strip()
                    if not os.path.isabs(img_path):
                        img_path = os.path.join(folder, img_path)
 
                tareas.append((idx, texto_preparado, img_path))
 
            # Lanzar en paralelo
            with concurrent.futures.ThreadPoolExecutor(max_workers=PILARES_BATCH_SIZE) as executor:
                futures = {
                    executor.submit(
                        _worker_pilares,
                        idx, texto, user_template, system_prompt, img
                    ): idx
                    for idx, texto, img in tareas
                }
 
                for future in concurrent.futures.as_completed(futures):
                    idx = futures[future]
                    try:
                        result_idx, valores = future.result()
                        if valores is None:
                            continue
                        if valores["leg"] is not None: df_filtrado.at[result_idx, 'legitimacion']            = valores["leg"]
                        if valores["efe"] is not None: df_filtrado.at[result_idx, 'efectividad']             = valores["efe"]
                        if valores["jus"] is not None: df_filtrado.at[result_idx, 'justicia_equidad']        = valores["jus"]
                        if valores["con"] is not None: df_filtrado.at[result_idx, 'confianza_institucional']  = valores["con"]
                        df_filtrado.at[result_idx, 'justif_legitimacion']            = valores["leg_j"]
                        df_filtrado.at[result_idx, 'justif_efectividad']             = valores["efe_j"]
                        df_filtrado.at[result_idx, 'justif_justicia_equidad']        = valores["jus_j"]
                        df_filtrado.at[result_idx, 'justif_confianza_institucional'] = valores["con_j"]
                    except Exception as e:
                        print(f"  ⚠️ Error escribiendo resultados (idx={idx}): {e}")
 
            # Guardar progreso tras cada lote (igual que en sentimiento)
            nuevo_nombre = arch.stem.replace("_analizado", "") + "_pilares.csv"
            ruta_salida  = folder / nuevo_nombre
            df_filtrado.to_csv(ruta_salida, sep=';', index=False, encoding='utf-8')
 
        print(f"✅ Guardado con pilares en: {ruta_salida.name}")

if __name__ == "__main__":

    u_conf = SimpleNamespace(
    tema = "tiroteo trump",
    desc_tema = "Un intento de magnicidio durante mitin político de Donald Trump.",
    population_scope = "SIN CONTEXTO GEOGRAFICO",
    languages = ["Castellano"],
    general = {"keywords": ["tiroteo trump", "magnicidio Trump", "ataque mitin Trump"],
               "output_folder": "/home/rrss/proyecto_web/RRSS_version_stance/project_web/Web_Proyecto/datos/admin/juguete"}
    )
    carpeta_prueba = u_conf.general["output_folder"]
    print(f"🧪 Iniciando prueba aislada en: {carpeta_prueba}")
    procesar_pilares_directorio(u_conf)

'''
def get_prompt_pilares(tema, desc_tema, keywords_list,population_scope,languages):
    keywords_str = ", ".join(keywords_list)
    # poblacion = ", ".join(population_scope) if isinstance(population_scope, list) else population_scope
    langs = ", ".join(languages) if languages else "Cualquiera"

    system = ("Eres un experto en análisis de opiniones y comunicación política."
              f"Tu tarea es identificar juicios de valor subjetivos (incluyendo ironía/sarcasmo) sobre el tema: {tema} (descripción: {desc_tema})."
              "Tu salida debe ser exclusivamente JSON.")

    # Usamos {tema} y {keywords_str} directamente de u_conf
    # Población: {poblacion}
    user_template = f"""
--- MARCO DE CONTROL DEL PROYECTO ---
- Tema central de análisis: {tema}
- Descripción técnica: {desc_tema}
- Idiomas permitidos: {langs}
- Ubicación permitida: {population_scope}

--- INSTRUCCIONES DE EVALUACIÓN ---
Analiza el [COMENTARIO] y su contexto ([ENLACE/FUENTE], [TÍTULO POST] , [CUERPO POST], [TÍTULO VIDEO] , [DESCRIPCIÓN], [TWEET ANTERIOR], etc) para completar la verificación.

🚨 PASO 0: FILTRO DE EXCLUSIÓN TOTAL (Gatekeeper) 🚨
Eres un filtro de elegibilidad. Tu única tarea en este paso es decidir si el texto es una OPINIÓN válida (relevante para {population_scope}) o si debe EXCLUIRSE.

✅ PRINCIPIO CLAVE (anti-falsos excluidos):
- Si tienes DUDA razonable entre excluir o no, elige excluded=false y pasa al PASO 1.
- Solo usa excluded=true cuando el criterio de exclusión sea CLARO e INEQUÍVOCO.
- NO excluyas por “falta de contexto”: usa solo el texto.

REGLAS:
1) Si se cumple de forma CLARA e INEQUÍVOCA CUALQUIERA de los criterios de exclusión, responde con excluded=true, motivo_exclusion y asigna "2" a TODOS los pilares. DETENTE.
2) Si NO se cumple de forma clara ningún criterio, responde excluded=false y pasa al PASO 1.
3) No inventes contexto. Usa solo el texto.

CRITERIOS DE EXCLUSIÓN TOTAL (aplicar SOLO si es evidente):

A) IDIOMA:
EXCLUIR solo si el texto del COMENTARIO está principalmente en un idioma NO permitido.
Idiomas permitidos: {languages}.

B) GEOGRAFÍA AJENA (REGLA DE HERENCIA): 
EXCLUIR si el TEXTO del CONTEXTO proporcionado o el texto del COMENTARIO indican un lugar (barrio, ciudad o país) que NO forman parte del contexto geográfico objetivo: {population_scope}. 


C) TIPO DE TEXTO (TEXTO PURO, NO OPINIÓN):

C1 NOTICIA/INFORMATIVO (EXCLUIR SOLO SI ES TEXTO PURO):
Excluir SOLO si el texto se limita a informar/reproducir/resumir una noticia, titular o comunicado (p.ej. "BOE", "decreto", "comunicado", "según", "última hora") SIN expresar valoración personal.
Si hay CUALQUIER indicio de valoración (crítica, apoyo, indignación, ironía, burla, desconfianza, tono evaluativo, emojis de juicio), NO excluir.

C2 PUBLICIDAD/VENTA:
Excluir solo si hay intención comercial clara (precio, oferta, comprar, promo, enlace, venta) o es spam.

C3 DESCRIPCIÓN NEUTRA/TÉCNICA (EXCLUIR SOLO SI ES TEXTO PURO):
Excluir SOLO si el texto se limita a describir/explicar de forma impersonal (funcionamiento, datos, contexto) SIN evaluación personal, SIN emoción, SIN ironía/sarcasmo, SIN apoyo/queja.
Si hay cualquier juicio, queja, apoyo o crítica (aunque sea sutil o implícita), NO excluir.

D) FALSO POSITIVO:
Excluir solo si NO se refiere al objeto de opinión del tema: {tema} con descripción: {desc_tema}.
Si hay duda, NO excluir.

⚠️ INSTRUCCIÓN CRÍTICA:
- Analiza EXCLUSIVAMENTE el bloque "COMENTARIO".
- El bloque "CONTEXTO" solo sirve para entender referencias implícitas, relación con ámbito geográfico, o relación con tema de análisis.
- NO evalúes el título ni el cuerpo.
- Si el texto del COMENTARIO es una opinión aunque el CONTEXTO sea noticia, NO excluir.

FORMATO DE SALIDA SI excluded=true:
Devuelve SOLO este JSON (sin texto extra):
{{
  "Legitimación_sociopolítica": "2",
  "Efectividad_percibida": "2",
  "Justicia_y_equidad_percibida": "2",
  "Confianza_y_legitimidad_institucional": "2"
}}

🚨 PASO 1: SOLO si excluded=false 🚨
Bloque de reglas generales:
REGLAS GENERALES DE ANÁLISIS (OBLIGATORIAS)
1) Analiza únicamente el texto del COMENTARIO.
- No evalúes el título ni el CONTEXTO como si fueran la opinión.
- El CONTEXTO solo sirve para entender mejor el COMENTARIO.
2) Detecta juicios de valor, no información.
- Analiza opiniones, valoraciones o interpretaciones.
- No analices descripciones neutras o información factual.
3) Cada pilar mide una dimensión diferente.
- Evalúa cada pilar de forma independiente.
- Un mismo COMENTARIO puede activar varios pilares a la vez.
- No asumas ningún pilar por defecto. Cada pilar debe activarse solo si hay evidencia específica.
4) Prioriza el significado implícito.
- Ten en cuenta ironía, sarcasmo y tono.
- Interpreta la intención real del COMENTARIO.
5) No infieras más allá del texto.
- No inventes intención si no hay indicios.
- Si el significado es ambiguo, usa "0" (neutro).
6) Diferencia entre "0" y "2":
- "0" → hay referencia al pilar pero es ambigua o sin orientación clara.
- "2" → no hay ninguna referencia interpretable a ese pilar.
- En caso de duda leve, usa "0" en lugar de "2".
7) Si hay evidencia, clasifica (evita el "2").
- Usa "2" solo si NO hay absolutamente ninguna evidencia.

REGLAS DE DESAMBIGUACIÓN GLOBAL (MUY IMPORTANTES)
Cada pilar representa un tipo distinto de juicio.
Un mismo COMENTARIO puede contener varios juicios a la vez.
Evalúa cada pilar de forma independiente.
Un COMENTARIO puede activar varios pilares simultáneamente.
No elijas un único pilar dominante si hay varios juicios distintos.
--------------------------------------------------
IDENTIFICACIÓN POR TIPO DE JUICIO:
1) LEGITIMIDAD / LEGALIDAD / AJUSTE A NORMAS → Legitimacion
- ¿La medida se percibe como legal, legítima, válida o acorde a normas, ley, justicia o razón?
2) RESULTADO de la medida → Efectividad percibida
- ¿Funciona? ¿Sirve? ¿Tiene impacto real?
3) IMPACTO sobre las personas → Justicia y equidad percibida
- ¿Es justo o injusto? ¿A quién beneficia o perjudica?
4) ACTORES o responsables → Confianza institucional
- ¿Se critica o valora al gobierno, políticos o instituciones?
--------------------------------------------------
REGLA DE RESOLUCIÓN DE AMBIGÜEDAD:
Si una misma expresión puede pertenecer a varios pilares:
- Identifica el tipo de juicio principal de esa expresión concreta (legitimidad, resultado, impacto o actor)
- Esto NO impide que el comentario active varios pilares si contiene varios juicios distintos
--------------------------------------------------
REGLAS CLAVE DE SEPARACIÓN:
- Hablar de legalidad, legitimidad o ajuste con normas → Legitimacion
- Evaluar resultados → Efectividad
- Hablar de impacto en personas → Justicia
- Criticar actores → Confianza institucional
--------------------------------------------------
CASOS FRECUENTES:
- “esto es ilegal” → Legitimacion (-1)
- “no sirve para nada” → Efectividad (-1)
- “es injusto” → Justicia (-1)
- “solo quieren recaudar” → Confianza (-1)
--------------------------------------------------
CASOS AMBIGUOS:
Palabras como “aceptable”, “válido”, “correcto”, “ilegítimo”:
- Si se refieren a conformidad con ley, normas o legitimidad → Legitimacion
- Si se refieren al impacto en personas o reparto → Justicia
--------------------------------------------------
REGLA FINAL:
Si hay duda:
- Identifica primero el tipo de juicio
- NO uses "2" si hay cualquier indicio interpretable
Bloque de los pilares:
1) LEGITIMACION
--------------------------------------------------
Se refiere a si el comentario evalúa la medida en términos de legalidad, legitimidad o ajuste con las normas.
Legitimar significa convertir algo en legítimo, lícito o conforme a la ley, justicia o razón.
Pregunta clave:
¿El comentario sugiere que la medida es legal, legítima, válida o acorde con la ley, la justicia, las normas o la razón?
--------------------------------------------------
QUÉ INCLUYE:
- Si la medida es legal o ilegal
- Si la medida se percibe como legítima o ilegítima
- Si se ajusta o no a la ley, a las normas o a principios considerados válidos
- Si se presenta como aceptable o inaceptable por razones normativas o legales
- Juicios sobre si “debería poder hacerse” o “no deberían poder hacer esto”
--------------------------------------------------
EVIDENCIA POSITIVA (1):
Se asigna cuando el comentario expresa o sugiere que la medida es legal,
legítima, válida o conforme con las normas, la ley, la justicia o la razón.
Esto incluye:
- percepción de conformidad legal
- aceptación de la medida como válida o legítima
- valoración positiva de su ajuste con normas o principios
Ejemplos:
- “es legal”
- “es legítimo”
- “es válido”
- “es correcto”
- “cumple la ley”
También implícito:
- “tiene base legal”
- “no veo problema en que lo hagan”
- “es una medida aceptable”
- “está dentro de lo normal”
--------------------------------------------------
EVIDENCIA NEGATIVA (-1):
Se asigna cuando el comentario expresa o sugiere que la medida es ilegal,
ilegítima, inválida o contraria a normas, ley, justicia o razón.
Esto incluye:
- percepción de ilegalidad o ilegitimidad
- rechazo por falta de base normativa o legal
- juicio de que la medida “no debería permitirse”
Ejemplos:
- “es ilegal”
- “es ilegítimo”
- “va contra la ley”
- “no deberían poder hacer esto”
- “esto no es válido”
También implícito:
- “esto no tiene base legal”
- “no es aceptable”
- “se están saltando las normas”
- “esto no debería permitirse”
--------------------------------------------------
EVIDENCIA NEUTRA (0):
Se asigna cuando el comentario hace referencia a la legalidad o legitimidad de la medida,
pero NO expresa una valoración clara (ni positiva ni negativa).
Esto incluye:
- duda o incertidumbre sobre si es legal o legítima
- evaluaciones ambiguas o poco definidas
- menciones a normas o ley sin juicio claro
Ejemplos:
- “no sé si es legal”
- “habría que ver si esto cumple la ley”
- “no tengo claro si esto es legítimo”
- “no sé hasta qué punto se ajusta a la norma”
--------------------------------------------------
NO INCLUYE:
- Resultados → Efectividad
- Impacto social → Justicia
- Actores → Confianza
--------------------------------------------------
REGLA FINAL:
Si hay cualquier evaluación sobre legalidad, legitimidad o ajuste con normas → NO uses "2"
2) EFECTIVIDAD PERCIBIDA
--------------------------------------------------
Se refiere a si el comentario evalúa los RESULTADOS o la UTILIDAD de la medida.
Pregunta clave:
¿El comentario sugiere que la medida funciona, no funciona o tendrá impacto?
--------------------------------------------------
QUÉ INCLUYE:
- Si funciona o no funciona
- Si sirve o no sirve
- Si tendrá efectos reales
- Si mejorará o empeorará la situación
- Expectativas de impacto (aunque sean subjetivas)
--------------------------------------------------
EVIDENCIA POSITIVA (1):
Se asigna cuando el comentario expresa o sugiere que la medida es eficaz,
útil o tendrá un impacto positivo en la realidad.
Esto incluye:
- creencias de que la medida funciona o funcionará
- expectativas de mejora o solución de un problema
- valoración positiva del impacto o resultados de la medida
Ejemplos:
- “funciona”
- “sirve”
- “va a mejorar”
- “es útil”
- “tendrá efecto”
También implícito:
- “esto ayudará”
- “puede solucionar el problema”
- “esto sí que arregla las cosas”
- “puede funcionar bien”
--------------------------------------------------
EVIDENCIA NEGATIVA (-1):
Se asigna cuando el comentario expresa o sugiere que la medida es ineficaz,
inútil o no tendrá impacto real (o incluso empeorará la situación).
Esto incluye:
- negación de eficacia o utilidad
- expectativas de fracaso o ausencia de resultados
- creencias de que la medida no cambiará nada o tendrá efectos negativos
Ejemplos:
- “no sirve para nada”
- “es inútil”
- “no va a cambiar nada”
- “no funcionará”
- “es un fracaso”
También implícito:
- “esto no arregla nada”
- “no tiene ningún efecto”
- “esto no sirve”
- “no soluciona el problema”
- “esto va a empeorar las cosas”
--------------------------------------------------
EVIDENCIA NEUTRA (0):
Se asigna cuando el comentario hace referencia a la posible eficacia de la medida,
pero NO expresa una valoración clara (ni positiva ni negativa).
Esto incluye:
- duda o incertidumbre sobre si funcionará
- evaluaciones ambiguas o poco definidas
- comentarios que reconocen la posibilidad de distintos resultados sin posicionarse
Ejemplos:
- “no sé si funcionará”
- “puede que sí o puede que no”
- “habrá que ver si funciona”
- “no está claro si tendrá efecto”
--------------------------------------------------
NO INCLUYE:
- Legitimacion → Legitimacion
- Justicia → Justicia
- Críticas a actores → Confianza
--------------------------------------------------
REGLA FINAL:
Si hay cualquier evaluación sobre resultados o impacto → NO uses "2"
3) JUSTICIA Y EQUIDAD PERCIBIDA
--------------------------------------------------
Se refiere a si la medida se percibe como justa o injusta en cómo afecta a las personas.
Pregunta clave:
¿El COMENTARIO evalúa si la medida trata a las personas de forma justa?
--------------------------------------------------
QUÉ INCLUYE:
- Quién gana y quién pierde
- Reparto de costes y beneficios
- Desigualdad o discriminación
- Impacto en grupos sociales
- Justicia del proceso de decisión
--------------------------------------------------
EVIDENCIA POSITIVA (1):
Se asigna cuando el comentario expresa o sugiere que la medida es justa,
equitativa o distribuye de forma adecuada sus efectos entre las personas.
Esto incluye:
- percepción de reparto equilibrado de costes y beneficios
- trato igualitario entre individuos o grupos
- valoración positiva del impacto social de la medida
Ejemplos:
- “es justo”
- “es equitativo”
- “beneficia a todos”
También implícito:
- “es equilibrado”
- “reparte bien el impacto”
- “afecta a todos por igual”
- “no perjudica a nadie en particular”
--------------------------------------------------
EVIDENCIA NEGATIVA (-1):
Se asigna cuando el comentario expresa o sugiere que la medida es injusta,
desigual o afecta de forma negativa o desproporcionada a ciertos grupos.
Esto incluye:
- percepción de desigualdad o discriminación
- reparto injusto de costes o beneficios
- impacto negativo en personas o colectivos de forma no equitativa
Ejemplos:
- “es injusto”
- “discrimina”
- “perjudica a la gente”
- “siempre pagan los mismos”
También implícito:
- “esto castiga a la mayoría”
- “beneficia a unos y perjudica a otros”
- “los de siempre salen perdiendo”
- “esto afecta sobre todo a la gente normal”
--------------------------------------------------
EVIDENCIA NEUTRA (0):
Se asigna cuando el comentario hace referencia a la justicia o al impacto social,
pero NO expresa una valoración clara (ni positiva ni negativa).
Esto incluye:
- duda o ambivalencia sobre si es justo
- evaluaciones poco definidas o sin posicionamiento claro
- menciones al impacto social sin juicio explícito
Ejemplos:
- “no sé si es justo”
- “puede ser justo o no”
- “habría que ver si es equitativo”
--------------------------------------------------
NO INCLUYE:
- Legitimidad o legalidad → Legitimacion
- Resultados → Efectividad
- Actores → Confianza
--------------------------------------------------
REGLA FINAL:
Si hay referencia al impacto social → NO uses "2"
4) CONFIANZA INSTITUCIONAL
--------------------------------------------------
Se refiere a la confianza o desconfianza hacia los actores responsables.
Pregunta clave:
¿El COMENTARIO evalúa a los responsables de la medida?
--------------------------------------------------
QUÉ INCLUYE:
- Intenciones (honestas vs interesadas)
- Competencia (capaces vs incompetentes)
- Corrupción o intereses ocultos
--------------------------------------------------
EVIDENCIA POSITIVA (1):
Se asigna cuando el comentario expresa o sugiere que los actores responsables 
(gobierno, políticos o instituciones) son confiables, competentes o actúan con buenas intenciones.
Esto incluye:
- confianza en su capacidad para gestionar la medida
- percepción de profesionalidad o competencia
- atribución de intenciones honestas o responsables
Ejemplos:
- “confío en que lo harán bien”
- “son competentes”
También implícito:
- “están haciendo lo correcto”
- “parece que saben lo que hacen”
- “lo están gestionando bien”
--------------------------------------------------
EVIDENCIA NEGATIVA (-1):
Se asigna cuando el comentario expresa o sugiere desconfianza hacia los actores responsables,
atribuyéndoles incompetencia, malas intenciones o intereses propios.
Esto incluye:
- sospecha de intereses ocultos (dinero, política, beneficio propio)
- percepción de corrupción o manipulación
- percepción de incompetencia o mala gestión
Ejemplos:
- “solo quieren recaudar”
- “son corruptos”
- “no tienen ni idea”
También implícito:
- “no me fío de ellos”
- “lo hacen por su beneficio”
- “esto es puro interés político”
- “solo miran por ellos mismos”
--------------------------------------------------
EVIDENCIA NEUTRA (0):
Se asigna cuando el comentario menciona o implica a los actores responsables,
pero NO expresa una valoración clara (ni positiva ni negativa) sobre ellos.
Esto incluye:
- duda o ambivalencia
- evaluaciones débiles o poco definidas
- menciones sin juicio claro
Ejemplos:
- “no sé si lo hacen bien”
- “puede que tengan buenas intenciones”
- “el gobierno ha propuesto esto” (sin valoración)
--------------------------------------------------
REGLA CLAVE:
Debe haber referencia a actores (gobierno, políticos, instituciones).
--------------------------------------------------
NO INCLUYE:
- Legitimidad o legalidad → Legitimacion
- Resultados → Efectividad
- Impacto → Justicia
--------------------------------------------------
CASOS LÍMITE:
- “esto es ilegal porque el gobierno se ha pasado” → Legitimacion (-1) + Confianza (-1)
- “no me fío del gobierno aunque quizá funcione” → Confianza (-1) + Efectividad (0 o 1/-1 según el resto del comentario)
--------------------------------------------------
REGLA FINAL:
Si se evalúan actores → NO uses "2"
--------------------------------------------------
REGLAS DE FORMATO:
- Responde SOLO en JSON, sin texto adicional.
- Los valores deben ser SOLO el número en formato string.


--- COMENTARIO A ANALIZAR ---
__COMENTARIO__


FORMATO DE SALIDA SI excluded=false:

{{
  "Legitimacion_sociopolítica": "<1|-1|0|2>",
  "Efectividad_percibida": "<1|-1|0|2>",
  "Justicia_y_equidad_percibida": "<1|-1|0|2>",
  "Confianza_y_legitimidad_institucional": "<1|-1|0|2>"
}}
"""
    return system, user_template

# =====================================================
# 3. PREPARACIÓN DE TEXTO SEGURO (CONTROL DE LONGITUD)
# =====================================================

def preparar_texto_pilares_seguro(row, num_ctx=NUM_CTX):
    def count_tokens(texto): return len(texto) // 4 if texto else 0
    def safe_text(val):
        if val is None or pd.isna(val) or str(val).strip().lower() == "nan": return ""
        return str(val).strip()

    comentario = safe_text(row.get("contenido"))
    # --- FILTRO PARA COMENTARIOS BORRADOS ---
    textos_basura = ["[removed]", "[deleted]", "nan", "", "none"]
    if comentario.lower() in textos_basura:
        return "BORRADO"
    # ----------------------------------------------------

    subreddit = safe_text(row.get("subreddit"))

    titulo = safe_text(row.get("post_title"))
    cuerpo = safe_text(row.get("post_selftext"))
    titulo_video = safe_text(row.get("titulo_video"))
    descripcion = safe_text(row.get("descripcion_video"))
    tweet_previo = safe_text(row.get("BeforeContenido"))

    texto_final = f"[COMENTARIO]\n{comentario}"
    
    if subreddit:
        texto_final = f"[ENLACE/FUENTE]\n{subreddit}\n" + texto_final

    total_tokens = count_tokens(comentario)

    if titulo or cuerpo:
        if titulo and total_tokens + count_tokens(titulo) < num_ctx:
            texto_final = f"[TÍTULO POST]\n{titulo}\n" + texto_final
            total_tokens += count_tokens(titulo)
        if cuerpo and total_tokens + count_tokens(cuerpo) < num_ctx:
            texto_final = f"[CUERPO POST]\n{cuerpo}\n" + texto_final
    elif titulo_video or descripcion:
        if titulo_video and total_tokens + count_tokens(titulo_video) < num_ctx:
            texto_final = f"[TÍTULO VIDEO]\n{titulo_video}\n" + texto_final
        if descripcion and total_tokens + count_tokens(descripcion) < num_ctx:
            texto_final = f"[DESCRIPCIÓN VIDEO]\n{descripcion}\n" + texto_final
    elif tweet_previo:
        if total_tokens + count_tokens(tweet_previo) < num_ctx:
            texto_final = f"[TWEET ANTERIOR]\n{tweet_previo}\n" + texto_final

    return texto_final
'''