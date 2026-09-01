from sqlalchemy.orm import Session
from bbdd.models_all import User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_test_users(db: Session):
    users = [
        {
            "username": "admin",
            "email": "admin@test.com",
            "phone": "600000001",
            "password": "admin123",
            "first_name": "Admin",
            "last_name": "System",
            "role": "admin",
        },
        {
            "username": "analista",
            "email": "analista1@test.com",
            "phone": "600000002",
            "password": "analista123",
            "first_name": "Ana",
            "last_name": "Lopez",
            "role": "analista",
        },
        {
            "username": "user",
            "email": "user1@test.com",
            "phone": "600000003",
            "password": "user123",
            "first_name": "Juan",
            "last_name": "Perez",
            "role": "user",
        },
    ]

    for u in users:
        existing = db.query(User).filter(
            (User.email == u["email"]) | (User.username == u["username"])
        ).first()

        if existing:
            continue

        new_user = User(
            username=u["username"],
            email=u["email"],
            phone=u["phone"],
            hashed_password=pwd_context.hash(u["password"]),
            first_name=u["first_name"],
            last_name=u["last_name"],
            role=u["role"],
            is_active=True
        )

        db.add(new_user)

    db.commit()