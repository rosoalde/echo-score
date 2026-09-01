# seed.py
from bbdd.database import SessionLocal
from bbdd.models_all import Role, Status, TaskType
from bbdd.load_data.usuarios_prueba import create_test_users


# Arrancar al inicio del proyecto junto con DOCKER
def seed_data():
    db: Session = SessionLocal()

    # ROLES
    roles = ["admin", "analista", "user"]
    for r in roles:
        exists = db.query(Role).filter(Role.name == r).first()
        if not exists:
            db.add(Role(name=r))

    # STATUS
    statuses = ["starting","pending", "running", "finished", "error"]
    for s in statuses:
        exists = db.query(Status).filter(Status.name == s).first()
        if not exists:
            db.add(Status(name=s))

    # TASK TYPES
    tasks = ["scraping", "analysis", "report"]
    for t in tasks:
        exists = db.query(TaskType).filter(TaskType.name == t).first()
        if not exists:
            db.add(TaskType(name=t))

    db.commit()

    #solo como prueba, en producción
    create_test_users(db)

    db.close()

if __name__ == "__main__":
    seed_data()
