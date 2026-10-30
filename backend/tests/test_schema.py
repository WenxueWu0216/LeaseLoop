import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_openapi_schema_generates_without_warnings(tmp_path):
    out = tmp_path / "schema.yml"
    call_command("spectacular", "--validate", "--fail-on-warn", "--file", str(out))
    text = out.read_text()
    assert "/api/prospects/" in text and "ProspectStatusEnum" in text
