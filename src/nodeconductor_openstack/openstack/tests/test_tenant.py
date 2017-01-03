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
