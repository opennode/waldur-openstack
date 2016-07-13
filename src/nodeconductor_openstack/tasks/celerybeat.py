import logging

from celery import shared_task
from django.utils import six, timezone

from nodeconductor.core import tasks as core_tasks, utils as core_utils
from nodeconductor.structure import ServiceBackendError

from . import models


logger = logging.getLogger(__name__)


class BackgroundPullTask(core_tasks.Task):

    def run(self, serialized_instance):
        instance = core_utils.deserialize_instance(serialized_instance)
        try:
            self.pull(instance)
        except ServiceBackendError as e:
            self.on_pull_fail(instance, e)
        else:
            self.on_pull_success(instance)

    def pull(self, instance):
        """ Pull instance from backend.

            This method should not handle backend exception.
        """
        raise NotImplementedError('Pull task should implement pull method.')

    def on_pull_fail(self, instance, error):
        error_message = six.text_type(error)
        self.log_error_message(instance, error_message)
        self.set_instance_erred(instance, error_message)

    def on_pull_success(self, instance):
        if instance.state == instance.States.ERRED:
            instance.recover()
            instance.error_message = ''
            instance.save(update_fields=['state', 'error_message'])

    def log_error_message(self, instance, error_message):
        logger_message = 'Failed to pull %s %s (PK: %s). Error: %s' % (
            instance.__class__.__name__, instance.name, instance.pk, error_message)
        if instance.state == instance.States.ERRED:  # report error on debug level if instance already was erred.
            logger.debug(logger_message)
        else:
            logger.error(logger_message, exc_info=True)

    def set_instance_erred(self, instance, error_message):
        """ Mark instance as erred and save error message """
        instance.set_erred()
        instance.error_message = error_message
        instance.save(update_fields=['state', 'error_message'])


class VolumeBackgroundPullTask(BackgroundPullTask):

    def pull(self, volume):
        backend = volume.get_backend()
        backend.pull_volume(volume)


class InstanceBackgroundPullTask(BackgroundPullTask):
    model = models.Instance

    def pull(self, instance):
        backend = instance.get_backend()
        backend.pull_instance(instance)

    def on_pull_success(self, instance):
        # Override method for instance because its pull operation updates state too.
        # Should be rewritten in NC-1207. Pull operation should update only
        # runtime state.
        if instance.state != self.model.States.ERRED and instance.error_message:
            # for instance state should be updated during pull
            instance.error_message = ''
            instance.save(update_fields=['error_message'])


class TenantBackgroundPullTask(BackgroundPullTask):

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


@shared_task(name='nodeconductor.openstack.pull_tenants')
def pull_tenants():
    States = models.Tenant.States
    for tenant in models.Tenant.objects.filter(state__in=[States.ERRED, States.OK]).exclude(backend_id=''):
        serialized_tenant = core_utils.serialize_instance(tenant)
        TenantBackgroundPullTask().delay(serialized_tenant)


@shared_task(name='nodeconductor.openstack.pull_instances')
def pull_instances():
    States = models.Instance.States
    for instance in models.Instance.objects.filter(
            state__in=[States.ERRED, States.ONLINE, States.OFFLINE]).exclude(backend_id=''):
        serialized_instance = core_utils.serialize_instance(instance)
        InstanceBackgroundPullTask().delay(serialized_instance)


@shared_task(name='nodeconductor.openstack.pull_volumes')
def pull_volumes():
    States = models.Volume.States
    for volume in models.Volume.objects.filter(state__in=[States.ERRED, States.OK]).exclude(backend_id=''):
        serialized_volume = core_utils.serialize_instance(volume)
        VolumeBackgroundPullTask().delay(serialized_volume)


@shared_task(name='nodeconductor.openstack.schedule_backups')
def schedule_backups():
    for schedule in models.BackupSchedule.objects.filter(is_active=True, next_trigger_at__lt=timezone.now()):
        backend = schedule.get_backend()
        backend.execute()


@shared_task(name='nodeconductor.openstack.delete_expired_backups')
def delete_expired_backups():
    from .. import executors  # import here to avoid circular imports
    for backup in models.Backup.objects.filter(kept_until__lt=timezone.now(), state=models.Backup.States.OK):
        executors.BackupDeleteExecutor.execute(backup)
    for dr_backup in models.DRBackup.objects.filter(kept_until__lt=timezone.now(), state=models.DRBackup.States.OK):
        executors.DRBackupDeleteExecutor.execute(dr_backup)
