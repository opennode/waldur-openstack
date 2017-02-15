import mock

from datetime import timedelta

from ddt import ddt, data
from django.test import TestCase
from django.utils import timezone

from nodeconductor.core import utils as core_utils

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


class ExecuteBackupScheduleTaskTest(TestCase):

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

    def test_command_does_not_create_backups_created_for_schedule_with_next_trigger_in_future(self):
        tasks.ScheduleBackups().run()
        self.assertEqual(self.future_schedule.backups.count(), 0)


class ExecuteSnapshotScheduleTaskTest(TestCase):

    def setUp(self):
        self.not_active_schedule = factories.SnapshotScheduleFactory(is_active=False)

        volume = factories.VolumeFactory(state=models.Volume.States.OK)
        self.schedule_for_execution = factories.SnapshotScheduleFactory(source_volume=volume)
        self.schedule_for_execution.next_trigger_at = timezone.now() - timedelta(minutes=10)
        self.schedule_for_execution.save()

        self.future_schedule = factories.SnapshotScheduleFactory(source_volume=volume)
        self.future_schedule.next_trigger_at = timezone.now() + timedelta(minutes=2)
        self.future_schedule.save()

    def test_command_does_not_create_snapshots_created_for_not_active_schedules(self):
        tasks.ScheduleSnapshots().run()
        self.assertEqual(self.not_active_schedule.snapshots.count(), 0)

    def test_command_create_one_snapshot_for_schedule_with_next_trigger_in_past(self):
        tasks.ScheduleSnapshots().run()
        self.assertEqual(self.schedule_for_execution.snapshots.count(), 1)

    def test_command_does_not_create_snapshots_created_for_schedule_with_next_trigger_in_future(self):
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
