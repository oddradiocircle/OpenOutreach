from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("linkedin", "0009_drop_legacy_pending_tasks"),
    ]

    operations = [
        migrations.RemoveField(model_name="campaign", name="is_freemium"),
        migrations.RemoveField(model_name="campaign", name="action_fraction"),
        migrations.RemoveField(model_name="campaign", name="seed_public_ids"),
        migrations.RemoveField(model_name="linkedinprofile", name="subscribe_newsletter"),
        migrations.RemoveField(model_name="linkedinprofile", name="newsletter_processed"),
    ]
