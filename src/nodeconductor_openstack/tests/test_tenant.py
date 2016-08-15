from mock import patch

from rest_framework import test, status
from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.models import Tenant, OpenStackService
from nodeconductor_openstack.views import TenantViewSet

from . import factories


class TenantCreateTest(test.APISimpleTestCase):
    def setUp(self):
        super(TenantCreateTest, self).setUp()
        staff = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=staff)

    def test_can_create_tenant_for_admin_service(self):
        response = self.create_tenant(factories.OpenStackServiceProjectLinkFactory())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_unable_create_tenant_for_non_admin_service(self):
        link = factories.OpenStackServiceProjectLinkFactory()
        settings = link.service.settings
        settings.options['is_admin'] = False
        settings.save()

        response = self.create_tenant(link)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['non_field_errors'],
                         'Tenant provisioning is only possible for admin service.')

    @patch('nodeconductor.structure.models.ServiceSettings.get_backend')
    def test_can_create_tenant_and_non_admin_service(self, mocked_backend):
        link = factories.OpenStackServiceProjectLinkFactory()
        customer = link.project.customer
        settings = link.service.settings
        settings.backend_url = 'http://example.com'
        settings.save()

        TenantViewSet.async_executor = False
        response = self.client.post(factories.TenantFactory.get_list_url(), {
            'name': 'Valid tenant name',
            'service_project_link': factories.OpenStackServiceProjectLinkFactory.get_url(link),
            'configure_as_service': True
        })
        TenantViewSet.async_executor = True

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tenant = Tenant.objects.get(uuid=response.data['uuid'])
        self.assertTrue(OpenStackService.objects.filter(
            customer=customer,
            settings__backend_url=settings.backend_url,
            settings__username=tenant.user_username,
            settings__password=tenant.user_password
        ).exists())

    def create_tenant(self, link):
        return self.client.post(factories.TenantFactory.get_list_url(), {
            'name': 'Valid tenant name',
            'service_project_link': factories.OpenStackServiceProjectLinkFactory.get_url(link)
        })


class BaseTenantActionsTest(test.APISimpleTestCase):

    def setUp(self):
        self.tenant = factories.TenantFactory()
        staff = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=staff)


@patch('nodeconductor_openstack.executors.TenantPushQuotasExecutor.execute')
class TenantQuotasTest(BaseTenantActionsTest):
    def test_non_staff_user_cannot_set_tenant_quotas(self, mocked_task):
        self.client.force_authenticate(user=structure_factories.UserFactory())
        response = self.client.post(self.get_url())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(mocked_task.called)

    def test_staff_can_set_tenant_quotas(self, mocked_task):
        quotas_data = {'security_group_count': 100, 'security_group_rule_count': 100}
        response = self.client.post(self.get_url(), data=quotas_data)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant, quotas=quotas_data)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant, 'set_quotas')


@patch('nodeconductor_openstack.executors.TenantDeleteExternalNetworkExecutor.execute')
class TenantDeleteExternalNetworkTest(BaseTenantActionsTest):
    def test_staff_user_can_delete_existing_external_network(self, mocked_task):
        self.tenant.external_network_id = 'abcd1234'
        self.tenant.save()

        response = self.client.delete(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant)

    def test_staff_user_cannot_delete_not_existing_external_network(self, mocked_task):
        self.tenant.external_network_id = ''
        self.tenant.save()

        response = self.client.delete(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(mocked_task.called)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant, 'external_network')


@patch('nodeconductor_openstack.executors.TenantCreateExternalNetworkExecutor.execute')
class TenantCreateExternalNetworkTest(BaseTenantActionsTest):

    def test_staff_user_can_create_external_network(self, mocked_task):
        payload = {
            'vlan_id': '2007',
            'network_ip': '10.7.122.0',
            'network_prefix': 26,
            'ips_count': 6
        }

        url = factories.TenantFactory.get_url(self.tenant, 'external_network')
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant, external_network_data=payload)


@patch('nodeconductor_openstack.executors.TenantAllocateFloatingIPExecutor.execute')
class TenantFloatingIPTest(BaseTenantActionsTest):
    def test_staff_cannot_allocate_floating_ip_from_tenant_without_external_network_id(self, mocked_task):
        self.tenant.external_network_id = ''
        self.tenant.save()

        response = self.client.post(factories.TenantFactory.get_url(self.tenant, 'allocate_floating_ip'))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], 'Tenant should have an external network ID.')
        self.assertFalse(mocked_task.called)

    def test_staff_cannot_allocate_floating_ip_from_tenant_in_unstable_state(self, mocked_task):
        tenant = factories.TenantFactory(external_network_id='12345', state=Tenant.States.ERRED)
        url = factories.TenantFactory.get_url(tenant, 'allocate_floating_ip')

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], 'Tenant should be in state OK.')
        self.assertFalse(mocked_task.delay.called)

    def test_staff_can_allocate_floating_ip_from_tenant_with_external_network_id(self, mocked_task):
        tenant = factories.TenantFactory(external_network_id='12345')
        url = factories.TenantFactory.get_url(tenant, 'allocate_floating_ip')

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['detail'], 'Floating IP allocation has been scheduled.')

        mocked_task.assert_called_once_with(tenant)


@patch('nodeconductor_openstack.executors.TenantPullExecutor.execute')
class TenantPullTest(BaseTenantActionsTest):
    def test_staff_can_pull_tenant(self, mocked_task):
        response = self.client.post(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant)

    def test_staff_can_not_pull_tenant_from_non_admin_service(self, mocked_task):
        settings = self.tenant.service_project_link.service.settings
        settings.options['is_admin'] = False
        settings.save()

        response = self.client.post(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(mocked_task.called)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant, 'pull')


@patch('nodeconductor_openstack.executors.TenantDeleteExecutor.execute')
class TenantDeleteTest(BaseTenantActionsTest):
    def test_staff_can_delete_tenant(self, mocked_task):
        response = self.client.delete(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant, async=True, force=False)

    def test_staff_can_not_delete_tenant_from_non_admin_service(self, mocked_task):
        settings = self.tenant.service_project_link.service.settings
        settings.options['is_admin'] = False
        settings.save()

        response = self.client.delete(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(mocked_task.called)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant)
