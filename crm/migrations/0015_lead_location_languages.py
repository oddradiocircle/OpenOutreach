from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0014_campaignlead"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="location",
            field=models.CharField(blank=True, default="", max_length=300),
        ),
        migrations.AddField(
            model_name="lead",
            name="country_code",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
        migrations.AddField(
            model_name="lead",
            name="languages",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
