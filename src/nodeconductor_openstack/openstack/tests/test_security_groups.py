from ddt import ddt, data
from mock import patch
from rest_framework import test, status

from nodeconductor.core.models import SynchronizationStates
from nodeconductor.structure.tests import factories as structure_factories

from .. import models
from . import factories, fixtures


class BaseSecurityGroupTest(test.APITransactionTestCase):
    def setUp(self):
        self.fixture = fixtures.OpenStackFixture()


@ddt
class SecurityGroupCreateTest(BaseSecurityGroupTest):
    def setUp(self):
        super(SecurityGroupCreateTest, self).setUp()
        self.valid_data = {
            'name': 'test_security_group',
            'description': 'test security_group description',
            'tenant': factories.TenantFactory.get_url(self.fixture.openstack_tenant),
            'rules': [
                {
                    'protocol': 'tcp',
                    'from_port': 1,
                    'to_port': 10,
                    'cidr': '11.11.1.2/24',
                }
            ]
        }
        self.url = factories.SecurityGroupFactory.get_list_url()

    @data('owner', 'admin', 'manager')
    def test_user_with_access_can_create_security_group(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))
        response = self.client.post(self.url, self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(models.SecurityGroup.objects.filter(name=self.valid_data['name']).exists())

    def test_security_group_can_not_be_created_if_quota_is_over_limit(self):
        self.fixture.openstack_tenant.set_quota_limit('security_group_count', 0)

        self.client.force_authenticate(self.fixture.admin)
        response = self.client.post(self.url, self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.SecurityGroup.objects.filter(name=self.valid_data['name']).exists())

    def test_security_group_can_not_be_created_if_rules_quota_is_over_limit(self):
        self.fixture.openstack_tenant.set_quota_limit('security_group_rule_count', 0)

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

            mocked_execute.assert_called_once_with(security_group, async=True)

    def test_security_group_raises_validation_error_on_wrong_tenant_in_request(self):
        del self.valid_data['tenant']

        self.client.force_authenticate(self.fixture.admin)
        response = self.client.post(self.url, data=self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.SecurityGroup.objects.filter(name=self.valid_data['name']).exists())

    def test_security_group_raises_validation_error_if_rule_port_is_invalid(self):
        self.valid_data['rules'][0]['to_port'] = 80000

        self.client.force_authenticate(self.fixture.admin)
        response = self.client.post(self.url, data=self.valid_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(models.SecurityGroup.objects.filter(name=self.valid_data['name']).exists())


@ddt
class SecurityGroupUpdateTest(BaseSecurityGroupTest):

    def setUp(self):
        super(SecurityGroupUpdateTest, self).setUp()
        self.security_group = factories.SecurityGroupFactory(
            service_project_link=self.fixture.openstack_spl,
            tenant=self.fixture.openstack_tenant,
            state=SynchronizationStates.IN_SYNC)
        self.url = factories.SecurityGroupFactory.get_url(self.security_group)

    @data('admin', 'manager')
    def test_user_with_access_can_update_security_group_rules(self, user):
        rules = [
            {
                'protocol': 'udp',
                'from_port': 100,
                'to_port': 8001,
                'cidr': '11.11.1.2/24',
            }
        ]

        self.client.force_authenticate(getattr(self.fixture, user))
        response = self.client.patch(self.url, data={'rules': rules})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        reread_security_group = models.SecurityGroup.objects.get(pk=self.security_group.pk)
        self.assertEqual(len(rules), reread_security_group.rules.count())
        saved_rule = reread_security_group.rules.first()
        for key, value in rules[0].items():
            self.assertEqual(getattr(saved_rule, key), value)

    def test_security_group_can_not_be_updated_in_unstable_state(self):
        self.security_group.state = SynchronizationStates.ERRED
        self.security_group.save()

        self.client.force_authenticate(self.fixture.admin)
        response = self.client.patch(self.url, data={'rules': []})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_security_group_tenant_can_not_be_updated(self):
        new_tenant = factories.TenantFactory(service_project_link=self.fixture.openstack_spl)
        new_tenant_url = factories.TenantFactory.get_url(new_tenant)

        self.client.force_authenticate(self.fixture.admin)
        self.client.patch(self.url, data={'tenant': {'url': new_tenant_url}})

        reread_security_group = models.SecurityGroup.objects.get(pk=self.security_group.pk)
        self.assertNotEqual(new_tenant, reread_security_group.tenant)

    def test_security_group_rules_can_not_be_updated_if_rules_quota_is_over_limit(self):
        self.fixture.openstack_tenant.set_quota_limit('security_group_rule_count', 0)

        rules = [
            {
                'protocol': 'udp',
                'from_port': 100,
                'to_port': 8001,
                'cidr': '11.11.1.2/24',
            }
        ]

        self.client.force_authenticate(self.fixture.admin)
        response = self.client.patch(self.url, data={'rules': rules})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        reread_security_group = models.SecurityGroup.objects.get(pk=self.security_group.pk)
        self.assertEqual(reread_security_group.rules.count(), self.security_group.rules.count())

    def test_security_group_update_starts_sync_task(self):
        self.client.force_authenticate(self.fixture.admin)

        with patch('nodeconductor_openstack.openstack.executors.SecurityGroupUpdateExecutor.execute') as mocked_execute:
            response = self.client.patch(self.url, data={'name': 'new_name'})

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mocked_execute.assert_called_once_with(self.security_group, updated_fields={'name'}, async=True)

    def test_user_can_remove_rule_from_security_group(self):
        rule1 = factories.SecurityGroupRuleFactory(security_group=self.security_group)
        factories.SecurityGroupRuleFactory(security_group=self.security_group)
        self.client.force_authenticate(self.fixture.admin)

        response = self.client.patch(self.url, data={'rules': [{'id': rule1.id}]})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.security_group.rules.count(), 1)
        self.assertEqual(self.security_group.rules.all()[0], rule1)

    def test_user_can_add_new_security_group_rule_and_left_existant(self):
        exist_rule = factories.SecurityGroupRuleFactory(security_group=self.security_group)
        self.client.force_authenticate(self.fixture.admin)
        new_rule_data = {
            'protocol': 'udp',
            'from_port': 100,
            'to_port': 8001,
            'cidr': '11.11.1.2/24',
        }

        response = self.client.patch(self.url, data={'rules': [{'id': exist_rule.id}, new_rule_data]})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.security_group.rules.count(), 2)
        self.assertTrue(self.security_group.rules.filter(id=exist_rule.id).exists())
        self.assertTrue(self.security_group.rules.filter(**new_rule_data).exists())


@ddt
class SecurityGroupDeleteTest(BaseSecurityGroupTest):

    def setUp(self):
        super(SecurityGroupDeleteTest, self).setUp()
        self.security_group = factories.SecurityGroupFactory(
            service_project_link=self.fixture.openstack_spl,
            tenant=self.fixture.openstack_tenant,
            state=SynchronizationStates.IN_SYNC)
        self.url = factories.SecurityGroupFactory.get_url(self.security_group)

    @data('admin', 'manager')
    def test_project_administrator_can_delete_security_group(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        with patch('nodeconductor_openstack.openstack.executors.SecurityGroupDeleteExecutor.execute') as mocked_execute:
            response = self.client.delete(self.url)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

            mocked_execute.assert_called_once_with(self.security_group, force=False, async=True)

    def test_security_group_can_be_deleted_from_erred_state(self):
        self.security_group.state = SynchronizationStates.ERRED
        self.security_group.save()

        self.client.force_authenticate(self.fixture.admin)
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)


@ddt
class SecurityGroupRetreiveTest(BaseSecurityGroupTest):

    def setUp(self):
        super(SecurityGroupRetreiveTest, self).setUp()
        self.security_group = factories.SecurityGroupFactory(
            service_project_link=self.fixture.openstack_spl,
            tenant=self.fixture.openstack_tenant,
        )

        self.url = factories.SecurityGroupFactory.get_url(self.security_group)

    @data('admin', 'manager')
    def test_user_can_access_security_groups_of_project_instances_he_has_role_in(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_user_cannot_access_security_groups_of_instances_not_connected_to_him(self):
        self.client.force_authenticate(user=structure_factories.UserFactory())
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
