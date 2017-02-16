from __future__ import unicode_literals

from ddt import data, ddt

from rest_framework import status
from rest_framework import test

from nodeconductor_openstack.openstack_tenant import models

from . import factories, fixtures


class BaseBackupScheduleTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()


class BackupScheduleActivateTest(BaseBackupScheduleTest):

    def setUp(self):
        super(BackupScheduleActivateTest, self).setUp()

    def test_backup_schedule_do_not_start_activation_of_active_schedule(self):
        self.client.force_authenticate(self.fixture.owner)
        schedule = self.fixture.openstack_backup_schedule
        url = factories.BackupScheduleFactory.get_url(schedule, action='activate')

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)


class BackupScheduleDeactivateTest(BaseBackupScheduleTest):

    def setUp(self):
        super(BackupScheduleDeactivateTest, self).setUp()

    def test_backup_schedule_do_not_start_deactivation_of_not_active_schedule(self):
        self.client.force_authenticate(self.fixture.owner)
        schedule = self.fixture.openstack_backup_schedule
        schedule.is_active = False
        schedule.save()
        url = factories.BackupScheduleFactory.get_url(schedule, action='deactivate')

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)


@ddt
class BackupScheduleRetrieveTest(BaseBackupScheduleTest):

    def setUp(self):
        super(BackupScheduleRetrieveTest, self).setUp()
        self.fixture.openstack_backup_schedule
        self.url = factories.BackupScheduleFactory.get_list_url()

    @data('owner', 'manager', 'admin', 'staff', 'global_support')
    def test_user_has_access_to_backup_schedules(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    @data('user')
    def test_user_has_no_project_level_access_to_backup_schedules(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)


@ddt
class BackupScheduleDeleteTest(BaseBackupScheduleTest):

    def setUp(self):
        super(BackupScheduleDeleteTest, self).setUp()
        self.schedule = factories.BackupScheduleFactory(instance=self.fixture.openstack_instance)
        self.url = factories.BackupScheduleFactory.get_url(self.schedule)

    @data('owner', 'admin', 'manager', 'staff')
    def test_user_can_delete_backup_schedule(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(models.BackupSchedule.objects.filter(pk=self.schedule.pk).exists())

    @data('user')
    def test_user_can_not_delete_backup_schedule(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
