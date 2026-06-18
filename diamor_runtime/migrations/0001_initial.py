from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DiamorStaffIdentityMap",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("django_user_id", models.IntegerField(db_index=True, unique=True)),
                ("staff_party_id", models.BigIntegerField()),
                ("app_role", models.CharField(default="manager", max_length=64)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "diamor_staff_identity_map",
            },
        ),
    ]
