# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openstack_tenant', '0015_snapshotrestoration'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='openstacktenantservice',
            name='name',
        ),
    ]
