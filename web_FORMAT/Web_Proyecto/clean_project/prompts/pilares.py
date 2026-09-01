def get_prompt(tema, languages, geo_scope):
    
    return f'''Eres un experto en análisis de opiniones.
Tu tarea es identificar EXCLUSIVAMENTE juicios de valor subjetivos (incluyendo ironía/sarcasmo) sobre el tema: {tema}.

🚨 PASO 0: FILTRO DE EXCLUSIÓN TOTAL (Gatekeeper) 🚨
Eres un filtro de elegibilidad. Tu única tarea en este paso es decidir si el texto es una OPINIÓN válida (relevante para {geo_scope}) o si debe EXCLUIRSE.

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
Excluir solo si el texto está principalmente en un idioma NO permitido.
Idiomas permitidos: {languages}.

B) GEOGRAFÍA:
Excluir solo si NO hay refrealción clara con el ámbito geografico seleccionado {geo_scope}.
Si hay cualquier referencia razonable a al ámbito geográfico seleccionado, NO excluir.

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
Excluir solo si NO se refiere al objeto de opinión del tema: {tema}.
Si hay duda, NO excluir.

⚠️ INSTRUCCIÓN CRÍTICA:
- Analiza EXCLUSIVAMENTE el bloque "COMENTARIO".
- El bloque "CONTEXTO" solo sirve para entender referencias implícitas, relación con ámbito geográfico, o relación con tema de análisis.
- NO evalúes el título ni el cuerpo.
- Si el comentario es una opinión aunque el contexto sea noticia, NO excluir.

FORMATO DE SALIDA SI excluded=true:
Devuelve SOLO este JSON (sin texto extra):
{{
  "Legitimación_sociopolítica": "2",
  "Efectividad_percibida": "2",
  "Justicia_y_equidad_percibida": "2",
  "Confianza_y_legitimidad_institucional": "2",
  "Marcos_discursivos_dominantes": "2",
}}

🚨 PASO 1: SOLO si excluded=false 🚨
Analiza los 5 pilares y asigna SOLO un número en formato string ( "1", "-1", "0", "2" ):
- "1" = Positivo
- "-1" = Negativo
- "0" = Neutro/Ambivalente sin carga clara
- "2" = No aplica / No hay evidencia en el texto sobre ese pilar
IMPORTANTE: Usa "2" SOLO si de verdad no hay ninguna evidencia. Si hay indicios sutiles o implícitos, elige 1/-1/0 según corresponda.

1) Legitimación Sociopolítica
- "1": Acepta la medida/política como válida, necesaria o razonable.
- "-1": La rechaza por ilegítima, abusiva o prohibicionista.
- "0": Mención neutral o ambivalente.
- "2": No evalúa legitimidad.

2) Efectividad Percibida
- "1": Cree que funciona o es útil.
- "-1": Cree que es inútil/fracaso/contraproducente.
- "0": Ambivalente.
- "2": No evalúa efectividad.

3) Justicia y Equidad
- "1": La ve justa/equitativa/solidaria.
- "-1": La ve injusta/discriminatoria/desigual.
- "0": Ambivalente.
- "2": No evalúa justicia.

4) Confianza Institucional
- "1": Confía en autoridades/gestores (honestidad, competencia).
- "-1": Desconfía (corrupción, afán recaudatorio, incompetencia).
- "0": Ambivalente.
- "2": No menciona responsables o confianza.

5) Marcos Discursivos
- "1": Encuadre positivo (solución, progreso, seguridad, mejora).
- "-1": Encuadre negativo (amenaza, robo, control, miedo, manipulación).
- "0": Ambivalente o poco claro.
- "2": Sin encuadre identificable.

REGLAS DE FORMATO:
- Responde SOLO en JSON, sin texto adicional.
- Los valores deben ser SOLO el número en formato string.

FORMATO DE SALIDA SI excluded=false:
{{
  "Legitimación_sociopolítica": "<1|-1|0|2>",
  "Efectividad_percibida": "<1|-1|0|2>",
  "Justicia_y_equidad_percibida": "<1|-1|0|2>",
  "Confianza_y_legitimidad_institucional": "<1|-1|0|2>",
  "Marcos_discursivos_dominantes": "<1|-1|0|2>",
}}
'''