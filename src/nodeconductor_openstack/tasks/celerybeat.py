import logging

from celery import shared_task, chain

from nodeconductor.core import tasks as core_tasks, utils as core_utils
from nodeconductor.structure import ServiceBackendError

from . import models


logger = logging.getLogger(__name__)


@shared_task(name='nodeconductor.openstack.pull_tenants')
def pull_tenants():
    for tenant in models.Tenant.objects.filter(state=models.Tenant.States.ERRED):
        serialized_tenant = core_utils.serialize_instance(tenant)
        core_tasks.BackendMethodTask().apply_async(
            args=(serialized_tenant, 'pull_tenant'),
            link=recover_tenant.si(serialized_tenant),
            link_error=core_tasks.ErrorMessageTask().s(serialized_tenant),
        )
    for tenant in models.Tenant.objects.filter(state=models.Tenant.States.OK):
        serialized_tenant = core_utils.serialize_instance(tenant)
        core_tasks.BackendMethodTask().delay(serialized_tenant, 'pull_tenant')


@shared_task
def recover_tenant(serialized_tenant):
    chain(
        core_tasks.StateTransitionTask().si(serialized_tenant, state_transition='recover'),
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
        except ServiceBackendError:
            logger.error('Failed to pull instance %s (PK: %s).' % (instance.name, instance.pk))


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
        except ServiceBackendError:
            logger.error('Failed to pull volume %s (PK: %s).' % (volume.name, volume.pk))
