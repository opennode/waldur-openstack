from rest_framework import status, test

from nodeconductor.structure.models import CustomerRole
from nodeconductor.structure.tests import factories as structure_factories

from ..apps import OpenStackConfig
from . import factories


class InstanceProvisionTest(test.APITransactionTestCase):
    def setUp(self):
        self.customer = structure_factories.CustomerFactory()

        self.settings = structure_factories.ServiceSettingsFactory(
            customer=self.customer, type=OpenStackConfig.service_name)
        self.service = factories.OpenStackServiceFactory(customer=self.customer, settings=self.settings)

        self.image = factories.ImageFactory(settings=self.settings, min_disk=10240, min_ram=1024)
        self.flavor = factories.FlavorFactory(settings=self.settings)

        self.project = structure_factories.ProjectFactory(customer=self.customer)
        self.link = factories.OpenStackServiceProjectLinkFactory(service=self.service, project=self.project)
        self.tenant = factories.TenantFactory(service_project_link=self.link)

        self.customer_owner = structure_factories.UserFactory()
        self.customer.add_user(self.customer_owner, CustomerRole.OWNER)

        self.client.force_authenticate(user=self.customer_owner)
        self.url = factories.InstanceFactory.get_list_url()

    def test_user_can_provision_instance_with_internal_ip_only(self):
        self.tenant.external_network_id = ''
        self.tenant.save()

        response = self.client.post(self.url, self.get_valid_data(
            skip_external_ip_assignment=True
        ))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_user_can_provision_instance_with_automatic_external_ip(self):
        response = self.client.post(self.url, self.get_valid_data(
            skip_external_ip_assignment=False
        ))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_user_can_provision_instance_with_manual_external_ip(self):
        floating_ip = factories.FloatingIPFactory(
            service_project_link=self.link, tenant=self.tenant, status='DOWN')
        response = self.client.post(self.url, self.get_valid_data(
            floating_ip=factories.FloatingIPFactory.get_url(floating_ip),
            skip_external_ip_assignment=True
        ))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def get_valid_data(self, **extra):
        default = {
            'service_project_link': factories.OpenStackServiceProjectLinkFactory.get_url(self.link),
            'tenant': factories.TenantFactory.get_url(self.tenant),
            'flavor': factories.FlavorFactory.get_url(self.flavor),
            'image': factories.ImageFactory.get_url(self.image),
            'name': 'Valid name',
            'system_volume_size': self.image.min_disk
        }
        default.update(extra)
        return default
