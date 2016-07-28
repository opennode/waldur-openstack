import logging

from django.db import transaction
from django.utils import timezone

from nodeconductor.quotas.exceptions import QuotaValidationError


logger = logging.getLogger(__name__)


class BackupError(Exception):
    pass


class BackupScheduleBackend(object):

    def __init__(self, schedule):
        self.schedule = schedule

    def check_instance_state(self):
        """
        Instance should be stable state.
        """
        instance = self.schedule.instance
        if instance.state not in instance.States.STABLE_STATES:
            logger.warning('Cannot execute backup schedule for %s in state %s.' % (instance, instance.state))
            return False

        return True

    def create_backup(self):
        """
        Creates new backup based on schedule and starts backup process
        """
        if not self.check_instance_state():
            return

        if self.schedule.backup_type == self.schedule.BackupTypes.REGULAR:
            self._create_regular_backup()
        elif self.schedule.backup_type == self.schedule.BackupTypes.DR:
            self._create_dr_backup()

    def _create_regular_backup(self):
        from . import models, executors, serializers
        kept_until = timezone.now() + \
            timezone.timedelta(days=self.schedule.retention_time) if self.schedule.retention_time else None
        try:
            with transaction.atomic():
                backup = models.Backup.objects.create(
                    instance=self.schedule.instance,
                    backup_schedule=self.schedule,
                    metadata=self.schedule.instance.as_dict(),
                    description='Scheduled backup of instance "%s"' % self.schedule.instance,
                    kept_until=kept_until,
                    tenant=self.schedule.instance.tenant,
                )
                serializers.create_backup_snapshots(backup)
        except QuotaValidationError as e:
            message = 'Failed to schedule backup creation. Error: %s' % e
            logger.exception('Backup schedule (PK: %s) execution failed. %s' % (self.schedule.pk, message))
            raise BackupError(message)
        else:
            executors.BackupCreateExecutor.execute(backup)

    def _create_dr_backup(self):
        from . import models, executors, serializers, backend
        kept_until = timezone.now() + \
            timezone.timedelta(days=self.schedule.retention_time) if self.schedule.retention_time else None

        try:
            with transaction.atomic():
                dr_backup = models.DRBackup.objects.create(
                    source_instance=self.schedule.instance,
                    name=('Backup of instance "%s"' % self.schedule.instance)[:150],
                    description='Scheduled DR backup.',
                    tenant=self.schedule.instance.tenant,
                    service_project_link=self.schedule.instance.service_project_link,
                    metadata=self.schedule.instance.as_dict(),
                    backup_schedule=self.schedule,
                    kept_until=kept_until,
                )
                serializers.create_dr_backup_related_resources(dr_backup)
        except (QuotaValidationError, backend.OpenStackBackendError) as e:
            message = 'Failed to schedule backup creation. Error: %s' % e
            logger.exception('Backup schedule (PK: %s) execution failed. %s' % (self.schedule.pk, message))
            raise BackupError(message)
        else:
            executors.DRBackupCreateExecutor.execute(dr_backup)

    def delete_extra_backups(self):
        """
        Deletes oldest existing backups if maximal_number_of_backups was reached
        """
        from . import executors
        if self.schedule.backup_type == self.schedule.BackupTypes.REGULAR:
            self._delete_backups(self.schedule.backups.all(), executors.BackupDeleteExecutor)
        elif self.schedule.backup_type == self.schedule.BackupTypes.DR:
            self._delete_backups(self.schedule.dr_backups.all(), executors.DRBackupDeleteExecutor)

    def _delete_backups(self, backups, delete_executor):
        States = backups.model.States
        stable_backups = backups.filter(state=States.OK)
        extra_backups_count = backups.count() - self.schedule.maximal_number_of_backups
        if extra_backups_count > 0:
            order_field = 'created_at' if self.schedule.backup_type == self.schedule.BackupTypes.REGULAR else 'created'
            for backup in stable_backups.order_by(order_field)[:extra_backups_count]:
                delete_executor.execute(backup)

    def execute(self):
        """
        Creates new backup, deletes existing if maximal_number_of_backups was
        reached, calculates new next_trigger_at time.
        """
        try:
            self.create_backup()
        except BackupError as e:
            self.schedule.runtime_state = 'Failed to schedule backup creation.'
            self.schedule.error_message = str(e)
            self.schedule.is_active = False
        else:
            self.schedule.runtime_state = 'Successfully started backup creation at %s.' % timezone.now()
        finally:
            self.delete_extra_backups()
            self.schedule.update_next_trigger_at()
            self.schedule.save()
