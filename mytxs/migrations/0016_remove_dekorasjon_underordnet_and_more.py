# Generated by Django 4.2 on 2024-07-02 13:27

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mytxs', '0015_dekorasjon_ikon'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='dekorasjon',
            name='underordnet',
        ),
        migrations.AddField(
            model_name='dekorasjon',
            name='erUnderordnet',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='erOverordnet', to='mytxs.dekorasjon'),
        ),
    ]
