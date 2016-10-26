from ddt import data, ddt
from mock import patch

from rest_framework import test, status
from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.openstack.models import Tenant, OpenStackService

from . import factories, fixtures


class BaseTenantActionsTest(test.APISimpleTestCase):

    def setUp(self):
        super(BaseTenantActionsTest, self).setUp()
        self.fixture = fixtures.OpenStackFixture()
        self.tenant = self.fixture.openstack_tenant


@patch('nodeconductor_openstack.openstack.executors.TenantPushQuotasExecutor.execute')
class TenantQuotasTest(BaseTenantActionsTest):
    def test_non_staff_user_cannot_set_tenant_quotas(self, mocked_task):
        self.client.force_authenticate(user=structure_factories.UserFactory())
        response = self.client.post(self.get_url())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(mocked_task.called)

    def test_staff_can_set_tenant_quotas(self, mocked_task):
        self.client.force_authenticate(self.fixture.staff)
        quotas_data = {'security_group_count': 100, 'security_group_rule_count': 100}
        response = self.client.post(self.get_url(), data=quotas_data)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant, quotas=quotas_data)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant, 'set_quotas')


@patch('nodeconductor_openstack.openstack.executors.TenantDeleteExternalNetworkExecutor.execute')
class TenantDeleteExternalNetworkTest(BaseTenantActionsTest):
    def test_staff_user_can_delete_existing_external_network(self, mocked_task):
        self.tenant.external_network_id = 'abcd1234'
        self.tenant.save()

        self.client.force_authenticate(self.fixture.staff)
        response = self.client.delete(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant)

    def test_staff_user_cannot_delete_not_existing_external_network(self, mocked_task):
        self.tenant.external_network_id = ''
        self.tenant.save()

        self.client.force_authenticate(self.fixture.staff)
        response = self.client.delete(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(mocked_task.called)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant, 'external_network')


@patch('nodeconductor_openstack.openstack.executors.TenantCreateExternalNetworkExecutor.execute')
class TenantCreateExternalNetworkTest(BaseTenantActionsTest):

    def test_staff_user_can_create_external_network(self, mocked_task):
        payload = {
            'vlan_id': '2007',
            'network_ip': '10.7.122.0',
            'network_prefix': 26,
            'ips_count': 6
        }

        self.client.force_authenticate(self.fixture.staff)
        url = factories.TenantFactory.get_url(self.tenant, 'external_network')
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant, external_network_data=payload)


@patch('nodeconductor_openstack.openstack.executors.TenantAllocateFloatingIPExecutor.execute')
class TenantFloatingIPTest(BaseTenantActionsTest):
    def test_staff_cannot_allocate_floating_ip_from_tenant_without_external_network_id(self, mocked_task):
        self.tenant.external_network_id = ''
        self.tenant.save()

        self.client.force_authenticate(self.fixture.staff)
        response = self.client.post(factories.TenantFactory.get_url(self.tenant, 'allocate_floating_ip'))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], 'Tenant should have an external network ID.')
        self.assertFalse(mocked_task.called)

    def test_staff_cannot_allocate_floating_ip_from_tenant_in_unstable_state(self, mocked_task):
        tenant = factories.TenantFactory(external_network_id='12345', state=Tenant.States.ERRED)
        url = factories.TenantFactory.get_url(tenant, 'allocate_floating_ip')

        self.client.force_authenticate(self.fixture.staff)
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['detail'], 'Tenant should be in state OK.')
        self.assertFalse(mocked_task.delay.called)

    def test_staff_can_allocate_floating_ip_from_tenant_with_external_network_id(self, mocked_task):
        tenant = factories.TenantFactory(external_network_id='12345')
        url = factories.TenantFactory.get_url(tenant, 'allocate_floating_ip')

        self.client.force_authenticate(self.fixture.staff)
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['detail'], 'Floating IP allocation has been scheduled.')

        mocked_task.assert_called_once_with(tenant)


@patch('nodeconductor_openstack.openstack.executors.TenantPullExecutor.execute')
class TenantPullTest(BaseTenantActionsTest):
    def test_staff_can_pull_tenant(self, mocked_task):
        self.client.force_authenticate(self.fixture.staff)
        response = self.client.post(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant)

    def test_staff_can_not_pull_tenant_from_non_admin_service(self, mocked_task):
        settings = self.tenant.service_project_link.service.settings
        settings.options['is_admin'] = False
        settings.save()

        self.client.force_authenticate(self.fixture.staff)
        response = self.client.post(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(mocked_task.called)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant, 'pull')


@patch('nodeconductor_openstack.openstack.executors.TenantDeleteExecutor.execute')
class TenantDeleteTest(BaseTenantActionsTest):
    def test_staff_can_delete_tenant(self, mocked_task):
        self.client.force_authenticate(self.fixture.staff)
        response = self.client.delete(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant, async=True, force=False)

    def test_staff_can_not_delete_tenant_from_non_admin_service(self, mocked_task):
        settings = self.tenant.service_project_link.service.settings
        settings.options['is_admin'] = False
        settings.save()

        self.client.force_authenticate(self.fixture.staff)
        response = self.client.delete(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(mocked_task.called)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant)


@ddt
class ServiceTenantCreateTest(BaseTenantActionsTest):

    def setUp(self):
        super(ServiceTenantCreateTest, self).setUp()
        self.settings = self.tenant.service_project_link.service.settings
        self.url = factories.TenantFactory.get_url(self.tenant, 'create_service')

    @data('owner', 'staff')
    @patch('nodeconductor.structure.executors.ServiceSettingsCreateExecutor.execute')
    def test_can_create_service(self, user, mocked_execute):
        self.client.force_authenticate(getattr(self.fixture, user))
        response = self.client.post(self.url, {'name': 'Valid service'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(mocked_execute.called)

        self.assertTrue(OpenStackService.objects.filter(
            customer=self.tenant.customer,
            name='Valid service',
            settings__backend_url=self.settings.backend_url,
            settings__username=self.tenant.user_username,
            settings__password=self.tenant.user_password
        ).exists())

    @data('manager', 'admin')
    def test_can_not_create_service(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))
        response = self.client.post(self.url, {'name': 'Valid service'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_can_not_create_service_from_erred_tenant(self):
        self.tenant.state = Tenant.States.ERRED
        self.tenant.save()

        self.client.force_authenticate(self.fixture.owner)
        response = self.client.post(self.url, {'name': 'Valid service'})
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
