# Generated by Django 4.2 on 2024-06-29 13:07

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mytxs', '0013_alter_medlem_sjekkheftesynlig'),
    ]

    operations = [
        migrations.AddField(
            model_name='dekorasjon',
            name='underordnet',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='mytxs.dekorasjon'),
        ),
    ]
