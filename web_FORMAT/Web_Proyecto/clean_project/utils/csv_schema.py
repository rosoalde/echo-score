"""
Esquema unificado de CSV para todas las redes sociales.
"""

# Columnas base (comunes a todas las redes)
BASE_COLUMNS = [
    "red_social",          # Reddit, YouTube, Bluesky, etc.
    "tipo_contenido",      # Post, Comentario, Video
    "usuario",             # Nombre del usuario
    "usuario_hash",        # Hash SHA256 del usuario (consistente)
    "contenido",           # Texto del post/comentario
    "fecha",               # Fecha en formato ISO
    "enlace",              # URL del contenido
    
    # Contexto (para comentarios)
    "es_comentario",       # true/false
    "post_padre_titulo",   # Título del post padre
    "post_padre_texto",    # Texto del post padre
    "usuario_original",    # Usuario del post padre
    "enlace_original",     # Enlace del post padre
    
    # Métricas de engagement
    "likes",               # Número de likes/upvotes
    "comentarios",         # Número de comentarios/respuestas
    "compartidos",         # Número de shares/retweets
    "visualizaciones",     # Número de vistas (YouTube)
    
    # Metadatos del usuario
    "seguidores",          # Followers
    "siguiendo",           # Following
    "bio",                 # Biografía
    "verificado",          # Cuenta verificada
    
    # Metadatos de búsqueda
    "search_keyword",      # Keyword usada para encontrar
    "keyword_languages",   # Idiomas de la keyword
    
    # Medios
    "imagenes_paths",      # JSON array con rutas a imágenes
    "gifs_paths",          # JSON array con rutas a GIFs
    "videos_paths",        # JSON array con rutas a videos
    "transcripcion_path",  # Ruta a transcripción (YouTube)
    
    # Análisis LLM
    "llm_relevante",       # SI, NO, PENDIENTE
    "idioma_detectado",    # es, en, ca, etc.
    
    # Análisis de stance (se añade después)
    "stance_global",       # 1, 0, -1
    "Legitimación_sociopolítica",
    "Efectividad_percibida",
    "Justicia_y_equidad_percibida",
    "Confianza_institucional",
    "Marcos_discursivos",
    "topic",               # Topic principal
]


def normalize_reddit_to_schema(reddit_row: dict) -> dict:
    """Convierte fila de Reddit al esquema unificado"""
    import json
    
    return {
        "red_social": "Reddit",
        "tipo_contenido": reddit_row.get("TipoDeTweet"),
        "usuario": reddit_row.get("usuario"),
        "usuario_hash": reddit_row.get("usuario_hash"),
        "contenido": reddit_row.get("contenido"),
        "fecha": reddit_row.get("fecha"),
        "enlace": reddit_row.get("enlace"),
        
        "es_comentario": reddit_row.get("TipoDeTweet") == "Comentario",
        "post_padre_titulo": reddit_row.get("post_title", ""),
        "post_padre_texto": reddit_row.get("post_selftext", ""),
        "usuario_original": reddit_row.get("UsuarioOriginal", ""),
        "enlace_original": reddit_row.get("EnlaceOriginal", ""),
        
        "likes": reddit_row.get("Likes", 0),
        "comentarios": reddit_row.get("comments", 0),
        "compartidos": 0,  # Reddit no tiene shares
        "visualizaciones": 0,
        
        "seguidores": 0,
        "siguiendo": 0,
        "bio": "",
        "verificado": False,
        
        "search_keyword": reddit_row.get("search_keyword"),
        "keyword_languages": reddit_row.get("keyword_languages"),
        
        "imagenes_paths": "[]",
        "gifs_paths": "[]",
        "videos_paths": "[]",
        "transcripcion_path": "",
        
        "llm_relevante": reddit_row.get("llm_relevante", "PENDIENTE"),
        "idioma_detectado": "",
    }


def normalize_youtube_to_schema(youtube_row: dict) -> dict:
    """Convierte fila de YouTube al esquema unificado"""
    return {
        "red_social": "YouTube",
        "tipo_contenido": youtube_row.get("tipo"),
        "usuario": youtube_row.get("usuario_comentario"),
        "usuario_hash": youtube_row.get("usuario_hash"),
        "contenido": youtube_row.get("contenido"),
        "fecha": youtube_row.get("fecha_comentario"),
        "enlace": youtube_row.get("enlace_video"),
        
        "es_comentario": youtube_row.get("tipo") == "COMENTARIO",
        "post_padre_titulo": youtube_row.get("titulo_video", ""),
        "post_padre_texto": youtube_row.get("descripcion_video", ""),
        "usuario_original": youtube_row.get("nombre_canal", ""),
        "enlace_original": youtube_row.get("enlace_video", ""),
        
        "likes": youtube_row.get("likes_comentario", 0) if youtube_row.get("tipo") == "COMENTARIO" else youtube_row.get("likes_video", 0),
        "comentarios": youtube_row.get("num_comentarios_video", 0),
        "compartidos": 0,
        "visualizaciones": youtube_row.get("numero_visualizaciones_video", 0),
        
        "seguidores": 0,
        "siguiendo": 0,
        "bio": "",
        "verificado": False,
        
        "search_keyword": youtube_row.get("search_keyword"),
        "keyword_languages": youtube_row.get("keyword_languages"),
        
        "imagenes_paths": "[]",
        "gifs_paths": "[]",
        "videos_paths": "[]",
        "transcripcion_path": youtube_row.get("transcripcion_path", ""),
        
        "llm_relevante": youtube_row.get("llm_relevante", "PENDIENTE"),
        "idioma_detectado": "",
    }


# Función para unificar todos los CSVs
def unify_all_csvs(output_folder: str):
    """
    Lee todos los *_global_dataset.csv y los unifica en uno solo.
    """
    import pandas as pd
    from pathlib import Path
    
    folder = Path(output_folder)
    archivos = list(folder.glob("*_global_dataset.csv"))
    
    all_data = []
    
    for archivo in archivos:
        print(f"📂 Procesando {archivo.name}...")
        
        with open(archivo, 'r', encoding='utf-8') as f:
            sep = ';' if ';' in f.readline() else ','
        
        df = pd.read_csv(archivo, sep=sep, encoding='utf-8')
        
        # Normalizar según red social
        if 'reddit' in archivo.name.lower():
            normalized = [normalize_reddit_to_schema(row.to_dict()) for _, row in df.iterrows()]
        elif 'youtube' in archivo.name.lower():
            normalized = [normalize_youtube_to_schema(row.to_dict()) for _, row in df.iterrows()]
        # elif 'bluesky' in archivo.name.lower():
        #     normalized = [normalize_bluesky_to_schema(row.to_dict()) for _, row in df.iterrows()]
        else:
            continue
        
        all_data.extend(normalized)
    
    # Crear DataFrame unificado
    df_unified = pd.DataFrame(all_data)
    
    # Guardar
    output_path = folder / "dataset_unificado.csv"
    df_unified.to_csv(output_path, index=False, encoding='utf-8', sep=';')
    
    print(f"✅ Dataset unificado guardado: {output_path} ({len(df_unified)} filas)")
    return output_path