from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260425_0004"
down_revision = "20260424_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "FREE_SIGNUP_CREDIT",
        "PURCHASE",
        "SPEND",
        "REFUND",
        "ADMIN_ADJUSTMENT",
        name="credit_transaction_type",
    ).create(bind, checkfirst=True)
    credit_transaction_type = postgresql.ENUM(
        "FREE_SIGNUP_CREDIT",
        "PURCHASE",
        "SPEND",
        "REFUND",
        "ADMIN_ADJUSTMENT",
        name="credit_transaction_type",
        create_type=False,
    )

    op.add_column("users", sa.Column("credit_balance", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("credits_charged", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("credit_spend_transaction_id", sa.Uuid(), nullable=True))
    op.add_column("jobs", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("transaction_type", credit_transaction_type, nullable=False),
        sa.Column("credit_amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("paddle_event_id", sa.String(length=255), nullable=True),
        sa.Column("paddle_transaction_id", sa.String(length=255), nullable=True),
        sa.Column("package_key", sa.String(length=64), nullable=True),
        sa.Column("payment_amount", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("payment_status", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paddle_event_id"),
    )
    op.create_index(op.f("ix_credit_transactions_job_id"), "credit_transactions", ["job_id"], unique=False)
    op.create_index(op.f("ix_credit_transactions_transaction_type"), "credit_transactions", ["transaction_type"], unique=False)
    op.create_index(op.f("ix_credit_transactions_user_id"), "credit_transactions", ["user_id"], unique=False)

    op.alter_column("users", "credit_balance", server_default=None)
    op.alter_column("jobs", "credits_charged", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_credit_transactions_user_id"), table_name="credit_transactions")
    op.drop_index(op.f("ix_credit_transactions_transaction_type"), table_name="credit_transactions")
    op.drop_index(op.f("ix_credit_transactions_job_id"), table_name="credit_transactions")
    op.drop_table("credit_transactions")
    op.drop_column("jobs", "refunded_at")
    op.drop_column("jobs", "failed_at")
    op.drop_column("jobs", "credit_spend_transaction_id")
    op.drop_column("jobs", "credits_charged")
    op.drop_column("users", "credit_balance")

    bind = op.get_bind()
    postgresql.ENUM(name="credit_transaction_type").drop(bind, checkfirst=True)
