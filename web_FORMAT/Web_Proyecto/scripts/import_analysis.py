from pathlib import Path
import json
from datetime import datetime

# Se ejecuta con este comando:
# docker compose exec api python scripts/import_analysis.py
from sqlalchemy.orm import Session

from bbdd.database import SessionLocal
from bbdd.models_all import (
    User,
    Analysis,
    AnalysisTask,
    TaskLog,
    AnalysisStatus,
    TaskStatus,
    TaskTypeEnum,
    generate_slug
)

db: Session = SessionLocal()

JSON_FILE = Path("/Web_Proyecto/analysis_db.json")

if not JSON_FILE.exists():
    raise FileNotFoundError(JSON_FILE)

with open(JSON_FILE, "r", encoding="utf-8") as f:
    projects = json.load(f)

inserted = 0
skipped = 0

for p in projects:

    username = p["username"]

    user = (
        db.query(User)
        .filter(User.username == username)
        .first()
    )

    if not user:
        print(f"Usuario inexistente: {username}")
        skipped += 1
        continue

    existing = (
        db.query(Analysis)
        .filter(
            Analysis.user_id == user.id,
            Analysis.project_name == p["project_name"]
        )
        .first()
    )

    if existing:
        print(f"Ya existe: {p['project_name']}")
        skipped += 1
        continue

    slug = generate_slug(
        db,
        p["project_name"],
        user.username
    )

    created_at = datetime.fromisoformat(
        p["created_at"]
    )

    analysis = Analysis(
        user_id=user.id,
        project_name=p["project_name"],
        slug=slug,
        output_folder=p["output_folder"],
        status=AnalysisStatus.COMPLETED,
        progress_percent=100,
        analysis_config=p,
        created_at=created_at,
    )

    db.add(analysis)
    db.flush()

    task = AnalysisTask(
        analysis_id=analysis.id,
        task_type=TaskTypeEnum.SCRAPING,
        status=TaskStatus.COMPLETED,
        priority=3,
        progress_percent=100,
        total_items=100,
        processed_items=100,
        queued_at=created_at,
        started_at=created_at,
        finished_at=created_at,
        current_step="Importación histórica",
        message="Análisis completado",
        input_config={
            "action": "import_analysis"
        },
        output_summary={
            "imported": True
        }
    )

    db.add(task)
    db.flush()

    log = TaskLog(
        task_id=task.id,
        level="INFO",
        message="Proyecto importado desde analysis_db.json"
    )

    db.add(log)

    inserted += 1

db.commit()

print(
    f"Insertados={inserted} "
    f"Saltados={skipped}"
)