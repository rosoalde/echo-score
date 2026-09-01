"""
scraper_profiler.py
-------------------
Módulo de cronometrado para youtube_scraper.
Registra tiempos de cada operación en un CSV separado,
una fila por evento, para análisis posterior.

COLUMNAS DEL CSV DE PROFILING:
-------------------------------
run_id          : ID único de la ejecución (timestamp al arrancar). Permite comparar runs distintos.
timestamp       : Momento exacto en que ocurrió el evento (ISO 8601 UTC).
event           : Nombre del evento/operación que se está midiendo. Ver catálogo abajo.
video_id        : ID del video al que pertenece el evento. Vacío para eventos globales.
keyword         : Keyword de búsqueda activa en ese momento.
duration_s      : Duración en segundos (float) de esa operación concreta.
batch_size      : Para eventos de batch LLM, cuántos ítems se procesaron juntos.
status          : "ok" | "skip" | "error" — resultado de la operación.
detail          : Texto libre: razón de descarte, mensaje de error, etc.

CATÁLOGO DE EVENTOS:
---------------------
run_start           : Inicio completo del scraper.
run_end             : Fin completo del scraper. duration_s = tiempo total.

keyword_search      : Llamada a youtube.search().list() para una keyword.
                      Cuello de botella: latencia de la API de YouTube.

video_stats_fetch   : Llamada a youtube.videos().list() para stats+snippet de UN video.
                      Cuello de botella: N llamadas secuenciales = N * latencia.

channel_stats_fetch : Llamada a youtube.channels().list() para suscriptores.
                      Cuello de botella: igual que el anterior.

transcript_fetch    : Descarga de transcripción via youtube-transcript-api.
                      Cuello de botella: red + disponibilidad del transcript.

thumbnail_download  : Descarga y base64 de la miniatura.
                      Cuello de botella: red.

llm_batch_call      : Llamada al LLM (vLLM) para evaluar relevancia.
                      batch_size indica cuántos videos se evaluaron juntos.
                      Cuello de botella: tiempo de inferencia × batch.

comment_page_fetch  : Una página de comentarios (hasta 100). Se repite por paginación.
                      Cuello de botella: N páginas × latencia API.

csv_write           : Escritura de filas al CSV de salida.
                      Cuello de botella: I/O disco (raro, pero medible).

api_key_switch      : Registro de cuándo se agotó una key y se cambió a otra.
                      duration_s ≈ 0. Útil para saber cuándo se consume la cuota.
"""

import csv
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ScraperProfiler:
    """
    Acumula eventos de timing y los vuelca a un CSV al finalizar (o en streaming).

    Uso básico:
        profiler = ScraperProfiler(output_path="./profiling/run_metrics.csv")
        profiler.start_run()

        t = profiler.tick()
        # ... operación ...
        profiler.record("keyword_search", duration_s=profiler.tock(t), keyword=kw)

        profiler.end_run()
    """

    COLUMNS = [
        "run_id", "timestamp", "event", "video_id",
        "keyword", "duration_s", "batch_size", "status", "detail"
    ]

    def __init__(self, output_path: str = "./profiling/scraper_profile.csv", stream: bool = True):
        """
        output_path : Ruta del CSV de profiling.
        stream      : Si True, escribe cada evento inmediatamente (seguro ante crashes).
                      Si False, acumula en memoria y escribe al final (más rápido).
        """
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = stream
        self.run_id = None
        self._run_start_time = None
        self._rows = []
        self._file = None
        self._writer = None

    # ------------------------------------------------------------------
    # Ciclo de vida del run
    # ------------------------------------------------------------------

    def start_run(self):
        """Abre el CSV y registra el inicio del run."""
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self._run_start_time = time.perf_counter()

        file_exists = self.output_path.exists()
        self._file = open(self.output_path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.COLUMNS)
        if not file_exists:
            self._writer.writeheader()

        self._write_row(event="run_start", duration_s=0.0, status="ok")
        print(f"📊 Profiler activo → {self.output_path}  [run_id={self.run_id}]")

    def end_run(self):
        """Registra fin del run y cierra el fichero."""
        total = time.perf_counter() - self._run_start_time
        self._write_row(event="run_end", duration_s=round(total, 4), status="ok",
                        detail=f"total_run_seconds={round(total,2)}")
        if self._file:
            self._file.flush()
            self._file.close()

    # ------------------------------------------------------------------
    # Temporización
    # ------------------------------------------------------------------

    @staticmethod
    def tick() -> float:
        """Devuelve el tiempo actual (para calcular duración después con tock)."""
        return time.perf_counter()

    @staticmethod
    def tock(start: float) -> float:
        """Devuelve los segundos transcurridos desde start."""
        return round(time.perf_counter() - start, 4)

    # ------------------------------------------------------------------
    # Registro de eventos
    # ------------------------------------------------------------------

    def record(self, event: str, duration_s: float = 0.0, video_id: str = "",
               keyword: str = "", batch_size: int = 1,
               status: str = "ok", detail: str = ""):
        """Registra un evento de profiling."""
        self._write_row(event=event, duration_s=duration_s, video_id=video_id,
                        keyword=keyword, batch_size=batch_size,
                        status=status, detail=detail)

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _write_row(self, **kwargs):
        row = {
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": kwargs.get("event", ""),
            "video_id": kwargs.get("video_id", ""),
            "keyword": kwargs.get("keyword", ""),
            "duration_s": kwargs.get("duration_s", 0.0),
            "batch_size": kwargs.get("batch_size", 1),
            "status": kwargs.get("status", "ok"),
            "detail": kwargs.get("detail", ""),
        }
        if self.stream and self._writer:
            self._writer.writerow(row)
            self._file.flush()
        else:
            self._rows.append(row)

    def flush(self):
        """Fuerza escritura de filas acumuladas (modo stream=False)."""
        if self._writer and self._rows:
            self._writer.writerows(self._rows)
            self._rows.clear()
            self._file.flush()
