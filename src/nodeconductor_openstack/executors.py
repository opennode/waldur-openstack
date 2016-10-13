import logging

from celery import chain

from nodeconductor.core import tasks as core_tasks, executors as core_executors, utils as core_utils

from . import tasks
from .log import event_logger


logger = logging.getLogger(__name__)


class SecurityGroupCreateExecutor(core_executors.CreateExecutor):

    @classmethod
    def get_task_signature(cls, security_group, serialized_security_group, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_security_group, 'create_security_group', state_transition='begin_creating')


class SecurityGroupUpdateExecutor(core_executors.UpdateExecutor):

    @classmethod
    def get_task_signature(cls, security_group, serialized_security_group, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_security_group, 'update_security_group', state_transition='begin_updating')


class SecurityGroupDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def get_task_signature(cls, security_group, serialized_security_group, **kwargs):
        if security_group.backend_id:
            return core_tasks.BackendMethodTask().si(
                serialized_security_group, 'delete_security_group', state_transition='begin_deleting')
        else:
            return core_tasks.StateTransitionTask().si(serialized_security_group, state_transition='begin_deleting')


class TenantCreateExecutor(core_executors.CreateExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, pull_security_groups=True, **kwargs):
        # create tenant, add user to it, create internal network, pull quotas
        creation_tasks = [
            core_tasks.BackendMethodTask().si(
                serialized_tenant, 'create_tenant',
                state_transition='begin_creating',
                runtime_state='creating tenant'),
            core_tasks.BackendMethodTask().si(
                serialized_tenant, 'add_admin_user_to_tenant',
                runtime_state='adding global admin user to tenant'),
            core_tasks.BackendMethodTask().si(
                serialized_tenant, 'create_tenant_user',
                runtime_state='creating tenant user'),
            core_tasks.BackendMethodTask().si(
                serialized_tenant, 'create_internal_network',
                runtime_state='creating internal network for tenant'),
        ]
        quotas = tenant.quotas.all()
        quotas = {q.name: int(q.limit) if q.limit.is_integer() else q.limit for q in quotas}
        creation_tasks.append(core_tasks.BackendMethodTask().si(
            serialized_tenant, 'push_tenant_quotas', quotas,
            runtime_state='pushing tenant quotas',
            success_runtime_state='online')
        )
        # handle security groups
        # XXX: Create default security groups that was connected to SPL earlier.
        serialized_executor = core_utils.serialize_class(SecurityGroupCreateExecutor)
        for security_group in tenant.security_groups.all():
            serialized_security_group = core_utils.serialize_instance(security_group)
            creation_tasks.append(core_tasks.ExecutorTask().si(serialized_executor, serialized_security_group))

        if pull_security_groups:
            creation_tasks.append(core_tasks.BackendMethodTask().si(
                serialized_tenant, 'pull_tenant_security_groups',
                runtime_state='pulling tenant security groups',
                success_runtime_state='online')
            )

        # initialize external network if it defined in service settings
        service_settings = tenant.service_project_link.service.settings
        external_network_id = service_settings.get_option('external_network_id')
        if external_network_id:
            creation_tasks.append(core_tasks.BackendMethodTask().si(
                serialized_tenant, 'connect_tenant_to_external_network',
                external_network_id=external_network_id,
                runtime_state='connecting tenant to external network',
                success_runtime_state='online')
            )

        return chain(*creation_tasks)


class TenantUpdateExecutor(core_executors.UpdateExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        updated_fields = kwargs['updated_fields']
        if 'name' in updated_fields or 'description' in updated_fields:
            return core_tasks.BackendMethodTask().si(
                serialized_tenant, 'update_tenant', state_transition='begin_updating')
        else:
            return core_tasks.StateTransitionTask().si(serialized_tenant, state_transition='begin_updating')


class TenantDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        if tenant.backend_id:
            return core_tasks.BackendMethodTask().si(
                serialized_tenant, 'cleanup_tenant', dryrun=False, state_transition='begin_deleting')
        else:
            return core_tasks.StateTransitionTask().si(serialized_tenant, state_transition='begin_deleting')


class TenantAllocateFloatingIPExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'allocate_floating_ip_address',
            state_transition='begin_updating',
            runtime_state='allocating floating ip',
            success_runtime_state='online')


class TenantDeleteExternalNetworkExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'delete_external_network',
            state_transition='begin_updating',
            runtime_state='deleting external network',
            success_runtime_state='online')


class TenantCreateExternalNetworkExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, external_network_data=None, **kwargs):
        if external_network_data is None:
            raise core_executors.ExecutorException(
                'Argument `external_network_data` should be specified for TenantCreateExcternalNetworkExecutor')
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'create_external_network',
            state_transition='begin_updating',
            runtime_state='creating external network',
            success_runtime_state='online',
            **external_network_data)


class TenantPushQuotasExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, quotas=None, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'push_tenant_quotas', quotas,
            state_transition='begin_updating',
            runtime_state='updating quotas',
            success_runtime_state='online')


class TenantPullExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'pull_tenant',
            state_transition='begin_updating')


class TenantPullSecurityGroupsExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'pull_tenant_security_groups',
            state_transition='begin_updating')


class TenantDetectExternalNetworkExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'detect_external_network',
            state_transition='begin_updating')


class TenantPullFloatingIPsExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'pull_tenant_floating_ips',
            state_transition='begin_updating')


class TenantPullQuotasExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'pull_tenant_quotas',
            state_transition='begin_updating')


class VolumeCreateExecutor(core_executors.CreateExecutor):

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        return chain(
            tasks.ThrottleProvisionTask().si(
                serialized_volume,
                'create_volume',
                state_transition='begin_creating'
            ),
            tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error',
            ).set(countdown=30)
        )


class VolumeUpdateExecutor(core_executors.UpdateExecutor):

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        updated_fields = kwargs['updated_fields']
        # TODO: call separate task on metadata update
        if 'name' in updated_fields or 'description' in updated_fields:
            return core_tasks.BackendMethodTask().si(
                serialized_volume, 'update_volume', state_transition='begin_updating')
        else:
            return core_tasks.StateTransitionTask().si(serialized_volume, state_transition='begin_updating')


class VolumeDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        if volume.backend_id:
            return chain(
                core_tasks.BackendMethodTask().si(
                    serialized_volume, 'delete_volume', state_transition='begin_deleting'),
                tasks.PollBackendCheckTask().si(serialized_volume, 'is_volume_deleted'),
            )
        else:
            return core_tasks.StateTransitionTask().si(serialized_volume, state_transition='begin_deleting')


class VolumePullExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_volume, 'pull_volume',
            state_transition='begin_updating')


class SnapshotCreateExecutor(core_executors.CreateExecutor):

    @classmethod
    def get_task_signature(cls, snapshot, serialized_snapshot, **kwargs):
        return chain(
            tasks.ThrottleProvisionTask().si(
                serialized_snapshot,
                'create_snapshot',
                state_transition='begin_creating'
            ),
            tasks.PollRuntimeStateTask().si(
                serialized_snapshot,
                backend_pull_method='pull_snapshot_runtime_state',
                success_state='available',
                erred_state='error',
            ).set(countdown=10)
        )


class SnapshotUpdateExecutor(core_executors.UpdateExecutor):

    @classmethod
    def get_task_signature(cls, snapshot, serialized_snapshot, **kwargs):
        updated_fields = kwargs['updated_fields']
        # TODO: call separate task on metadata update
        if 'name' in updated_fields or 'description' in updated_fields:
            return core_tasks.BackendMethodTask().si(
                serialized_snapshot, 'update_snapshot', state_transition='begin_updating')
        else:
            return core_tasks.StateTransitionTask().si(serialized_snapshot, state_transition='begin_updating')


class SnapshotDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def get_task_signature(cls, snapshot, serialized_snapshot, **kwargs):
        if snapshot.backend_id:
            return chain(
                core_tasks.BackendMethodTask().si(
                    serialized_snapshot, 'delete_snapshot', state_transition='begin_deleting'),
                tasks.PollBackendCheckTask().si(serialized_snapshot, 'is_snapshot_deleted'),
            )
        else:
            return core_tasks.StateTransitionTask().si(serialized_snapshot, state_transition='begin_deleting')


class SnapshotPullExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, snapshot, serialized_snapshot, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_snapshot, 'pull_snapshot',
            state_transition='begin_updating')


class DRBackupCreateExecutor(core_executors.BaseExecutor):
    """ Create backup for each instance volume separately using temporary volumes and snapshots """

    @classmethod
    def get_task_signature(cls, dr_backup, serialized_dr_backup, **kwargs):
        volumes_backups = dr_backup.volume_backups.all()
        tmp_volumes = [volume_backup.source_volume for volume_backup in volumes_backups]
        tmp_snapshots = [tmp_volume.source_snapshot for tmp_volume in tmp_volumes]

        serialized_volume_backups = [
            core_utils.serialize_instance(volumes_backup) for volumes_backup in volumes_backups]
        serialized_tmp_volumes = [core_utils.serialize_instance(tmp_volume) for tmp_volume in tmp_volumes]
        serialized_tmp_snapshots = [core_utils.serialize_instance(tmp_snapshot) for tmp_snapshot in tmp_snapshots]

        _tasks = [
            core_tasks.StateTransitionTask().si(serialized_dr_backup, state_transition='begin_creating'),
        ]

        # Part 1. Temporary snapshots
        _tasks.append(
            core_tasks.RuntimeStateChangeTask().si(serialized_dr_backup, runtime_state='Creating temporary snapshots'))
        # create temporary snapshots
        for serialized_tmp_snapshot in serialized_tmp_snapshots:
            _tasks.append(tasks.ThrottleProvisionTask().si(
                serialized_tmp_snapshot,
                'create_snapshot',
                force=True,
                state_transition='begin_creating'
            ))
        # wait for snapshots creation
        for serialized_tmp_snapshot in serialized_tmp_snapshots:
            _tasks.append(tasks.PollRuntimeStateTask().si(
                serialized_tmp_snapshot,
                backend_pull_method='pull_snapshot_runtime_state',
                success_state='available',
                erred_state='error',
            ).set(countdown=10))
        # mark snapshots as OK on success creation
        for serialized_tmp_snapshot in serialized_tmp_snapshots:
            _tasks.append(core_tasks.StateTransitionTask().si(serialized_tmp_snapshot, state_transition='set_ok'))

        # Part 2. Temporary volumes
        # Countdown added make sure that volume creation starts in 10 seconds
        # after snapshot creation due to OpenStack internal restrictions
        _tasks.append(core_tasks.RuntimeStateChangeTask().si(
            serialized_dr_backup, runtime_state='Creating temporary volumes').set(countdown=10))
        # Create temporary volumes from temporary snapshots
        for serialized_tmp_volume in serialized_tmp_volumes:
            _tasks.append(tasks.ThrottleProvisionTask().si(
                serialized_tmp_volume,
                'create_volume',
                state_transition='begin_creating'
            ))
            # Wait for volumes creation
            _tasks.append(tasks.PollRuntimeStateTask().si(
                serialized_tmp_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error',
            ).set(countdown=30))
            # Mark volumes as OK on success creation
            _tasks.append(core_tasks.StateTransitionTask().si(serialized_tmp_volume, state_transition='set_ok'))

        # Part 3. Backups of temporary volumes
        # Countdown added make sure that backup creation starts in 10 seconds
        # after volume creation due to OpenStack internal restrictions
        _tasks.append(core_tasks.RuntimeStateChangeTask().si(
            serialized_dr_backup, runtime_state='Creating volume backups').set(countdown=10))
        # Create backup of temporary volume
        for serialized_volume_backup in serialized_volume_backups:
            _tasks.append(core_tasks.BackendMethodTask().si(
                serialized_volume_backup, 'create_volume_backup', state_transition='begin_creating'))
        # Wait for backups creation
        for index, serialized_volume_backup in enumerate(serialized_volume_backups):
            _tasks.append(tasks.PollRuntimeStateTask().si(
                serialized_volume_backup,
                backend_pull_method='pull_volume_backup_runtime_state',
                success_state='available',
                erred_state='error',
            ).set(countdown=50 if index == 0 else 0))
            # Pull backup record and mark it as OK on success creation
            _tasks.append(core_tasks.BackendMethodTask().si(serialized_volume_backup, 'pull_volume_backup_record'))
            _tasks.append(core_tasks.StateTransitionTask().si(serialized_volume_backup, state_transition='set_ok'))

        return chain(*_tasks)

    @classmethod
    def get_success_signature(cls, dr_backup, serialized_dr_backup, **kwargs):
        # mark DR backup as OK and delete all temporary objects - volumes and snapshots
        return tasks.CleanUpDRBackupTask().si(serialized_dr_backup, state_transition='set_ok').set(countdown=10)

    @classmethod
    def get_failure_signature(cls, dr_backup, serialized_dr_backup, **kwargs):
        # mark DR and all related non-OK resources as Erred
        return tasks.SetDRBackupErredTask().s(serialized_dr_backup)


class DRBackupDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def pre_apply(cls, dr_backup, **kwargs):
        for volume_backup in dr_backup.volume_backups.all():
            volume_backup.schedule_deleting()
            volume_backup.save(update_fields=['state'])
        core_executors.DeleteExecutor.pre_apply(dr_backup)

    @classmethod
    def get_task_signature(cls, dr_backup, serialized_dr_backup, force=False, **kwargs):
        _tasks = [
            core_tasks.StateTransitionTask().si(serialized_dr_backup, state_transition='begin_deleting'),
            core_tasks.RuntimeStateChangeTask().si(serialized_dr_backup, runtime_state='Deleting volume backups'),
            tasks.CleanUpDRBackupTask().si(serialized_dr_backup, force=force),  # remove temporary volumes and snapshots
        ]
        # Remove volume backups
        serialized_volume_backups = [
            core_utils.serialize_instance(volume_backup) for volume_backup in dr_backup.volume_backups.all()]
        # Start volume backups deletion
        for serialized_volume_backup in serialized_volume_backups:
            _tasks.append(core_tasks.BackendMethodTask().si(
                serialized_volume_backup, 'delete_volume_backup', state_transition='begin_deleting'))
        # Poll for deletion and delete backups from NodeConductor database
        for serialized_volume_backup in serialized_volume_backups:
            _tasks.append(tasks.PollBackendCheckTask().si(serialized_volume_backup, 'is_volume_backup_deleted'))
            _tasks.append(core_tasks.DeletionTask().si(serialized_volume_backup))

        return chain(*_tasks)

    @classmethod
    def get_failure_signature(cls, dr_backup, serialized_dr_backup, force=False, **kwargs):
        # Mark DR and all related non-OK resources as Erred
        if not force:
            return tasks.SetDRBackupErredTask().s(serialized_dr_backup)
        else:
            return tasks.ForceDeleteDRBackupTask().s(serialized_dr_backup)


class DRBackupRestorationCreateExecutor(core_executors.CreateExecutor):
    """ DRBackup restoration process creates new volumes and restores backups. """

    @classmethod
    def get_task_signature(cls, dr_backup_restoration, serialized_dr_backup_restoration, **kwargs):
        """ Restore each volume backup on separate volume. """
        volume_backup_restorations = dr_backup_restoration.volume_backup_restorations.all()
        volume_backups = [
            volume_backup_restoration.volume_backup for volume_backup_restoration in volume_backup_restorations]
        volumes = [volume_backup_restoration.volume for volume_backup_restoration in volume_backup_restorations]
        mirrored_backups = [volume_backup_restoration.mirorred_volume_backup
                            for volume_backup_restoration in volume_backup_restorations]

        serialized_instance = core_utils.serialize_instance(dr_backup_restoration.instance)
        serialized_volume_backups = [core_utils.serialize_instance(volume_backup) for volume_backup in volume_backups]
        serialized_volumes = [core_utils.serialize_instance(volume) for volume in volumes]
        serialized_mirrored_backups = [
            core_utils.serialize_instance(mirrored_backup)
            for mirrored_backup in mirrored_backups]

        _tasks = [
            tasks.ThrottleProvisionStateTask().si(
                serialized_instance,
                state_transition='begin_provisioning'
            )
        ]
        # Create empty volumes for instance
        for serialized_volume in serialized_volumes:
            _tasks.append(tasks.ThrottleProvisionTask().si(
                serialized_volume, 'create_volume', state_transition='begin_creating'))
            # Wait for volumes creation
            _tasks.append(tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error',
            ).set(countdown=30))
        # Import backups
        for serialized_mirrored_backup in serialized_mirrored_backups:
            _tasks.append(core_tasks.BackendMethodTask().si(
                serialized_mirrored_backup, 'import_volume_backup_from_record',
                state_transition='begin_creating'))
        # Wait for backups import
        for serialized_mirrored_backup in serialized_mirrored_backups:
            _tasks.append(tasks.PollRuntimeStateTask().si(
                serialized_mirrored_backup,
                backend_pull_method='pull_volume_backup_runtime_state',
                success_state='available',
                erred_state='error',
            ))
            # Mark backup as OK on success import
            _tasks.append(core_tasks.StateTransitionTask().si(
                serialized_mirrored_backup, state_transition='set_ok'))
        # Restore backups on volumes
        for serialized_volume, serialized_mirrored_backup in zip(serialized_volumes, serialized_mirrored_backups):
            _tasks.append(tasks.RestoreVolumeBackupTask().si(serialized_mirrored_backup, serialized_volume))
        # Wait for volumes restoration
        for index, serialized_volume in enumerate(serialized_volumes):
            _tasks.append(tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error_restoring',
            ).set(countdown=20 if index == 0 else 0))
            # Pull volume to make sure it reflects restored data
            _tasks.append(core_tasks.BackendMethodTask().si(serialized_volume, 'pull_volume'))
        # After restoration volumes will have names of temporary copied for backup volumes, we need to rename them.
        # This task should be deleted if backend will be done from origin volume, not its temporary copy.
        for serialized_volume_backup, serialized_volume in zip(serialized_volume_backups, serialized_volumes):
            _tasks.append(tasks.RestoreVolumeOriginNameTask().si(serialized_volume_backup, serialized_volume))
            _tasks.append(core_tasks.StateTransitionTask().si(serialized_volume, state_transition='set_ok'))
        # Create instance based on restored volumes.
        # Wait 10 seconds before instance creation due to OpenStack restrictions.
        _tasks.append(tasks.CreateInstanceFromVolumesTask().si(serialized_dr_backup_restoration).set(countdown=10))
        return chain(*_tasks)

    @classmethod
    def get_success_signature(cls, dr_backup_restoration, serialized_dr_backup_restoration, **kwargs):
        serialized_instance = core_utils.serialize_instance(dr_backup_restoration.instance)
        return tasks.SuccessRestorationTask().si(serialized_instance, state_transition='set_online')

    @classmethod
    def get_failure_signature(cls, dr_backup_restoration, serialized_dr_backup_restoration, **kwargs):
        return tasks.SetDRBackupRestorationErredTask().s(serialized_dr_backup_restoration)


class InstanceCreateExecutor(core_executors.CreateExecutor):
    """ First - create instance volumes in parallel, after - create instance based on created volumes """

    @classmethod
    def get_task_signature(cls, instance, serialized_instance,
                           ssh_key=None, flavor=None, floating_ip=None, skip_external_ip_assignment=False):
        """ Create all instance volumes in parallel and wait for them to provision """
        serialized_volumes = [core_utils.serialize_instance(volume) for volume in instance.volumes.all()]

        _tasks = [tasks.ThrottleProvisionStateTask().si(serialized_instance, state_transition='begin_provisioning')]
        # Create volumes
        for serialized_volume in serialized_volumes:
            _tasks.append(tasks.ThrottleProvisionTask().si(
                serialized_volume, 'create_volume', state_transition='begin_creating'))
        for index, serialized_volume in enumerate(serialized_volumes):
            # Wait for volume creation
            _tasks.append(tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error',
            ).set(countdown=30 if index == 0 else 0))
            # Pull volume to sure that it is bootable
            _tasks.append(core_tasks.BackendMethodTask().si(serialized_volume, 'pull_volume'))
            # Mark volume as OK
            _tasks.append(core_tasks.StateTransitionTask().si(serialized_volume, state_transition='set_ok'))
        # Create instance based on volumes
        kwargs = {
            'backend_flavor_id': flavor.backend_id,
            'skip_external_ip_assignment': skip_external_ip_assignment,
        }
        if ssh_key is not None:
            kwargs['public_key'] = ssh_key.public_key
        if floating_ip is not None:
            kwargs['floating_ip_uuid'] = floating_ip.uuid.hex
        # Wait 10 seconds after volume creation due to OpenStack restrictions.
        _tasks.append(core_tasks.BackendMethodTask().si(
            serialized_instance, 'create_instance', **kwargs).set(countdown=10))

        return chain(*_tasks)

    @classmethod
    def get_success_signature(cls, instance, serialized_instance, **kwargs):
        # XXX: This method is overridden to support old-style states.
        return core_tasks.StateTransitionTask().si(serialized_instance, state_transition='set_online')

    @classmethod
    def get_failure_signature(cls, instance, serialized_instance, **kwargs):
        return tasks.SetInstanceErredTask().s(serialized_instance)


class InstanceUpdateExecutor(core_executors.BaseExecutor):
    # TODO: After instance state refactoring:
    #        - update security groups only if they were changed
    #        - change instance state on update (inherit this executor from UpdateExecutor)

    @classmethod
    def get_task_signature(cls, instance, serialized_instance, **kwargs):
        updated_fields = kwargs['updated_fields']
        _tasks = [core_tasks.BackendMethodTask().si(serialized_instance, 'push_instance_security_groups')]
        if 'name' in updated_fields and instance.backend_id:
            _tasks.append(core_tasks.BackendMethodTask().si(serialized_instance, 'update_instance'))
        return chain(*_tasks)


class InstanceDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def pre_apply(cls, instance, **kwargs):
        instance.schedule_deletion()
        instance.save(update_fields=['state'])

    @classmethod
    def get_task_signature(cls, instance, serialized_instance, force=False, **kwargs):
        delete_volumes = kwargs.pop('delete_volumes', True)
        delete_instance = cls.get_delete_instance_tasks(serialized_instance)

        # Case 1. Instance does not exist at backend
        if not instance.backend_id:
            return core_tasks.StateTransitionTask().si(
                serialized_instance,
                state_transition='begin_deleting'
            )

        # Case 2. Instance exists at backend.
        # Data volumes are deleted by OpenStack because delete_on_termination=True
        elif delete_volumes:
            return chain(delete_instance)

        # Case 3. Instance exists at backend.
        # Data volumes are detached and not deleted.
        else:
            detach_volumes = cls.get_detach_data_volumes_tasks(instance, serialized_instance)
            return chain(detach_volumes + delete_instance)

    @classmethod
    def get_delete_instance_tasks(cls, serialized_instance):
        return [
            core_tasks.BackendMethodTask().si(
                serialized_instance,
                backend_method='delete_instance',
                state_transition='begin_deleting',
            ),
            tasks.PollBackendCheckTask().si(
                serialized_instance,
                backend_check_method='is_instance_deleted'
            ),
            core_tasks.BackendMethodTask().si(
                serialized_instance,
                backend_method='pull_instance_volumes'
            )
        ]

    @classmethod
    def get_detach_data_volumes_tasks(cls, instance, serialized_instance):
        data_volumes = instance.volumes.all().filter(bootable=False)
        detach_volumes = [
            core_tasks.BackendMethodTask().si(
                core_utils.serialize_instance(volume),
                backend_method='detach_volume',
            )
            for volume in data_volumes
        ]
        check_volumes = [
            tasks.PollRuntimeStateTask().si(
                core_utils.serialize_instance(volume),
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error'
            )
            for volume in data_volumes
        ]
        return detach_volumes + check_volumes


class InstanceFlavorChangeExecutor(core_executors.BaseExecutor):

    @classmethod
    def pre_apply(cls, instance, **kwargs):
        instance.schedule_resizing()
        instance.save(update_fields=['state'])

        event_logger.openstack_flavor.info(
            'Virtual machine {resource_name} has been scheduled to change flavor.',
            event_type='resource_flavor_change_scheduled',
            event_context={'resource': instance, 'flavor': kwargs['flavor']}
        )

    @classmethod
    def get_task_signature(cls, instance, serialized_instance, **kwargs):
        flavor = kwargs.pop('flavor')
        return chain(
            core_tasks.BackendMethodTask().si(
                serialized_instance,
                backend_method='resize_instance',
                state_transition='begin_resizing',
                flavor_id=flavor.backend_id
            ),
            tasks.PollRuntimeStateTask().si(
                serialized_instance,
                backend_pull_method='pull_instance_runtime_state',
                success_state='VERIFY_RESIZE',
                erred_state='ERRED'
            ),
            core_tasks.BackendMethodTask().si(
                serialized_instance,
                backend_method='confirm_instance_resize'
            ),
            tasks.PollRuntimeStateTask().si(
                serialized_instance,
                backend_pull_method='pull_instance_runtime_state',
                success_state='SHUTOFF',
                erred_state='ERRED'
            ),
        )

    @classmethod
    def get_success_signature(cls, instance, serialized_instance, **kwargs):
        flavor = kwargs.pop('flavor')
        return tasks.LogFlavorChangeSucceeded().si(
            serialized_instance, core_utils.serialize_instance(flavor), state_transition='set_resized')

    @classmethod
    def get_failure_signature(cls, instance, serialized_instance, **kwargs):
        flavor = kwargs.pop('flavor')
        return tasks.LogFlavorChangeFailed().s(serialized_instance, core_utils.serialize_instance(flavor))


class InstancePullExecutor(core_executors.BaseExecutor):
    @classmethod
    def pre_apply(cls, instance, **kwargs):
        # XXX: Should be changed after migrating from the old-style states (NC-1207).
        logger.info("About to pull instance with uuid %s from the backend.", instance.uuid.hex)

    @classmethod
    def get_task_signature(cls, instance, serialized_instance, **kwargs):
        # XXX: State transition should be added after migrating from the old-style states (NC-1207).
        return core_tasks.BackendMethodTask().si(serialized_instance, backend_method='pull_instance')

    @classmethod
    def get_success_signature(cls, instance, serialized_instance, **kwargs):
        # XXX: On success instance's state is pulled from the backend. Must be changed in NC-1207.
        logger.info("Successfully pulled data from the backend for instance with uuid %s", instance.uuid.hex)

    @classmethod
    def get_failure_signature(cls, instance, serialized_instance, **kwargs):
        # XXX: This method is overridden to support old-style states. Must be changed in NC-1207.
        return core_tasks.StateTransitionTask().si(serialized_instance, state_transition='set_erred')


class VolumeExtendExecutor(core_executors.ActionExecutor):

    @classmethod
    def pre_apply(cls, volume, **kwargs):
        super(VolumeExtendExecutor, cls).pre_apply(volume, **kwargs)
        new_size = kwargs.pop('new_size')

        if volume.instance:
            volume.instance.schedule_resizing()
            volume.instance.save(update_fields=['state'])

            event_logger.openstack_volume.info(
                'Virtual machine {resource_name} has been scheduled to extend disk.',
                event_type='resource_volume_extension_scheduled',
                event_context={
                    'resource': volume.instance,
                    'volume_size': new_size
                }
            )

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        new_size = kwargs.pop('new_size')

        extend = [
            tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error'
            ),
            core_tasks.BackendMethodTask().si(
                serialized_volume,
                backend_method='extend_volume',
                new_size=new_size,
                state_transition='begin_updating'
            ),
            tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error'
            )
        ]

        check = tasks.PollRuntimeStateTask().si(
            serialized_volume,
            backend_pull_method='pull_volume_runtime_state',
            success_state='in-use',
            erred_state='error'
        )

        if volume.instance:
            detach = core_tasks.BackendMethodTask().si(
                serialized_volume,
                backend_method='detach_volume',
                state_transition='begin_resizing',
            )
            attach = core_tasks.BackendMethodTask().si(
                serialized_volume,
                backend_method='attach_volume',
            )
            return chain([detach] + extend + [attach, check])

        return chain(extend + [check])

    @classmethod
    def get_success_signature(cls, volume, serialized_volume, **kwargs):
        new_size = kwargs.pop('new_size')
        return tasks.LogVolumeExtendSucceeded().si(serialized_volume, state_transition='set_ok', new_size=new_size)

    @classmethod
    def get_failure_signature(cls, volume, serialized_volume, **kwargs):
        new_size = kwargs.pop('new_size')
        return tasks.LogVolumeExtendFailed().s(serialized_volume, new_size=new_size)


class VolumeAttachExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        return chain(
            core_tasks.BackendMethodTask().si(
                serialized_volume, backend_method='attach_volume', state_transition='begin_updating'),
            tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='in-use',
                erred_state='error',
            ),
            # additional pull to populate field "device".
            core_tasks.BackendMethodTask().si(serialized_volume, backend_method='pull_volume'),
        )


class VolumeDetachExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        return chain(
            core_tasks.BackendMethodTask().si(
                serialized_volume, backend_method='detach_volume', state_transition='begin_updating'),
            tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error',
            )
        )


class BackupCreateExecutor(core_executors.CreateExecutor):

    @classmethod
    def get_task_signature(cls, backup, serialized_backup, **kwargs):
        serialized_snapshots = [core_utils.serialize_instance(snapshot) for snapshot in backup.snapshots.all()]

        _tasks = [core_tasks.StateTransitionTask().si(serialized_backup, state_transition='begin_creating')]
        for serialized_snapshot in serialized_snapshots:
            _tasks.append(tasks.ThrottleProvisionTask().si(
                serialized_snapshot, 'create_snapshot', force=True, state_transition='begin_creating'))
        for index, serialized_snapshot in enumerate(serialized_snapshots):
            _tasks.append(tasks.PollRuntimeStateTask().si(
                serialized_snapshot,
                backend_pull_method='pull_snapshot_runtime_state',
                success_state='available',
                erred_state='error',
            ).set(countdown=10 if index == 0 else 0))
            _tasks.append(core_tasks.StateTransitionTask().si(serialized_snapshot, state_transition='set_ok'))

        return chain(*_tasks)

    @classmethod
    def get_failure_signature(cls, backup, serialized_backup, **kwargs):
        return tasks.SetBackupErredTask().s(serialized_backup)


class BackupDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def pre_apply(cls, backup, **kwargs):
        for snapshot in backup.snapshots.all():
            snapshot.schedule_deleting()
            snapshot.save(update_fields=['state'])
        core_executors.DeleteExecutor.pre_apply(backup)

    @classmethod
    def get_task_signature(cls, backup, serialized_backup, force=False, **kwargs):
        serialized_snapshots = [core_utils.serialize_instance(snapshot) for snapshot in backup.snapshots.all()]

        _tasks = [core_tasks.StateTransitionTask().si(serialized_backup, state_transition='begin_deleting')]
        for serialized_snapshot in serialized_snapshots:
            _tasks.append(core_tasks.BackendMethodTask().si(
                serialized_snapshot, 'delete_snapshot', state_transition='begin_deleting'))
        for serialized_snapshot in serialized_snapshots:
            _tasks.append(tasks.PollBackendCheckTask().si(serialized_snapshot, 'is_snapshot_deleted'))
            _tasks.append(core_tasks.DeletionTask().si(serialized_snapshot))

        return chain(*_tasks)

    @classmethod
    def get_failure_signature(cls, backup, serialized_backup, force=False, **kwargs):
        if not force:
            return tasks.SetBackupErredTask().s(serialized_backup)
        else:
            return tasks.ForceDeleteBackupTask().s(serialized_backup)


class BackupRestorationCreateExecutor(core_executors.CreateExecutor):
    """ Restore volumes from backup snapshots, create instance based on restored volumes """

    @classmethod
    def get_task_signature(cls, backup_restoration, serialized_backup_restoration, **kwargs):
        """ Restore each volume from snapshot """
        instance = backup_restoration.instance
        serialized_instance = core_utils.serialize_instance(instance)
        serialized_volumes = [core_utils.serialize_instance(volume) for volume in instance.volumes.all()]

        _tasks = [
            tasks.ThrottleProvisionStateTask().si(
                serialized_instance,
                state_transition='begin_provisioning'
            )
        ]
        # Create volumes
        for serialized_volume in serialized_volumes:
            _tasks.append(tasks.ThrottleProvisionTask().si(
                serialized_volume, 'create_volume', state_transition='begin_creating'))
        for index, serialized_volume in enumerate(serialized_volumes):
            # Wait for volume creation
            _tasks.append(tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error',
            ).set(countdown=30 if index == 0 else 0))
            # Pull volume to sure that it is bootable
            _tasks.append(core_tasks.BackendMethodTask().si(serialized_volume, 'pull_volume'))
            # Mark volume as OK
            _tasks.append(core_tasks.StateTransitionTask().si(serialized_volume, state_transition='set_ok'))
        # Create instance. Wait 10 seconds after volumes creation due to OpenStack restrictions.
        _tasks.append(core_tasks.BackendMethodTask().si(
            serialized_instance, 'create_instance',
            skip_external_ip_assignment=False,
            backend_flavor_id=backup_restoration.flavor.backend_id
        ).set(countdown=10))
        return chain(*_tasks)

    @classmethod
    def get_success_signature(cls, backup_restoration, serialized_backup_restoration, **kwargs):
        serialized_instance = core_utils.serialize_instance(backup_restoration.instance)
        return tasks.SuccessRestorationTask().si(serialized_instance, state_transition='set_online')

    @classmethod
    def get_failure_signature(cls, backup_restoration, serialized_backup_restoration, **kwargs):
        return tasks.SetBackupRestorationErredTask().s(serialized_backup_restoration)
