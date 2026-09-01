## TAREAS URGENTES CRISTHIAN/ROMINA:
- Enlazar archivos de descarga en la plataforma (COMPLETADO ✓)
- Eficiencia (twitter, bkuesky y reddit, ya se extraen datos más rápidamente)
- Entregar un único excel como se muestra en la imagen project_web\PROPUESTA VISUALIZACION DATOS.png
 (.CSV (DATOS MÍNIMOS), .txt informe MÉTRICA, .txt NO INFORMAMOS CIERTOS TIPOS DE ERRORES POR SEGUIRDAD, EJEMPLO LINKEDIN NO ESTA FUNCIONANDO TEMPORALMENTE, O SE HA CONSUMIDO LA CUOTA DIARIA DE LA API DE YOUTUBE (introduce tu API), ADVERTENCIAS GENÉRICAS) (CRISTHIAN)
- Por defecto si no se selecciona ningún idioma (la búsqueda se realiza únicamente con las palabras clave introducidas por el usuario). (CRISTHIAN ✓)

- Crear automáticamente archivos de fallos de tal manera que el usuario final pueda identificar errores fácilmente (ejemplo cuota API youtube consumida) NO (PROBLEMAS DE SEGURIDAD)

- Enlazar prompts en el sistema (Romina) (Deberíamos ocultarlo, de tal manera que solamente un grupo restringido pueda cambiar las indicaciones)
- FILTRAR LOS COMENTARIOS EXTRAIDOS POR TOPIC DADO, QUE SE PUEDE DEFINIR MANUALMENTE (NO DE LOS DETECTADOS POR EL MODELO DE LENGUAJE) (Romina✓)
- AppBot es capaz de filtrar los comentarios asociados con una palabra clave dada (fijada por el usuario) y a partir de ahí dar el sentimiento global asociado con es Topic. Ver embeddings multilingües. Crear embeddings para cada topic detectado, crear embedding para topic introducido por el usuario, seleccionar aquellos comentarios con mayor similitud semántica. Devolver informe sentimiento de los topic relacionados. (Hecho)

## MUY PRIORITARIAS (CRISTHIAN):
1. Revisar comportamiento linkedin
2. Revisar comportamiento TIKTOK (Agregar filtro tanto publicaciones como comentarios deben estar dentro del período establecido) 
3. ¿Queremos guardar los datos a medida que va buscando? (Sí, Tenemos que hacerlo)
4. iNTENTAREMOS AGREGAR LOS COMENTARIOS DE LAS PUBLICACIONES RECUPERADAS (Bluesky, LinkedIN, Twitter) (Lo haremos)

## MUY PRIORITARIAS:
1. MEJORAR INSTRUCCIONES (David mirará si es posible obtener buenos resultados con modelos pequeños) (CHEQUEAR COMPORTAMIENTO ESPERADO)
2. GRAFICAS VISUALIZACIÓN PARA APP

## OTRAS:
1. AGREGAR OTRAS FUENTES DE DATOS (CRISTIAN / BRUNO):
   * PERIÓDICOS DIGITALES (CRISTIAN)
   * INSTAGRAM (?)
   * FACEBOOK (CRISTHIAN, abortamos de momento)
   * Mastodon – REST API
   * Tumblr – Tumblr API (No sirve la API)
   * PARALELIZAR EL SISTEMA DE BÚSQUEDA (que a la vez busque en X, Reddit, Linkedin, etc)

2. MEJORAR LA HERRAMIENTA:
   * Mejorar métricas:
     * (ponderar por fecha de publicación (?))
     * ponderar por rasgos socio-psicológicos (?)
3. DOCUMENTAR METODOLOGÍA Y PROCESO 
* Ajustar documento previo a los nuevos avances (En proceso continuo. David-Romina)
* Documentar con capturas los avances en la herramienta

## SECUNDARIAS
1. Predicción Aceptación de políticas públicas
   * Análisis perfiles Redes Sociales
2. Análisis de aceptación de medidas/objetivos (Mirar archivo DESARROLLO LOCAL / INFORME USO DE DRONES ESPAÑA)
3. Explorar modelos bayesianos para fundamentar predicción


# Ngrok es una herramienta (principalmente un cliente de línea de comandos) diseñada para crear túneles seguros y exponer servidores locales a internet, asignando una URL pública, sin necesidad de configurar el router ni abrir puertos manualmente. Es ideal para desarrolladores que necesitan compartir aplicaciones, probar webhooks o acceder a servicios locales de forma temporal. URL ES UNA CREADA POR DEFECTO Y ES UN SERVICIO LIMITADO


