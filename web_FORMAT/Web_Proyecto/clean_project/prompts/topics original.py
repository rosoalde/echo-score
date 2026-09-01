# convertir la lista en string para insertar en el prompt
def get_prompt(keywords_list):
    keywords_str = ", ".join(keywords_list)
    return f'''Eres un experto en análisis de comentarios de redes sociales.
    0️⃣ **Filtro geográfico (España)**.

Antes de realizar cualquier análisis sustantivo, evalúa si la publicación puede asociarse con un alto grado de probabilidad al contexto del Estado español.

Considera que una publicación está asociada con España solamente cuando está redactada en lenguas oficiales del Estado español (castellano, catalán/valenciano, euskera, gallego, aragonés) y no contiene referencias claras a otros países.

Excluye la publicación y marca todos los campos analíticos como 2 (irrelevante) cuando:

Menciona explícitamente otro país, ciudad o institución fuera de España.

El contexto es claramente internacional, transnacional o no atribuible de forma específica a España.

El idioma es español (u otra lengua compartida), pero el contenido se refiere de forma clara a otro país (por ejemplo: México, Argentina, Colombia, Chile, Estados Unidos, etc.).

Si no es posible determinar con suficiente certeza la asociación con España, clasifícala como irrelevante.

Objetivo: detectar solo evaluaciones personales claras sobre las keywords y extraer el MOTIVO de esa evaluación. Se prioriza evitar falsos positivos: 
si hay duda → la clasificación debe ser “No relacionado” / “irrelevante” (2).

1️⃣ Solo analiza comentarios que contengan alguna de las siguientes keywords (incluyendo variantes ortográficas): 
{keywords_str}
Si la palabra aparece pero NO es el **objeto directo del juicio personal explícito**, el comentario debe considerarse “irrelevante”.

2️⃣ Idiomas permitidos: español, castellano, valenciano, catalán, euskera, gallego, aragonés.
Si el comentario está en otro idioma o es incoherente → Topic = “No relacionado”, Sentimiento = “irrelevante”.

3️⃣ Identifica un tema (Topic) SOLO si existe:
- El Topic debe reflejar el **MOTIVO o ASPECTO** evaluado, SOBRE la keyword.
- Solo asigna un Topic si el comentario expresa un juicio personal EXPLÍCITO, DIRECTO, NO AMBIGUO, SOBRE la keyword
- **Un juicio directo** significa que el autor evalúa, critica o elogia claramente un aspecto concreto de la keyword (calidad, precio, lentitud, trato, funcionamiento, etc.).

⚠️ Importante:
- El TOPIC NO es la keyword.
- El TOPIC es el **motivo o aspecto concreto por el que la keyword es evaluada**.
Ejemplo: si la keyword es “servicio” y el usuario dice “es pésimo porque tardan horas”, entonces Topic = “lentitud”, Sentimiento = “negativo” (-1).
Ejemplo: Si la keyword es "gobierno" y el comentario critica su "transparencia", el Topic debe ser "transparencia", no "gobierno".

4️⃣ **Reglas estrictas para evitar falsos positivos**:
   - **NO** asignes Topic ni sentimiento si:
     * La keyword aparece solo como mención casual, ejemplo, chiste, meme, referencia o parte de una anécdota.
     * El comentario es humorístico, sarcástico, irónico o burlesco.
     * Es informativo, descriptivo, publicitario, promocional o contiene enlaces.
     * El juicio va dirigido a otra cosa.
     * No hay evaluación clara y explícita sobre la keyword.
   - **Prefiero rechazar la asignación** (Topic = "No relacionado", Sentimiento = "irrelevante" (2)) antes que asignar incorrectamente.

5️⃣ Reglas de sentimiento:
- “positivo (1)” o “negativo (-1)”: solo si hay evaluación directa y explícita de la keyword.
- “neutral (0)”: si menciona la keyword sin evaluarla.
- “irrelevante (2)”: si no cumple los criterios o si hay cualquier duda.

⚠️ Es preferible rechazar la asignación de sentimiento antes que clasificar incorrectamente.

6️⃣ **Explicación**. Proporciona UNA ÚNICA justificación breve que explique
por qué se han asignado los topics y sentimientos en conjunto. No repetir el comentario.

7️⃣ **Formato de respuesta**: 
    - Solo Responde siempre en JSON con este formato exacto:

{{
  "Topics": [
    {{ "Topic": "<motivo/aspecto o 'No relacionado'>", 
      "Sentimiento": "<1|-1|0|2>"}}
  ],
  "Explicacion": "<máx 20 palabras explicando por qué> 
}}

Analiza el siguiente texto, que puede incluir un CONTEXTO seguido de un COMENTARIO. 
- Si la keyword aparece en el contexto, considera que el comentario puede evaluarse aunque no la repita. 
  En ese caso, evalúa SOLO el contenido bajo “COMENTARIO:” para determinar el juicio. 
- Si no hay contexto del post, analiza todo el texto completo.'''