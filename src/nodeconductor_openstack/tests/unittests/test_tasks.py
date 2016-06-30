import mock

from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from ... import tasks, models
from ...tests import factories


class DeleteExpiredBackupsTaskTest(TestCase):

    def setUp(self):
        self.expired_backup1 = factories.BackupFactory(
            state=models.Backup.States.OK, kept_until=timezone.now() - timedelta(minutes=1))
        self.expired_backup2 = factories.BackupFactory(
            state=models.Backup.States.OK, kept_until=timezone.now() - timedelta(minutes=10))

    @mock.patch('nodeconductor_openstack.executors.BackupDeleteExecutor.execute')
    def test_command_starts_backend_deletion(self, mocked_execute):
        tasks.delete_expired_backups()
        mocked_execute.assert_has_calls([
            mock.call(self.expired_backup1),
            mock.call(self.expired_backup2),
        ], any_order=True)


class ExecuteScheduleTaskTest(TestCase):

    def setUp(self):
        self.not_active_schedule = factories.BackupScheduleFactory(is_active=False)

        backupable = factories.InstanceFactory(state=models.Instance.States.OFFLINE)
        self.schedule_for_execution = factories.BackupScheduleFactory(instance=backupable)
        self.schedule_for_execution.next_trigger_at = timezone.now() - timedelta(minutes=10)
        self.schedule_for_execution.save()

        self.future_schedule = factories.BackupScheduleFactory()
        self.future_schedule.next_trigger_at = timezone.now() + timedelta(minutes=2)
        self.future_schedule.save()

    def test_command_does_not_create_backups_created_for_not_active_schedules(self):
        tasks.schedule_backups()
        self.assertEqual(self.not_active_schedule.backups.count(), 0)

    def test_command_create_one_backup_created_for_schedule_with_next_trigger_in_past(self):
        tasks.schedule_backups()
        self.assertEqual(self.schedule_for_execution.backups.count(), 1)

    def test_command_does_not_create_backups_created_for_schedule_with_next_trigger_in_future(self):
        tasks.schedule_backups()
        self.assertEqual(self.future_schedule.backups.count(), 0)
