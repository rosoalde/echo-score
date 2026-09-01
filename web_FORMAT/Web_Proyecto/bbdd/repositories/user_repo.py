import csv
from pathlib import Path
from bbdd.models.user import User
from datetime import datetime
from passlib.context import CryptContext

USERS_FILE = Path("../backend/BBDD/users.csv")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class UserRepositoryCSV:

    def get_all(self):
        users = []
        if USERS_FILE.exists():
            with open(USERS_FILE, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    row["id"] = int(row["id"])
                    row["is_active"] = row["is_active"] == "True"
                    users.append(User(**row))
        return users

    def get_by_username(self, username):
        return next((u for u in self.get_all() if u.username == username), None)

    def save(self, user: User):
        users = self.get_all()
        user.id = max([u.id for u in users], default=0) + 1
        users.append(user)
        self._write_all(users)

    def update(self, user: User):
        users = self.get_all()
        for i, u in enumerate(users):
            if u.id == user.id:
                users[i] = user
        self._write_all(users)

    def authenticate(self, username: str, password: str):
        user = self.get_by_username(username)
        if not user:
            return None
        if pwd_context.verify(password, user.hashed_password):
            return user
        return None

    def _write_all(self, users):
        with open(USERS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=users[0].__dataclass_fields__.keys())
            writer.writeheader()
            for u in users:
                writer.writerow(u.__dict__)
    
