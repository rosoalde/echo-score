"""
Autenticación de /metrics -- pensado para que lo lea Prometheus (una
máquina), no una persona con sesión de navegador.

A propósito NO reutiliza el JWT/cookie del login del admin:
- Ese token caduca cada 300 min (ver aux_admin.create_access_token). Nadie
  "refresca sesión" por Prometheus, así que el scrape se rompería solo
  cada pocas horas sin que nadie tocara nada.
- Verificarlo aquí obligaría a compartir el SECRET_KEY del panel admin
  con este servicio -- acopla dos sistemas que hoy son independientes a
  propósito, y en la dirección incorrecta (el servicio más expuesto
  terminaría con la clave que protege al más privilegiado).

En su lugar: un token de máquina, largo y aleatorio (256 bits), de vida
larga, que rotas tú a mano cuando quieras. La app NUNCA guarda el token
en claro -- solo su hash SHA-256 (METRICS_TOKEN_HASH). Así, aunque
alguien lea las variables de entorno de este contenedor, no se lleva un
credential utilizable, solo el hash.

No hace falta guardar nada en BBDD: no es una credencial que rote por
usuario/sesión (para eso ya existe UserSession), es un secreto de
servicio único que gestionas tú directamente por .env.
"""

import hashlib
import os
import secrets

from fastapi import Request, HTTPException


METRICS_TOKEN_HASH = os.getenv("METRICS_TOKEN_HASH")

if not METRICS_TOKEN_HASH:
    raise RuntimeError(
        "METRICS_TOKEN_HASH no está configurado. Sin esto, /metrics quedaría "
        "sin protección, así que arrancar sin él es un error, no un warning. "
        "Genera un token con `openssl rand -hex 32`, calcula su SHA-256 y "
        "pon el HASH (no el token) en el .env de este servicio."
    )


def verificar_metrics_token(request: Request):

    auth_header = request.headers.get("authorization", "")

    if not auth_header.startswith("Bearer "):
        # 404, nunca 401/403: no delatamos que la ruta existe
        raise HTTPException(status_code=404)

    presented_token = auth_header.removeprefix("Bearer ").strip()
    presented_hash = hashlib.sha256(presented_token.encode()).hexdigest()

    if not secrets.compare_digest(presented_hash, METRICS_TOKEN_HASH):
        raise HTTPException(status_code=404)

    return True
