from ddt import data, ddt
from mock import patch

from rest_framework import test, status

from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.openstack.models import Tenant, OpenStackService

from . import factories, fixtures
from .. import models


class BaseTenantActionsTest(test.APITransactionTestCase):

    def setUp(self):
        super(BaseTenantActionsTest, self).setUp()
        self.fixture = fixtures.OpenStackFixture()
        self.tenant = self.fixture.tenant


class TenantCreateTest(BaseTenantActionsTest):
    def setUp(self):
        super(TenantCreateTest, self).setUp()
        self.valid_data = {
            'name': 'Test tenant',
            'service_project_link': factories.OpenStackServiceProjectLinkFactory.get_url(self.fixture.openstack_spl),
        }
        self.url = factories.TenantFactory.get_list_url()

    def test_cannot_create_tenant_with_service_settings_username(self):
        self.client.force_authenticate(self.fixture.staff)
        self.fixture.openstack_service_settings.username = 'admin'
        self.fixture.openstack_service_settings.save()
        data = self.valid_data.copy()
        data['user_username'] = self.fixture.openstack_service_settings.username

        response = self.client.post(self.url, data=data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.Tenant.objects.filter(user_username=data['user_username']).exists())

    def test_cannot_create_tenant_with_blacklisted_username(self):
        self.client.force_authenticate(self.fixture.staff)
        self.fixture.openstack_service_settings.options['blacklisted_usernames'] = ['admin']
        data = self.valid_data.copy()
        data['user_username'] = self.fixture.openstack_service_settings.options['blacklisted_usernames'][0]

        response = self.client.post(self.url, data=data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.Tenant.objects.filter(user_username=data['user_username']).exists())

    def test_cannot_create_tenant_with_duplicated_username(self):
        self.client.force_authenticate(self.fixture.staff)
        self.fixture.tenant.user_username = 'username'
        self.fixture.tenant.save()
        data = self.valid_data.copy()
        data['user_username'] = self.fixture.tenant.user_username

        response = self.client.post(self.url, data=data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(models.Tenant.objects.filter(user_username=data['user_username']).count(), 1)


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


@patch('nodeconductor_openstack.openstack.executors.TenantPullExecutor.execute')
class TenantPullTest(BaseTenantActionsTest):
    def test_staff_can_pull_tenant(self, mocked_task):
        self.client.force_authenticate(self.fixture.staff)
        response = self.client.post(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant, 'pull')


@patch('nodeconductor_openstack.openstack.executors.TenantDeleteExecutor.execute')
class TenantDeleteTest(BaseTenantActionsTest):
    def test_staff_can_delete_tenant(self, mocked_task):
        self.client.force_authenticate(self.fixture.staff)
        response = self.client.delete(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant, async=True, force=False)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant)


@ddt
class TenantCreateServiceTest(BaseTenantActionsTest):

    def setUp(self):
        super(TenantCreateServiceTest, self).setUp()
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


class TenantActionsMetadataTest(BaseTenantActionsTest):
    def test_if_tenant_is_ok_actions_enabled(self):
        self.client.force_authenticate(self.fixture.staff)
        actions = self.get_actions()
        for action in 'create_service', 'set_quotas':
            self.assertTrue(actions[action]['enabled'])

    def test_if_tenant_is_not_ok_actions_disabled(self):
        self.tenant.state = Tenant.States.DELETING
        self.tenant.save()

        self.client.force_authenticate(self.fixture.owner)
        actions = self.get_actions()
        for action in 'create_service', 'set_quotas':
            self.assertFalse(actions[action]['enabled'])

    def get_actions(self):
        url = factories.TenantFactory.get_url(self.tenant)
        response = self.client.options(url)
        return response.data['actions']


@patch('nodeconductor_openstack.openstack.executors.FloatingIPCreateExecutor.execute')
class TenantCreateFloatingIPTest(BaseTenantActionsTest):

    def setUp(self):
        super(TenantCreateFloatingIPTest, self).setUp()
        self.client.force_authenticate(self.fixture.owner)
        self.url = factories.TenantFactory.get_url(self.tenant, 'create_floating_ip')

    def test_that_floating_ip_count_quota_increases_when_floating_ip_is_created(self, mocked_task):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.tenant.floating_ips.count(), 1)
        self.assertTrue(mocked_task.called)

    def test_that_floating_ip_count_quota_exceeds_limit_if_too_many_ips_are_created(self, mocked_task):
        self.tenant.set_quota_limit('floating_ip_count', 0)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.tenant.floating_ips.count(), 0)
        self.assertFalse(mocked_task.called)


@patch('nodeconductor_openstack.openstack.executors.NetworkCreateExecutor.execute')
class TenantCreateNetworkTest(BaseTenantActionsTest):
    quota_name = 'network_count'

    def setUp(self):
        super(TenantCreateNetworkTest, self).setUp()
        self.client.force_authenticate(self.fixture.owner)
        self.url = factories.TenantFactory.get_url(self.tenant, 'create_network')
        self.request_data = {
            'name': 'test_network_name'
        }

    def test_that_network_quota_is_increased_when_network_is_created(self, mocked_task):
        response = self.client.post(self.url, self.request_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.tenant.networks.count(), 1)
        self.assertEqual(self.tenant.quotas.get(name=self.quota_name).usage, 1)
        self.assertTrue(mocked_task.called)

    def test_that_network_is_not_created_when_quota_exceeds_set_limit(self, mocked_task):
        self.tenant.set_quota_limit(self.quota_name, 0)
        response = self.client.post(self.url, self.request_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.tenant.networks.count(), 0)
        self.assertEqual(self.tenant.quotas.get(name=self.quota_name).usage, 0)
        self.assertFalse(mocked_task.called)


@ddt
class SecurityGroupCreateTest(BaseTenantActionsTest):
    def setUp(self):
        super(SecurityGroupCreateTest, self).setUp()
        self.valid_data = {
            'name': 'test_security_group',
            'description': 'test security_group description',
            'rules': [
                {
                    'protocol': 'tcp',
                    'from_port': 1,
                    'to_port': 10,
                    'cidr': '11.11.1.2/24',
                }
            ]
        }
        self.url = factories.TenantFactory.get_url(self.fixture.tenant, action='create_security_group')

    @data('owner', 'admin', 'manager')
    def test_user_with_access_can_create_security_group(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))
        response = self.client.post(self.url, self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(models.SecurityGroup.objects.filter(name=self.valid_data['name']).exists())

    def test_security_group_can_not_be_created_if_quota_is_over_limit(self):
        self.fixture.tenant.set_quota_limit('security_group_count', 0)

        self.client.force_authenticate(self.fixture.admin)
        response = self.client.post(self.url, self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.SecurityGroup.objects.filter(name=self.valid_data['name']).exists())

    def test_security_group_quota_increses_on_security_group_creation(self):
        self.client.force_authenticate(self.fixture.admin)
        response = self.client.post(self.url, self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.fixture.tenant.quotas.get(name='security_group_count').usage, 1)
        self.assertEqual(self.fixture.tenant.quotas.get(name='security_group_rule_count').usage, 1)

    def test_security_group_can_not_be_created_if_rules_quota_is_over_limit(self):
        self.fixture.tenant.set_quota_limit('security_group_rule_count', 0)

        self.client.force_authenticate(self.fixture.admin)
        response = self.client.post(self.url, self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.SecurityGroup.objects.filter(name=self.valid_data['name']).exists())

    def test_security_group_creation_starts_sync_task(self):
        self.client.force_authenticate(self.fixture.admin)

        with patch('nodeconductor_openstack.openstack.executors.SecurityGroupCreateExecutor.execute') as mocked_execute:
            response = self.client.post(self.url, data=self.valid_data)

            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
            security_group = models.SecurityGroup.objects.get(name=self.valid_data['name'])

            mocked_execute.assert_called_once_with(security_group)

    def test_security_group_raises_validation_error_if_rule_port_is_invalid(self):
        self.valid_data['rules'][0]['to_port'] = 80000

        self.client.force_authenticate(self.fixture.admin)
        response = self.client.post(self.url, data=self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.SecurityGroup.objects.filter(name=self.valid_data['name']).exists())
