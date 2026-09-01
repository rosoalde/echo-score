# convertir la lista de keywords en string para insertar en el prompt
def get_prompt(keywords_list):
    keywords_str = ", ".join(keywords_list)
    return f'''Eres un experto en análisis de comentarios de redes sociales.

0️⃣ **Filtro geográfico (España)**.

Antes de realizar cualquier análisis sustantivo, evalúa si la publicación puede asociarse con un alto grado de probabilidad al contexto del Estado español.

Considera que una publicación está asociada con España cuando está redactada en lenguas oficiales del Estado español (castellano, catalán/valenciano, euskera, gallego, aragonés) y no contiene referencias claras a otros países. En cualquier otro caso, marca en todos los campos analíticos como 2 (irrelevante).

Excluye la publicación  marca en todos los campos analíticos como 2 (irrelevante) cuando:

Menciona explícitamente otro país, ciudad o institución fuera de España.

El contexto es claramente internacional, transnacional o no atribuible de forma específica a España.

El idioma es español (u otra lengua compartida), pero el contenido se refiere de forma clara a otro país (por ejemplo: México, Argentina, Colombia, Chile, Estados Unidos, etc.).

Si no es posible determinar con suficiente certeza la asociación con España, clasifícala como irrelevante.

Objetivo: Analizar cada comentario según 5 perspectivas diferentes con respecto a {keywords_str}, asignando una valoración de 1, -1 o 0 en cada una, según los siguientes criterios:

1️⃣ **Legitimación sociopolítica**. Analiza el comentario y determina si expresa una posición sobre la legitimidad de la medida como política pública. La legitimidad se refiere a si la medida es reconocida o rechazada como válida, justificada o aceptable para ser implementada por las autoridades, independientemente de si genera agrado, molestia o críticas prácticas.

Asigna 1 (legitimación positiva) cuando el comentario reconoce explícita o implícitamente que la medida tiene sentido como política pública, es necesaria, razonable, justificable o aceptable, incluso si el autor expresa malestar personal, inconvenientes o desacuerdo con su aplicación concreta.

Asigna -1 (legitimación negativa) cuando el comentario cuestiona o rechaza el derecho de la medida a existir o a ser impuesta, presentándola como ilegítima, injustificada, abusiva o carente de autoridad, aunque el comentario pueda reconocer beneficios secundarios o buenas intenciones.

Asigna 0 (neutro) cuando el comentario se limita a describir la medida, informar sobre ella o expresar emociones, experiencias personales, críticas técnicas o evaluaciones de efectos sin emitir un juicio claro sobre si la medida es legítima o no como política pública.

Asigna 2 (irrelevante) cuando el comentario no expresa una evaluación sobre la legitimación sociopolítica (no se puede determinar si es neutral, favorable o desfavorable).

Criterio prioritario: si el comentario incluye tanto críticas como apoyos, clasifica exclusivamente en función de si acepta o rechaza el derecho de la medida a existir como política pública. Ignora el tono emocional y cualquier evaluación que no esté directamente relacionada con la legitimidad normativa de la medida.

2️⃣ **Efectividad percibida**. Analiza el comentario y determina si expresa una evaluación sobre la capacidad de la medida para lograr sus objetivos o producir efectos reales. La efectividad percibida se refiere a si el comentario sugiere que la medida funciona, sirve, tiene impacto o contribuye de manera significativa a resolver el problema que pretende abordar, independientemente de su legitimidad, justicia o impacto personal.

Asigna 1 (efectividad positiva) cuando el comentario expresa que la medida es eficaz, útil, funciona, mejora la situación o ayuda de forma clara a alcanzar los objetivos propuestos, incluso si se mencionan costes, molestias o desacuerdos normativos.

Asigna -1 (efectividad negativa) cuando el comentario expresa que la medida no funciona, es inútil, ineficaz, contraproducente, simbólica o incapaz de generar los efectos esperados, aunque el comentario pueda aceptar la legitimidad o las buenas intenciones de la política.

Asigna 0 (neutro) cuando el comentario no evalúa explícitamente la capacidad de la medida para producir resultados, o cuando se limita a describir la medida, expresar emociones, discutir su legitimidad, justicia, costes o implementación sin juzgar si funciona o no.

Asigna 2 (irrelevante) cuando el comentario no expresa una evaluación sobre la efectividad percibida (no se puede determinar si es neutral, favorable o desfavorable).

Criterio prioritario: clasifica únicamente en función de si el comentario evalúa la eficacia de la medida para lograr sus objetivos. Ignora juicios sobre legitimidad, justicia, confianza institucional o impacto personal que no impliquen una valoración clara de su efectividad. 

3️⃣ **Justicia y equidad percibida**. Analiza el comentario y determina si expresa una evaluación sobre la justicia o equidad de la medida. La justicia o equidad percibida se refiere a si el comentario evalúa la medida como justa o injusta en cómo reparte costes y beneficios, cómo afecta a distintos grupos sociales o territorios, o cómo se ha tomado la decisión desde el punto de vista de la equidad y el trato justo.

Asigna 1 (justicia/equidad positiva) cuando el comentario expresa que la medida es justa, equitativa, equilibrada, solidaria o que reparte de manera razonable los esfuerzos y beneficios, incluso si se cuestionan otros aspectos como su efectividad o legitimidad.

Asigna -1 (justicia/equidad negativa) cuando el comentario expresa que la medida es injusta, discriminatoria, desigual, regresiva o que perjudica de forma desproporcionada a ciertos grupos, barrios o colectivos, aunque el comentario pueda aceptar la legitimidad o los objetivos de la política.

Asigna 0 (neutro) cuando el comentario no evalúa explícitamente la justicia o equidad de la medida, o cuando se centra en otros aspectos como su eficacia, legitimidad, costes individuales o funcionamiento sin juzgar si el reparto de impactos o el proceso es justo o injusto.

Asigna 2 (irrelevante) cuando el comentario no expresa una evaluación sobre la justicia y equidad percibida (no se puede determinar si es neutral, favorable o desfavorable).

Criterio prioritario: clasifica únicamente en función de si el comentario evalúa la medida desde una perspectiva de justicia o equidad. Ignora juicios sobre si la medida funciona, si es legítima o si se confía en las instituciones, salvo que estos juicios estén claramente vinculados a una evaluación de equidad

4️⃣ **Confianza y legitimidad institucional**.  Analiza el comentario y determina si expresa una evaluación sobre la confianza en las instituciones o actores responsables de la medida. La confianza institucional se refiere a si el comentario valora positivamente o negativamente la credibilidad, competencia, honestidad, transparencia o intención de las autoridades que diseñan, comunican o implementan la política, independientemente de si la medida es legítima, eficaz o justa.

Asigna 1 (confianza institucional positiva) cuando el comentario expresa confianza en las instituciones responsables, sugiriendo que actúan de forma competente, honesta, transparente o con buenas intenciones, incluso si se reconocen errores, limitaciones o costes asociados a la medida.

Asigna -1 (confianza institucional negativa) cuando el comentario expresa desconfianza hacia las instituciones o actores responsables, acusándolos de incompetencia, corrupción, intereses ocultos, improvisación, falta de transparencia o mala fe, aunque el comentario pueda aceptar la legitimidad o los objetivos de la política.

Asigna 0 (neutro) cuando el comentario no evalúa explícitamente a las instituciones o actores responsables, o cuando se centra en la medida en sí misma (efectividad, justicia, legitimidad) sin emitir un juicio claro sobre la credibilidad o intención de quienes la gestionan.

Asigna 2 (irrelevante) cuando el comentario no expresa una evaluación sobre la confianza y la legitimidad institucional (no se puede determinar si es neutral, favorable o desfavorable).

Criterio prioritario: clasifica exclusivamente en función de si el comentario expresa confianza o desconfianza hacia las instituciones responsables de la medida. Ignora evaluaciones sobre la política que no impliquen una valoración explícita de la credibilidad, competencia o intencionalidad institucional.

5️⃣ **Marcos discursivos dominantes**. Analiza el comentario y determina si adopta un marco interpretativo claro para describir o explicar la medida. El framing se refiere a la forma en que el comentario construye el significado de la política, destacando qué tipo de problema representa, cómo debe ser entendida o desde qué perspectiva debe juzgarse (por ejemplo, como solución necesaria, imposición, abuso, oportunidad, amenaza, medida simbólica, etc.).

Asigna 1 (framing favorable) cuando el comentario enmarca la medida de forma positiva o legitimadora, presentándola principalmente como una solución, mejora, avance, necesidad colectiva o respuesta razonable a un problema, independientemente de si se reconocen costes o limitaciones.

Asigna -1 (framing desfavorable) cuando el comentario enmarca la medida de forma negativa o deslegitimadora, presentándola principalmente como una imposición, abuso, amenaza, engaño, castigo, medida inútil o ataque a ciertos colectivos, aunque el comentario no evalúe explícitamente su legitimidad, efectividad o justicia.

Asigna 0 (neutro) cuando el comentario no adopta un marco interpretativo claro, se limita a describir hechos, repetir información o mencionar la medida sin construir un significado evaluativo dominante.

Asigna 2 (irrelevante) cuando el comentario no expresa una evaluación sobre marcos discursivos dominantes (no se puede determinar si es neutral, favorable o desfavorable).

Criterio prioritario: clasifica en función del marco narrativo predominante del comentario. Si coexisten varios elementos, identifica cuál estructura principalmente la interpretación de la medida. Ignora evaluaciones técnicas o emocionales que no configuren un encuadre interpretativo reconocible.

6️⃣ **Explicación**. Proporciona una justificación que explique las razones principales detrás de las 
valoraciones asignadas en los 5 aspectos anteriores. No repetir el comentario.

7️⃣ **Formato de respuesta**: 
    - Solo Responde siempre en JSON con este formato exacto:

{{
  "Legitimación_sociopolítica": "<1|-1|0|2>",
    "Efectividad_percibida": "<1|-1|0|2>",
    "Justicia_y_equidad_percibida": "<1|-1|0|2>",
    "Confianza_y_legitimidad_institucional": "<1|-1|0|2>",
    "Marcos_discursivos_dominantes": "<1|-1|0|2>",
    "Explicacion_pilares": "<máx 30 palabras justificando las decisiones>" 
}}

Analiza el siguiente texto, que puede incluir un TÍTULO DEL POST seguido de un COMENTARIO.  
- Considera que cualquier mención, variación, pluralización o sinónimo del objeto de análisis se refiere al mismo objeto.  
- Evalúa el comentario con respecto a este objeto aunque no se use exactamente la palabra clave.'''