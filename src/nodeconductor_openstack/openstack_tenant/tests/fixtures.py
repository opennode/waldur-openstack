from django.utils.functional import cached_property

from nodeconductor_openstack.openstack.tests import fixtures as openstack_fixtures

from . import factories
from .. import models


class OpenStackTenantFixture(openstack_fixtures.OpenStackFixture):

    @cached_property
    def openstack_tenant_service_settings(self):
        return factories.OpenStackTenantServiceSettingsFactory(
            name=self.tenant.name,
            scope=self.tenant,
            customer=self.customer,
            backend_url=self.openstack_service_settings.backend_url,
            username=self.tenant.user_username,
            password=self.tenant.user_password,
            options={
                'availability_zone': self.tenant.availability_zone,
                'tenant_id': self.tenant.backend_id,
            },
        )

    @cached_property
    def openstack_tenant_service(self):
        return factories.OpenStackTenantServiceFactory(
            name=self.tenant.name,
            customer=self.customer,
            settings=self.openstack_tenant_service_settings
        )

    @cached_property
    def openstack_tenant_spl(self):
        return factories.OpenStackTenantServiceProjectLinkFactory(
            project=self.project, service=self.openstack_tenant_service)

    @cached_property
    def openstack_volume(self):
        return factories.VolumeFactory(
            service_project_link=self.openstack_tenant_spl,
            state=models.Volume.States.OK,
            runtime_state=models.Volume.RuntimeStates.OFFLINE,
        )

    @cached_property
    def openstack_instance(self):
        return factories.InstanceFactory(
            service_project_link=self.openstack_tenant_spl,
            state=models.Instance.States.OK,
            runtime_state=models.Instance.RuntimeStates.SHUTOFF,
        )

    @cached_property
    def openstack_snapshot(self):
        return factories.SnapshotFactory(
            service_project_link=self.openstack_tenant_spl,
            state=models.Volume.States.OK,
            runtime_state=models.Volume.RuntimeStates.OFFLINE,
        )
