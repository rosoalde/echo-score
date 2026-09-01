from sqlalchemy.orm import Session
from bbdd.models_all import User, Role
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_test_users(db: Session):

    role_names = ["admin", "analista", "user"]
    roles_dict = {}

    for name in role_names:
        role = db.query(Role).filter_by(name=name).first()
        if not role:
            role = Role(name=name)
            db.add(role)
            db.flush()
        roles_dict[name] = role

    users = [
        {
            "username": "admin",
            "email": "admin@test.com",
            "password": "_10lmdnd023_.$usj&asjs", #admin123
            "first_name": "Admin",
            "last_name": "System",
            "roles": ["admin", "analista"]
        },
        {
            "username": "analista",
            "email": "analista@test.com",
            "password": "kksn.1i92$ghhs&jadj", #analista123
            "first_name": "Ana",
            "last_name": "Lopez",
            "roles": ["analista"]
        },
        {
            "username": "user",
            "email": "user@test.com",
            "password": "user4test",
            "first_name": "Juan",
            "last_name": "Perez",
            "roles": ["user"]
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
            hashed_password=get_password_hash(u["password"]),
            first_name=u["first_name"],
            last_name=u["last_name"],
            is_active=True,
            is_verified=True,
        )

        # roles many-to-many
        new_user.roles = [roles_dict[r] for r in u["roles"]]

        db.add(new_user)

    db.commit()