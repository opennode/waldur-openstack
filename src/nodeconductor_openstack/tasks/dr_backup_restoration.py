from nodeconductor.core import tasks, utils

from .. import models


class RestoreVolumeBackupTask(tasks.Task):

    def execute(self, volume_backup, serialized_volume):
        volume = utils.deserialize_instance(serialized_volume)
        backend = volume_backup.get_backend()
        backend.restore_volume_backup(volume_backup, volume)
        return volume


class RestoreVolumeOriginNameTask(tasks.Task):

    def execute(self, volume_backup, serialized_volume):
        volume = utils.deserialize_instance(serialized_volume)
        backend = volume_backup.get_backend()
        volume.name = volume_backup.name
        volume.description = volume_backup.description
        volume.save()
        backend.update_volume(volume)
        return volume


class DRBackupRestorationException(Exception):
    pass


class CreateInstanceFromVolumesTask(tasks.Task):

    def execute(self, dr_backup_restoration):
        instance = dr_backup_restoration.instance
        volumes = [restoration.volume for restoration in dr_backup_restoration.volume_backup_restorations.all()]
        flavor = dr_backup_restoration.flavor

        if len(volumes) > 2:
            raise DRBackupRestorationException(
                'Current instance creation process does not support more instances with more than 2 volumes.')
        try:
            system_volume_id = next(volume.backend_id for volume in volumes if volume.bootable)
        except StopIteration:
            raise DRBackupRestorationException('Cannot restore instance without system volume.')
        try:
            data_volume_id = next(volume.backend_id for volume in volumes if not volume.bootable)
        except StopIteration:
            raise DRBackupRestorationException('Cannot restore instance without data volume.')

        backend = instance.get_backend()
        backend.provision_instance(
            instance,
            backend_flavor_id=flavor.backend_id,
            data_volume_id=data_volume_id,
            system_volume_id=system_volume_id,
            skip_external_ip_assignment=True,
        )


class SetDRBackupRestorationErredTask(tasks.ErrorStateTransitionTask):
    """ Mark DR backup restoration instance as erred and delete resources that were not created. """

    def execute(self, dr_backup_restoration):
        instance = dr_backup_restoration.instance
        super(SetDRBackupRestorationErredTask, self).execute(instance)

        ok_state = models.DRBackup.States.OK
        creation_scheduled_state = models.DRBackup.States.CREATION_SCHEDULED

        related_resources = []
        for volume_backup_restoration in dr_backup_restoration.volume_backup_restorations.all():
            related_resources.append(volume_backup_restoration.volume)
            related_resources.append(volume_backup_restoration.mirrored_volume_backup)

        # delete resources if they were not created on backend,
        # mark as erred if creation was started, but not ended,
        # leave as is, if they are OK.
        for resource in related_resources:
            if resource.state == creation_scheduled_state:
                resource.delete()
            elif resource.state == ok_state:
                pass
            else:
                resource.set_erred()
