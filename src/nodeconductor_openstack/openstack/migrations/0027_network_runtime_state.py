# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0026_auto_20161228_1540'),
    ]

    operations = [
        migrations.AddField(
            model_name='network',
            name='runtime_state',
            field=models.CharField(max_length=150, verbose_name='runtime state', blank=True),
        ),
    ]
