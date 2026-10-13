from django.db import migrations

from core.rls import proteggi

IMMUTABILE = """
CREATE FUNCTION audit_immutabile() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Il registro di audit non si modifica e non si cancella';
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_immutabile
    BEFORE UPDATE OR DELETE ON audit_eventoaudit
    FOR EACH ROW EXECUTE FUNCTION audit_immutabile();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        proteggi("audit_eventoaudit"),
        migrations.RunSQL(
            IMMUTABILE,
            reverse_sql="DROP TRIGGER audit_immutabile ON audit_eventoaudit; DROP FUNCTION audit_immutabile();",
        ),
    ]
