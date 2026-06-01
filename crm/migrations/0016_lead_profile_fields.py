from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0015_lead_location_languages"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="full_name",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="lead",
            name="first_name",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="lead",
            name="headline",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="lead",
            name="industry",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="lead",
            name="current_company",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="lead",
            name="current_title",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
    ]
