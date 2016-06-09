import logging

from django.utils import six, timezone

from nodeconductor.core.tasks import send_task
from nodeconductor.quotas.exceptions import QuotaValidationError
from nodeconductor.structure import ServiceBackendError


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
        if self.schedule.backup_type == self.schedule.BackupTypes.REGULAR:
            self._create_regular_backup()
        elif self.schedule.backup_type == self.schedule.BackupTypes.DR:
            self._create_dr_backup()

    def _create_regular_backup(self):
        if not self.check_instance_state():
            return

        kept_until = timezone.now() + \
            timezone.timedelta(days=self.schedule.retention_time) if self.schedule.retention_time else None
        backup = self.schedule.backups.create(
            instance=self.schedule.instance, kept_until=kept_until, description='scheduled backup')
        backend = backup.get_backend()
        backend.start_backup()
        return backup

    def _create_dr_backup(self):
        from . import models, executors, serializers
        kept_until = timezone.now() + \
            timezone.timedelta(days=self.schedule.retention_time) if self.schedule.retention_time else None

        dr_backup = models.DRBackup.objects.create(
            source_instance=self.schedule.instance,
            name='DR backup of instance "%s"' % self.schedule.instance,
            description='Scheduled DR backup.',
            tenant=self.schedule.instance.tenant,
            service_project_link=self.schedule.instance.service_project_link,
            metadata=self.schedule.instance.as_dict(),
            backup_schedule=self.schedule,
        )
        try:
            serializers.create_dr_backup_related_resources(dr_backup)
        except QuotaValidationError as e:
            message = 'Failed to schedule backup creation. Error: %s' % e
            logger.exception('Backup schedule (PK: %s) execution failed. %s' % (self.schedule.pk, message))
            raise BackupError(message)
        else:
            dr_backup.kept_until = kept_until
            dr_backup.save()
            executors.DRBackupCreateExecutor.execute(dr_backup)

    def delete_extra_backups(self):
        """
        Deletes oldest existing backups if maximal_number_of_backups was reached
        """
        if self.schedule.backup_type == self.schedule.BackupTypes.REGULAR:
            self._delete_regular_backups()
        elif self.schedule.backup_type == self.schedule.BackupTypes.DR:
            self._delate_dr_backups()

    def _delete_regular_backups(self):
        states = self.schedule.backups.model.States
        exclude_states = (states.DELETING, states.DELETED, states.ERRED)
        stable_backups = self.schedule.backups.exclude(state__in=exclude_states)
        extra_backups_count = stable_backups.count() - self.schedule.maximal_number_of_backups
        if extra_backups_count > 0:
            for backup in stable_backups.order_by('created_at')[:extra_backups_count]:
                backend = backup.get_backend()
                backend.start_deletion()

    def _delate_dr_backups(self):
        from . import executors
        states = self.schedule.dr_backups.model.States
        stable_dr_backups = self.schedule.dr_backups.filter(state=states.OK)
        extra_backups_count = stable_dr_backups.count() - self.schedule.maximal_number_of_backups
        if extra_backups_count > 0:
            for dr_backup in stable_dr_backups.order_by('created')[:extra_backups_count]:
                executors.DRBackupDeleteExecutor.execute(dr_backup)

    def execute(self):
        """
        Creates new backup, deletes existing if maximal_number_of_backups was
        reached, calculates new next_trigger_at time.
        """
        try:
            self.create_backup()
        except BackupError as e:
            self.schedule.runtime_state = str(e)
            self.schedule.is_active = False
        else:
            self.schedule.runtime_state = 'Successfully started backup creation.'
        finally:
            self.delete_extra_backups()
            self.schedule.update_next_trigger_at()
            self.schedule.save()


class BackupBackend(object):

    def __init__(self, backup):
        self.backup = backup

    def start_backup(self):
        self.backup.starting_backup()
        self.backup.save(update_fields=['state'])
        send_task('openstack', 'backup_start_create')(self.backup.uuid.hex)

    def start_deletion(self):
        self.backup.starting_deletion()
        self.backup.save(update_fields=['state'])
        send_task('openstack', 'backup_start_delete')(self.backup.uuid.hex)

    def start_restoration(self, instance_uuid, user_input, snapshot_ids):
        self.backup.starting_restoration()
        self.backup.save(update_fields=['state'])
        send_task('openstack', 'backup_start_restore')(
            self.backup.uuid.hex, instance_uuid, user_input, snapshot_ids)

    def get_metadata(self):
        # populate backup metadata
        instance = self.backup.instance
        metadata = {
            'name': instance.name,
            'description': instance.description,
            'service_project_link': instance.service_project_link.pk,
            'tenant': instance.tenant.pk,
            'system_volume_id': instance.system_volume_id,
            'system_volume_size': instance.system_volume_size,
            'data_volume_id': instance.data_volume_id,
            'data_volume_size': instance.data_volume_size,
            'min_ram': instance.min_ram,
            'min_disk': instance.min_disk,
            'key_name': instance.key_name,
            'key_fingerprint': instance.key_fingerprint,
            'user_data': instance.user_data,
            'flavor_name': instance.flavor_name,
            'image_name': instance.image_name,
            'tags': [tag.name for tag in instance.tags.all()],
        }
        return metadata

    def create(self):
        instance = self.backup.instance
        quota_errors = instance.tenant.validate_quota_change({
            'storage': instance.system_volume_size + instance.data_volume_size
        })

        if quota_errors:
            raise BackupError('No space for instance %s backup' % instance.uuid.hex)

        try:
            backend = instance.get_backend()
            snapshots = backend.create_snapshots(
                tenant=instance.tenant,
                volume_ids=[instance.system_volume_id, instance.data_volume_id],
                prefix='Instance %s backup: ' % instance.uuid,
            )
            system_volume_snapshot_id, data_volume_snapshot_id = snapshots
        except ServiceBackendError as e:
            six.reraise(BackupError, e)

        # populate backup metadata
        metadata = self.get_metadata()
        metadata['system_snapshot_id'] = system_volume_snapshot_id
        metadata['data_snapshot_id'] = data_volume_snapshot_id
        metadata['system_snapshot_size'] = instance.system_volume_size
        metadata['data_snapshot_size'] = instance.data_volume_size

        return metadata

    def delete(self):
        instance = self.backup.instance
        metadata = self.backup.metadata
        try:
            backend = instance.get_backend()
            backend.delete_snapshots(
                tenant=instance.tenant,
                snapshot_ids=[metadata['system_snapshot_id'], metadata['data_snapshot_id']],
            )
        except ServiceBackendError as e:
            six.reraise(BackupError, e)

    def restore(self, instance_uuid, user_input, snapshot_ids):
        instance = self.backup.instance.__class__.objects.get(uuid=instance_uuid)
        backend = instance.get_backend()

        # restore tags
        tags = self.backup.metadata.get('tags')
        if tags and isinstance(tags, list):
            instance.tags.add(*tags)

        # restore user_data
        user_data = self.backup.metadata.get('user_data')
        if user_data:
            instance.user_data = user_data

        # create a copy of the volumes to be used by a new VM
        try:
            cloned_volumes_ids = backend.promote_snapshots_to_volumes(
                tenant=instance.tenant,
                snapshot_ids=snapshot_ids,
                prefix='Restored volume'
            )
        except ServiceBackendError as e:
            six.reraise(BackupError, e)

        from nodeconductor_openstack.models import Flavor

        flavor = Flavor.objects.get(uuid=user_input['flavor_uuid'])

        backend.provision(
            instance,
            flavor=flavor,
            system_volume_id=cloned_volumes_ids[0],
            data_volume_id=cloned_volumes_ids[1],
            skip_external_ip_assignment=True)

    def deserialize(self, user_raw_input):
        metadata = self.backup.metadata
        user_input = {
            'name': user_raw_input.get('name'),
            'flavor': user_raw_input.get('flavor'),
        }

        # overwrite metadata attributes with user provided ones
        input_parameters = dict(metadata.items() + [u for u in user_input.items() if u[1] is not None])
        # special treatment for volume sizes -- they will be created equal to snapshot sizes
        try:
            input_parameters['system_volume_size'] = metadata['system_snapshot_size']
            input_parameters['data_volume_size'] = metadata['data_snapshot_size']
        except (KeyError, IndexError):
            return None, None, None, 'Missing system_snapshot_size or data_snapshot_size in metadata'

        # import here to avoid circular dependency
        from nodeconductor_openstack.serializers import BackupRestorationSerializer
        serializer = BackupRestorationSerializer(data=input_parameters)

        if serializer.is_valid():
            try:
                system_volume_snapshot_id = metadata['system_snapshot_id']
                data_volume_snapshot_id = metadata['data_snapshot_id']
            except (KeyError, IndexError):
                return None, None, None, 'Missing system_snapshot_id or data_snapshot_id in metadata'

            # all user_input should be json serializable
            user_input = {'flavor_uuid': serializer.validated_data.pop('flavor').uuid.hex}
            instance = serializer.save()
            # note that root/system volumes of a backup will be linked to the volumes belonging to a backup
            return instance, user_input, [system_volume_snapshot_id, data_volume_snapshot_id], None

        # if there were errors in input parameters
        errors = dict(serializer.errors)

        try:
            non_field_errors = errors.pop('non_field_errors')
            errors['detail'] = non_field_errors[0]
        except (KeyError, IndexError):
            pass

        return None, None, None, errors
