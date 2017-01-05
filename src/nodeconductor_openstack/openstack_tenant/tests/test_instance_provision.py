from rest_framework import status, test

from nodeconductor.structure.models import ServiceSettings

from . import factories, fixtures


class BaseFloatingIpInstanceProvisionTest(test.APITransactionTestCase):
    def setUp(self):
        self.openstack_tenant_fixture = fixtures.OpenStackTenantFixture()
        self.openstack_settings = self.openstack_tenant_fixture.openstack_tenant_service_settings
        self.openstack_spl = self.openstack_tenant_fixture.openstack_tenant_spl
        self.image = factories.ImageFactory(settings=self.openstack_settings, min_disk=10240, min_ram=1024)
        self.flavor = factories.FlavorFactory(settings=self.openstack_settings)

        self.client.force_authenticate(user=self.openstack_tenant_fixture.owner)
        self.url = factories.InstanceFactory.get_list_url()

    def get_valid_data(self, **extra):
        default = {
            'service_project_link': factories.OpenStackTenantServiceProjectLinkFactory.get_url(self.openstack_spl),
            'flavor': factories.FlavorFactory.get_url(self.flavor),
            'image': factories.ImageFactory.get_url(self.image),
            'name': 'Valid name',
            'system_volume_size': self.image.min_disk
        }
        default.update(extra)
        return default


class FixedIpInstanceProvisionTest(BaseFloatingIpInstanceProvisionTest):
    def test_user_can_provision_instance_with_internal_ip_only(self):
        response = self.client.post(self.url, self.get_valid_data())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)


class ManualFloatingIpInstanceProvisionTest(BaseFloatingIpInstanceProvisionTest):
    def test_user_can_provision_instance_with_manual_external_ip(self):
        self.floating_ip = factories.FloatingIPFactory(settings=self.openstack_settings, status='DOWN')
        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_user_can_not_provision_instance_if_external_ip_is_not_available(self):
        self.floating_ip = factories.FloatingIPFactory(settings=self.openstack_settings, status='ACTIVE')

        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['floating_ip'], ['Floating IP status must be DOWN.'])

    def test_user_can_not_provision_instance_if_external_ip_belongs_to_another_service_project_link(self):
        another_settings = factories.OpenStackTenantServiceSettingsFactory()
        self.floating_ip = factories.FloatingIPFactory(settings=another_settings, status='DOWN')

        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['floating_ip'], ['Floating IP must belong to the same service settings.'])

    def get_response(self):
        return self.client.post(self.url, self.get_valid_data(
            floating_ip=factories.FloatingIPFactory.get_url(self.floating_ip),
        ))


class AutomaticFloatingIpInstanceProvisionTest(BaseFloatingIpInstanceProvisionTest):

    def test_user_can_provision_instance_with_automatic_external_ip(self):
        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_user_can_not_provision_instance_if_tenant_quota_exceeded(self):
        quota = self.openstack_settings.quotas.get(name='floating_ip_count')
        quota.limit = quota.usage
        quota.save()

        response = self.client.post(self.url, self.get_valid_data(
            allocate_floating_ip=True
        ))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['allocate_floating_ip'],
                         ['Can not allocate floating IP - quota has been filled.'])

    def get_response(self):
        return self.client.post(self.url, self.get_valid_data())
