# convertir la lista en string para insertar en el prompt
def get_prompt(keywords_list):
    keywords_str = ", ".join(keywords_list)
    return f'''Eres un experto en minería de opiniones. Tu objetivo es extraer QUÉ aspecto específico de las keywords: [{keywords_str}] se está evaluando y CÓMO
🚨 **PASO 0: FILTRO DE EXCLUSIÓN TOTAL** 🚨

Si el comentario cumple alguna de estas condiciones, el resultado debe ser Topic: "No relacionado", Sentimiento: "2" y detenerse inmediatamente:    
1. **Idioma**: No es una lengua oficial de España, ejemplo Portugués, Inglés, Francés, Italiano, etc. (SOLO se permite: Castellano, Español, Catalán, Valenciano, Euskera, Gallego, Aragonés).
2. **Geografía**: Se refiere claramente a otro país (Ucrania, Israel, Vietnam, Latam, etc.).
3. **Tipo de Texto**:
   - **NOTICIAS**: Reportes de sucesos.
   - **VENTAS**: Anuncios con precios o enlaces.
   - **DESCRIPCIONES**: Explicaciones o descripciones sin juicio de valor.
   - **FALSOS POSITIVOS**: La keyword aparece pero no es el objeto de la opinión.

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