def get_prompt_keywords(tema: str, languages: list[str]): #, poblacion: str):
    """
    Devuelve el prompt para generar keywords basado en un tema específico.
    """
    tema = tema.strip()
    languages_str = ", ".join(languages)
    # if isinstance(poblacion, list):
    #     poblacion_str = ", ".join(poblacion) if poblacion else "público general"
    # else:
    #     poblacion_str = poblacion.strip() if poblacion else "público general"

    # REGLA: Llaves dobles {{ }} para el texto que debe ir al LLM como JSON
    # Llaves simples { } para las variables de Python (tema, languages_str, etc.)
    print(f"📝 Generando prompt para tema: {tema} | Idiomas: {languages_str}") # | Población: {poblacion_str}")

    # ---------- Construir prompt ----------
    # Población objetivo: {poblacion_str} (si está vacía, asumir 'público general')
    prompt = f"""
Eres un experto en social listening y análisis de conversación ciudadana.
--- DATOS DE ENTRADA ---
Tema principal: {tema}

Idiomas Permitidos: {languages_str}

--- OBJETIVO ---
Genera una lista pequeña, limpia y semánticamente coherente de términos de búsqueda en todos los idiomas indicados únicamente en "Idiomas Permitidos", para extraer publicaciones y comentarios en redes sociales (Twitter/X, LinkedIn, Bluesky, Reddit y YouTube) relacionados con el tema indicado, teniendo en cuenta la/s población/es objetivo.

Debes tener en cuenta la población de interés proporcionada por el usuario, que puede incluir atributos como ubicación, rango de edad, intereses o grupo demográfico. Esto guía la selección de términos: deben reflejar el lenguaje que esta población usaría naturalmente en redes sociales.

IMPORTANTE — DISTINCIÓN ANALÍTICA:

El "Tema principal" describe el objeto del estudio,
pero NO es un Topic.

El Topic debe representar el ÁNGULO DE VALORACIÓN del comentario,
es decir, la razón, argumento o preocupación expresada por la persona.

--- REGLAS OBLIGATORIAS ---
1. Nunca más de 100 términos.
2. Cada término debe tener entre 2 y 5 palabras separadas por espacios.
3. No concatenar palabras ni usar tecnicismos.
4. Cada término debe poder aparecer literalmente en un comentario real.
5. No generar hashtags ni palabras sueltas.
6. Evitar repeticiones y variaciones mínimas.
7. Generar al menos 1 término por cada idioma indicado únicamente en "Idiomas Permitidos". No generar términos en idiomas que no estén en "Idiomas Permitidos". 
8. Agrupar keywords por idioma y solo indicar el idioma principal del término.
9. Nunca utilices abreviaturas de idioma ni códigos de dos letras.
El valor debe coincidir exactamente con el texto mostrado en "Idiomas Permitidos".
Ejemplo válido: "Castellano"
Ejemplo inválido: "es"

--- FORMATO DE SALIDA OBLIGATORIO (JSON) ---
Devuelve únicamente un JSON con esta estructura, sin explicaciones ni texto adicional:

{{
  "keywords": [
    {{
      "keyword": "termino clave 1",
      "languages": "idioma(s) permitido(s) del término 1"
    }},
    {{
      "keyword": "termino clave 2",
      "languages": "idioma(s) permitido(s) del término 2"
    }}
  ]
}}
"""

    return prompt