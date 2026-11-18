# Trigram indexes for prospect search (?q=). See docs/perf.md section 7.
#
# The indexes are created with RunSQL because Django renders an OpClass over an expression
# as ((UPPER("col") gin_trgm_ops)), which Postgres rejects as a syntax error. The
# state_operations keep Django's model state in sync with Prospect.Meta.indexes.

from django.contrib.postgres.indexes import GinIndex, OpClass
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations
from django.db.models.functions import Upper

COLUMNS = ["first_name", "last_name", "email", "phone"]


def trgm_index(column):
    name = f"prospect_{column}_trgm"
    return migrations.RunSQL(
        sql=f'CREATE INDEX "{name}" ON "crm_prospect" USING gin (UPPER("{column}") gin_trgm_ops)',
        reverse_sql=f'DROP INDEX IF EXISTS "{name}"',
        state_operations=[
            migrations.AddIndex(
                model_name="prospect",
                index=GinIndex(OpClass(Upper(column), name="gin_trgm_ops"), name=name),
            )
        ],
    )


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0004_prospect_list_order_index"),
    ]

    operations = [TrigramExtension(), *[trgm_index(column) for column in COLUMNS]]
