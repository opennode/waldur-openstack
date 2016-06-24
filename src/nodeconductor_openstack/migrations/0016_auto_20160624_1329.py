# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


def init_backup_snapshots(apps, schema_editor):
    Backup = apps.get_model('openstack', 'Backup')
    Snapshot = apps.get_model('openstack', 'Snapshot')
    for backup in Backup.objects.all():
        if backup.metadata.get('system_snapshot_id'):
            Snapshot.objects.create(
                size=backup.metadata.get('system_snapshot_size', 0),
                backend_id=backup.metadata.get('system_snapshot_id'),
                tenant=backup.tenant,
                service_project_link=backup.service_project_link,
                name='Backup %s snapshot' % backup.uuid.hex,
                state=3,  # OK state
            )
        if backup.metadata.get('data_snapshot_id'):
            Snapshot.objects.create(
                size=backup.metadata.get('data_snapshot_size', 0),
                backend_id=backup.metadata.get('data_snapshot_id'),
                tenant=backup.tenant,
                service_project_link=backup.service_project_link,
                name='Backup %s snapshot' % backup.uuid.hex,
                state=3,  # OK state
            )


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0015_auto_20160624_1243'),
    ]

    operations = [
        migrations.AddField(
            model_name='backup',
            name='snapshots',
            field=models.ManyToManyField(related_name='backups', to='openstack.Snapshot'),
        ),
        migrations.AlterField(
            model_name='backup',
            name='tenant',
            field=models.ForeignKey(related_name='backups', to='openstack.Tenant'),
        ),
        migrations.RunPython(init_backup_snapshots),
    ]
