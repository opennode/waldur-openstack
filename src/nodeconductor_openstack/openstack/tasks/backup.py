import logging

from nodeconductor.core import tasks as core_tasks

from .. import models


logger = logging.getLogger(__name__)


class SetBackupErredTask(core_tasks.ErrorStateTransitionTask):
    """ Mark DR backup and all related resources that are not in state OK as Erred """

    def execute(self, backup):
        super(SetBackupErredTask, self).execute(backup)
        for snapshot in backup.snapshots.all():
            # If snapshot creation was not started - delete it from NC DB.
            if snapshot.state == models.Snapshot.States.CREATION_SCHEDULED:
                snapshot.decrease_backend_quotas_usage()
                snapshot.delete()
            else:
                snapshot.set_erred()
                snapshot.save(update_fields=['state'])

        # Deactivate schedule if its backup become erred.
        schedule = backup.backup_schedule
        if schedule:
            schedule.error_message = 'Failed to execute backup schedule for %s. Error: %s' % (
                backup.instance, backup.error_message)
            schedule.runtime_state = 'Failed to create backup'
            schedule.is_active = False
            schedule.save()


class ForceDeleteBackupTask(core_tasks.StateTransitionTask):

    def execute(self, backup):
        backup.snapshots.all().delete()
        backup.delete()
