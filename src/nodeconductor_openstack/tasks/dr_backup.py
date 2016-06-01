from nodeconductor.core import tasks, utils

from . import models


class CreateTemporarySnapshotTask(tasks.Task):

    def execute(self, volume, serialized_dr_backup):
        dr_backup = utils.deserialize_instance(serialized_dr_backup)
        dr_backup.instance_volumes.add(volume)  # XXX: hack to store imported instance volumes.
        snapshot = models.Snapshot.objects.create(
            source_volume=volume,
            tenant=volume.tenant,
            service_project_link=volume.service_project_link,
            size=volume.size,
            name='Temporary snapshot for volume: %s' % volume.name,
            description='Part of DR backup %s' % dr_backup.name,
            metadata={'source_volume_name': volume.name, 'source_volume_description': volume.description},
        )
        dr_backup.temporary_snapshots.add(snapshot)
        return snapshot


class CreateTemporaryVolumeTask(tasks.Task):

    def execute(self, snapshot, serialized_dr_backup):
        dr_backup = utils.deserialize_instance(serialized_dr_backup)
        source_volume_name = snapshot.metadata['source_volume_name']
        volume = models.Volume.objects.create(
            service_project_link=snapshot.service_project_link,
            tenant=snapshot.tenant,
            source_snapshot=snapshot,
            metadata=snapshot.metadata,
            name='Temporary copy for volume: %s' % source_volume_name,
            description='Part of DR backup %s' % dr_backup.name,
            size=snapshot.size,
        )
        dr_backup.temporary_volumes.add(volume)
        return volume


class CreateVolumeBackupTask(tasks.Task):

    def execute(self, volume, serialized_dr_backup):
        dr_backup = utils.deserialize_instance(serialized_dr_backup)
        source_volume_name = volume.metadata['source_volume_name']
        source_volume_description = volume.metadata['source_volume_description']
        volume_backup = models.VolumeBackup.objects.create(
            name=source_volume_name,
            description=source_volume_description,
            source_volume=volume,
            tenant=volume.tenant,
            size=volume.size,
            service_project_link=volume.service_project_link,
            metadata={
                'source_volume_name': volume.name,
                'source_volume_description': volume.description,
                'source_volume_bootable': volume.bootable,
                'source_volume_size': volume.size,
                'source_volume_metadata': volume.metadata,
                'source_volume_image_metadata': volume.image_metadata,
                'source_volume_type': volume.type,
            }
        )
        dr_backup.volume_backups.add(volume_backup)
        return volume_backup


class SetDRBackupErredTask(tasks.ErrorStateTransitionTask):
    """ Mark DR backup and all related resources that are not in state OK as Erred """

    def execute(self, dr_backup):
        super(SetDRBackupErredTask, self).execute(dr_backup)
        ok_state = models.DRBackup.States.OK
        related_resources = (
            list(dr_backup.temporary_volumes.exclude(state=ok_state)) +
            list(dr_backup.temporary_snapshots.exclude(state=ok_state)) +
            list(dr_backup.volume_backups.exclude(state=ok_state))
        )
        for resource in related_resources:
            resource.set_erred()
            resource.save(update_fields=['state'])
        # Temporary: Unlink imported volumes. Should be removed after NC-1410 implementation.
        for volume in dr_backup.instance_volumes.all():
            volume.delete()


class CleanUpDRBackupTask(tasks.StateTransitionTask):
    """ Mark DR backup as OK and delete related resources.

        Celery is too fragile with groups or chains in callback.
        It is safer to make cleanup in one task.
    """
    def execute(self, dr_backup):
        # Temporary: Unlink imported volumes. Should be removed after NC-1410 implementation.
        for volume in dr_backup.instance_volumes.all():
            volume.delete()

        # import here to avoid circular dependencies
        from ..executors import SnapshotDeleteExecutor, VolumeDeleteExecutor
        for snapshot in dr_backup.temporary_snapshots.all():
            SnapshotDeleteExecutor.execute(snapshot)
        for volume in dr_backup.temporary_volumes.all():
            VolumeDeleteExecutor.execute(volume)
