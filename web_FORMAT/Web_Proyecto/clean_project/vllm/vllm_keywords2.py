"""
PATCH — Clasificación Hiperlocal / Universal agnóstica
=======================================================
Sustituye las funciones hardcodeadas de España + transporte por equivalentes
que delegan en el LLM toda la clasificación y la expansión geográfica.
Funciona para cualquier idioma, país y tema.

INTEGRACIÓN:
  1. Añade este fichero junto a vllm_keywords2.py (o pega las funciones dentro).
  2. En generar_keywords() / generar_keywords_con_ia(), sustituye
     la llamada a clasificar_tema() por clasificar_tema_llm().
  3. La función expandir_geografia() ya es agnóstica — solo actualiza el prompt.
  4. El resto del pipeline (combinar_keywords_hiperlocal, etc.) no cambia.
"""
def _tiene_topónimo_inventado(keyword: str) -> bool:
    """
    Heurística para detectar posibles topónimos inventados.
    Detecta palabras compuestas con guión que mezclan idiomas de forma inusual.
    No es infalible — es una señal de alarma, no un descarte automático.
    """
    # Patrón: palabra-palabra donde la segunda parte no es común en topónimos españoles
    partes = re.findall(r'\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:-[A-Za-záéíóúñ]+)+\b', keyword)
    # Por ahora solo lo marca, no lo descarta automáticamente
    return len(partes) > 0 and any(len(p) > 20 for p in partes)

import json
import re
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from ddgs import DDGS

def reducir_redundancias(keywords: list) -> list:
    """
    Si 'semana santa sagunto' existe, elimina 'semana santa sagunto procesiones'
    porque la búsqueda corta ya incluye los resultados de la larga.
    """
    # Ordenar de más corta a más larga
    keywords_ordenadas = sorted(keywords, key=lambda x: len(x["keyword"]))
    finales =[]
    
    for kw in keywords_ordenadas:
        texto_kw = kw["keyword"].lower()
        es_redundante = False
        
        for aceptada in finales:
            texto_aceptada = aceptada["keyword"].lower()
            # Si la keyword corta está contenida exactamente dentro de la larga
            if re.search(rf'\b{re.escape(texto_aceptada)}\b', texto_kw):
                es_redundante = True
                print(f"   ✂️  Redundancia eliminada: '{texto_kw}' (ya cubierta por '{texto_aceptada}')")
                break
                
        if not es_redundante:
            finales.append(kw)
            
    return finales

def get_instruccion_lengua_cooficial(idioma: str) -> str:
    if idioma.lower() in IDIOMAS_COOFICIALES:
        return f"""
⚠️ IMPORTANTE: Responde EXCLUSIVAMENTE en {idioma}.
No mezcles con castellano ni ningún otro idioma.
Si no tienes suficientes términos en {idioma},
usa los términos en castellano que la comunidad de esa región
usaría realmente en redes sociales, ya que el code-switching
(mezcla de lenguas) es habitual en Twitter/X, Instagram y TikTok.
"""
    return ""

def get_ejemplos_logica_por_idioma(idioma: str) -> str:
    """
    Devuelve ejemplos de PROCESO DE RAZONAMIENTO, no de temática concreta.
    El objetivo es que el modelo aprenda el patrón mental:
      "para este tema en este lugar → busco entidades reales → combino con el lugar"
    Los ejemplos usan temas y lugares variados y deliberadamente distintos
    al tema que se va a analizar, para evitar que el modelo copie en lugar de razonar.
    """
    idioma_lower = idioma.lower()

    # ------------------------------------------------------------------
    # BLOQUE COMÚN: razonamiento geográfico (se incluye en TODOS los idiomas)
    # ------------------------------------------------------------------
    razonamiento_geografico = """
--- PROCESO DE RAZONAMIENTO GEOGRÁFICO ---
Cuando el análisis tiene un contexto geográfico, sigue este proceso mental:

PASO 1 — Pregúntate: ¿Quién gestiona o protagoniza este tema en ese lugar?
  → Busca el nombre real de la entidad local (organismo, empresa, institución).
  → Ejemplo de proceso: tema=AGUA, lugar=Madrid → respuesta="Canal de Isabel II"
  → Ejemplo de proceso: tema=EMPLEO, lugar=Andalucía → respuesta="SAE" (Servicio Andaluz de Empleo)
  → Ejemplo de proceso: tema=EDUCACIÓN, lugar=País Vasco → respuesta="Hezkuntza", "Ikastola"

PASO 2 — Pregúntate: ¿Qué infraestructuras, espacios o elementos concretos
  asocia la gente de ese lugar con este tema?
  → Ejemplo de proceso: tema=PLAYA, lugar=Málaga → respuesta="La Malagueta", "Baños del Carmen"
  → Ejemplo de proceso: tema=VIVIENDA, lugar=Barcelona → respuesta="22@", "Eixample"
  → Ejemplo de proceso: tema=SEGURIDAD, lugar=Sevilla → respuesta="Polígono Sur"

PASO 3 — Pregúntate: ¿Cómo llama la gente de ese lugar a este asunto en el día a día?
  → Busca apodos, abreviaciones o jerga local real.
  → Ejemplo de proceso: tema=FIESTAS, lugar=Valencia → respuesta="les Falles", "la cremà", "mascletà"
  → Ejemplo de proceso: tema=IMPUESTOS, lugar=Madrid → respuesta="plusvalía", "IBI"
  → Ejemplo de proceso: tema=TRANSPORTE, lugar=Sevilla → respuesta="Tussam", "Metro de Sevilla"

PASO 4 — Añade combinaciones naturales SOLO si la gente las usa realmente.
  → Ejemplo de proceso: tema=CONTAMINACIÓN, lugar=Valencia → "contaminación Valencia" ✅
  → Ejemplo de proceso: tema=HUELGA, lugar=Barcelona → "huelga Barcelona" ✅
  → NUNCA: "trabajadores barceloneses en huelga" ❌ (nadie lo escribe así en redes)

❌ ERRORES DE RAZONAMIENTO QUE DEBES EVITAR:
  → Pegar el gentilicio al sustantivo genérico: "metro valenciano", "hospital andaluz" ❌
  → Usar términos sin anclaje local: "metro", "autobús", "línea 1", "hospital", "colegio" ❌
  → Inventar nombres: "TransValencia", "BusRed Local" ❌
  → Términos temporales o de noticias: "noticias", "hoy", "última hora", "reciente" ❌
  → Frases genéricas aunque sean de dos palabras: "movilidad urbana", "calidad del aire" ❌
    (estas frases podrían ser de cualquier ciudad del mundo, no anclan al lugar)
"""

    # ------------------------------------------------------------------
    # CASTELLANO
    # ------------------------------------------------------------------
    if idioma_lower in ["castellano", "español", "es", "spanish"]:
        return razonamiento_geografico + """
--- EJEMPLOS DE APLICACIÓN DE LA LÓGICA (CASTELLANO) ---
Los siguientes ejemplos muestran cómo aplicar el razonamiento anterior.
Cada ejemplo es un tema DISTINTO al que estás analizando — aprende el patrón, no copies el contenido.

TEMA: "pantalán de sagunto" | LUGAR: Comunitat Valenciana
  RAZONAMIENTO: Es una infraestructura portuaria concreta → busco su nombre oficial y variantes reales
  ✅ "pantalán de sagunto"      → nombre oficial de la infraestructura
  ✅ "paseo marítimo sagunto"   → zona asociada que la gente menciona
  ✅ "puerto sagunto"           → referencia geográfica natural
  ❌ "zona portuaria"           → demasiado genérico
  ❌ "pantallán sagunto"        → error ortográfico
  ❌ "sagunto maritimo"         → construcción artificial

TEMA: "carril VAO" | LUGAR: España (sin ámbito local específico)
  RAZONAMIENTO: Es un término técnico con nombre oficial → busco nombre oficial + sinónimos reales
  ✅ "carril VAO"                       → término central oficial
  ✅ "carril vehículo alta ocupación"   → nombre completo oficial
  ✅ "carril multiocupante"             → sinónimo técnico real usado en prensa
  ✅ "carril bus VAO"                   → variante con tipo de vía
  ❌ "movilidad sostenible"             → demasiado genérico
  ❌ "carril vao hoy"                   → temporal
  ❌ "vaovao"                           → inventado

TEMA: "regularización de inmigrantes" | LUGAR: España (sin ámbito local específico)
  RAZONAMIENTO: Es un término político-legal → busco cómo habla la gente de esto en redes, no el lenguaje oficial
  ✅ "regularización inmigrantes"              → forma natural abreviada
  ✅ "legalizar inmigrantes"                  → sinónimo real usado en redes
  ✅ "regularización extraordinaria"          → variante de decreto real
  ✅ "amnistía inmigrantes"                   → término coloquial político usado en redes
  ❌ "decreto regularización"                 → demasiado genérico e institucional
  ❌ "regularización marroquíes"              → demasiado específico por origen

TEMA: "calidad del aire" | LUGAR: Madrid
  RAZONAMIENTO: Hay un protocolo municipal con nombre propio → busco ese nombre + zonas afectadas
  ✅ "protocolo anticontaminación Madrid"     → nombre del protocolo real
  ✅ "Madrid Central"                         → zona de restricción con nombre propio
  ✅ "restricciones tráfico Madrid"           → combinación natural real
  ✅ "contaminación Madrid"                   → combinación usada en redes
  ❌ "calidad del aire madrileña"             → gentilicio pegado artificialmente
  ❌ "calidad del aire"                       → genérico sin anclaje (vale para cualquier ciudad)
  ❌ "polución ciudad"                        → genérico sin anclaje
"""

    # ------------------------------------------------------------------
    # CATALÁN / VALENCIANO
    # ------------------------------------------------------------------
    elif idioma_lower in ["catalan", "català", "valenciano", "valencià"]:
        return razonamiento_geografico + """
--- EXEMPLES D'APLICACIÓ DE LA LÒGICA (CATALÀ / VALENCIÀ) ---
Els exemples següents mostren com aplicar el raonament anterior en català o valencià.
Aprèn el patró, no copiïs el contingut.

TEMA: "transport públic" | LLOC: Barcelona
  RAONAMENT: Hi ha operadors locals amb noms propis → busco el nom real de l'operador
  ✅ "Rodalies Barcelona"       → operador real amb nom propi
  ✅ "TMB Barcelona"            → Transports Metropolitans de Barcelona
  ✅ "metro Barcelona"          → combinació natural en xarxes
  ❌ "transport barceloní"      → gentilici enganxat artificialment
  ❌ "metro"                    → massa genèric (podria ser el metro de qualsevol ciutat)
  ❌ "movilitat urbana"         → frase genèrica sense ancoratge local
  ❌ "transport públic"         → frase genèrica sense ancoratge local

TEMA: "habitatge" | LLOC: Catalunya
  RAONAMENT: Hi ha lleis i organismes amb nom propi → busco-los
  ✅ "llei habitatge Catalunya"  → nom real de la llei
  ✅ "pisos turístics Barcelona" → combinació real usada a les xarxes
  ✅ "lloguer assequible"        → terme real usat en el debat
  ❌ "habitatge català"          → gentilici artificial

❌ ERROR ESPECÍFIC — NÚMEROS DE LÍNIA SENSE OPERADOR:
  "línia 1", "línia 2", "línia 3", "línia 4" → ❌ PROHIBIT ABSOLUTAMENT
  Sense el nom de l'operador, "línia 1" pot ser qualsevol línia d'arreu del món.
  ✅ Forma correcta: "línia 1 metrovalencia", "línia 3 metro valència"
  Si no coneixes el nom oficial de la línia en aquest context local, NO la incloguis.

❌ ERROR ESPECÍFIC — PARAULES DE NOTÍCIES O TEMPORALS:
  "metro valència notícies", "autobús noticias", "tramvia avui" → ❌ PROHIBIT
  Les paraules 'notícies', 'noticias', 'avui', 'hoy', 'reciente', 'recent'
  invaliden completament la keyword.
  Les keywords capturen converses, NO titulars de premsa.

NOTA D'IDIOMA: Si el terme real és un nom propi en castellà (p. ex. "Cercanías"),
manté'l tal qual. El code-switching és natural en xarxes socials valencianes i catalanes.
"""

    # ------------------------------------------------------------------
    # EUSKERA
    # ------------------------------------------------------------------
    elif idioma_lower in ["euskera", "basque", "eu"]:
        return razonamiento_geografico + """
--- LOGIKA APLIKATZEKO ADIBIDEAK (EUSKARA) ---
Honako adibideek aurreko arrazonamendua nola aplikatu erakusten dute.
Patroia ikasi, edukia ez kopiatu.

TEMA: "osasuna" | LEKUA: Euskadi
  ARRAZONAMENDUA: Osasun sistema propioa dago → bilatu izena
  ✅ "Osakidetza"              → osasun-zerbitzu publikoaren izena
  ✅ "Osakidetza itxaron"      → konbinazio naturala sare sozialetan
  ❌ "ospitalea"               → gehiegi generikoa

TEMA: "etxebizitza" | LEKUA: Bilbo
  ARRAZONAMENDUA: Bilboko auzo ezagunak daude → bilatu auzo-izenak
  ✅ "Casco Viejo etxebizitza" → auzoaren izen errealarekin
  ✅ "Bilboko alokairua"       → konbinazio naturala
  ❌ "etxe euskalduna"         → artifizialki sorturiko termino

❌ OHARRA — ALBISTE-HITZAK:
  "gaur", "azken ordua", "berriak" → ❌ DEBEKATUA
  Hitz hauek keyword bat baliogabetzen dute.

OHARRA: Gaztelaniazko izen propioak (adib. "Cercanías") bere horretan mantentzen dira.
"""

    # ------------------------------------------------------------------
    # INGLÉS
    # ------------------------------------------------------------------
    elif idioma_lower in ["ingles", "inglés", "english", "en"]:
        return razonamiento_geografico + """
--- EXAMPLES OF LOGIC APPLICATION (ENGLISH) ---
The following examples show how to apply the reasoning above.
Learn the pattern, do not copy the content.

TOPIC: "public transport" | PLACE: London
  REASONING: There are real operators with proper names → find the real name
  ✅ "TfL London"              → real operator name
  ✅ "London Underground"      → proper name used naturally
  ✅ "tube strike"             → colloquial term really used on social media
  ❌ "London buses"            → too generic
  ❌ "urban mobility"          → generic phrase with no local anchor

TOPIC: "housing" | PLACE: New York
  REASONING: There are real programs and areas with proper names → find them
  ✅ "NYC Housing Authority"   → real institution name
  ✅ "NYCHA"                   → real abbreviation used on social media
  ✅ "rent stabilization NYC"  → real policy term used in debates
  ❌ "New York housing"        → too generic
  ❌ "affordable homes"        → too generic without location anchor

❌ BANNED WORDS: "news", "today", "latest", "recent", "breaking"
  These words invalidate a keyword completely.

NOTE: Keep proper nouns in their original language if that is how
people use them on social media.
"""

    # ------------------------------------------------------------------
    # FRANCÉS
    # ------------------------------------------------------------------
    elif idioma_lower in ["frances", "francés", "french", "fr"]:
        return razonamiento_geografico + """
--- EXEMPLES D'APPLICATION DE LA LOGIQUE (FRANÇAIS) ---
Les exemples suivants montrent comment appliquer le raisonnement ci-dessus.
Apprenez le schéma, ne copiez pas le contenu.

THÈME: "transport en commun" | LIEU: Paris
  RAISONNEMENT: Il existe des opérateurs réels avec des noms propres → trouvez le vrai nom
  ✅ "RATP Paris"              → nom réel de l'opérateur
  ✅ "métro parisien"          → combinaison naturelle utilisée sur les réseaux
  ✅ "RER grève"               → terme colloquial réellement utilisé
  ❌ "transport parisien"      → trop générique
  ❌ "mobilité urbaine"        → phrase générique sans ancrage local

❌ MOTS INTERDITS: "actualités", "aujourd'hui", "récent", "dernières nouvelles"
  Ces mots invalident complètement un mot-clé.
"""

    # ------------------------------------------------------------------
    # PORTUGUÉS
    # ------------------------------------------------------------------
    elif idioma_lower in ["portugues", "portugués", "portuguese", "pt"]:
        return razonamiento_geografico + """
--- EXEMPLOS DE APLICAÇÃO DA LÓGICA (PORTUGUÊS) ---
Os exemplos seguintes mostram como aplicar o raciocínio acima.
Aprenda o padrão, não copie o conteúdo.

TEMA: "transporte público" | LOCAL: Lisboa
  RACIOCÍNIO: Existem operadores reais com nomes próprios → encontre o nome real
  ✅ "Carris Lisboa"           → nome real do operador
  ✅ "Metro de Lisboa"         → nome próprio usado naturalmente
  ✅ "passe Lisboa"            → termo real usado nas redes
  ❌ "transportes lisboetas"   → gentílico colado artificialmente
  ❌ "mobilidade urbana"       → frase genérica sem âncora local


❌ PALABRAS PROIBIDAS: "notícias", "hoje", "recente", "últimas"
  Estas palavras invalidam completamente uma keyword.
"""

    # ------------------------------------------------------------------
    # ITALIANO
    # ------------------------------------------------------------------
    elif idioma_lower in ["italiano", "italian", "it"]:
        return razonamiento_geografico + """
--- ESEMPI DI APPLICAZIONE DELLA LOGICA (ITALIANO) ---
I seguenti esempi mostrano come applicare il ragionamento sopra.
Impara il modello, non copiare il contenuto.

TEMA: "trasporto pubblico" | LUOGO: Milano
  RAGIONAMENTO: Esistono operatori reali con nomi propri → trova il nome reale
  ✅ "ATM Milano"              → nome reale dell'operatore
  ✅ "metro Milano"            → combinazione naturale usata sui social
  ✅ "passante ferroviario"    → nome proprio dell'infrastruttura
  ❌ "mobilità urbana"         → frase generica senza ancoraggio locale
  ❌ "autobus"                 → generico senza ancoraggio locale

❌ PAROLE VIETATE: "notizie", "oggi", "recente", "ultime notizie"
  Queste parole invalidano completamente una keyword.
"""

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------
    else:
        return razonamiento_geografico



# ==============================
# Configuración
# ==============================
client = OpenAI(
    base_url="http://host.docker.internal:8001/v1",
    api_key="token-local"
)
# vllm serve Qwen/Qwen2.5-14B-Instruct \
#   --port 8001 \
#   --dtype bfloat16 \
#   --max-model-len 7000 \
#   --gpu-memory-utilization 0.95
MODELO = "Qwen/Qwen2.5-14B-Instruct-AWQ"#"Qwen/Qwen2.5-VL-7B-Instruct"

IDIOMAS_COOFICIALES = {"catalán", "valenciano", "euskera", "gallego"}


# ──────────────────────────────────────────────────────────────────────────────
# 1. CLASIFICADOR AGNÓSTICO  (reemplaza a clasificar_tema())
# ──────────────────────────────────────────────────────────────────────────────

_PROMPT_CLASIFICAR = """
You are an expert in social media analysis and information retrieval.

Your task: classify whether a given topic requires **hyperlocal** keywords or **universal** keywords
when searching for social media posts about it.

DEFINITIONS:

HYPERLOCAL topic — The useful keywords depend on WHERE the analysis takes place.
  The most relevant search terms are names of local operators, local infrastructure,
  local neighborhoods, or local institutions. Without knowing the specific place,
  you cannot generate good keywords.
  
  Examples (any country, any topic):
    - "public transport" in Berlin → keywords are "BVG", "S-Bahn Berlin", "U-Bahn Mitte", etc.
    - "public transport" in São Paulo → keywords are "SPTrans", "CPTM", "Metrô SP", etc.
    - "waste collection" in Paris → keywords are "Veolia Paris", "grève éboueurs Paris", etc.
    - "local police" in Chicago → keywords are "CPD", "Chicago Police District 1", etc.
    - "water supply" in Lagos → keywords are "Lagos Water Corporation", "LAWMA", etc.
    - "local elections" in Catalonia → keywords are "Esquerra", "JxCat", "CUP", "PSC", etc.
    - "housing" in London → keywords are "Right to Buy London", "Sadiq Khan housing", "Hackney council", etc.

UNIVERSAL topic — The useful keywords do NOT depend on WHERE the analysis takes place.
  The search terms are the same regardless of the specific city or region.
  Geography is used as a FILTER after retrieval, not as part of the keyword itself.
  
  Examples (any country, any topic):
    - "immigration policy" → keywords are the same whether scope is France or Argentina
    - "cryptocurrency regulation" → same keywords worldwide
    - "climate change opinions" → same core keywords everywhere
    - "abortion rights debate" → same core keywords everywhere
    - "social media censorship" → same core keywords everywhere
    - "remote work trends" → same core keywords everywhere

DECISION RULE:
  Ask yourself: "If I change the geographic scope from City A to City B (different country),
  do the keywords change completely?"
  → YES, they change completely → HYPERLOCAL
  → NO, mostly the same core terms → UNIVERSAL

  HYPERLOCAL signals:
    - Topic involves a municipal or regional PUBLIC SERVICE (transport, waste, water, police,
      local health centers, local schools, local politics)
    - Topic involves LOCAL INFRASTRUCTURE (specific roads, bridges, parks, metro lines)
    - Topic involves LOCAL EVENTS (local elections, local festivals, local referendums)
    - Topic involves LOCAL INSTITUTIONS with different names per place

  UNIVERSAL signals:
    - Topic is a NATIONAL or GLOBAL POLICY debate (immigration, taxes, foreign policy)
    - Topic is a CULTURAL or SOCIAL MOVEMENT that transcends geography
    - Topic is a TECHNOLOGY or PRODUCT that has the same name everywhere
    - Topic is an INTERNATIONAL EVENT (global sports, international politics)

Topic: "{tema}"
Geographic scope: "{scope}"

Return ONLY valid JSON, no extra text:
{{
  "tipo": "hiperlocal" | "universal",
  "confianza": "alta" | "media" | "baja",
  "razon": "one sentence explaining the classification decision"
}}
"""


def clasificar_tema_llm(tema: str, population_scope: str, client, MODELO: str) -> str:
    """
    Clasifica el tema como 'hiperlocal' o 'universal' usando el LLM.
    Es completamente agnóstico: funciona para cualquier idioma, país y tema.

    Returns: 'hiperlocal' | 'universal'
    """
    scope = _normalizar_scope(population_scope)
    prompt = _PROMPT_CLASIFICAR.format(tema=tema, scope=scope)

    try:
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a classification expert. "
                        "You respond ONLY with valid JSON, no markdown, no extra text."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        raw = response.choices[0].message.content
        resultado = json.loads(raw)
        tipo = resultado.get("tipo", "universal")
        confianza = resultado.get("confianza", "?")
        razon = resultado.get("razon", "")

        # Normaliza por si el LLM devuelve variantes
        tipo = "hiperlocal" if "hiperlocal" in tipo.lower() else "universal"

        print(
            f"   🏷️  Tipo detectado: {tipo.upper()} "
            f"(confianza={confianza}) — {razon}"
        )
        return tipo

    except Exception as e:
        print(f"   ⚠️  Error en clasificación LLM: {e}. Usando 'universal' por defecto.")
        return "universal"


# ──────────────────────────────────────────────────────────────────────────────
# 2. EXPANSIÓN GEOGRÁFICA AGNÓSTICA  (reemplaza a expandir_geografia())
# ──────────────────────────────────────────────────────────────────────────────
_BANNED_TOKENS = {
    "noticias", "notícies", "noticia", "notícia",
    "última hora", "últimas noticias",
    "hoy", "avui", "gaur", "hoje",
    "reciente", "recientes", "recent", "recents",
    "novedad", "novedades", "novetat", "novetats",
    "breaking", "urgente", "urgent",
}

_NUMBERED_LINE_RE = re.compile(
    r"^(l[ií]n[ei]a|l[ií]nia|line|linia|línia)\s*\d+$",
    re.IGNORECASE
)

_GENERIC_PHRASES = {
    "movilidad urbana", "movilitat urbana", "mobilitat urbana",
    "transporte urbano", "transport urbà", "transporte público",
    "calidad del aire", "qualitat de l'aire", "qualitat de l aire",
    "medio ambiente", "medi ambient",
    "servicios públicos", "serveis públics",
    "infraestructura pública", "infraestructura publica",
    "gestión municipal", "gestió municipal",
}
_GENERIC_STANDALONE = {
    # transporte
    "metro", "bus", "autobús", "autobus", "autobuses", "autobusos",
    "tranvía", "tramvia", "tramvía", "tram",
    "tren", "renfe", "cercanías", "rodalies",
    "movilidad", "movilitat", "mobilitat", "transport", "transporte", "conectividad", "información",
    "línea", "linia", "línia", "linea",
    # sanidad
    "hospital", "clínica", "clinica", "médico", "medico",
    # educación
    "colegio", "instituto", "escuela", "escola", "ikastola",
    # seguridad
    "policía", "policia", "bomberos",
    # vivienda
    "vivienda", "habitatge", "etxebizitza", "alquiler", "lloguer",
    # genéricos absolutos
    "servicio", "servei", "infraestructura", "gestión", "gestió",
}




_PROMPT_EXPANSION_GEO = """
You are an expert in world geography and local public services analysis.

Topic: "{tema}"
Geographic scope: "{scope}"

Your task: decompose "{scope}" into the smaller geographic units that are most
useful for finding social media content about "{tema}".

RULES:
1. If "{scope}" is a CITY → return its main districts, neighborhoods, or boroughs.
2. If "{scope}" is a METROPOLITAN AREA → return the main municipalities it comprises.
3. If "{scope}" is a PROVINCE, DEPARTMENT, COUNTY, or REGION → return its main cities/towns.
4. If "{scope}" is a COUNTRY → return its main cities, regions, or federal states (max 15).
5. If "{scope}" is already a NEIGHBORHOOD or small area → return it as-is plus adjacent areas.
6. Also identify: operators/managers of "{tema}" in this area, and specific infrastructure names.

CRITICAL: Only include REAL, VERIFIABLE names. Do NOT invent names.
If you don't know the exact sub-units, return the most important ones you know with certainty.

Return ONLY valid JSON:
{{
  "tipo_scope": "city|metropolitan_area|province_region|country|neighborhood|other",
  "unidades_geograficas": ["name1", "name2", ...],
  "operadores_locales": ["real operator/institution name 1", ...],
  "terminos_infraestructura": ["real infrastructure name 1", ...]
}}
"""
def expandir_tema(tema: str, population_scope: str) -> dict | None:
    scope = _normalizar_scope(population_scope)
    print(f"   🔎 Buscando contexto web... tema='{tema}' | scope='{scope}'")
    contexto_web = buscar_contexto_web(tema, scope)

    prompt = get_prompt_topic_expansion(tema, scope, contexto_web)
    try:
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": "Eres un analista experto. Respondes únicamente en JSON válido."
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        raw = response.choices[0].message.content
        return json.loads(raw)
    except Exception as e:
        print(f"❌ Error en expansión del tema: {e}")
        return None
def get_prompt_keywords(tema: str, population_scope: str, idioma: str, brief: dict) -> str:
    scope = _normalizar_scope(population_scope)
    instruccion_lengua = get_instruccion_lengua_cooficial(idioma)
    ejemplos_logica = get_ejemplos_logica_por_idioma(idioma)

    seccion_geografica = ""
    if scope.upper() != "GLOBAL":
        seccion_geografica = f"""
--- CONTEXTO GEOGRÁFICO: {scope} ---
El análisis se centra EXCLUSIVAMENTE en: **{scope}**

Antes de generar cada término, hazte estas preguntas:
  1. ¿Quién gestiona o protagoniza este tema en {scope}? → usa su nombre real
  2. ¿Qué infraestructuras o lugares asocia la gente de {scope} con este tema? → úsalos
  3. ¿Cómo llama la gente de {scope} a esto en el día a día? → usa esa jerga local
  4. ¿Se usa el nombre del lugar junto al término? → solo si es natural, nunca forzado

❌ NUNCA hagas esto:
  - Pegar el gentilicio al término genérico: "hospital andaluz", "metro valenciano"
  - Usar términos sin anclaje local: "metro", "línea 1", "línia 2", "autobús", "hospital"
  - Usar frases genéricas de dos palabras: "movilidad urbana", "calidad del aire"
    (estas frases valen para CUALQUIER ciudad, no anclan a {scope})
  - Inventar nombres de organismos que no existen
  - Añadir palabras temporales: "hoy", "noticias", "reciente", "última hora"
  - Añadir números de línea sin operador: "línia 1", "línea 3" (sin nombre del operador)
"""

    return f"""
Eres un experto en recuperación de información para redes sociales.
Tu objetivo es generar términos de búsqueda en el idioma **{idioma.upper()}**
que maximicen la cobertura de publicaciones reales sobre el tema indicado.

{instruccion_lengua}

{seccion_geografica}

--- CONTEXTO DEL TEMA ---
Tema original: {tema}
Tema normalizado: {brief.get("tema_normalizado", tema)}
Descripción: {brief.get("descripcion_breve", "")}
Términos oficiales: {", ".join(brief.get("terminos_oficiales", []))}
⚠️ NO confundir con: {", ".join(brief.get("temas_relacionados_confundibles", []))}

--- OBJETIVO ---
Genera los términos que un usuario nativo de {idioma} usaría REALMENTE en redes sociales
(Bluesky, Reddit, YouTube, Twitter/X, Instagram, TikTok) para hablar de este tema.
El objetivo es capturar comentarios positivos, negativos y neutros sobre el tema.

{ejemplos_logica}

--- REGLAS FINALES ---
1. Máximo 15 términos. Solo los más relevantes y específicos.
2. Entre 2 y 4 palabras por término. Una sola palabra es demasiado genérica. Más de 5 palabras es institucional y nadie la usa en redes.
3. PROHIBIDO inventar términos, siglas o nombres que no existan en el habla real.
4. PROHIBIDO queries informacionales: "horarios de X", "paradas de X", "cómo llegar a X" → son búsquedas de Google, no posts en redes.
5. PROHIBIDO nombres institucionales completos: "Consejería de...", "Dirección General de..." → nadie los escribe en redes.
6. PROHIBIDO usar frases genéricas sin ancla local (ej: "movilidad urbana", "calidad del aire").
7. PROHIBIDO incluir palabras de noticias: "noticias", "hoy", "última hora", "reciente".
8. PROHIBIDO incluir números de línea sin el nombre del operador: "línia 1", "línea 3".
9. TEST DE REDES SOCIALES — antes de incluir cada término hazte estas 3 preguntas:
   a) ¿Una persona lo escribiría espontáneamente en redes, o lo buscaría en Google?
      "horario autobuses valencia" → Google ❌ | "metrovalencia" → redes ✅
   b) ¿Funciona igual si cambias Valencia por Madrid o Barcelona?
      Si SÍ → demasiado genérico ❌
   c) ¿Traería posts de otro tema distinto?
      Ejemplos de combinaciones INCORRECTAS:
      "bicicletas valencia" → ciclismo deportivo ❌ 
      Ejemplos de combinaciones correctas:  
        - "línea 1 metrovalencia" → exclusivamente metro de Valencia ✅
        - "valenbisi" → Servicio de Bicicletas de la ciudad de Valencia✅
        - "atmv" " → exclusivamente transporte público de Valencia ✅
      Si más del 30% de los resultados probables serían de otro tema → DESCÁRTALO.
0. PROHIBIDO construir frases con palabras-comodín pegadas a entidades reales:
    ❌ "problemas + entidad", "horario + entidad", "servicios + entidad",
       "mejoras + entidad", "información + entidad", "tarifas + entidad"
    Estas frases suenan a titular de nota de prensa, no a post de usuario.
    ✅ En su lugar: el nombre de la entidad solo, o combinado con el lugar.
       "emt valencia", "metrovalencia", "autobuses valencia"
--- FORMATO DE SALIDA (JSON) ---
{{
  "configuracion": {{
    "idioma_solicitado": "{idioma}",
    "ambito_geografico": "{scope}",
    "traduccion_fiel_del_tema": "nombre del tema en {idioma}"
  }},
  "keywords": [
    {{
      "keyword": "término de búsqueda",
      "languages": "{idioma}",
      "razon_tema": "¿Una persona normal escribiría EXACTAMENTE este término en Twitter/Reddit para quejarse, celebrar o comentar algo sobre este tema? Si la respuesta es 'lo buscaría en Google pero no lo escribiría en redes', descártalo.",
      "razon_geografica": "¿Este término funcionaría igual para buscar el mismo tema en Madrid, Barcelona o Sevilla sin cambiar nada? Si la respuesta es SÍ, es demasiado genérico y debes descartarlo."
    }}
  ]
}}
"""

def es_keyword_valida(kw_entry: dict) -> bool:
    """
    Devuelve False si la keyword cae en alguna categoría prohibida:
      1. Contiene palabras temporales / de noticias
      2. Es un solo término genérico sin anclaje
      3. Es el patrón "línea N" sin nombre de operador
      4. Es una frase genérica conocida sin anclaje geográfico
    """
    keyword = kw_entry.get("keyword", "").strip().lower()
    tokens = keyword.split()

    # 1. Tokens prohibidos (temporal / noticias)
    if any(t in _BANNED_TOKENS for t in tokens):
        return False
    # Cubre frases de dos palabras como "última hora"
    if any(phrase in keyword for phrase in _BANNED_TOKENS if " " in phrase):
        return False

    # 2. Genérico standalone (una sola palabra)
    if len(tokens) == 1 and tokens[0] in _GENERIC_STANDALONE:
        return False

    # 3. Patrón "línia N" / "línea N" sin operador
    if _NUMBERED_LINE_RE.match(keyword):
        return False

    # 4. Frase genérica conocida
    if keyword in _GENERIC_PHRASES:
        return False
    
    if len(tokens) > 5:
        return False

    return True

def generar_keywords_por_idioma(tema: str, idioma: str, population_scope: str, brief: dict) -> list:
    scope = _normalizar_scope(population_scope)
    prompt = get_prompt_keywords(tema, scope, idioma, brief)
    print(f"   📝 Generando keywords en {idioma} para '{tema}' | scope='{scope}'")
    try:
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un keyword generator experto en redes sociales. "
                        "Respondes solo en JSON válido. "
                        "Nunca usas términos genéricos sin anclaje geográfico o temático concreto. "
                        "Nunca incluyes palabras de noticias (noticias, hoy, reciente). "
                        "Nunca incluyes números de línea sin el nombre del operador (línia 1, línea 3)."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        return data.get("keywords", [])
    except Exception as e:
        print(f"❌ Error generando keywords para {idioma}: {e}")
        return []
def filtrar_keywords(keywords: list) -> list:
    validas = [k for k in keywords if es_keyword_valida(k)]
    descartadas = [k["keyword"] for k in keywords if not es_keyword_valida(k)]
    if descartadas:
        print(f"   🗑️  Filtradas {len(descartadas)} keywords inválidas: {descartadas}")
    return validas


def combinar_keywords_multilingue(keywords_por_idioma: list) -> dict:
    # Filtrar antes de combinar
    keywords_por_idioma = filtrar_keywords(keywords_por_idioma)

    keywords_por_idioma = reducir_redundancias(keywords_por_idioma)

    combinadas = {}
    razones_tema = {}
    razones_geo = {}

    for kw in keywords_por_idioma:
        key = kw["keyword"].strip().lower()
        idioma = kw.get("languages", "")
        razon_tema = kw.get("razon_tema", kw.get("razon", ""))
        razon_geo = kw.get("razon_geografica", "")

        if key in combinadas:
            idiomas_existentes = set(combinadas[key].split(", "))
            idiomas_existentes.add(idioma)
            combinadas[key] = ", ".join(sorted(idiomas_existentes))
        else:
            combinadas[key] = idioma
            razones_tema[key] = razon_tema
            razones_geo[key] = razon_geo

    return {
        "keywords": [
            {
                "keyword": k,
                "languages": v,
                "razon_tema": razones_tema.get(k, ""),
                "razon_geografica": razones_geo.get(k, "")
            }
            for k, v in combinadas.items()
        ]
    }


def expandir_geografia(tema: str, population_scope: str) -> dict:
    scope = _normalizar_scope(population_scope)
    
    # ── NUEVO: contexto web para obtener nombres reales ──────────────
    print(f"   🔎 Buscando contexto web para geografía... scope='{scope}'")
    contexto_web = buscar_contexto_web(f"barrios distritos {scope}", scope, max_results=5)
    
    seccion_web = ""
    if contexto_web:
        seccion_web = f"""
--- INFORMACIÓN WEB SOBRE {scope} ---
{contexto_web}

USA SOLO los nombres que aparezcan en esta información web o que conozcas con certeza absoluta.
NO inventes ni combines nombres que no hayas visto en fuentes reales.
"""
    # ────────────────────────────────────────────────────────────────
    
    prompt = _PROMPT_EXPANSION_GEO.format(tema=tema, scope=scope) + seccion_web

    try:
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a world geography expert. "
                        "You respond ONLY with valid JSON. "
                        "You NEVER invent names of places, operators, or infrastructure."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        raw = response.choices[0].message.content
        resultado = json.loads(raw)

        n_unidades = len(resultado.get("unidades_geograficas", []))
        operadores = resultado.get("operadores_locales", [])
        print(
            f"   🗺️  Expansión geográfica: {n_unidades} unidades | "
            f"Operadores: {operadores}"
        )
        return resultado

    except Exception as e:
        print(f"   ⚠️  Error en expansión geográfica: {e}")
        return {
            "tipo_scope": "other",
            "unidades_geograficas": [scope],
            "operadores_locales": [],
            "terminos_infraestructura": []
        }


# ──────────────────────────────────────────────────────────────────────────────
# 3. PROMPT HIPERLOCAL AGNÓSTICO  (reemplaza a get_prompt_keywords_hiperlocal())
# ──────────────────────────────────────────────────────────────────────────────

def get_prompt_keywords_hiperlocal(
    tema: str,          
    population_scope: str,
    idioma: str,
    brief: dict,
    geo_expansion: dict,
    get_instruccion_lengua_cooficial_fn=None,
    get_ejemplos_logica_por_idioma_fn=None,
) -> str:
    """
    Genera el prompt para keywords hiperlocales.
    Completamente agnóstico de idioma, país y tema.

    Parámetros opcionales para reutilizar las funciones ya existentes en
    vllm_keywords2.py sin duplicarlas:
      - get_instruccion_lengua_cooficial_fn: función del módulo original
      - get_ejemplos_logica_por_idioma_fn: función del módulo original
    """
    scope = _normalizar_scope(population_scope)

    # Reutiliza helpers existentes si se pasan; si no, cadena vacía
    instruccion_lengua = (
        get_instruccion_lengua_cooficial_fn(idioma)
        if get_instruccion_lengua_cooficial_fn
        else ""
    )
    ejemplos_logica = (
        get_ejemplos_logica_por_idioma_fn(idioma)
        if get_ejemplos_logica_por_idioma_fn
        else ""
    )

    unidades = geo_expansion.get("unidades_geograficas", [scope])
    operadores = geo_expansion.get("operadores_locales", [])
    infraestructuras = geo_expansion.get("terminos_infraestructura", [])
    tipo_scope = geo_expansion.get("tipo_scope", "other")

    # Bloque de contexto geográfico enriquecido (agnóstico)
    contexto_geo = f"""
--- GEOGRAPHIC CONTEXT: {scope} ---
Scope type: {tipo_scope}

Sub-units within this scope (districts, municipalities, boroughs, etc.):
  {", ".join(unidades[:20]) if unidades else scope}

Known local operators / managers of "{tema}" in this area:
  {", ".join(operadores) if operadores else "Find the ones you know with certainty."}

Known local infrastructure / specific elements:
  {", ".join(infraestructuras) if infraestructuras else "Find the ones you know with certainty."}
"""

    return f"""
You are an expert in social media information retrieval.
Your goal is to generate search terms in **{idioma.upper()}** that capture
REAL social media posts about "{tema}" within "{scope}".

{instruccion_lengua}

{contexto_geo}

--- TOPIC CONTEXT ---
Topic: {tema}
Description: {brief.get("descripcion_breve", brief.get("description", ""))}
Official terms: {", ".join(brief.get("terminos_oficiales", brief.get("official_terms", [])))}

--- GENERATION STRATEGY (HYPERLOCAL TOPIC) ---
For a hyperlocal topic, the most effective keywords combine:

LEVEL 1 — Name of the LOCAL OPERATOR / MANAGER (most important):
  Examples of the reasoning pattern:
    topic=PUBLIC TRANSPORT, place=Berlin → "BVG", "S-Bahn Berlin", "U-Bahn Berlin"
    topic=PUBLIC TRANSPORT, place=São Paulo → "SPTrans", "CPTM", "Metrô SP"
    topic=WASTE COLLECTION, place=Paris → "Veolia Paris", "éboueurs Paris"
    topic=WATER SUPPLY, place=Lagos → "Lagos Water Corporation", "LAWMA"
  → Apply this pattern to: topic="{tema}", place="{scope}"
  → Generate all operators YOU KNOW WITH CERTAINTY exist in {scope}.
  → NEVER invent operator names.

LEVEL 2 — Operator name + specific sub-unit:
  Examples of the reasoning pattern:
    "BVG Mitte", "S-Bahn Wedding", "SPTrans Pinheiros"
  → Combine the real operator with the sub-units listed above.
  → Only if the combination sounds natural in {idioma} social media.

LEVEL 3 — Named infrastructure (lines, stations, routes with REAL names):
  → Only include names you KNOW are real in {scope}.
  → NEVER invent line names, station names, or route numbers.
  → If unsure about the official name, skip it.

LEVEL 4 — Topic term + place (natural in social media):
  Examples: "public transport Berlin", "bus London", "metro Cairo"
  → Only combine if people actually write it this way on social media in {idioma}.

LEVEL 5 — Opinion terms + topic + place:
  Examples: "delay BVG Berlin", "strike SPTrans", "price metro Cairo"
  → Captures complaints, praise, or debates specific to {scope}.

--- SPECIAL RULES FOR HYPERLOCAL TOPICS ---
✅ ALLOWED (different from universal topics):
  - Single-word proper nouns that are local brand names (e.g., "Valenbisi", "BVG", "RATP")
  - Operator + place combinations even if individual words are generic
  - Up to 30 keywords if there are enough geographic sub-units to cover
  - Terms in multiple local languages if commonly used in that area

❌ PROHIBITED (same as always):
  - Inventing operator names, line names, or infrastructure names
  - Temporal words: "news", "today", "latest", "noticias", "hoy", "aujourd'hui", etc.
  - Phrases longer than 5 words
  - Informational queries: "how to get to...", "schedule of...", "how much does X cost"
  - Generic phrases without local anchor: "urban mobility", "public services", etc.

⚠️ ANTI-HALLUCINATION RULE (CRITICAL — READ CAREFULLY):
Before including ANY proper noun (neighborhood, district, street, institution):
  1. Does this name appear EXACTLY in the verified geographic context above?
  2. Are you 100% certain of the EXACT spelling?
  If the answer to EITHER question is NO → DO NOT include it.
 
Known hallucination examples to AVOID:
  ❌ "Cabañal-Carparisse" → does NOT exist. Correct name: "Cabanyal-Canyamelar"
  ❌ "TransValencia" → does NOT exist. Correct names: "Metrovalencia", "EMT Valencia", "Valenbisi", "metrobús" 
  ❌ Any hyphenated neighborhood name you are not 100% sure about → OMIT IT
 
When in doubt, use the broader place name (e.g., "seguridad Valencia") instead of
a specific neighborhood name you are unsure about.

{ejemplos_logica}

--- OUTPUT FORMAT (JSON) ---
{{
  "configuracion": {{
    "idioma_solicitado": "{idioma}",
    "ambito_geografico": "{scope}",
    "tipo_tema": "hiperlocal"
  }},
  "keywords": [
    {{
      "keyword": "search term",
      "languages": "{idioma}",
      "nivel": "1|2|3|4|5",
      "razon": "Why would someone in {scope} write EXACTLY this on social media about {tema}?"
    }}
  ]
}}

Return ONLY valid JSON, no markdown, no extra text.
"""


# ──────────────────────────────────────────────────────────────────────────────
# 4. FUNCIÓN DE GENERACIÓN HIPERLOCAL POR IDIOMA (agnóstica)
# ──────────────────────────────────────────────────────────────────────────────

def generar_keywords_hiperlocal_por_idioma(
    tema: str,
    idioma: str,
    population_scope: str,
    brief: dict,
    geo_expansion: dict,
    client,
    MODELO: str,
    get_instruccion_lengua_cooficial_fn=None,
    get_ejemplos_logica_por_idioma_fn=None,
) -> list:
    """
    Genera keywords para temas hiperlocales en un idioma dado.
    Agnóstica de idioma, país y tema.
    NO aplica el filtro de términos genéricos (_GENERIC_STANDALONE)
    porque para hiperlocal "bus + place" SÍ tiene sentido.
    """
    scope = _normalizar_scope(population_scope)
    prompt = get_prompt_keywords_hiperlocal(
        tema, scope, idioma, brief, geo_expansion,
        get_instruccion_lengua_cooficial_fn,
        get_ejemplos_logica_por_idioma_fn,
    )

    print(f"   📝 [HIPERLOCAL] Generando en {idioma} | tema='{tema}' | scope='{scope}'")
    try:
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a social media keyword generation expert specializing in "
                        "local services and municipal topics worldwide. "
                        "You respond ONLY with valid JSON. "
                        "You NEVER invent operator names, line names, or infrastructure names. "
                        "You NEVER include temporal words (news, today, latest, noticias, hoy)."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.15,  # Ligeramente más alto para cubrir variantes locales
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        keywords = data.get("keywords", [])
        print(f"   ✅ [HIPERLOCAL] {idioma}: {len(keywords)} keywords generadas")
        return keywords
    except Exception as e:
        print(f"   ❌ Error generando keywords hiperlocales en {idioma}: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 5. COMBINADOR HIPERLOCAL (sin filtro de genéricos, con filtro de temporales)
# ──────────────────────────────────────────────────────────────────────────────

def combinar_keywords_hiperlocal(
    keywords_lista: list,
    banned_tokens: set = None,
    reducir_redundancias_fn=None,
) -> dict:
    """
    Combina y deduplica keywords para temas hiperlocales.
    NO aplica el filtro _GENERIC_STANDALONE (porque "bus + place" es válido).
    Solo aplica el filtro de términos temporales/de noticias.

    Parámetros:
      - banned_tokens: usa _BANNED_TOKENS de vllm_keywords2.py si no se pasa
      - reducir_redundancias_fn: usa reducir_redundancias() de vllm_keywords2.py si no se pasa
    """
    if banned_tokens is None:
        # Tokens temporales/de noticias internacionales (multi-idioma)
        banned_tokens = {
            # ES
            "noticias", "noticia", "notícies", "notícia",
            "última hora", "últimas noticias",
            "hoy", "avui", "gaur", "hoje",
            "reciente", "recientes", "recent",
            "novedad", "novedades", "novetat",
            "breaking", "urgente", "urgent",
            # EN
            "news", "today", "latest", "breaking", "update", "updates",
            # FR
            "actualités", "aujourd'hui", "récent", "dernières",
            # DE
            "nachrichten", "heute", "aktuell", "neueste",
            # IT
            "notizie", "oggi", "recente", "ultime",
            # PT
            "notícias", "hoje", "recente", "últimas",
            # AR
            "أخبار", "اليوم",
            # ZH
            "新闻", "今天",
        }

    def es_valida_hiperlocal(kw_entry: dict) -> bool:
        keyword = kw_entry.get("keyword", "").strip().lower()
        tokens = keyword.split()

        # Filtro 1: Tokens temporales/de noticias
        if any(t in banned_tokens for t in tokens):
            return False
        if any(phrase in keyword for phrase in banned_tokens if " " in phrase):
            return False

        # Filtro 2: Frases demasiado largas (más permisivo que el estándar)
        if len(tokens) > 6:
            return False

        # Filtro 3: Vacías
        if not keyword:
            return False

        return True

    keywords_validas = [k for k in keywords_lista if es_valida_hiperlocal(k)]
    descartadas = [k["keyword"] for k in keywords_lista if not es_valida_hiperlocal(k)]
    if descartadas:
        print(f"   🗑️  [HIPERLOCAL] Filtradas {len(descartadas)} keywords: {descartadas}")

    # Deduplicar redundancias
    if reducir_redundancias_fn:
        keywords_validas = reducir_redundancias_fn(keywords_validas)

    combinadas = {}
    razones = {}

    for kw in keywords_validas:
        key = kw["keyword"].strip().lower()
        idioma = kw.get("languages", "")
        razon = kw.get("razon", kw.get("razon_tema", ""))

        if key in combinadas:
            idiomas_existentes = set(combinadas[key].split(", "))
            idiomas_existentes.add(idioma)
            combinadas[key] = ", ".join(sorted(idiomas_existentes))
        else:
            combinadas[key] = idioma
            razones[key] = razon

    return {
        "keywords": [
            {"keyword": k, "languages": v, "razon_tema": razones.get(k, "")}
            for k, v in combinadas.items()
        ]
    }


# ──────────────────────────────────────────────────────────────────────────────
# 6. PIPELINE PRINCIPAL ACTUALIZADO
# ──────────────────────────────────────────────────────────────────────────────

def generar_keywords_con_ia(
    tema: str,
    population_scope,
    target_languages: list,
    # Inyecta las funciones del módulo original para no duplicar código:
    client=None,
    MODELO=None,
    expandir_tema_fn=None,
    generar_keywords_por_idioma_fn=None,
    combinar_keywords_multilingue_fn=None,
    reducir_redundancias_fn=None,
    get_instruccion_lengua_cooficial_fn=None,
    get_ejemplos_logica_por_idioma_fn=None,
):
    """
    Pipeline principal. Agnóstico de idioma, país y tema.

    Para integrar con logica.py, llama a esta función pasando las funciones
    del módulo original como parámetros, o simplemente copia este pipeline
    dentro de logica.py y llama a las funciones directamente.
    """
    poblacion_str = (
        ", ".join(population_scope)
        if isinstance(population_scope, list) and population_scope
        else str(population_scope).strip() or "GLOBAL"
    )

    if not tema:
        return {"keywords": [], "brief": ""}

    print(f"\n🚀 tema='{tema}' | idiomas={target_languages} | scope='{poblacion_str}'")

    # 1. Clasificar tipo (LLM, agnóstico)
    tipo_tema = clasificar_tema_llm(tema, poblacion_str, client, MODELO)

    # 2. Expandir tema (común para A y B)
    brief = expandir_tema_fn(tema, poblacion_str) if expandir_tema_fn else {}
    if not brief:
        print("⚠️  No se pudo expandir el tema.")
        return {"keywords": [], "brief": ""}
    print(f"   BRIEF: {brief.get('descripcion_breve', brief.get('description', ''))}")

    if tipo_tema == "hiperlocal":
        # ── RAMA B: HIPERLOCAL ─────────────────────────────────────────
        print(f"\n🏙️  [HIPERLOCAL] Expandiendo geografía de '{poblacion_str}'...")
        geo_expansion = expandir_geografia(tema, poblacion_str, client, MODELO)

        todas = []
        with ThreadPoolExecutor(max_workers=max(1, len(target_languages))) as executor:
            futuros = {
                executor.submit(
                    generar_keywords_hiperlocal_por_idioma,
                    tema, idioma, poblacion_str, brief, geo_expansion,
                    client, MODELO,
                    get_instruccion_lengua_cooficial_fn,
                    get_ejemplos_logica_por_idioma_fn,
                ): idioma
                for idioma in target_languages
            }
            for futuro in as_completed(futuros):
                idioma = futuros[futuro]
                try:
                    kws = futuro.result()
                    todas.extend(kws)
                except Exception as e:
                    print(f"   ❌ {idioma}: {e}")

        resultado = combinar_keywords_hiperlocal(
            todas,
            reducir_redundancias_fn=reducir_redundancias_fn,
        )

    else:
        # ── RAMA A: UNIVERSAL ──────────────────────────────────────────
        print(f"\n🌍  [UNIVERSAL] Generando keywords estándar...")
        todas = []
        with ThreadPoolExecutor(max_workers=max(1, len(target_languages))) as executor:
            futuros = {
                executor.submit(
                    generar_keywords_por_idioma_fn, tema, idioma, poblacion_str, brief
                ): idioma
                for idioma in target_languages
            }
            for futuro in as_completed(futuros):
                idioma = futuros[futuro]
                try:
                    kws = futuro.result()
                    todas.extend(kws)
                except Exception as e:
                    print(f"   ❌ {idioma}: {e}")

        resultado = combinar_keywords_multilingue_fn(todas)

    n = len(resultado["keywords"])
    print(f"\n✅ {n} keywords ({tipo_tema}): {[k['keyword'] for k in resultado['keywords']]}")

    return {
        "keywords": resultado["keywords"],
        "brief": brief.get("descripcion_breve", brief.get("description", "")),
        "tipo_tema": tipo_tema,
    }


# ──────────────────────────────────────────────────────────────────────────────
# HELPER (reutilizado de vllm_keywords2.py — incluido aquí por completitud)
# ──────────────────────────────────────────────────────────────────────────────

def _normalizar_scope(population_scope) -> str:
    """Convierte cualquier tipo de entrada en un string limpio."""
    if isinstance(population_scope, list):
        return ", ".join(population_scope) if population_scope else "GLOBAL"
    return str(population_scope).strip() or "GLOBAL"

# ============================================================
# FIX 1 — Añadir al FINAL de vllm_keywords2.py (no borrar nada)
# ============================================================
# Pega este bloque al final del fichero original.
# Conserva todas las funciones existentes intactas.
# ============================================================

# ──────────────────────────────────────────────────────────────
# CLASIFICADOR AGNÓSTICO (reemplaza la lista hardcodeada)
# ──────────────────────────────────────────────────────────────

_PROMPT_CLASIFICAR = """
You are an expert in social media analysis and information retrieval.

Your task: classify whether a given topic requires **hyperlocal** keywords or **universal**
keywords when searching for social media posts about it.

HYPERLOCAL — useful keywords DEPEND on WHERE the analysis takes place.
  The most relevant terms are names of local operators, local infrastructure,
  neighborhoods, or local institutions.  Without knowing the specific place
  you cannot generate good keywords.

  Examples (any country, any topic):
    "public transport" in Berlin      → "BVG", "S-Bahn Berlin", "U-Bahn Mitte"
    "public transport" in São Paulo   → "SPTrans", "CPTM", "Metrô SP"
    "waste collection"  in Paris      → "Veolia Paris", "grève éboueurs Paris"
    "local police"      in Chicago    → "CPD", "Chicago Police District 1"
    "water supply"      in Lagos      → "Lagos Water Corporation", "LAWMA"
    "local elections"   in Catalonia  → "Esquerra", "JxCat", "CUP", "PSC"
    "housing"           in London     → "Right to Buy London", "Hackney council"

UNIVERSAL — useful keywords are the SAME regardless of specific city/region.
  Geography is a retrieval filter, NOT part of the keyword itself.

  Examples:
    "immigration policy"      → same terms whether scope is France or Argentina
    "cryptocurrency regulation"
    "climate change opinions"
    "abortion rights debate"
    "remote work trends"

DECISION RULE:
  "If I change the geographic scope from City A to City B (different country),
   do the keywords change completely?"
  → YES → HYPERLOCAL
  → NO  → UNIVERSAL

  HYPERLOCAL signals: municipal/regional public service, local infrastructure,
    local events (festivals, referendums), local institutions with different
    names per place.
  UNIVERSAL signals: national/global policy debate, cultural/social movement
    that transcends geography, technology/product with the same name everywhere,
    international event.

Topic: "{tema}"
Geographic scope: "{scope}"

Return ONLY valid JSON, no extra text:
{{
  "tipo": "hiperlocal",
  "confianza": "alta|media|baja",
  "razon": "one sentence"
}}
OR
{{
  "tipo": "universal",
  "confianza": "alta|media|baja",
  "razon": "one sentence"
}}
"""


def clasificar_tema_llm(tema: str, population_scope: str) -> str:
    """
    Classifies a topic as 'hiperlocal' or 'universal' using the LLM.
    Fully agnostic: works for any language, country, and topic.

    Uses the module-level `client` and `MODELO` already defined above.
    Returns: 'hiperlocal' | 'universal'
    """
    scope = _normalizar_scope(population_scope)
    prompt = _PROMPT_CLASIFICAR.format(tema=tema, scope=scope)

    try:
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a classification expert. "
                        "Respond ONLY with valid JSON, no markdown, no extra text."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        raw = response.choices[0].message.content
        resultado = json.loads(raw)
        tipo = resultado.get("tipo", "universal")
        confianza = resultado.get("confianza", "?")
        razon = resultado.get("razon", "")

        # Normalise in case the LLM returns variants
        tipo = "hiperlocal" if "hiperlocal" in tipo.lower() else "universal"

        print(
            f"   🏷️  Tipo detectado: {tipo.upper()} "
            f"(confianza={confianza}) — {razon}"
        )
        return tipo

    except Exception as e:
        print(f"   ⚠️  Error en clasificación LLM: {e}. Usando 'universal' por defecto.")
        return "universal"


# Backward-compat alias so that logica.py can keep importing `clasificar_tema`
clasificar_tema = clasificar_tema_llm


# ──────────────────────────────────────────────────────────────
# EXPANSIÓN GEOGRÁFICA AGNÓSTICA
# ──────────────────────────────────────────────────────────────

_PROMPT_EXPANSION_GEO = """
You are an expert in world geography and local public services analysis.

Topic: "{tema}"
Geographic scope: "{scope}"

Decompose "{scope}" into the smaller geographic units most useful for finding
social media content about "{tema}".

RULES:
1. CITY          → main districts, neighborhoods, boroughs.
2. METROPOLITAN AREA → main municipalities it comprises.
3. PROVINCE / DEPARTMENT / COUNTY / REGION → main cities/towns.
4. COUNTRY       → main cities, regions, or federal states (max 15).
5. NEIGHBORHOOD  → return it as-is plus adjacent areas.
6. Also identify: real operators/managers of "{tema}" here, and real infrastructure names.

CRITICAL: Only include REAL, VERIFIABLE names. Never invent names.

Return ONLY valid JSON:
{{
  "tipo_scope": "city|metropolitan_area|province_region|country|neighborhood|other",
  "unidades_geograficas": ["name1", "name2"],
  "operadores_locales": ["real operator name 1"],
  "terminos_infraestructura": ["real infrastructure name 1"]
}}
"""


def expandir_geografia(tema: str, population_scope: str) -> dict:
    """
    Decomposes the geographic scope into sub-units for hyperlocal topics.
    Fully agnostic: works for any country and language.
    Uses the module-level `client` and `MODELO`.
    """
    scope = _normalizar_scope(population_scope)
    prompt = _PROMPT_EXPANSION_GEO.format(tema=tema, scope=scope)

    try:
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a world geography expert. "
                        "Respond ONLY with valid JSON. "
                        "NEVER invent names of places, operators, or infrastructure."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        raw = response.choices[0].message.content
        resultado = json.loads(raw)
        n = len(resultado.get("unidades_geograficas", []))
        ops = resultado.get("operadores_locales", [])
        print(f"   🗺️  Expansión geográfica: {n} unidades | Operadores: {ops}")
        return resultado

    except Exception as e:
        print(f"   ⚠️  Error en expansión geográfica: {e}")
        return {
            "tipo_scope": "other",
            "unidades_geograficas": [scope],
            "operadores_locales": [],
            "terminos_infraestructura": []
        }


# ──────────────────────────────────────────────────────────────
# PROMPT HIPERLOCAL AGNÓSTICO
# ──────────────────────────────────────────────────────────────

def get_prompt_keywords_hiperlocal(
    tema: str,
    population_scope: str,
    idioma: str,
    brief: dict,
    geo_expansion: dict,
) -> str:
    """
    Builds the hyperlocal keyword prompt.
    Fully agnostic of language, country, and topic.
    Reuses the existing get_instruccion_lengua_cooficial and
    get_ejemplos_logica_por_idioma already defined in this module.
    """
    scope = _normalizar_scope(population_scope)
    instruccion_lengua = get_instruccion_lengua_cooficial(idioma)
    ejemplos_logica = get_ejemplos_logica_por_idioma(idioma)

    unidades = geo_expansion.get("unidades_geograficas", [scope])
    operadores = geo_expansion.get("operadores_locales", [])
    infraestructuras = geo_expansion.get("terminos_infraestructura", [])
    tipo_scope = geo_expansion.get("tipo_scope", "other")

    contexto_geo = f"""
--- GEOGRAPHIC CONTEXT: {scope} ---
Scope type: {tipo_scope}

Sub-units within this scope (districts, municipalities, boroughs, etc.):
  {", ".join(unidades[:20]) if unidades else scope}

Known local operators / managers of "{tema}" in this area:
  {", ".join(operadores) if operadores else "Find the ones you know with certainty."}

Known local infrastructure / specific elements:
  {", ".join(infraestructuras) if infraestructuras else "Find the ones you know with certainty."}
"""

    return f"""
You are an expert in social media information retrieval.
Your goal is to generate search terms in **{idioma.upper()}** that capture
REAL social media posts about "{tema}" within "{scope}".

{instruccion_lengua}

{contexto_geo}

--- TOPIC CONTEXT ---
Topic: {tema}
Description: {brief.get("descripcion_breve", "")}
Official terms: {", ".join(brief.get("terminos_oficiales", []))}

--- GENERATION STRATEGY (HYPERLOCAL TOPIC) ---
LEVEL 1 — Name of the LOCAL OPERATOR / MANAGER (most important):
  Pattern examples (apply to topic="{tema}", place="{scope}"):
    PUBLIC TRANSPORT + Berlin → "BVG", "S-Bahn Berlin", "U-Bahn Berlin"
    PUBLIC TRANSPORT + São Paulo → "SPTrans", "CPTM", "Metrô SP"
    WASTE COLLECTION + Paris → "Veolia Paris", "éboueurs Paris"
    WATER SUPPLY + Lagos → "Lagos Water Corporation", "LAWMA"
  → Only generate operators YOU KNOW WITH CERTAINTY exist in {scope}.
  → NEVER invent operator names.

LEVEL 2 — Operator + specific sub-unit:
  Pattern: "BVG Mitte", "S-Bahn Wedding", "SPTrans Pinheiros"
  → Only if natural in {idioma} social media.

LEVEL 3 — Named infrastructure (lines, stations with REAL names only):
  → Skip if unsure of the official name.

LEVEL 4 — Topic + place (natural in social media):
  Pattern: "public transport Berlin", "bus London", "metro Cairo"

LEVEL 5 — Opinion + topic + place:
  Pattern: "delay BVG Berlin", "strike SPTrans", "price metro Cairo"

✅ ALLOWED for hyperlocal:
  - Single-word proper nouns: "Valenbisi", "BVG", "RATP", "Metrovalencia"
  - Operator + place even if individual words are generic
  - Up to 30 keywords if enough geographic sub-units
  - Terms in multiple local languages if commonly mixed in that area

❌ PROHIBITED:
  - Inventing any operator, line, or infrastructure name
  - Temporal words: "news", "today", "noticias", "hoy", "aujourd'hui", "heute", etc.
  - Phrases longer than 5 words
  - Informational queries: "how to get to...", "schedule of...", "how much..."
  - Generic phrases without local anchor: "urban mobility", "public services"

{ejemplos_logica}

--- OUTPUT FORMAT (JSON) ---
{{
  "configuracion": {{
    "idioma_solicitado": "{idioma}",
    "ambito_geografico": "{scope}",
    "tipo_tema": "hiperlocal"
  }},
  "keywords": [
    {{
      "keyword": "search term",
      "languages": "{idioma}",
      "nivel": "1|2|3|4|5",
      "razon": "Why would someone in {scope} write EXACTLY this on social media about {tema}?"
    }}
  ]
}}

Return ONLY valid JSON, no markdown, no extra text.
"""


# ──────────────────────────────────────────────────────────────
# GENERADOR HIPERLOCAL POR IDIOMA
# ──────────────────────────────────────────────────────────────

def generar_keywords_hiperlocal_por_idioma(
    tema: str,
    idioma: str,
    population_scope: str,
    brief: dict,
    geo_expansion: dict,
) -> list:
    """
    Generates hyperlocal keywords for a given language.
    Does NOT apply _GENERIC_STANDALONE filter (because "bus + place" is valid here).
    Uses module-level client and MODELO.
    """
    scope = _normalizar_scope(population_scope)
    prompt = get_prompt_keywords_hiperlocal(tema, scope, idioma, brief, geo_expansion)

    print(f"   📝 [HIPERLOCAL] Generando en {idioma} | tema='{tema}' | scope='{scope}'")
    try:
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a social media keyword generation expert specializing in "
                        "local services and municipal topics worldwide. "
                        "Respond ONLY with valid JSON. "
                        "NEVER invent operator names, line names, or infrastructure names. "
                        "NEVER include temporal words (news, today, noticias, hoy, heute)."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.15,
        )
        raw = response.choices[0].message.content
        data = json.loads(raw)
        keywords = data.get("keywords", [])
        print(f"   ✅ [HIPERLOCAL] {idioma}: {len(keywords)} keywords generadas")
        return keywords
    except Exception as e:
        print(f"   ❌ Error generando keywords hiperlocales en {idioma}: {e}")
        return []


# ──────────────────────────────────────────────────────────────
# COMBINADOR HIPERLOCAL
# ──────────────────────────────────────────────────────────────

# Temporal/news tokens in multiple languages (does NOT include _GENERIC_STANDALONE)
_BANNED_TOKENS_HIPERLOCAL = {
    # ES
    "noticias", "noticia", "notícies", "notícia",
    "última hora", "últimas noticias",
    "hoy", "avui", "gaur", "hoje",
    "reciente", "recientes", "recent",
    "novedad", "novedades", "novetat",
    "breaking", "urgente", "urgent",
    # EN
    "news", "today", "latest", "update", "updates",
    # FR
    "actualités", "aujourd'hui", "récent", "dernières",
    # DE
    "nachrichten", "heute", "aktuell", "neueste",
    # IT
    "notizie", "oggi", "recente", "ultime",
    # PT
    "notícias", "hoje", "recente", "últimas",
    # AR / ZH
    "أخبار", "اليوم", "新闻", "今天",
}


def combinar_keywords_hiperlocal(keywords_lista: list) -> dict:
    """
    Combines and deduplicates hyperlocal keywords.
    Does NOT apply _GENERIC_STANDALONE filter.
    Only filters temporal/news tokens.
    """
    def es_valida(kw_entry: dict) -> bool:
        keyword = kw_entry.get("keyword", "").strip().lower()
        tokens = keyword.split()
        if not keyword:
            return False
        if any(t in _BANNED_TOKENS_HIPERLOCAL for t in tokens):
            return False
        if any(phrase in keyword for phrase in _BANNED_TOKENS_HIPERLOCAL if " " in phrase):
            return False
        if len(tokens) > 6:   # More permissive than standard (5)
            return False
        return True

    validas = [k for k in keywords_lista if es_valida(k)]
    descartadas = [k["keyword"] for k in keywords_lista if not es_valida(k)]
    if descartadas:
        print(f"   🗑️  [HIPERLOCAL] Filtradas {len(descartadas)} keywords: {descartadas}")

    validas = reducir_redundancias(validas)

    combinadas: dict = {}
    razones: dict = {}

    for kw in validas:
        key = kw["keyword"].strip().lower()
        idioma = kw.get("languages", "")
        razon = kw.get("razon", kw.get("razon_tema", ""))

        if key in combinadas:
            idiomas_existentes = set(combinadas[key].split(", "))
            idiomas_existentes.add(idioma)
            combinadas[key] = ", ".join(sorted(idiomas_existentes))
        else:
            combinadas[key] = idioma
            razones[key] = razon

    return {
        "keywords": [
            {"keyword": k, "languages": v, "razon_tema": razones.get(k, "")}
            for k, v in combinadas.items()
        ]
    }

def buscar_contexto_web(tema: str, population_scope: str, max_results: int = 5) -> str:
    """
    Busca información actual sobre el tema en la web.
    Devuelve un texto con los snippets más relevantes.
    Si falla (sin internet, proxy bloqueado), devuelve cadena vacía
    y el pipeline continúa sin contexto web.
    """
    scope = _normalizar_scope(population_scope)
    try:
        with DDGS() as ddgs:
            query = f"{tema} {scope}".strip() if scope and scope.upper() != "GLOBAL" else tema
            resultados = ddgs.text(query, max_results=max_results)
            if not resultados:
                return ""
            textos = []
            for r in resultados:
                titulo = r.get("title", "")
                cuerpo = r.get("body", "")
                if cuerpo:
                    textos.append(f"- {titulo}: {cuerpo}")
            contexto = "\n".join(textos)
            print(f"   🌐 Contexto web obtenido ({len(textos)} resultados)")
            return contexto
    except Exception as e:
        print(f"   ⚠️  Búsqueda web no disponible: {e}")
        return ""


def get_prompt_topic_expansion(tema: str, population_scope: str, contexto_web: str = "") -> str:
    scope = _normalizar_scope(population_scope)
    seccion_web = ""
    if contexto_web:
        seccion_web = f"""
--- CONTEXTO ACTUAL (fuentes web recientes) ---
{contexto_web}

Usa este contexto para enriquecer tu análisis con información actual.
"""

    return f"""
Eres un analista de medios y redes sociales.

Dado este tema de interés público: "{tema}" y contexto geográfico asociado: "{scope}", \
tu tarea es expandirlo y enriquecerlo con información actual obtenida de la web.
{seccion_web}
Devuelve un JSON con esta estructura:
{{
  "tema_normalizado": "nombre oficial o formal del tema",
  "descripcion_breve": "qué es exactamente en 2 frases",
  "terminos_oficiales": ["términos usados por medios o instituciones"],
  "hashtags_probables": ["#ejemploHashtag"],
  "temas_relacionados_confundibles": ["temas similares que HAY QUE EVITAR mezclar"]
}}

Responde SOLO en JSON, sin texto adicional, sin bloques de código.
"""
