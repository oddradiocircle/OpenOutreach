from django.db import migrations, models


class Migration(migrations.Migration):
    """Make snapshot/enrichment columns nullable so stale-process INSERTs don't crash.

    AddField with NOT NULL and no stored DB default (SQLite behaviour) means any
    INSERT from code that predates the column raises IntegrityError.  Making the
    columns nullable forces a table rebuild on SQLite, resulting in columns that
    accept NULL — old code omitting the field won't crash.  New code always writes
    "" / [] so stored NULLs won't appear in practice.
    """

    dependencies = [
        ("crm", "0016_lead_profile_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="full_name",
            field=models.CharField(blank=True, default="", max_length=200, null=True),
        ),
        migrations.AlterField(
            model_name="lead",
            name="first_name",
            field=models.CharField(blank=True, default="", max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name="lead",
            name="headline",
            field=models.CharField(blank=True, default="", max_length=500, null=True),
        ),
        migrations.AlterField(
            model_name="lead",
            name="industry",
            field=models.CharField(blank=True, default="", max_length=200, null=True),
        ),
        migrations.AlterField(
            model_name="lead",
            name="current_company",
            field=models.CharField(blank=True, default="", max_length=200, null=True),
        ),
        migrations.AlterField(
            model_name="lead",
            name="current_title",
            field=models.CharField(blank=True, default="", max_length=200, null=True),
        ),
        migrations.AlterField(
            model_name="lead",
            name="location",
            field=models.CharField(blank=True, default="", max_length=300, null=True),
        ),
        migrations.AlterField(
            model_name="lead",
            name="country_code",
            field=models.CharField(blank=True, default="", max_length=10, null=True),
        ),
        migrations.AlterField(
            model_name="lead",
            name="languages",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
