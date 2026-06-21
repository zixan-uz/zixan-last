from django.db import migrations, models


def seed_genesis(apps, schema_editor):
    AuditChainHead = apps.get_model("audit", "AuditChainHead")
    db = schema_editor.connection.alias
    AuditChainHead.objects.using(db).get_or_create(
        id=1, defaults={"last_sequence": 0, "last_hash": None}
    )


def unseed_genesis(apps, schema_editor):
    AuditChainHead = apps.get_model("audit", "AuditChainHead")
    db = schema_editor.connection.alias
    AuditChainHead.objects.using(db).filter(id=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditChainHead",
            fields=[
                ("id", models.SmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("last_sequence", models.BigIntegerField()),
                ("last_hash", models.CharField(blank=True, max_length=64, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [models.CheckConstraint(condition=models.Q(("id", 1)), name="audit_chain_head_singleton")],
            },
        ),
        migrations.RunPython(seed_genesis, unseed_genesis),
    ]
