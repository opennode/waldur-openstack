import mock

from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from ... import tasks
from ...models import Instance
from ...tests import factories


@mock.patch('celery.app.base.Celery.send_task')
class BackupTest(TestCase):

    def assert_task_called(self, task, name, *args, **kawargs):
        task.assert_has_calls([mock.call(name, args, kawargs, countdown=2)], any_order=True)

    def test_start_backup(self, mocked_task):
        backup = factories.BackupFactory()
        backend = backup.get_backend()
        backend.start_backup()
        self.assert_task_called(mocked_task,
                                'nodeconductor.openstack.backup_start_create',
                                backup.uuid.hex)

    def test_start_restoration(self, mocked_task):
        backup = factories.BackupFactory()
        instance = factories.InstanceFactory()
        user_input = {}
        snapshot_ids = []

        backend = backup.get_backend()
        backend.start_restoration(instance.uuid.hex, user_input, snapshot_ids)
        self.assert_task_called(mocked_task,
                                'nodeconductor.openstack.backup_start_restore',
                                backup.uuid.hex, instance.uuid.hex, user_input, snapshot_ids)

    def test_start_deletion(self, mocked_task):
        backup = factories.BackupFactory()
        backend = backup.get_backend()
        backend.start_deletion()

        self.assert_task_called(mocked_task,
                                'nodeconductor.openstack.backup_start_delete',
                                backup.uuid.hex)


class DeleteExpiredBackupsTaskTest(TestCase):

    def setUp(self):
        self.expired_backup1 = factories.BackupFactory(kept_until=timezone.now() - timedelta(minutes=1))
        self.expired_backup2 = factories.BackupFactory(kept_until=timezone.now() - timedelta(minutes=10))

    @mock.patch('celery.app.base.Celery.send_task')
    def test_command_starts_backend_deletion(self, mocked_task):
        tasks.delete_expired_backups()
        mocked_task.assert_has_calls([
            mock.call('nodeconductor.openstack.backup_start_delete', (self.expired_backup1.uuid.hex,), {}, countdown=2),
            mock.call('nodeconductor.openstack.backup_start_delete', (self.expired_backup2.uuid.hex,), {}, countdown=2),
        ], any_order=True)


class ExecuteScheduleTaskTest(TestCase):

    def setUp(self):
        self.not_active_schedule = factories.BackupScheduleFactory(is_active=False)

        backupable = factories.InstanceFactory(state=Instance.States.OFFLINE)
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
