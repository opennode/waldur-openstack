# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0029_auto_20161230_1139'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='subnet',
            unique_together=set([]),
        ),
    ]
