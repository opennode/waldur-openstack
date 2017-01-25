from __future__ import unicode_literals

from mock import patch
from rest_framework import status
from rest_framework import test

from nodeconductor.core.tests import helpers
from nodeconductor.structure.tests import factories as structure_factories
from .. import models
from . import factories, fixtures


class BackupUsageTest(test.APITransactionTestCase):

    def setUp(self):
        self.user = structure_factories.UserFactory.create(is_staff=True, is_superuser=True)
        self.client.force_authenticate(user=self.user)

    def test_backup_manually_create(self):
        backupable = factories.InstanceFactory(
            state=models.Instance.States.OK,
            runtime_state=models.Instance.RuntimeStates.SHUTOFF,
        )
        url = factories.InstanceFactory.get_url(backupable, action='backup')
        response = self.client.post(url, data={'name': 'test backup'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        models.Backup.objects.get(instance_id=backupable.id)

    def test_user_cannot_backup_unstable_instance(self):
        instance = factories.InstanceFactory(state=models.Instance.States.UPDATING)
        url = factories.InstanceFactory.get_url(instance, action='backup')

        response = self.client.post(url, data={'name': 'test backup'})
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

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
        self.fixture = fixtures.OpenStackTenantFixture()
        self.instance = self.fixture.openstack_instance
        self.backup = factories.BackupFactory(
            service_project_link=self.fixture.openstack_tenant_spl,
            state=models.Backup.States.OK,
            instance=self.instance,
        )

    def get_users_with_permission(self, url, method):
        if method == 'GET':
            return [self.fixture.staff, self.fixture.admin, self.fixture.manager]
        else:
            return [self.fixture.staff, self.fixture.admin, self.fixture.manager, self.fixture.owner]

    def get_users_without_permissions(self, url, method):
        return [self.fixture.user]

    def get_urls_configs(self):
        yield {'url': factories.BackupFactory.get_url(self.backup), 'method': 'GET'}
        yield {'url': factories.BackupFactory.get_url(self.backup), 'method': 'DELETE'}

    def test_permissions(self):
        with patch('nodeconductor_openstack.openstack_tenant.executors.BackupDeleteExecutor.execute'):
            super(BackupPermissionsTest, self).test_permissions()


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
            'instance_uuid': instance1.uuid.hex})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(2, len(response.data))
        self.assertEqual(factories.InstanceFactory.get_url(instance1), response.data[0]['instance'])


class BackupRestorationTest(test.APITransactionTestCase):
    def setUp(self):
        user = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=user)

        self.backup = factories.BackupFactory(state=models.Backup.States.OK)
        self.url = factories.BackupFactory.get_url(self.backup, 'restore')

        system_volume = self.backup.instance.volumes.get(bootable=True)
        self.disk_size = system_volume.size

        service_settings = self.backup.instance.service_project_link.service.settings
        self.valid_flavor = factories.FlavorFactory(disk=self.disk_size + 10, settings=service_settings)
        self.invalid_flavor = factories.FlavorFactory(disk=self.disk_size - 10, settings=service_settings)

    def test_flavor_disk_size_should_match_system_volume_size(self):
        response = self.client.post(self.url, {
            'flavor': factories.FlavorFactory.get_url(self.valid_flavor)
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_if_flavor_disk_size_lesser_then_system_volume_size_validation_fails(self):
        response = self.client.post(self.url, {
            'flavor': factories.FlavorFactory.get_url(self.invalid_flavor)
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['flavor'], ['Flavor disk size should match system volume size.'])
