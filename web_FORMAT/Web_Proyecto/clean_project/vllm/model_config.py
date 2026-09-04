# clean_project/src/clean_project/config/model_config.py
"""
Configuración central del modelo de IA.

Para cambiar de modo, edita SOLO las dos líneas marcadas con ← EDITAR.
El resto del código se adapta automáticamente.

Modos disponibles:
  "texto"  → Qwen2.5-14B-Instruct-AWQ  (solo texto, más rápido, menos VRAM)
  "vision" → Qwen2.5-VL-7B-Instruct    (texto + imágenes, requiere más VRAM)
  "texto_razonador" → Qwen3.8-27B-NVFP4 (texto con razonamiento, requiere más VRAM)
"""

# ─────────────────────────────────────────────────────────
# ← EDITAR: elige "texto", "vision" o "texto_razonador"
MODO: str = "texto_razonador" #"texto"
# ─────────────────────────────────────────────────────────
# ← EDITAR (opcional): cambia el nombre del modelo si lo actualizas
_MODELOS = {
    "texto":            "Qwen/Qwen2.5-14B-Instruct-AWQ",
    "vision":           "Qwen/Qwen2.5-VL-7B-Instruct",
    "texto_razonador":  "Inferact/Qwen3.8-27B-NVFP4",
}
# Modelos "thinking": generan un bloque de razonamiento interno (expuesto
# vía 'reasoning_content', separado de 'content') antes de la respuesta
# final. Necesitan bastante más max_tokens que un modelo Instruct normal.
_MODELOS_RAZONADORES = {"texto_razonador"}
# ─────────────────────────────────────────────────────────

# Valores derivados (no editar)
MODELO_ACTIVO: str = _MODELOS[MODO]
VISION_HABILITADA: bool = MODO == "vision"
MODELO_ES_RAZONADOR: bool = MODO in _MODELOS_RAZONADORES

# extra_body para desactivar el modo thinking en modelos razonadores.
# Pásalo SIEMPRE a client.chat.completions.create(..., extra_body=EXTRA_BODY_LLM):
# en modelos normales es un dict vacío y no hace nada.
EXTRA_BODY_LLM: dict = (
    {"chat_template_kwargs": {"enable_thinking": False}} if MODELO_ES_RAZONADOR else {}
)

# Tokens de salida por tipo de tarea. Valores de partida — valídalos con
# test_modelo_debug.py contra ejemplos reales y ajusta si hace falta.
MAX_TOKENS_GATEKEEPER: int = 1500 if MODELO_ES_RAZONADOR else 200
MAX_TOKENS_ANALISIS: int = 6000 if MODELO_ES_RAZONADOR else 4000

# ── Resumen al importar ───────────────────────────────────
print(
    f"[model_config] Modo: {MODO.upper()} | "
    f"Modelo: {MODELO_ACTIVO} | "
    f"Visión: {'✅' if VISION_HABILITADA else '❌'} | Razonador: {'✅' if MODELO_ES_RAZONADOR else '❌'}"
)