"""
Filtro LLM para verificar relevancia de posts antes de descargar comentarios.
Diseñado para ser rápido y asíncrono.
"""
import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import aiohttp
import json
from openai import AsyncOpenAI


@dataclass
class PostContent:
    """Contenedor para el contenido de un post"""
    text: str
    images: List[str] = None  # URLs de imágenes
    metadata: Dict = None     # Metadata adicional (fecha, autor, etc)
    

class LLMRelevanceFilter:
    """
    Filtro LLM asíncrono para verificar relevancia de posts.
    Usa vLLM API Server para máxima velocidad.
    """
    
    def __init__(
        self, 
        base_url: str = "http://localhost:8001/v1",
        #model: str = "Qwen/Qwen2.5-14B-Instruct",
	model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
max_concurrent: int = 10
    ):
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key="token-local-no-necesario"
        )
        self.model = model
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
    def _build_relevance_prompt(
        self, 
        tema: str, 
        keywords: List[str],
        geo_scope: str,
        languages: List[str],
        desc_tema: str
    ) -> str:
        """Construye el prompt para verificar relevancia"""
        
        keywords_str = ", ".join(keywords)
        languages_str = ", ".join(languages)
        
        return f"""Eres un filtro de relevancia para análisis de redes sociales.

**TEMA DE ANÁLISIS**: {tema}
**DESCRIPCIÓN DEL TEMA**: {desc_tema}
**ÁMBITO GEOGRÁFICO**: {geo_scope}
**IDIOMAS PERMITIDOS**: {languages_str}
**KEYWORDS DE REFERENCIA**: {keywords_str}

**TAREA**: Determinar si este post/video es relevante para el análisis.

**CRITERIOS DE RELEVANCIA** (Deben cumplirse TODOS):

1. **IDIOMA**: El texto está principalmente en uno de los idiomas permitidos
2. **GEOGRAFÍA**: Hay referencia clara o razonable al ámbito geográfico
3. **TEMA**: El contenido se relaciona directamente con "{tema}"  cuya descripción es "{desc_tema}"
   - El post menciona explícitamente el tema o sus componentes clave
   - NO es solo una mención tangencial o indirecta
   
**CRITERIOS DE EXCLUSIÓN AUTOMÁTICA**:
- spam evidente
- Idioma totalmente diferente a los permitidos
- Sin relación alguna con {tema}
- Hay referencia implícita en el contexto o explícita en el contenido fuera del ámbito geográfico

**INSTRUCCIONES**:
- Sé PERMISIVO: En caso de duda razonable, marca como relevante
- Busca la intención: ¿Este post aporta algo al análisis de opinión sobre {tema}?
- Un post con opinión sobre {tema} es SIEMPRE relevante, incluso si parece noticia

**FORMATO DE SALIDA** (JSON):
{{
  "es_relevante": true o false,
  "confianza": 0.0-1.0,
  "razon": "breve explicación de 1-2 líneas"
}}

Responde SOLO con el JSON, sin texto adicional."""

    async def check_relevance(
        self,
        post: PostContent,
        tema: str,
        keywords: List[str],
        geo_scope: str,
        languages: List[str],
        desc_tema: str = ""
    ) -> Tuple[bool, float, str]:
        """
        Verifica si un post es relevante.
        
        Returns:
            (es_relevante, confianza, razón)
        """
        async with self.semaphore:
            try:
                prompt = self._build_relevance_prompt(tema, keywords, geo_scope, languages,desc_tema)
                
                # Preparar el contenido del post
                user_content = f"**TEXTO DEL POST:**\n{post.text}"
                
                if post.images:
                    user_content += f"\n\n**TIENE IMÁGENES**: {len(post.images)} imagen(es)"
                    # Nota: Para análisis de imágenes, se podría usar GPT-4V o similar
                
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_content}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=200
                )
                
                raw = response.choices[0].message.content
                data = json.loads(raw)
                
                return (
                    data.get("es_relevante", False),
                    data.get("confianza", 0.0),
                    data.get("razon", "Sin razón")
                )
                
            except Exception as e:
                print(f"❌ Error en filtro LLM: {e}")
                # En caso de error, marcamos como relevante para no perder datos
                return (True, 0.0, f"Error: {str(e)}")
    
    async def check_batch(
        self,
        posts: List[PostContent],
        tema: str,
        keywords: List[str],
        geo_scope: str,
        languages: List[str],
        desc_tema: str = ""
    ) -> List[Tuple[bool, float, str]]:
        """
        Procesa múltiples posts en paralelo.
        """
        tasks = [
            self.check_relevance(post, tema, keywords, geo_scope, languages, desc_tema)
            for post in posts
        ]
        return await asyncio.gather(*tasks)


# ==============================================================================
# FUNCIONES DE UTILIDAD SÍNCRONAS (Para compatibilidad con código existente)
# ==============================================================================

def check_relevance_sync(
    text: str,
    images: List[str] = None,
    tema: str = "",
    keywords: List[str] = None,
    geo_scope: str = "España",
    languages: List[str] = None,
    desc_tema: str = ""
) -> bool:
    """
    Versión síncrona simple para uso en scrapers actuales.
    
    Returns:
        True si es relevante, False si no
    """
    if languages is None:
        languages = ["es", "ca", "eu", "gl", "en"]
    if keywords is None:
        keywords = []
    
    post = PostContent(text=text, images=images)
    filter_instance = LLMRelevanceFilter()
    
    # Ejecutar de forma síncrona
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        es_relevante, confianza, razon = loop.run_until_complete(
            filter_instance.check_relevance(post, tema, keywords, geo_scope, languages, desc_tema)
        )
        print(f"  → Relevancia: {es_relevante} (confianza: {confianza:.2f}) - {razon}")
        return es_relevante
    finally:
        loop.close()
