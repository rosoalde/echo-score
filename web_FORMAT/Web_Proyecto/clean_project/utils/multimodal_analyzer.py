"""
Analizador multimodal que procesa texto e imágenes.
Usa GPT-4V de OpenAI (requiere API key).
"""
from openai import OpenAI
from typing import List, Dict, Optional
import base64


class MultimodalAnalyzer:
    """Analiza contenido multimodal (texto + imágenes)"""
    
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
    
    def _encode_image(self, image_path: str) -> str:
        """Codifica imagen a base64"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def analyze_post_with_images(
        self,
        text: str,
        image_paths: List[str],
        tema: str,
        geo_scope: str
    ) -> Dict:
        """
        Analiza un post con texto e imágenes.
        
        Returns:
            {
                "es_relevante": bool,
                "razon": str,
                "descripcion_imagenes": str
            }
        """
        # Preparar contenido multimodal
        content = [
            {
                "type": "text",
                "text": f"""Analiza este contenido para determinar si es relevante para un estudio sobre "{tema}" en {geo_scope}.

TEXTO DEL POST:
{text}

¿Es relevante? Explica brevemente."""
            }
        ]
        
        # Añadir imágenes
        for img_path in image_paths[:4]:  # Máximo 4 imágenes
            try:
                base64_image = self._encode_image(img_path)
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                })
            except:
                continue
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                max_tokens=300
            )
            
            answer = response.choices[0].message.content
            es_relevante = "sí" in answer.lower() or "relevante" in answer.lower()
            
            return {
                "es_relevante": es_relevante,
                "razon": answer,
                "descripcion_imagenes": answer
            }
            
        except Exception as e:
            print(f"Error en análisis multimodal: {e}")
            return {
                "es_relevante": True,  # Permisivo por defecto
                "razon": f"Error: {str(e)}",
                "descripcion_imagenes": ""
            }


# PLACEHOLDER: Si no quieres usar GPT-4V (caro), usa LLaVA local
def analyze_with_llava(text: str, image_path: str) -> bool:
    """
    Alternativa usando LLaVA (modelo local de visión).
    Requiere instalar ollama y descargar llava.
    """
    import ollama
    
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        
        response = ollama.chat(
            model='llava',
            messages=[{
                'role': 'user',
                'content': f'Describe esta imagen y di si se relaciona con: {text}',
                'images': [image_data]
            }]
        )
        
        answer = response['message']['content']
        return "sí" in answer.lower() or "relaciona" in answer.lower()
        
    except:
        return True  # Permisivo si falla