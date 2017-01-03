import logging

from django.utils import six

from nodeconductor.structure import ServiceBackendError, tasks as structure_tasks

from nodeconductor_openstack.openstack import models


logger = logging.getLogger(__name__)


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
