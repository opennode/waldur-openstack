from nodeconductor.core import tasks as core_tasks, utils as core_utils

from .. import models


class RestoreVolumeBackupTask(core_tasks.Task):

    def execute(self, volume_backup, serialized_volume):
        volume = core_utils.deserialize_instance(serialized_volume)
        backend = volume_backup.get_backend()
        backend.restore_volume_backup(volume_backup, volume)
        return volume


class RestoreVolumeOriginNameTask(core_tasks.Task):

    def execute(self, volume_backup, serialized_volume):
        volume = core_utils.deserialize_instance(serialized_volume)
        backend = volume.get_backend()
        volume.name = volume_backup.name
        volume.description = volume_backup.description
        volume.save()
        backend.update_volume(volume)
        return volume


class DRBackupRestorationException(Exception):
    pass


class CreateInstanceFromVolumesTask(core_tasks.Task):

    def execute(self, dr_backup_restoration):
        instance = dr_backup_restoration.instance
        flavor = dr_backup_restoration.flavor

        backend = instance.get_backend()
        skip_external_ip_assignment = not instance.get_crm()  # XXX: should be moved to itacloud assembly
        backend.create_instance(
            instance,
            backend_flavor_id=flavor.backend_id,
            skip_external_ip_assignment=skip_external_ip_assignment,
        )


class SuccessRestorationTask(core_tasks.StateTransitionTask):

    def execute(self, instance):
        # XXX: This should be moved to itacloud assembly:
        crm = instance.get_crm()
        if crm:
            crm.set_online()
            crm.save()
            from nodeconductor_sugarcrm.tasks import init_crm_api_url, init_crm_quotas
            init_crm_api_url.delay(crm.uuid)
            init_crm_quotas.delay(crm.uuid)


class SetDRBackupRestorationErredTask(core_tasks.ErrorStateTransitionTask):
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
                resource.save(update_fields=['state'])

        # XXX: This should be moved to itacloud assembly:
        crm = instance.get_crm()
        if crm:
            crm.error_message = 'OpenStack Instance restoration failed.'
            crm.set_erred()
            crm.save()
