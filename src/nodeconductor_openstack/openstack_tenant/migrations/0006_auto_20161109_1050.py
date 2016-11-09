# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openstack_tenant', '0005_auto_20161108_1510'),
    ]

    operations = [
        migrations.AddField(
            model_name='instance',
            name='action',
            field=models.CharField(max_length=50, blank=True),
        ),
        migrations.AddField(
            model_name='instance',
            name='action_details',
            field=models.TextField(blank=True),
        ),
    ]
