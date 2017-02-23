# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openstack_tenant', '0017_snapshot_schedule'),
    ]

    operations = [
        migrations.AlterField(
            model_name='floatingip',
            name='is_booked',
            field=models.BooleanField(default=False, help_text='Marks if floating IP has been booked for provisioning.'),
        ),
    ]
