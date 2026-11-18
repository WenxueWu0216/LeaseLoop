# Trigram indexes for prospect search (?q=). See docs/perf.md section 7.

from django.contrib.postgres.indexes import GinIndex, OpClass
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations
from django.db.models.functions import Upper


def trgm_index(column):
    return migrations.AddIndex(
        model_name="prospect",
        index=GinIndex(
            OpClass(Upper(column), name="gin_trgm_ops"), name=f"prospect_{column}_trgm"
        ),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0004_prospect_list_order_index"),
    ]

    operations = [
        TrigramExtension(),
        trgm_index("first_name"),
        trgm_index("last_name"),
        trgm_index("email"),
        trgm_index("phone"),
    ]
