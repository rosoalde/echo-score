"""
Gestor de descarga y almacenamiento de medios (imágenes, GIFs, videos).
"""
import requests
import hashlib
from pathlib import Path
from typing import Optional, List
import mimetypes


class MediaDownloader:
    """Descarga y gestiona medios de redes sociales"""
    
    def __init__(self, base_folder: str):
        self.base_folder = Path(base_folder)
        self.images_folder = self.base_folder / "images"
        self.gifs_folder = self.base_folder / "gifs"
        self.videos_folder = self.base_folder / "videos"
        
        # Crear carpetas
        for folder in [self.images_folder, self.gifs_folder, self.videos_folder]:
            folder.mkdir(parents=True, exist_ok=True)
    
    def _get_file_hash(self, url: str) -> str:
        """Genera hash único para la URL"""
        return hashlib.sha256(url.encode()).hexdigest()[:16]
    
    def _detect_media_type(self, url: str, content_type: Optional[str] = None) -> str:
        """Detecta si es imagen, GIF o video"""
        if content_type:
            if 'gif' in content_type:
                return 'gif'
            elif 'image' in content_type:
                return 'image'
            elif 'video' in content_type:
                return 'video'
        
        # Detectar por extensión
        url_lower = url.lower()
        if url_lower.endswith('.gif'):
            return 'gif'
        elif any(url_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
            return 'image'
        elif any(url_lower.endswith(ext) for ext in ['.mp4', '.webm', '.mov']):
            return 'video'
        
        return 'image'  # Default
    
    def download_media(self, url: str, media_type: Optional[str] = None) -> Optional[str]:
        """
        Descarga un medio y retorna la ruta relativa.
        
        Args:
            url: URL del medio
            media_type: 'image', 'gif', 'video' (se detecta automáticamente si no se especifica)
        
        Returns:
            Ruta relativa al medio guardado, o None si falla
        """
        try:
            # Descargar con timeout
            response = requests.get(url, timeout=10, stream=True)
            response.raise_for_status()
            
            # Detectar tipo de medio
            content_type = response.headers.get('Content-Type', '')
            detected_type = media_type or self._detect_media_type(url, content_type)
            
            # Determinar carpeta destino
            if detected_type == 'gif':
                folder = self.gifs_folder
                extension = '.gif'
            elif detected_type == 'video':
                folder = self.videos_folder
                extension = '.mp4'
            else:
                folder = self.images_folder
                # Detectar extensión real
                ext = mimetypes.guess_extension(content_type)
                extension = ext if ext else '.jpg'
            
            # Generar nombre de archivo único
            file_hash = self._get_file_hash(url)
            filename = f"{file_hash}{extension}"
            filepath = folder / filename
            
            # Si ya existe, no descargar de nuevo
            if filepath.exists():
                return str(filepath.relative_to(self.base_folder))
            
            # Guardar archivo
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return str(filepath.relative_to(self.base_folder))
            
        except Exception as e:
            print(f"⚠️ Error descargando {url}: {e}")
            return None
    
    def download_multiple(self, urls: List[str]) -> List[str]:
        """Descarga múltiples medios y retorna las rutas"""
        paths = []
        for url in urls:
            path = self.download_media(url)
            if path:
                paths.append(path)
        return paths


# Función auxiliar para usar en scrapers
def save_media_from_post(post_data: dict, base_folder: str) -> dict:
    """
    Extrae y guarda medios de un post.
    
    Args:
        post_data: Diccionario con datos del post (debe tener 'images', 'gifs', etc.)
        base_folder: Carpeta base para guardar
    
    Returns:
        Dict con rutas a los medios guardados
    """
    downloader = MediaDownloader(base_folder)
    
    result = {
        "images": [],
        "gifs": [],
        "videos": []
    }
    
    # Procesar imágenes
    if "images" in post_data and post_data["images"]:
        for img_url in post_data["images"]:
            path = downloader.download_media(img_url, media_type='image')
            if path:
                result["images"].append(path)
    
    # Procesar GIFs
    if "gifs" in post_data and post_data["gifs"]:
        for gif_url in post_data["gifs"]:
            path = downloader.download_media(gif_url, media_type='gif')
            if path:
                result["gifs"].append(path)
    
    # Procesar videos
    if "videos" in post_data and post_data["videos"]:
        for vid_url in post_data["videos"]:
            path = downloader.download_media(vid_url, media_type='video')
            if path:
                result["videos"].append(path)
    
    return result