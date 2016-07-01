import logging

from celery import shared_task, chain
from django.utils import six, timezone

from nodeconductor.core import tasks as core_tasks, utils as core_utils
from nodeconductor.structure import ServiceBackendError

from . import models


logger = logging.getLogger(__name__)


@shared_task(name='nodeconductor.openstack.pull_tenants')
def pull_tenants():
    # Cannot pull tenants without backend_id
    for tenant in models.Tenant.objects.filter(state=models.Tenant.States.ERRED).exclude(backend_id=''):
        serialized_tenant = core_utils.serialize_instance(tenant)
        core_tasks.BackendMethodTask().apply_async(
            args=(serialized_tenant, 'pull_tenant'),
            link=recover_tenant.si(serialized_tenant),
            link_error=core_tasks.ErrorMessageTask().s(serialized_tenant),
        )
    for tenant in models.Tenant.objects.filter(state=models.Tenant.States.OK):
        serialized_tenant = core_utils.serialize_instance(tenant)
        core_tasks.BackendMethodTask().apply_async(
            args=(serialized_tenant, 'pull_tenant'),
            link_error=core_tasks.ErrorStateTransitionTask().s(serialized_tenant),
        )


@shared_task
def recover_tenant(serialized_tenant):
    chain(
        core_tasks.RecoverTask().si(serialized_tenant),
        core_tasks.BackendMethodTask().si(serialized_tenant, 'pull_tenant_security_groups'),
        core_tasks.BackendMethodTask().si(serialized_tenant, 'pull_tenant_floating_ips'),
        core_tasks.BackendMethodTask().si(serialized_tenant, 'pull_tenant_quotas'),
    ).delay()


@shared_task(name='nodeconductor.openstack.pull_tenants_properties')
def pull_tenants_properties():
    for tenant in models.Tenant.objects.filter(state=models.Tenant.States.OK):
        serialized_tenant = core_utils.serialize_instance(tenant)
        core_tasks.BackendMethodTask().delay(serialized_tenant, 'pull_tenant_security_groups')
        core_tasks.BackendMethodTask().delay(serialized_tenant, 'pull_tenant_floating_ips')
        core_tasks.BackendMethodTask().delay(serialized_tenant, 'pull_tenant_quotas')


@shared_task(name='nodeconductor.openstack.pull_instances')
def pull_instances():
    for tenant in models.Tenant.objects.exclude(state=models.Tenant.States.ERRED):
        # group instance update by tenant to reduce amount of logins and update
        # all instance with one session.
        # Ideally session should be cached in backend module.
        pull_tenant_instances.delay(core_utils.serialize_instance(tenant))


@shared_task
def pull_tenant_instances(serialized_tenant):
    tenant = core_utils.deserialize_instance(serialized_tenant)
    backend = tenant.get_backend()
    States = models.Instance.States
    stable_states = [States.ONLINE, States.OFFLINE, States.ERRED]
    for instance in tenant.instances.filter(state__in=stable_states).exclude(backend_id=''):
        try:
            backend.pull_instance(instance)
        except ServiceBackendError as e:
            message = six.text_type(e)
            logger.error('Failed to pull instance %s (PK: %s). Error: %s' % (instance.name, instance.pk, message))
            instance.set_erred()
            instance.error_message = message
            instance.save(update_fields=['state', 'error_message'])
        else:
            if instance.state != States.ERRED and instance.error_message:
                # for instance state should be updated during pull
                instance.error_message = ''
                instance.save(update_fields=['error_message'])


@shared_task(name='nodeconductor.openstack.pull_volumes')
def pull_volumes():
    for tenant in models.Tenant.objects.exclude(state=models.Tenant.States.ERRED):
        # group volumes update by tenant to reduce amount of logins and update
        # all volumes with one session.
        # Ideally session should be cached in backend module.
        pull_tenant_volumes.delay(core_utils.serialize_instance(tenant))


@shared_task
def pull_tenant_volumes(serialized_tenant):
    tenant = core_utils.deserialize_instance(serialized_tenant)
    backend = tenant.get_backend()
    States = models.Volume.States
    for volume in tenant.volumes.filter(state__in=[States.OK, States.ERRED]).exclude(backend_id=''):
        try:
            backend.pull_volume(volume)
        except ServiceBackendError as e:
            message = six.text_type(e)
            logger.error('Failed to pull volume %s (PK: %s). Error: %s' % (volume.name, volume.pk, message))
            volume.set_erred()
            volume.error_message = message
            volume.save(update_fields=['state', 'error_message'])
        else:
            if volume.state == States.ERRED:
                volume.recover()
                volume.error_message = ''
                volume.save(update_fields=['state', 'error_message'])


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
