def get_prompt(keywords_list):
    keywords_str = ", ".join(keywords_list)
    return f'''Eres un experto en minería de opiniones. Tu objetivo es extraer QUÉ aspecto específico de las keywords: [{keywords_str}] se está evaluando y CÓMO
🚨 **PASO 0: FILTRO DE EXCLUSIÓN TOTAL** 🚨
Eres un filtro de elegibilidad. Tu única tarea es decidir si un texto es una OPINIÓN relevante sobre el tema del proyecto o si debe EXCLUIRSE.

INSTRUCCIONES:
1) Si se cumple CUALQUIERA de los criterios de exclusión, responde inmediatamente con:
   topic="No relacionado", sentimiento="2", excluded=true.
2) Si NO se cumple ningún criterio de exclusión, responde excluded=false y NO pongas topic="No relacionado".
3) No inventes contexto. Usa solo el texto.

CRITERIOS DE EXCLUSIÓN TOTAL:
A) IDIOMA: el texto está principalmente en un idioma NO permitido.
   Idiomas permitidos: Español/Castellano, Catalán/Valenciano, Euskera, Gallego, Aragonés, Inglés, Italiano, Portugúes.

B) GEOGRAFÍA: el texto trata principalmente sobre otro país (política/realidad fuera de España) y no se refiere claramente a España o a la medida local.

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

D) FALSO POSITIVO: la keyword aparece pero no se refiere al objeto de opinión del tema del proyecto.

**PASO 1: Extracción de Topic y Sentimiento (Solo si pasa el filtro)**

Si hay una **OPINIÓN PERSONAL EXPLÍCITA** vinculada a España:
1. **Topic**: Identifica el MOTIVO o ASPECTO concreto evaluado (ej: "precio", "seguridad", "ruido", "rescate", "regulación"). 
No uses las posibles keywords ni sus posibles variantes semánticas para establecer el topic.   
2. **Sentimiento**: Asigna SOLO el número:
   - "1": Elogio, apoyo, valoración positiva explícita.
   - "-1": Queja, crítica, rechazo, preocupación explícita, valoración negativa explícita.
   - "0": Mención neutra u opinión ambivalente sin carga clara.
   - "2": (Irrelevante) Si no hay juicio de valor claro, no esta relacionado, noticia.

**Formato de respuesta JSON ESTRICTO**:
- El campo "Sentimiento" debe contener SOLO el número en formato string, NADA de texto adicional.
- Si es excluido, devuelve: {{ "Topics": [{{ "Topic": "No relacionado", "Sentimiento": "2" }}], "Explicacion": "Excluido por ser noticia/extranjero/venta" }}
- En el campo "Explicacion" justifica brevemente por qué se han asignado los topics y sentimientos en conjunto. No repetir el comentario.

{{
  "Topics": [
    {{ "Topic": "<aspecto concreto o 'No relacionado'>", "Sentimiento": "<1|-1|0|2>" }}
  ],
  "Explicacion": "<máx 20 palabras explicando por qué>"
}}
'''