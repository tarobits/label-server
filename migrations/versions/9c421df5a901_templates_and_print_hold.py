"""Versioned template documents and persistent automatic-print hold."""

import sqlalchemy as sa
from alembic import op

revision = "9c421df5a901"
down_revision = "72215c74c054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("printer_state") as batch:
        batch.add_column(
            sa.Column("automatic_printing_held", sa.Boolean(), nullable=False, server_default="0")
        )
    op.create_table(
        "label_templates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "template_revisions",
        sa.Column(
            "template_id", sa.String(), sa.ForeignKey("label_templates.id"), primary_key=True
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("template_revisions")
    op.drop_table("label_templates")
    with op.batch_alter_table("printer_state") as batch:
        batch.drop_column("automatic_printing_held")
