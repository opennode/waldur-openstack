import logging

from celery import chain, group

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
            return core_tasks.BackendMethodTask().si(serialized_tenant, 'update_tenant', state_transition='begin_updating')
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
            core_tasks.BackendMethodTask().si(serialized_volume, 'create_volume', state_transition='begin_creating'),
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
            return core_tasks.BackendMethodTask().si(serialized_volume, 'update_volume', state_transition='begin_updating')
        else:
            return core_tasks.StateTransitionTask().si(serialized_volume, state_transition='begin_updating')


class VolumeDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        if volume.backend_id:
            return chain(
                core_tasks.BackendMethodTask().si(serialized_volume, 'delete_volume', state_transition='begin_deleting'),
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
            core_tasks.BackendMethodTask().si(serialized_snapshot, 'create_snapshot', state_transition='begin_creating'),
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
                core_tasks.BackendMethodTask().si(serialized_snapshot, 'delete_snapshot', state_transition='begin_deleting'),
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


class DRBackupCreateExecutor(core_executors.BaseChordExecutor):
    """ Create backup for each instance volume separately using temporary volumes and snapshots """

    @classmethod
    def get_task_signature(cls, dr_backup, serialized_dr_backup, **kwargs):
        creation_tasks = [
            core_tasks.StateTransitionTask().si(serialized_dr_backup, state_transition='begin_creating'),
            core_tasks.RuntimeStateChangeTask().si(serialized_dr_backup, runtime_state='Creating temporary snapshots')
        ]
        for volume_backup in dr_backup.volume_backups.all():
            tmp_volume = volume_backup.source_volume
            tmp_snapshot = tmp_volume.source_snapshot
            serialzied_tmp_volume = core_utils.serialize_instance(tmp_volume)
            serialized_tmp_snapshot = core_utils.serialize_instance(tmp_snapshot)
            serialized_volume_backup = core_utils.serialize_instance(volume_backup)

            creation_tasks.append(chain(
                # 1. Create temporary snapshot on backend.
                core_tasks.BackendMethodTask().si(
                    serialized_tmp_snapshot, 'create_snapshot', force=True, state_transition='begin_creating'),
                tasks.PollRuntimeStateTask().si(
                    serialized_tmp_snapshot,
                    backend_pull_method='pull_snapshot_runtime_state',
                    success_state='available',
                    erred_state='error',
                ).set(countdown=10),
                core_tasks.StateTransitionTask().si(serialized_tmp_snapshot, state_transition='set_ok'),
                core_tasks.RuntimeStateChangeTask().si(serialized_dr_backup, runtime_state='Creating temporary volumes'),
                # 2. Create temporary volume on backend.
                core_tasks.BackendMethodTask().si(
                    serialzied_tmp_volume, 'create_volume', state_transition='begin_creating'),
                tasks.PollRuntimeStateTask().si(
                    serialzied_tmp_volume,
                    backend_pull_method='pull_volume_runtime_state',
                    success_state='available',
                    erred_state='error',
                ).set(countdown=30),
                core_tasks.StateTransitionTask().si(serialzied_tmp_volume, state_transition='set_ok'),
                core_tasks.RuntimeStateChangeTask().si(serialized_dr_backup, runtime_state='Backing up temporary volumes'),
                # 3. Create volume_backup on backend
                core_tasks.BackendMethodTask().si(
                    serialized_volume_backup, 'create_volume_backup', state_transition='begin_creating'),
                tasks.PollRuntimeStateTask().si(
                    serialized_volume_backup,
                    backend_pull_method='pull_volume_backup_runtime_state',
                    success_state='available',
                    erred_state='error',
                ).set(countdown=50),
                core_tasks.BackendMethodTask().si(serialized_volume_backup, 'pull_volume_backup_record'),
                core_tasks.StateTransitionTask().si(serialized_volume_backup, state_transition='set_ok'),
            ))
        return group(creation_tasks)

    @classmethod
    def get_success_signature(cls, dr_backup, serialized_dr_backup, **kwargs):
        # mark DR backup as OK and delete all temporary objects - volumes and snapshots
        return tasks.CleanUpDRBackupTask().si(serialized_dr_backup, state_transition='set_ok')

    @classmethod
    def get_failure_signature(cls, dr_backup, serialized_dr_backup, **kwargs):
        # mark DR and all related non-OK resources as Erred
        return tasks.SetDRBackupErredTask().s(serialized_dr_backup)


class DRBackupDeleteExecutor(core_executors.DeleteExecutor, core_executors.BaseChordExecutor):

    @classmethod
    def pre_apply(cls, dr_backup, **kwargs):
        for volume_backup in dr_backup.volume_backups.all():
            volume_backup.schedule_deleting()
            volume_backup.save(update_fields=['state'])
        core_executors.DeleteExecutor.pre_apply(dr_backup)

    @classmethod
    def get_task_signature(cls, dr_backup, serialized_dr_backup, force=False, **kwargs):
        deletion_tasks = [
            core_tasks.StateTransitionTask().si(serialized_dr_backup, state_transition='begin_deleting'),
            core_tasks.RuntimeStateChangeTask().si(serialized_dr_backup, runtime_state='Deleting volume backups'),
            tasks.CleanUpDRBackupTask().si(serialized_dr_backup, force=force),  # remove temporary volumes and snapshots
        ]
        # remove volume backups
        for volume_backup in dr_backup.volume_backups.all():
            serialized = core_utils.serialize_instance(volume_backup)
            deletion_tasks.append(chain(
                core_tasks.BackendMethodTask().si(serialized, 'delete_volume_backup', state_transition='begin_deleting'),
                tasks.PollBackendCheckTask().si(serialized, 'is_volume_backup_deleted'),
                core_tasks.DeletionTask().si(serialized),
            ))

        return group(deletion_tasks)

    @classmethod
    def get_failure_signature(cls, dr_backup, serialized_dr_backup, force=False, **kwargs):
        # mark DR and all related non-OK resources as Erred
        if not force:
            return tasks.SetDRBackupErredTask().s(serialized_dr_backup)
        else:
            return tasks.ForceDeleteDRBackupTask().s(serialized_dr_backup)


class DRBackupRestorationCreateExecutor(core_executors.CreateExecutor, core_executors.BaseChordExecutor):
    """ DRBackup restoration process creates new volumes and restores backups. """

    @classmethod
    def get_task_signature(cls, dr_backup_restoration, serialized_dr_backup_restoration, **kwargs):
        """ Restore each volume backup on separate volume. """
        serialized_instance = core_utils.serialize_instance(dr_backup_restoration.instance)
        volume_backup_restoration_tasks = [
            core_tasks.StateTransitionTask().si(serialized_instance, state_transition='begin_provisioning')
        ]
        for volume_backup_restoration in dr_backup_restoration.volume_backup_restorations.all():
            volume_backup = volume_backup_restoration.volume_backup
            serialized_volume_backup = core_utils.serialize_instance(volume_backup)
            # volume that is restored from backup.
            volume = volume_backup_restoration.volume
            serialized_volume = core_utils.serialize_instance(volume)
            # temporary copy of volume backup that is used for volume restoration
            mirorred_volume_backup = volume_backup_restoration.mirorred_volume_backup
            serialized_mirorred_volume_backup = core_utils.serialize_instance(mirorred_volume_backup)

            volume_backup_restoration_tasks.append(chain(
                # Start volume creation on backend.
                core_tasks.BackendMethodTask().si(serialized_volume, 'create_volume', state_transition='begin_creating'),
                # Start tmp volume backup import.
                core_tasks.BackendMethodTask().si(serialized_mirorred_volume_backup, 'import_volume_backup_from_record',
                                                  state_transition='begin_creating'),
                # Wait for volume creation.
                tasks.PollRuntimeStateTask().si(
                    serialized_volume,
                    backend_pull_method='pull_volume_runtime_state',
                    success_state='available',
                    erred_state='error',
                ).set(countdown=30),
                # Wait for backup import.
                tasks.PollRuntimeStateTask().si(
                    serialized_mirorred_volume_backup,
                    backend_pull_method='pull_volume_backup_runtime_state',
                    success_state='available',
                    erred_state='error',
                ),
                core_tasks.StateTransitionTask().si(serialized_mirorred_volume_backup, state_transition='set_ok'),
                # Restore backup on volume.
                tasks.RestoreVolumeBackupTask().si(serialized_mirorred_volume_backup, serialized_volume),
                # Wait for volume restoration.
                tasks.PollRuntimeStateTask().si(
                    serialized_volume,
                    backend_pull_method='pull_volume_runtime_state',
                    success_state='available',
                    erred_state='error_restoring',
                ).set(countdown=20),
                # Pull volume to make sure it reflects restored data.
                core_tasks.BackendMethodTask().si(serialized_volume, 'pull_volume'),
                # After restoration volumes will have names of temporary copied for backup volumes,
                # we need to rename them.
                # This task should be deleted if backend will be done from origin volume, not its
                # temporary copy.
                tasks.RestoreVolumeOriginNameTask().si(serialized_volume_backup, serialized_volume),
                core_tasks.StateTransitionTask().si(serialized_volume, state_transition='set_ok'),
            ))

        return group(volume_backup_restoration_tasks)

    @classmethod
    def get_callback_signature(cls, dr_backup_restoration, serialized_dr_backup_restoration, **kwargs):
        return tasks.CreateInstanceFromVolumesTask().si(serialized_dr_backup_restoration)

    @classmethod
    def get_success_signature(cls, dr_backup_restoration, serialized_dr_backup_restoration, **kwargs):
        serialized_instance = core_utils.serialize_instance(dr_backup_restoration.instance)
        return core_tasks.StateTransitionTask().si(serialized_instance, state_transition='set_online')

    @classmethod
    def get_failure_signature(cls, dr_backup_restoration, serialized_dr_backup_restoration, **kwargs):
        return tasks.SetDRBackupRestorationErredTask().s(serialized_dr_backup_restoration)


class InstanceCreateExecutor(core_executors.CreateExecutor, core_executors.BaseChordExecutor):
    """ First - create instance volumes in parallel, after - create instance based on created volumes """

    @classmethod
    def get_task_signature(cls, instance, serialized_instance, **kwargs):
        """ Create all instance volumes in parallel and wait for them to provision """
        volumes_tasks = [core_tasks.StateTransitionTask().si(serialized_instance, state_transition='begin_provisioning')]
        for volume in instance.volumes.all():
            serialized_volume = core_utils.serialize_instance(volume)
            volumes_tasks.append(chain(
                # start volume creation
                core_tasks.BackendMethodTask().si(serialized_volume, 'create_volume', state_transition='begin_creating'),
                # wait until volume become available
                tasks.PollRuntimeStateTask().si(
                    serialized_volume,
                    backend_pull_method='pull_volume_runtime_state',
                    success_state='available',
                    erred_state='error',
                ).set(countdown=30),
                # pull volume to sure that it is bootable
                core_tasks.BackendMethodTask().si(serialized_volume, 'pull_volume'),
                # mark volume as OK
                core_tasks.StateTransitionTask().si(serialized_volume, state_transition='set_ok'),
            ))
        return group(volumes_tasks)

    @classmethod
    def get_callback_signature(cls, instance, serialized_instance,
                               ssh_key=None, flavor=None, floating_ip=None,
                               skip_external_ip_assignment=False):
        # Note that flavor is required for instance creation.
        kwargs = {
            'backend_flavor_id': flavor.backend_id,
            'skip_external_ip_assignment': skip_external_ip_assignment,
        }
        if ssh_key is not None:
            kwargs['public_key'] = ssh_key.public_key

        if floating_ip is not None:
            kwargs['floating_ip_uuid'] = floating_ip.uuid.hex

        return core_tasks.BackendMethodTask().si(serialized_instance, 'create_instance', **kwargs)

    @classmethod
    def get_success_signature(cls, instance, serialized_instance, **kwargs):
        # XXX: This method is overridden to support old-style states.
        return core_tasks.StateTransitionTask().si(serialized_instance, state_transition='set_online')

    @classmethod
    def get_failure_signature(cls, instance, serialized_instance, **kwargs):
        return tasks.SetInstanceErredTask().s(serialized_instance)


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
                serialized_instance,
                backend_method='detach_instance_volume',
                backend_volume_id=volume.backend_id
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

        for instance in volume.instances.all():
            instance.schedule_resizing()
            instance.save(update_fields=['state'])

            event_logger.openstack_volume.info(
                'Virtual machine {resource_name} has been scheduled to extend disk.',
                event_type='resource_volume_extension_scheduled',
                event_context={
                    'resource': instance,
                    'volume_size': new_size
                }
            )

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        new_size = kwargs.pop('new_size')

        detach = [
            core_tasks.BackendMethodTask().si(
                core_utils.serialize_instance(instance),
                backend_method='detach_instance_volume',
                state_transition='begin_resizing',
                backend_volume_id=volume.backend_id
            )
            for instance in volume.instances.all()
        ]

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

        attach = [
            core_tasks.BackendMethodTask().si(
                core_utils.serialize_instance(instance),
                backend_method='attach_instance_volume',
                backend_volume_id=volume.backend_id
            )
            for instance in volume.instances.all()
        ]

        check = tasks.PollRuntimeStateTask().si(
            serialized_volume,
            backend_pull_method='pull_volume_runtime_state',
            success_state='in-use',
            erred_state='error'
        )

        return chain(detach + extend + attach + [check])

    @classmethod
    def get_success_signature(cls, volume, serialized_volume, **kwargs):
        new_size = kwargs.pop('new_size')
        return tasks.LogVolumeExtendSucceeded().si(serialized_volume, state_transition='set_ok', new_size=new_size)

    @classmethod
    def get_failure_signature(cls, volume, serialized_volume, **kwargs):
        new_size = kwargs.pop('new_size')
        return tasks.LogVolumeExtendFailed().s(serialized_volume, new_size=new_size)


class BackupCreateExecutor(core_executors.CreateExecutor, core_executors.BaseChordExecutor):

    @classmethod
    def get_task_signature(cls, backup, serialized_backup, **kwargs):
        creations_tasks = [core_tasks.StateTransitionTask().si(serialized_backup, state_transition='begin_creating')]
        for snapshot in backup.snapshots.all():
            serialized_snapshot = core_utils.serialize_instance(snapshot)
            creations_tasks.append(chain(
                core_tasks.BackendMethodTask().si(
                    serialized_snapshot, 'create_snapshot', force=True, state_transition='begin_creating'),
                tasks.PollRuntimeStateTask().si(
                    serialized_snapshot,
                    backend_pull_method='pull_snapshot_runtime_state',
                    success_state='available',
                    erred_state='error',
                ).set(countdown=10),
                core_tasks.StateTransitionTask().si(serialized_snapshot, state_transition='set_ok'),
            ))
        return group(creations_tasks)

    @classmethod
    def get_failure_signature(cls, backup, serialized_backup, **kwargs):
        return tasks.SetBackupErredTask().s(serialized_backup)


class BackupDeleteExecutor(core_executors.DeleteExecutor, core_executors.BaseChordExecutor):

    @classmethod
    def pre_apply(cls, backup, **kwargs):
        for snapshot in backup.snapshots.all():
            snapshot.schedule_deleting()
            snapshot.save(update_fields=['state'])
        core_executors.DeleteExecutor.pre_apply(backup)

    @classmethod
    def get_task_signature(cls, backup, serialized_backup, force=False, **kwargs):
        deletion_tasks = [core_tasks.StateTransitionTask().si(serialized_backup, state_transition='begin_deleting')]
        # remove volume backups
        for snapshot in backup.snapshots.all():
            serialized = core_utils.serialize_instance(snapshot)
            deletion_tasks.append(chain(
                core_tasks.BackendMethodTask().si(serialized, 'delete_snapshot', state_transition='begin_deleting'),
                tasks.PollBackendCheckTask().si(serialized, 'is_snapshot_deleted'),
                core_tasks.DeletionTask().si(serialized),
            ))

        return group(deletion_tasks)

    @classmethod
    def get_failure_signature(cls, backup, serialized_backup, force=False, **kwargs):
        if not force:
            return tasks.SetBackupErredTask().s(serialized_backup)
        else:
            return tasks.ForceDeleteBackupTask().s(serialized_backup)


class BackupRestorationCreateExecutor(core_executors.CreateExecutor, core_executors.BaseChordExecutor):
    """ Restore volumes from backup snapshots, create instance based on restored volumes """

    @classmethod
    def get_task_signature(cls, backup_restoration, serialized_backup_restoration, **kwargs):
        """ Restore each volume from snapshot """
        instance = backup_restoration.instance
        serialized_instance = core_utils.serialize_instance(instance)
        volumes_tasks = [core_tasks.StateTransitionTask().si(serialized_instance, state_transition='begin_provisioning')]
        for volume in instance.volumes.all():
            serialized_volume = core_utils.serialize_instance(volume)
            volumes_tasks.append(chain(
                # start volume creation
                core_tasks.BackendMethodTask().si(serialized_volume, 'create_volume', state_transition='begin_creating'),
                # wait until volume become available
                tasks.PollRuntimeStateTask().si(
                    serialized_volume,
                    backend_pull_method='pull_volume_runtime_state',
                    success_state='available',
                    erred_state='error',
                ).set(countdown=30),
                # pull volume to sure that it is bootable
                core_tasks.BackendMethodTask().si(serialized_volume, 'pull_volume'),
                # mark volume as OK
                core_tasks.StateTransitionTask().si(serialized_volume, state_transition='set_ok'),
            ))
        return group(volumes_tasks)

    @classmethod
    def get_callback_signature(cls, backup_restoration, serialized_backup_restoration, **kwargs):
        flavor = backup_restoration.flavor
        kwargs = {
            'backend_flavor_id': flavor.backend_id,
            'skip_external_ip_assignment': False,
        }
        serialized_instance = core_utils.serialize_instance(backup_restoration.instance)
        return core_tasks.BackendMethodTask().si(serialized_instance, 'create_instance', **kwargs)

    @classmethod
    def get_success_signature(cls, backup_restoration, serialized_backup_restoration, **kwargs):
        serialized_instance = core_utils.serialize_instance(backup_restoration.instance)
        return core_tasks.StateTransitionTask().si(serialized_instance, state_transition='set_online')

    @classmethod
    def get_failure_signature(cls, backup_restoration, serialized_backup_restoration, **kwargs):
        return tasks.SetBackupRestorationErredTask().s(serialized_backup_restoration)
