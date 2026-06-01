from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0012_deal_regeneration_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="deal",
            name="pending_message_created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
