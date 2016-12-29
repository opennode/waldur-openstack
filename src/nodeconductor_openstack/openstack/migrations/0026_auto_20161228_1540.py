# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0025_auto_20161228_1539'),
    ]

    operations = [
        migrations.AlterField(
            model_name='network',
            name='service_project_link',
            field=models.ForeignKey(related_name='networks', on_delete=django.db.models.deletion.PROTECT, to='openstack.OpenStackServiceProjectLink'),
        ),
        migrations.AlterField(
            model_name='network',
            name='tenant',
            field=models.ForeignKey(related_name='networks', to='openstack.Tenant'),
        ),
    ]
