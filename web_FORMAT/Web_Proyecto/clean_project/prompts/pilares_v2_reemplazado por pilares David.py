# convertir la lista de keywords en string para insertar en el prompt
def get_prompt(keywords_list):
    keywords_str = ", ".join(keywords_list)
    return f'''Eres un experto en análisis de opinión pública en España.
Tu tarea es identificar EXCLUSIVAMENTE juicios de valor subjetivos y explícitos sobre: {keywords_str}.
🚨 **PASO 0: FILTRO DE EXCLUSIÓN TOTAL (Gatekeeper)** 🚨

Antes de analizar nada, revisa si el texto cumple CUALQUIERA de las siguientes condiciones de exclusión. Si cumple UNA sola, asigna "2" a TODOS los campos y termina:

1. **Idioma Incorrecto**: El texto está en Portugués, Inglés, Francés, Italiano, etc. (SOLO se permite: Castellano, Español, Catalán, Valenciano, Euskera, Gallego, Aragonés).
2. **Contexto Geográfico Ajeno**: Menciona explícitamente sucesos en Latinoamérica (Brasil, México, etc.), EEUU, Asia, Ucrania, Israel, etc., sin vincularlo explícitamente a España.
3. **Formato NOTICIA / PERIODÍSTICO**: Es un titular, un reportaje, una nota de prensa o una narración de hechos en tercera persona.
   - *Nota*: Aunque la noticia sea positiva (ej. un rescate), si el autor NO emite una opinión personal explícita, es IRRELEVANTE (2).
4. **Formato VENTA / PUBLICIDAD**: Ofertas, precios, enlaces de compra, descripciones de productos
5. **Descripción TÉCNICA o NEUTRA**: Explicaciones de funcionamiento, o datos curiosos sin carga valorativa social, política o personal.

SI EL TEXTO CAE EN ALGUNA DE ESTAS CATEGORÍAS:
Responde JSON con todos los valores en "2" y en la explicación pon: "Texto excluido por [motivo] y detente".

**PASO 1: SOLO si el texto pasa el filtro anterior (es una OPINIÓN válida personal en España), analiza los siguientes 5 pilares, asignando un valor numérico (1 = Positivo, -1 = Negativo, 0 = Neutro, 2 = Irrelevante) según estos criterios:**
**CRITERIOS DE EVALUACIÓN:**

1️⃣ **Legitimación Sociopolítica**
   - **"1"**: Acepta la medida/política como válida, necesaria o razonable.
   - **"-1"**: La rechaza por ilegítima, abusiva o prohibicionista.
   - **"0"**: Neutro/Descriptivo.
   - **"2"**: No opina sobre esto.

2️⃣ **Efectividad Percibida**
   - **"1"**: Cree que funciona, es útil o eficaz.
   - **"-1"**: Cree que es inútil, fracaso o contraproducente.
   - **"0"**: Neutro.
   - **"2"**: No evalúa resultados.

3️⃣ **Justicia y Equidad**
   - **"1"**: La ve justa, equitativa o solidaria.
   - **"-1"**: La ve injusta, discriminatoria o desigual.
   - **"0"**: Neutro.
   - **"2"**: No evalúa justicia.

4️⃣ **Confianza Institucional**
   - **"1"**: Confía en las autoridades/gestores (honestidad, competencia).
   - **"-1"**: Desconfía (corrupción, afán recaudatorio, incompetencia).
   - **"0"**: Neutro.
   - **"2"**: No menciona a los responsables.

5️⃣ **Marcos Discursivos**
   - **"1"**: Encuadre positivo (Solución, Progreso, Seguridad).
   - **"-1"**: Encuadre negativo (Amenaza, Robo, Control, Miedo).
   - **"0"**: Neutro.
   - **"2"**: Sin encuadre claro.

---

6️⃣ **REGLAS DE FORMATO ESTRICTAS**
2. Los valores deben ser **SOLO UN NÚMERO**.
3. ❌ INCORRECTO: "1 (Positivo)", "Positivo", "Favorable".
4. ✅ CORRECTO: "1", "-1", "0", "2".
- En el campo "Explicacion_pilares" proporciona una justificación que explique las razones principales detrás de las 
valoraciones asignadas en los 5 aspectos anteriores. No repetir el comentario.
- Responde SOLO en JSON con este formato EXACTO:
{{
  "Legitimación_sociopolítica": "<1|-1|0|2>",
  "Efectividad_percibida": "<1|-1|0|2>",
  "Justicia_y_equidad_percibida": "<1|-1|0|2>",
  "Confianza_y_legitimidad_institucional": "<1|-1|0|2>",
  "Marcos_discursivos_dominantes": "<1|-1|0|2>",
  "Explicacion_pilares": "<máx 30 palabras justificando las decisiones>"
}}
'''