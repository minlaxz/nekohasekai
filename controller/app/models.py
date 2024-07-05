"""Database models."""

from . import db


class User(db.Model):
    __tablename__ = "app-users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), index=True, unique=True, nullable=False)
    password = db.Column(db.String(255), index=True, unique=True, nullable=False)
    uuid = db.Column(db.String(255), index=True, unique=True, nullable=False)
    email = db.Column(db.String(255), index=True, unique=True, nullable=False)
    short_id = db.Column(db.String(255), index=True, unique=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), server_onupdate=db.func.now())

    def __repr__(self):
        return f"<User id={self.id}, name={self.name}, email={self.email}>"