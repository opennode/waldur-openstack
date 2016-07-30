# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0017_backup_snapshots_and_restorations'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='instancesecuritygroup',
            name='instance',
        ),
        migrations.RemoveField(
            model_name='instancesecuritygroup',
            name='security_group',
        ),
        migrations.AddField(
            model_name='instance',
            name='security_groups',
            field=models.ManyToManyField(related_name='instances', to='openstack.SecurityGroup'),
        ),
        migrations.DeleteModel(
            name='InstanceSecurityGroup',
        ),
    ]
