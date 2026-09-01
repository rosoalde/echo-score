from celery import Celery
import os

# Mismo broker/backend que usa el proyecto principal (Web_Proyecto/celery_app.py).
# admin-api NO comparte volumen con Web_Proyecto, así que no importamos esa app:
# creamos un cliente separado que habla con el mismo Redis para poder:
#   - inspeccionar workers (ping/active/reserved)
#   - revocar tareas en curso
#   - relanzar tareas por nombre, sin necesitar el código fuente de la tarea

broker = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

celery_admin = Celery("admin_client", broker=broker, backend=backend)
