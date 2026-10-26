"""User record table

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("password", sa.String(), nullable=False, unique=True),
        sa.Column("admin", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=True),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("ts_auth_key", sa.String(), nullable=True),
        sa.Column("warp_key", sa.String(), nullable=True),
        sa.Column("warp_ipv6", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("users")
