import json
import re
from openai import OpenAI
from ddgs import DDGS
from concurrent.futures import ThreadPoolExecutor, as_completed

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


# ==============================
# Filtro post-generación
# ==============================

# Palabras temporales o de noticias que invalidan una keyword
_BANNED_TOKENS = {
    "noticias", "notícies", "noticia", "notícia",
    "última hora", "últimas noticias",
    "hoy", "avui", "gaur", "hoje",
    "reciente", "recientes", "recent", "recents",
    "novedad", "novedades", "novetat", "novetats",
    "breaking", "urgente", "urgent",
}

# Términos genéricos de una sola palabra sin anclaje local
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

# Frases genéricas de 2+ palabras sin anclaje geográfico
_GENERIC_PHRASES = {
    "movilidad urbana", "movilitat urbana", "mobilitat urbana",
    "transporte urbano", "transport urbà", "transporte público",
    "calidad del aire", "qualitat de l'aire", "qualitat de l aire",
    "medio ambiente", "medi ambient",
    "servicios públicos", "serveis públics",
    "infraestructura pública", "infraestructura publica",
    "gestión municipal", "gestió municipal",
}

# Patrón: "línia N", "línea N", "line N", "linia N" sin nada más
_NUMBERED_LINE_RE = re.compile(
    r"^(l[ií]n[ei]a|l[ií]nia|line|linia|línia)\s*\d+$",
    re.IGNORECASE
)


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


def filtrar_keywords(keywords: list) -> list:
    validas = [k for k in keywords if es_keyword_valida(k)]
    descartadas = [k["keyword"] for k in keywords if not es_keyword_valida(k)]
    if descartadas:
        print(f"   🗑️  Filtradas {len(descartadas)} keywords inválidas: {descartadas}")
    return validas


# ==============================
# Helpers de normalización
# ==============================
def _normalizar_scope(population_scope) -> str:
    """Convierte cualquier tipo de entrada en un string limpio."""
    if isinstance(population_scope, list):
        return ", ".join(population_scope) if population_scope else "GLOBAL"
    return str(population_scope).strip() or "GLOBAL"


# ==============================
# Búsqueda web (DuckDuckGo)
# ==============================
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


# ==============================
# Capa 1: Expansión del tema
# ==============================
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


# ==============================
# Capa 2: Generación de keywords
# ==============================

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


❌ PALAVRAS PROIBIDAS: "notícias", "hoje", "recente", "últimas"
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


# ==============================
# Capa 3: Combinación y deduplicación
# ==============================
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

# ==============================
# Pipeline principal
# ==============================
def generar_keywords(tema: str, population_scope: str, idiomas: list) -> dict:
    scope = _normalizar_scope(population_scope)
    print(f"\n🚀 [INICIO] Probando generación para: '{tema}' | Idiomas: {idiomas} | Población objetivo: {scope}")

    print(f"   🔎 Buscando contexto web... tema='{tema}' | scope='{scope}'")
    brief = expandir_tema(tema, scope)
    if not brief:
        print("⚠️  No se pudo expandir el tema. Abortando.")
        return {}

    descripcion = brief.get("descripcion_breve", "")
    print(f"\n BRIEF: {descripcion}")

    print(f"🚀 Generando keywords en {len(idiomas)} idiomas en paralelo...")
    todas_las_keywords = []

    with ThreadPoolExecutor(max_workers=len(idiomas)) as executor:
        futuros = {
            executor.submit(generar_keywords_por_idioma, tema, idioma, scope, brief): idioma
            for idioma in idiomas
        }
        for futuro in as_completed(futuros):
            idioma = futuros[futuro]
            try:
                kws = futuro.result()
                print(f"   ✅ {idioma}: {len(kws)} keywords (antes de filtrar)")
                todas_las_keywords.extend(kws)
            except Exception as e:
                print(f"   ❌ {idioma}: error — {e}")

    resultado = combinar_keywords_multilingue(todas_las_keywords)
    print(f"\n✅ ¡ÉXITO! {len(resultado['keywords'])} keywords únicas generadas: {resultado['keywords']}")

    return {
        "tema_original": tema,
        "population_scope": scope,
        "brief": brief,
        "resultado": resultado
    }


# ==============================
# Ejemplo de uso
# ==============================
if __name__ == "__main__":

    IDIOMAS = [
        "Castellano",
        "Catalan",
        # "valenciano",
        # "euskera",
        # "gallego",
        # "inglés",
        # "francés",
        # "italiano",
        # "portugués"
    ]

    casos_prueba = [
        ("transporte público", "Provincia Valencia"),
        ("transporte público", "ciudad de Valencia"),
        ("transporte público", "área metropolitana de Valencia"),
        ("regularización de inmigrantes", "España"),
        ("calidad del aire", "Madrid"),
        ("educación pública", "País Vasco"),
    ]

    for tema, scope in casos_prueba:
        print(f"\n{'='*60}")
        output = generar_keywords(tema, scope, IDIOMAS)
        print("\n--- RESULTADO FINAL ---")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        print("=" * 60)