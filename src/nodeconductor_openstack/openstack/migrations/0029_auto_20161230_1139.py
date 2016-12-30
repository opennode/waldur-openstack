# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0028_subnet'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='subnet',
            unique_together=set([('network', 'cidr')]),
        ),
    ]
