from alembic import context
from sqlalchemy import create_engine

from app import store

url = context.config.get_main_option("sqlalchemy.url") or store.DB_URL
with create_engine(url).connect() as connection:
    context.configure(connection=connection, target_metadata=store.SQLModel.metadata)
    with context.begin_transaction():
        context.run_migrations()
