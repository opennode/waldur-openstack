import logging

from celery import shared_task
from datetime import timedelta
from django.utils import six, timezone

from nodeconductor.core import utils as core_utils
from nodeconductor.structure import ServiceBackendError, models as structure_models, tasks as structure_tasks

from . import models


logger = logging.getLogger(__name__)


class VolumeBackgroundPullTask(structure_tasks.BackgroundPullTask):

    def pull(self, volume):
        backend = volume.get_backend()
        backend.pull_volume(volume)


class InstanceBackgroundPullTask(structure_tasks.BackgroundPullTask):
    model = models.Instance

    def pull(self, instance):
        backend = instance.get_backend()
        backend.pull_instance(instance)

    def on_pull_success(self, instance):
        # Override method for instance because its pull operation updates state too.
        # Should be rewritten in NC-1207. Pull operation should update only
        # runtime state.
        if instance.state != self.model.States.ERRED and instance.error_message:
            # instance state should be updated during pull
            instance.error_message = ''
            instance.save(update_fields=['error_message'])
        backend = instance.get_backend()
        try:
            backend.pull_instance_security_groups(instance)
        except ServiceBackendError as e:
            error_message = six.text_type(e)
            logger.warning('Failed to pull instance security groups: %s (PK: %s). Error: %s' % (
                instance, instance.pk, error_message))


class TenantBackgroundPullTask(structure_tasks.BackgroundPullTask):

    def pull(self, tenant):
        backend = tenant.get_backend()
        backend.pull_tenant(tenant)

    def on_pull_success(self, tenant):
        super(TenantBackgroundPullTask, self).on_pull_success(tenant)
        try:
            backend = tenant.get_backend()
            backend.pull_tenant_security_groups(tenant)
            backend.pull_tenant_floating_ips(tenant)
            backend.pull_tenant_quotas(tenant)
        except ServiceBackendError as e:
            error_message = six.text_type(e)
            logger.warning('Failed to pull properties of tenant: %s (PK: %s). Error: %s' % (
                tenant, tenant.pk, error_message))


class TenantListPullTask(structure_tasks.BackgroundListPullTask):
    name = 'openstack.TenantListPullTask'
    model = models.Tenant
    pull_task = TenantBackgroundPullTask


class InstanceListPullTask(structure_tasks.BackgroundListPullTask):
    name = 'openstack.InstanceListPullTask'
    model = models.Instance
    pull_task = InstanceBackgroundPullTask


class VolumeListPullTask(structure_tasks.BackgroundListPullTask):
    name = 'openstack.VolumeListPullTask'
    model = models.Volume
    pull_task = VolumeBackgroundPullTask


@shared_task(name='openstack.schedule_backups')
def schedule_backups():
    for schedule in models.BackupSchedule.objects.filter(is_active=True, next_trigger_at__lt=timezone.now()):
        backend = schedule.get_backend()
        backend.execute()


@shared_task(name='openstack.delete_expired_backups')
def delete_expired_backups():
    from .. import executors  # import here to avoid circular imports
    for backup in models.Backup.objects.filter(kept_until__lt=timezone.now(), state=models.Backup.States.OK):
        executors.BackupDeleteExecutor.execute(backup)
    for dr_backup in models.DRBackup.objects.filter(kept_until__lt=timezone.now(), state=models.DRBackup.States.OK):
        executors.DRBackupDeleteExecutor.execute(dr_backup)


@shared_task(name='openstack.set_erred_stuck_resources')
def set_erred_stuck_resources():
    for model in (models.Instance, models.Volume, models.Snapshot):
        cutoff = timezone.now() - timedelta(minutes=30)
        for resource in model.objects.filter(modified__lt=cutoff, state=structure_models.NewResource.States.CREATING):
            resource.set_erred()
            resource.error_message = 'Provisioning is timed out.'
            resource.save(update_fields=['state', 'error_message'])
            logger.warning('Switching resource %s to erred state, '
                           'because provisioning is timed out.',
                           core_utils.serialize_instance(resource))
