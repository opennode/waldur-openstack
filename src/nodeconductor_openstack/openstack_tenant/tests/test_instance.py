from django.conf import settings
from rest_framework import test, status

from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.openstack_tenant import models

from . import factories


class InstanceCreateBackupSchedule(test.APITransactionTestCase):
    action_name = 'create_backup_schedule'

    def setUp(self):
        self.user = structure_factories.UserFactory.create(is_staff=True)
        self.client.force_authenticate(user=self.user)
        backupable = factories.InstanceFactory(state=models.Instance.States.OK)
        self.create_url = factories.InstanceFactory.get_url(backupable, action=self.action_name)
        self.backup_schedule_data = {
            'name': 'test schedule',
            'retention_time': 3,
            'schedule': '*/5 * * * *',
            'maximal_number_of_resources': 3,
        }

    def test_staff_can_create_backup_schedule(self):
        response = self.client.post(self.create_url, self.backup_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['retention_time'], self.backup_schedule_data['retention_time'])
        self.assertEqual(
            response.data['maximal_number_of_resources'], self.backup_schedule_data['maximal_number_of_resources'])
        self.assertEqual(response.data['schedule'], self.backup_schedule_data['schedule'])

    def test_backup_schedule_default_state_is_OK(self):
        response = self.client.post(self.create_url, self.backup_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        backup_schedule = models.BackupSchedule.objects.first()
        self.assertIsNotNone(backup_schedule)
        self.assertEqual(backup_schedule.state, backup_schedule.States.OK)

    def test_backup_schedule_can_not_be_created_with_wrong_schedule(self):
        # wrong schedule:
        self.backup_schedule_data['schedule'] = 'wrong schedule'
        response = self.client.post(self.create_url, self.backup_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('schedule', response.content)

    def test_backup_schedule_creation_with_correct_timezone(self):
        backupable = factories.InstanceFactory(state=models.Instance.States.OK)
        create_url = factories.InstanceFactory.get_url(backupable, action=self.action_name)
        backup_schedule_data = {
            'name': 'test schedule',
            'retention_time': 3,
            'schedule': '*/5 * * * *',
            'timezone': 'Europe/London',
            'maximal_number_of_resources': 3,
        }
        response = self.client.post(create_url, backup_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['timezone'], 'Europe/London')

    def test_backup_schedule_creation_with_incorrect_timezone(self):
        backupable = factories.InstanceFactory(state=models.Instance.States.OK)
        create_url = factories.InstanceFactory.get_url(backupable, action=self.action_name)

        backup_schedule_data = {
            'name': 'test schedule',
            'retention_time': 3,
            'schedule': '*/5 * * * *',
            'timezone': 'incorrect',
            'maximal_number_of_resources': 3,
        }
        response = self.client.post(create_url, backup_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('timezone', response.data)

    def test_backup_schedule_creation_with_default_timezone(self):
        backupable = factories.InstanceFactory(state=models.Instance.States.OK)
        create_url = factories.InstanceFactory.get_url(backupable, action=self.action_name)
        backup_schedule_data = {
            'name': 'test schedule',
            'retention_time': 3,
            'schedule': '*/5 * * * *',
            'maximal_number_of_resources': 3,
        }
        response = self.client.post(create_url, backup_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['timezone'], settings.TIME_ZONE)
