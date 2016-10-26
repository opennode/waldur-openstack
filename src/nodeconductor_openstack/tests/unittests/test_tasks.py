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
        tasks.schedule_backups()
        self.assertEqual(self.not_active_schedule.backups.count(), 0)

    def test_command_create_one_backup_created_for_schedule_with_next_trigger_in_past(self):
        tasks.schedule_backups()
        self.assertEqual(self.schedule_for_execution.backups.count(), 1)

    def test_command_does_not_create_backups_created_for_schedule_with_next_trigger_in_future(self):
        tasks.schedule_backups()
        self.assertEqual(self.future_schedule.backups.count(), 0)


class SetErredProvisioningResourcesTaskTest(TestCase):
    def test_stuck_resource_becomes_erred(self):
        with mock.patch('model_utils.fields.now') as mocked_now:
            mocked_now.return_value = timezone.now() - timedelta(hours=1)
            stuck_vm = factories.InstanceFactory(state=models.Instance.States.CREATING)
            stuck_volume = factories.VolumeFactory(state=models.Volume.States.CREATING)

        tasks.set_erred_stuck_resources()

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
        tasks.set_erred_stuck_resources()

        ok_vm.refresh_from_db()
        ok_volume.refresh_from_db()

        self.assertEqual(ok_vm.state, models.Instance.States.CREATING)
        self.assertEqual(ok_volume.state, models.Volume.States.CREATING)


@ddt
class ThrottleProvisionTaskTest(TestCase):

    @data(
        dict(size=tasks.ThrottleProvisionTask.DEFAULT_LIMIT + 1, retried=True),
        dict(size=tasks.ThrottleProvisionTask.DEFAULT_LIMIT - 1, retried=False),
    )
    def test_if_limit_is_reached_provisioning_is_delayed(self, params):
        link = factories.OpenStackServiceProjectLinkFactory()
        factories.InstanceFactory.create_batch(
            size=params['size'],
            state=models.Instance.States.CREATING,
            service_project_link=link
        )
        vm = factories.InstanceFactory(
            state=models.Instance.States.CREATION_SCHEDULED,
            service_project_link=link
        )
        serialized_vm = core_utils.serialize_instance(vm)
        mocked_retry = mock.Mock()
        tasks.ThrottleProvisionTask.retry = mocked_retry
        tasks.ThrottleProvisionTask().si(
            serialized_vm,
            'create_instance',
            state_transition='begin_creating'
        ).apply()
        self.assertEqual(mocked_retry.called, params['retried'])
