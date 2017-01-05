# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0026_make_floatingip_resource'),
    ]

    operations = [
        migrations.AlterField(
            model_name='floatingip',
            name='address',
            field=models.GenericIPAddressField(null=True, protocol='IPv4', blank=True),
        ),
    ]
