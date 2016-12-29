from __future__ import unicode_literals

from rest_framework import status
from rest_framework import test

from nodeconductor.core.tests import helpers
from nodeconductor.structure import models as structure_models
from nodeconductor.structure.tests import factories as structure_factories
from .. import models
from . import factories


class BackupUsageTest(test.APITransactionTestCase):

    def setUp(self):
        self.user = structure_factories.UserFactory.create(is_staff=True, is_superuser=True)
        self.client.force_authenticate(user=self.user)

    def test_backup_manually_create(self):
        # success:
        backupable = factories.InstanceFactory(
            state=models.Instance.States.OK,
            runtime_state=models.Instance.RuntimeStates.SHUTOFF,
        )
        backup_data = {
            'instance': factories.InstanceFactory.get_url(backupable),
        }
        url = factories.BackupFactory.get_list_url()
        response = self.client.post(url, data=backup_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        models.Backup.objects.get(instance_id=backupable.id)
        # fail:
        backup_data = {
            'instance': 'some_random_url',
        }
        response = self.client.post(url, data=backup_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('instance', response.content)

    def test_user_cannot_backup_unstable_instance(self):
        instance = factories.InstanceFactory(state=models.Instance.States.UPDATING)
        backup_data = {
            'instance': factories.InstanceFactory.get_url(instance),
        }
        url = factories.BackupFactory.get_list_url()
        response = self.client.post(url, data=backup_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_backup_delete(self):
        backup = factories.BackupFactory(state=models.Backup.States.OK)
        url = factories.BackupFactory.get_url(backup)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)


class BackupListPermissionsTest(helpers.ListPermissionsTest):

    def get_url(self):
        return factories.BackupFactory.get_list_url()

    def get_users_and_expected_results(self):
        models.Backup.objects.all().delete()
        instance = factories.InstanceFactory()
        backup1 = factories.BackupFactory(instance=instance)
        backup2 = factories.BackupFactory(instance=instance)

        user_with_view_permission = structure_factories.UserFactory.create(is_staff=True, is_superuser=True)
        user_without_view_permission = structure_factories.UserFactory.create()

        return [
            {
                'user': user_with_view_permission,
                'expected_results': [
                    {'url': factories.BackupFactory.get_url(backup1)},
                    {'url': factories.BackupFactory.get_url(backup2)}
                ]
            },
            {
                'user': user_without_view_permission,
                'expected_results': []
            },
        ]


class BackupPermissionsTest(helpers.PermissionsTest):

    def setUp(self):
        super(BackupPermissionsTest, self).setUp()
        # objects
        self.customer = structure_factories.CustomerFactory()
        self.project = structure_factories.ProjectFactory(customer=self.customer)
        self.service = factories.OpenStackServiceFactory(customer=self.customer)
        self.spl = factories.OpenStackServiceProjectLinkFactory(service=self.service, project=self.project)
        self.instance = factories.InstanceFactory(service_project_link=self.spl, state=models.Instance.States.OK)
        self.backup = factories.BackupFactory(instance=self.instance)
        # users
        self.staff = structure_factories.UserFactory(username='staff', is_staff=True)
        self.regular_user = structure_factories.UserFactory(username='regular user')
        self.project_admin = structure_factories.UserFactory(username='admin')
        self.project.add_user(self.project_admin, structure_models.ProjectRole.ADMINISTRATOR)
        self.project_manager = structure_factories.UserFactory(username='manager')
        self.project.add_user(self.project_manager, structure_models.ProjectRole.MANAGER)
        self.customer_owner = structure_factories.UserFactory(username='owner')
        self.customer.add_user(self.customer_owner, structure_models.CustomerRole.OWNER)

    def get_users_with_permission(self, url, method):
        if method == 'GET':
            return [self.staff, self.project_admin, self.project_manager]
        else:
            return [self.staff, self.project_admin, self.project_manager, self.customer_owner]

    def get_users_without_permissions(self, url, method):
        if method == 'GET':
            return [self.regular_user]
        else:
            return [self.regular_user]

    def get_urls_configs(self):
        yield {'url': factories.BackupFactory.get_url(self.backup), 'method': 'GET'}
        yield {'url': factories.BackupFactory.get_list_url(), 'method': 'POST',
               'data': {'instance': factories.InstanceFactory.get_url(self.instance)}}
        yield {'url': factories.BackupFactory.get_url(self.backup), 'method': 'DELETE'}


class BackupSourceFilterTest(test.APITransactionTestCase):

    def test_filter_backup_by_scope(self):
        user = structure_factories.UserFactory.create(is_staff=True)

        instance1 = factories.InstanceFactory()
        factories.BackupFactory(instance=instance1)
        factories.BackupFactory(instance=instance1)

        instance2 = factories.InstanceFactory()
        factories.BackupFactory(instance=instance2)

        self.client.force_authenticate(user=user)
        response = self.client.get(factories.BackupFactory.get_list_url())
        self.assertEqual(3, len(response.data))

        response = self.client.get(factories.BackupFactory.get_list_url(), data={
            'instance': instance1.uuid.hex})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(2, len(response.data))
        self.assertEqual(factories.InstanceFactory.get_url(instance1), response.data[0]['instance'])
