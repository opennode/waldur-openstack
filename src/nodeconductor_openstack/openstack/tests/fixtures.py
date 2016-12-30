from django.utils.functional import cached_property

from nodeconductor.structure.tests.fixtures import ProjectFixture

from . import factories


class OpenStackFixture(ProjectFixture):
    @cached_property
    def openstack_service_settings(self):
        return factories.OpenStackServiceSettingsFactory(customer=self.customer)

    @cached_property
    def openstack_service(self):
        return factories.OpenStackServiceFactory(
            customer=self.customer, settings=self.openstack_service_settings)

    @cached_property
    def openstack_spl(self):
        return factories.OpenStackServiceProjectLinkFactory(
            project=self.project, service=self.openstack_service)

    @cached_property
    def openstack_tenant(self):
        return factories.TenantFactory(service_project_link=self.openstack_spl)
