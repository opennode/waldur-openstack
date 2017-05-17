from ddt import data, ddt
from django.conf import settings
from django.contrib.auth import get_user_model
from mock import patch
from rest_framework import test, status

from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.openstack.models import Tenant
from nodeconductor_openstack.openstack.tests.helpers import override_openstack_settings

from . import factories, fixtures
from .. import models


@override_openstack_settings(TENANT_CREDENTIALS_VISIBLE=True)
class BaseTenantActionsTest(test.APITransactionTestCase):

    def setUp(self):
        super(BaseTenantActionsTest, self).setUp()
        self.fixture = fixtures.OpenStackFixture()
        self.tenant = self.fixture.tenant


class TenantGetTest(BaseTenantActionsTest):

    def setUp(self):
        super(TenantGetTest, self).setUp()
        self.fixture.openstack_service_settings.backend_url = 'https://waldur.com/'
        self.fixture.openstack_service_settings.save()

    @override_openstack_settings(TENANT_CREDENTIALS_VISIBLE=False)
    def test_user_name_and_password_and_access_url_are_not_returned_if_credentials_are_not_visible(self):
        self.client.force_authenticate(self.fixture.staff)

        response = self.client.get(factories.TenantFactory.get_url(self.fixture.tenant))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('user_username', response.data)
        self.assertNotIn('user_password', response.data)
        self.assertNotIn('access_url', response.data)

    def test_user_name_and_password_and_access_url_are_returned_if_credentials_are_visible(self):
        self.client.force_authenticate(self.fixture.staff)

        response = self.client.get(factories.TenantFactory.get_url(self.fixture.tenant))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.fixture.tenant.user_username, response.data['user_username'])
        self.assertEqual(self.fixture.tenant.user_password, response.data['user_password'])
        self.assertEqual(self.fixture.tenant.get_access_url(), response.data['access_url'])


@ddt
class TenantCreateTest(BaseTenantActionsTest):
    def setUp(self):
        super(TenantCreateTest, self).setUp()
        self.valid_data = {
            'name': 'Test tenant',
            'service_project_link': factories.OpenStackServiceProjectLinkFactory.get_url(self.fixture.openstack_spl),
        }
        self.url = factories.TenantFactory.get_list_url()

    @data('admin', 'manager', 'staff', 'owner')
    def test_can_create_tenant(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.post(self.url, data=self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(models.Tenant.objects.filter(name=self.valid_data['name']).exists())

    @data('admin', 'manager', 'owner')
    def test_cannot_create_tenant_with_shared_service_settings(self, user):
        self.fixture.openstack_service_settings.shared = True
        self.fixture.openstack_service_settings.save()
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.post(self.url, data=self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.Tenant.objects.filter(name=self.valid_data['name']).exists())

    @data('global_support', 'user')
    def test_cannot_create_tenant(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.post(self.url, data=self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.Tenant.objects.filter(name=self.valid_data['name']).exists())

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

    @override_openstack_settings(TENANT_CREDENTIALS_VISIBLE=False)
    def test_user_name_and_password_are_autogenerated_if_credentials_are_not_visible(self):
        self.client.force_authenticate(self.fixture.staff)
        payload = self.valid_data.copy()
        payload['user_username'] = 'random'
        payload['user_password'] = '12345678secret'

        response = self.client.post(self.url, data=payload)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tenant = models.Tenant.objects.get(name=payload['name'])
        self.assertIsNotNone(tenant.user_username)
        self.assertIsNotNone(tenant.user_password)
        self.assertNotEqual(tenant.user_username, payload['user_username'])
        self.assertNotEqual(tenant.user_password, payload['user_password'])

    def test_user_can_set_username_if_autogeneration_is_disabled(self):
        self.client.force_authenticate(self.fixture.staff)
        payload = self.valid_data.copy()
        payload['user_username'] = 'random'

        response = self.client.post(self.url, data=payload)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tenant = models.Tenant.objects.get(name=payload['name'])
        self.assertIsNotNone(tenant.user_username)
        self.assertIsNotNone(tenant.user_password)
        self.assertEqual(tenant.user_username, payload['user_username'])


class TenantUpdateTest(BaseTenantActionsTest):

    def test_user_cannot_update_username_even_if_credentials_autogeneration_is_disabled(self):
        self.client.force_authenticate(self.fixture.staff)
        payload = dict(name=self.fixture.tenant.name, user_username='new_username')

        response = self.client.put(factories.TenantFactory.get_url(self.fixture.tenant), payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertNotEqual(response.data['user_username'], payload['user_username'])


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


@patch('nodeconductor_openstack.openstack.executors.TenantPullQuotasExecutor.execute')
class TenantPullQuotasTest(BaseTenantActionsTest):
    def test_staff_can_pull_tenant_quotas(self, mocked_task):
        self.client.force_authenticate(self.fixture.staff)
        response = self.client.post(self.get_url())
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant, 'pull_quotas')


@ddt
@patch('nodeconductor_openstack.openstack.executors.TenantDeleteExecutor.execute')
class TenantDeleteTest(BaseTenantActionsTest):

    @data('staff', 'owner', 'admin', 'manager')
    def test_can_delete_tenant(self, user, mocked_task):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.delete(self.get_url())

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant, async=True, force=False)

    @data('admin', 'manager')
    def test_cannot_delete_tenant_from_shared_settings(self, user, mocked_task):
        self.fixture.openstack_service_settings.shared = True
        self.fixture.openstack_service_settings.save()
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.delete(self.get_url())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(mocked_task.call_count, 0)

    def test_manager_can_delete_tenant_from_shared_settings_with_permission_from_settings(self, mocked_task):
        self.fixture.openstack_service_settings.shared = True
        self.fixture.openstack_service_settings.save()
        openstack_settings = settings.NODECONDUCTOR_OPENSTACK.copy()
        openstack_settings['MANAGER_CAN_MANAGE_TENANTS'] = True
        self.client.force_authenticate(user=self.fixture.manager)

        with self.settings(NODECONDUCTOR_OPENSTACK=openstack_settings):
            response = self.client.delete(self.get_url())

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mocked_task.assert_called_once_with(self.tenant, async=True, force=False)

    @data('global_support')
    def test_cannot_delete_tenant(self, user, mocked_task):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.delete(self.get_url())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(mocked_task.call_count, 0)

    def get_url(self):
        return factories.TenantFactory.get_url(self.tenant)


class TenantActionsMetadataTest(BaseTenantActionsTest):
    def test_if_tenant_is_ok_actions_enabled(self):
        self.client.force_authenticate(self.fixture.staff)
        actions = self.get_actions()
        self.assertTrue(actions['set_quotas']['enabled'])

    def test_if_tenant_is_not_ok_actions_disabled(self):
        self.tenant.state = Tenant.States.DELETING
        self.tenant.save()

        self.client.force_authenticate(self.fixture.owner)
        actions = self.get_actions()
        self.assertFalse(actions['set_quotas']['enabled'])

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

    def test_user_cannot_create_floating_ip_if_external_network_is_not_defined_for_tenant(self, mocked_task):
        self.tenant.external_network_id = ''
        self.tenant.save()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
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
class TenantChangePasswordTest(BaseTenantActionsTest):

    def setUp(self):
        super(TenantChangePasswordTest, self).setUp()
        self.tenant = self.fixture.tenant
        self.url = factories.TenantFactory.get_url(self.tenant, action='change_password')
        self.new_password = get_user_model().objects.make_random_password()[:50]

    @data('owner', 'staff', 'admin', 'manager')
    def test_user_can_change_tenant_user_password(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.post(self.url, {'user_password': self.new_password})

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.user_password, self.new_password)

    @data('global_support', 'customer_support', 'project_support')
    def test_user_cannot_change_tenant_user_password(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.post(self.url, {'user_password': self.new_password})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_cannot_set_password_if_it_consists_only_with_digits(self):
        self.client.force_authenticate(self.fixture.owner)
        response = self.client.post(self.url, {'user_password': 682992000})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_cannot_set_password_with_length_less_than_8_characters(self):
        request_data = {
            'user_password': get_user_model().objects.make_random_password()[:7]
        }

        self.client.force_authenticate(self.fixture.owner)
        response = self.client.post(self.url, request_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_cannot_set_password_if_it_matches_to_the_old_one(self):
        self.client.force_authenticate(self.fixture.owner)

        response = self.client.post(self.url, {'user_password': self.fixture.tenant.user_password})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_cannot_change_password_if_tenant_is_not_in_OK_state(self):
        self.tenant.state = self.tenant.States.ERRED
        self.tenant.save()

        self.client.force_authenticate(self.fixture.owner)
        response = self.client.post(self.url, {'user_password': self.fixture.tenant.user_password})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_user_can_set_an_empty_password(self):
        self.client.force_authenticate(self.fixture.owner)
        response = self.client.post(self.url, {'user_password': ''})

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)


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
