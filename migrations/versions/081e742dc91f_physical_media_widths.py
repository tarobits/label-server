"""Store physical media widths without changing frozen render documents.

Revision ID: 081e742dc91f
Revises: f31a729de840
"""

import copy

import sqlalchemy as sa
from alembic import op

revision = "081e742dc91f"
down_revision = "f31a729de840"
branch_labels = None
depends_on = None


def change_columns(old, new, column_type):
    # Native ADD/DROP/RENAME preserves all referring foreign keys and history.
    for table in ("tape_profiles", "print_jobs"):
        op.add_column(
            table, sa.Column("physical_width_mm", column_type, nullable=False, server_default="0")
        )
        op.execute(
            sa.text(
                f"UPDATE {table} SET physical_width_mm = CASE WHEN width_mm = :old THEN :new ELSE width_mm END"
            ).bindparams(old=old, new=new)
        )
        op.drop_column(table, "width_mm")
        op.execute(sa.text(f"ALTER TABLE {table} RENAME COLUMN physical_width_mm TO width_mm"))


def change_runs(old, new):
    connection = op.get_bind()
    runs = sa.Table("print_runs", sa.MetaData(), autoload_with=connection)
    for row in connection.execute(runs.select()).mappings():
        manifest = copy.deepcopy(row["manifest"])
        changed = False
        for entry in manifest["rows"]:
            if entry["width_mm"] == old:
                entry["width_mm"] = new
                changed = True
        if changed:
            connection.execute(
                runs.update().where(runs.c.id == row["id"]).values(manifest=manifest)
            )


def upgrade():
    change_columns(4, 3.5, sa.Double())
    change_runs(4, 3.5)
    connection = op.get_bind()
    templates = sa.Table("label_templates", sa.MetaData(), autoload_with=connection)
    revisions = sa.Table("template_revisions", sa.MetaData(), autoload_with=connection)
    for row in connection.execute(templates.select()).mappings():
        if row["document"]["width_mm"] != 4:
            continue
        document = copy.deepcopy(row["document"])
        document["width_mm"] = 3.5
        for element in document["elements"]:
            element["y"] -= 0.25
        revision = row["revision"] + 1
        connection.execute(
            templates.update()
            .where(templates.c.id == row["id"])
            .values(document=document, revision=revision)
        )
        connection.execute(
            revisions.insert().values(
                template_id=row["id"], revision=revision, name=row["name"], document=document
            )
        )


def downgrade():
    change_columns(3.5, 4, sa.Integer())
    change_runs(3.5, 4)
    # Historical revisions and newly edited documents are deliberately retained.
