# clean_project/src/clean_project/config/model_config.py
"""
Configuración central del modelo de IA.

Para cambiar de modo, edita SOLO las dos líneas marcadas con ← EDITAR.
El resto del código se adapta automáticamente.

Modos disponibles:
  "texto"  → Qwen2.5-14B-Instruct-AWQ  (solo texto, más rápido, menos VRAM)
  "vision" → Qwen2.5-VL-7B-Instruct    (texto + imágenes, requiere más VRAM)
"""

# ─────────────────────────────────────────────────────────
# ← EDITAR: elige "texto" o "vision"
MODO: str = "texto"
# ─────────────────────────────────────────────────────────
# ← EDITAR (opcional): cambia el nombre del modelo si lo actualizas
_MODELOS = {
    "texto":  "Qwen/Qwen2.5-14B-Instruct-AWQ",
    "vision": "Qwen/Qwen2.5-VL-7B-Instruct",
}
# ─────────────────────────────────────────────────────────

# Valores derivados (no editar)
MODELO_ACTIVO: str = _MODELOS[MODO]
VISION_HABILITADA: bool = MODO == "vision"

# ── Resumen al importar ───────────────────────────────────
print(
    f"[model_config] Modo: {MODO.upper()} | "
    f"Modelo: {MODELO_ACTIVO} | "
    f"Visión: {'✅' if VISION_HABILITADA else '❌'}"
)