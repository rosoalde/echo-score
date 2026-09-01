import sys
import json
import re
import ollama
from pathlib import Path

# =============================================================================
# 1. CONFIGURACIÓN DE RUTAS E IMPORTS (Intento robusto)
# =============================================================================
try:
    # Ajusta esto según tu estructura real si falla
    ROOT_DIR = Path(__file__).resolve().parents[1] 
    RUTA_CLEAN_PROJECT = ROOT_DIR / "clean_project" / "src"
    
    if str(RUTA_CLEAN_PROJECT) not in sys.path:
        sys.path.insert(0, str(RUTA_CLEAN_PROJECT))
        
    print(f"📂 Ruta añadida al path: {RUTA_CLEAN_PROJECT}")

    from clean_project.prompts.keywords import get_prompt_keywords
    print("✅ Import 'get_prompt_keywords' exitoso.")

except ImportError as e:
    print(f"⚠️ No se pudo importar el prompt real ({e}). Usando prompt de prueba.")
    
    # Fallback por si fallan las rutas, para que pruebes OLLAMA igual
    def get_prompt_keywords(tema):
        return f"Genera un JSON con 5 keywords para buscar en redes sociales sobre: {tema}. Formato: {{ 'keywords': [...] }}"

except Exception as e:
    print(f"❌ Error general en configuración de rutas: {e}")
    sys.exit(1)

# =============================================================================
# 2. FUNCIONES DE AYUDA
# =============================================================================
def extraer_json(texto: str):
    """Función de extracción por Regex (copiada de tu lógica)"""
    if not texto: return None
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # Busca lo que esté entre llaves { ... }
        match = re.search(r"\{[\s\S]*\}", texto)
        if match:
            try: return json.loads(match.group(0))
            except: return None
    return None

# =============================================================================
# 3. FUNCIÓN PRINCIPAL DE PRUEBA
# =============================================================================
def test_generacion(tema: str):
    print(f"\n🚀 [INICIO] Probando generación para: '{tema}'")
    
    # 1. CHECK OLLAMA VIVO
    print("👉 Paso 1: Verificando conexión con Ollama...")
    try:
        models = ollama.list()
        print("   ✅ Ollama está corriendo. Modelos disponibles:",
        [m["model"] for m in models["models"][:3]]
    )
    except Exception as e:
        print(f"   ❌ ERROR FATAL: Ollama no responde. Detalles: {e}")
        return

    prompt = get_prompt_keywords(tema)
    
    # IMPORTANTE: Usa un modelo que SEPAS que tienes descargado.
    # Si pones gemma3:4b y no lo tienes, se quedará "colgado" descargando gigas.
    model_name = "qwen2.5:1.5b" #"llama3:latest" #"gemma3:4b"#"qwen2.5:0.5b" "llama3"#
    
    print(f"👉 Paso 2: Enviando prompt al modelo '{model_name}'...")
    print("   (Si se queda aquí pegado más de 1 min, es que el modelo se está descargando o tu GPU murió)")

    try:
        # SIN format="json" y SIN GPU para evitar bloqueos
        response = ollama.chat(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            # format="json",  <-- DESACTIVADO PARA VER SI RESPONDE ALGO
            options={
                "temperature": 0.1,
                "num_ctx": 4096, 
                #"num_gpu": 1 # <-- DESACTIVADO POR SEGURIDAD
            }
        )
        
        raw_content = response.get("message", {}).get("content", "")
        print(f"\n👉 Paso 3: Respuesta cruda recibida:\n{'-'*40}\n{raw_content}\n{'-'*40}")
        
        data = extraer_json(raw_content)
        
        if data and "keywords" in data:
            print(f"\n✅ ¡ÉXITO! Keywords extraídas: {data['keywords']}")
            return data["keywords"]
        else:
            print(f"\n⚠️ El modelo respondió, pero no se pudo extraer JSON válido.")
            return []
    except Exception as e:
        print(f"\n❌ ERROR DURANTE LA GENERACIÓN: {e}")
    return []
# =============================================================================
# EJECUCIÓN
# =============================================================================
if __name__ == "__main__":
    import time
    start_time = time.time()
    tema = "opinión pública sobre el uso de drones civiles en ciudades"
    print(f"🕵️‍♂️ Iniciando ejecución a las {start_time}")
    contexto = f"Crea keywords específicas para la búsqueda en redes sociales sobre la {tema}"
    print("esta es la salida:", test_generacion(contexto))
    end_time = time.time()
    print(f"\n⏱️ Tiempo total de ejecución: {end_time - start_time:.2f} segundos")