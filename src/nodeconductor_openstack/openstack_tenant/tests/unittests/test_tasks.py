from datetime import timedelta, datetime
import mock

from croniter import croniter
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
import pytz

from ... import tasks, models
from ...tests import factories


class DeleteExpiredBackupsTaskTest(TestCase):

    def setUp(self):
        self.expired_backup1 = factories.BackupFactory(
            state=models.Backup.States.OK, kept_until=timezone.now() - timedelta(minutes=1))
        self.expired_backup2 = factories.BackupFactory(
            state=models.Backup.States.OK, kept_until=timezone.now() - timedelta(minutes=10))

    @mock.patch('nodeconductor_openstack.openstack_tenant.executors.BackupDeleteExecutor.execute')
    def test_command_starts_backend_deletion(self, mocked_execute):
        tasks.DeleteExpiredBackups().run()
        mocked_execute.assert_has_calls([
            mock.call(self.expired_backup1),
            mock.call(self.expired_backup2),
        ], any_order=True)


class DeleteExpiredSnapshotsTaskTest(TestCase):

    def setUp(self):
        self.expired_snapshot1 = factories.SnapshotFactory(
            state=models.Snapshot.States.OK, kept_until=timezone.now() - timedelta(minutes=1))
        self.expired_snapshot2 = factories.SnapshotFactory(
            state=models.Snapshot.States.OK, kept_until=timezone.now() - timedelta(minutes=10))

    @mock.patch('nodeconductor_openstack.openstack_tenant.executors.SnapshotDeleteExecutor.execute')
    def test_command_starts_snapshot_deletion(self, mocked_execute):
        tasks.DeleteExpiredSnapshots().run()
        mocked_execute.assert_has_calls([
            mock.call(self.expired_snapshot1),
            mock.call(self.expired_snapshot2),
        ], any_order=True)


class BackupScheduleTaskTest(TestCase):

    def setUp(self):
        self.not_active_schedule = factories.BackupScheduleFactory(is_active=False)

        backupable = factories.InstanceFactory(
            state=models.Instance.States.OK,
        )
        self.schedule_for_execution = factories.BackupScheduleFactory(instance=backupable)
        self.schedule_for_execution.next_trigger_at = timezone.now() - timedelta(minutes=10)
        self.schedule_for_execution.save()

        self.future_schedule = factories.BackupScheduleFactory(instance=backupable)
        self.future_schedule.next_trigger_at = timezone.now() + timedelta(minutes=2)
        self.future_schedule.save()

    def test_command_does_not_create_backups_created_for_not_active_schedules(self):
        tasks.ScheduleBackups().run()
        self.assertEqual(self.not_active_schedule.backups.count(), 0)

    def test_command_create_one_backup_created_for_schedule_with_next_trigger_in_past(self):
        tasks.ScheduleBackups().run()
        self.assertEqual(self.schedule_for_execution.backups.count(), 1)

    def test_command_does_not_create_a_second_backup_if_timedelta_is_less_than_schedule(self):
        tasks.ScheduleBackups().run()
        self.assertEqual(self.schedule_for_execution.backups.count(), 1)
        # timedelta is 0
        tasks.ScheduleBackups().run()
        self.assertEqual(self.schedule_for_execution.backups.count(), 1)

    def test_command_create_two_backups_if_enough_time_has_passed(self):
        tasks.ScheduleBackups().run()
        self.assertEqual(self.schedule_for_execution.backups.count(), 1)
        tasks.ScheduleBackups().run()
        base_time = timezone.now().replace(tzinfo=pytz.timezone(self.schedule_for_execution.timezone))
        next_trigger_at = croniter(self.schedule_for_execution.schedule, base_time).get_next(datetime)
        mocked_now = next_trigger_at + timezone.timedelta(seconds=5)
        with freeze_time(mocked_now):
            tasks.ScheduleBackups().run()
            self.assertEqual(self.schedule_for_execution.backups.count(), 2)

    def test_command_does_not_create_backups_created_for_schedule_with_next_trigger_in_future(self):
        tasks.ScheduleBackups().run()
        self.assertEqual(self.future_schedule.backups.count(), 0)


class SnapshotScheduleTaskTest(TestCase):

    def test_command_does_not_create_snapshots_created_for_not_active_schedules(self):
        self.not_active_schedule = factories.SnapshotScheduleFactory(is_active=False)

        tasks.ScheduleSnapshots().run()

        self.assertEqual(self.not_active_schedule.snapshots.count(), 0)

    def test_command_create_one_snapshot_for_schedule_with_next_trigger_in_past(self):
        self.schedule_for_execution = factories.SnapshotScheduleFactory()
        self.schedule_for_execution.next_trigger_at = timezone.now() - timedelta(minutes=10)
        self.schedule_for_execution.save()

        tasks.ScheduleSnapshots().run()

        self.assertEqual(self.schedule_for_execution.snapshots.count(), 1)

    def test_command_does_not_create_snapshots_created_for_schedule_with_next_trigger_in_future(self):
        self.future_schedule = factories.SnapshotScheduleFactory()
        self.future_schedule.next_trigger_at = timezone.now() + timedelta(minutes=2)
        self.future_schedule.save()

        tasks.ScheduleSnapshots().run()

        self.assertEqual(self.future_schedule.snapshots.count(), 0)


class SetErredProvisioningResourcesTaskTest(TestCase):
    def test_stuck_resource_becomes_erred(self):
        with mock.patch('model_utils.fields.now') as mocked_now:
            mocked_now.return_value = timezone.now() - timedelta(hours=1)
            stuck_vm = factories.InstanceFactory(state=models.Instance.States.CREATING)
            stuck_volume = factories.VolumeFactory(state=models.Volume.States.CREATING)

        tasks.SetErredStuckResources().run()

        stuck_vm.refresh_from_db()
        stuck_volume.refresh_from_db()

        self.assertEqual(stuck_vm.state, models.Instance.States.ERRED)
        self.assertEqual(stuck_volume.state, models.Volume.States.ERRED)

    def test_ok_vm_unchanged(self):
        ok_vm = factories.InstanceFactory(
            state=models.Instance.States.CREATING,
            modified=timezone.now() - timedelta(minutes=1)
        )
        ok_volume = factories.VolumeFactory(
            state=models.Volume.States.CREATING,
            modified=timezone.now() - timedelta(minutes=1)
        )
        tasks.SetErredStuckResources().run()

        ok_vm.refresh_from_db()
        ok_volume.refresh_from_db()

        self.assertEqual(ok_vm.state, models.Instance.States.CREATING)
        self.assertEqual(ok_volume.state, models.Volume.States.CREATING)
