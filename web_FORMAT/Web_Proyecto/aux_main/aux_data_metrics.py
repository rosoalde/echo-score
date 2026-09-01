"""
Métricas de tamaño en disco de Web_Proyecto/datos/, expuestas por Prometheus.

Diseño:
- Un Gauge por usuario (`app_user_data_bytes{username=...}`) + un total
  (`app_total_data_bytes`). Cardinalidad acotada al número de usuarios --
  es lo que Prometheus/Grafana manejan bien a largo plazo.
- A propósito NO se expone un Gauge por proyecto/dataset individual: con
  el tiempo eso puede crecer sin límite (cardinalidad descontrolada, un
  antipatrón conocido de Prometheus -- cada combinación de labels se
  guarda como serie propia para siempre). El desglose por proyecto de un
  usuario concreto es mejor consultarlo bajo demanda (ej. una futura
  columna "tamaño" en la página de Análisis del panel admin), no como
  serie temporal.
- El recorrido del árbol de carpetas se hace en un hilo de fondo cada
  DATA_METRICS_INTERVAL_SECONDS (5 min por defecto), no en cada scrape:
  con muchos datos, un os.walk cada 15s sería caro y podría hacer
  timeout en el scrape (10s configurado en prometheus.yml).
"""

import os
import threading
import time

from prometheus_client import Gauge


DATOS_DIR = os.getenv("DATOS_DIR", "/Web_Proyecto/datos")
REFRESH_SECONDS = int(os.getenv("DATA_METRICS_INTERVAL_SECONDS", "300"))

user_data_bytes = Gauge(
    "app_user_data_bytes",
    "Espacio en disco usado por cada usuario en datos/",
    ["username"],
)

total_data_bytes = Gauge(
    "app_total_data_bytes",
    "Espacio en disco total usado en datos/",
)

last_refresh_timestamp = Gauge(
    "app_data_metrics_last_refresh_timestamp",
    "Unix timestamp de la última vez que se recalcularon estas métricas",
)


def _dir_size_bytes(path: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                total += os.path.getsize(fp)
            except OSError:
                # el archivo pudo borrarse justo entre el listado y el getsize
                pass
    return total


def _refresh_once():
    if not os.path.isdir(DATOS_DIR):
        print(f"⚠️  DATOS_DIR no existe: {DATOS_DIR}")
        return

    grand_total = 0

    try:
        with os.scandir(DATOS_DIR) as entries:
            for entry in entries:
                if not entry.is_dir():
                    continue
                size = _dir_size_bytes(entry.path)
                user_data_bytes.labels(username=entry.name).set(size)
                grand_total += size

        total_data_bytes.set(grand_total)
        last_refresh_timestamp.set(time.time())

    except Exception as e:
        print("🔥 ERROR refrescando métricas de datos:", e)


def _refresh_loop():
    while True:
        _refresh_once()
        time.sleep(REFRESH_SECONDS)


def start_data_metrics_thread():
    """Llamar una vez al arrancar la app. Corre en background, no bloquea el arranque."""
    thread = threading.Thread(target=_refresh_loop, daemon=True)
    thread.start()
