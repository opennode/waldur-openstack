from celery import chain

from nodeconductor.core import executors as core_executors, tasks as core_tasks, utils as core_utils

from . import tasks


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


class VolumeExtendExecutor(core_executors.ActionExecutor):

    @classmethod
    def pre_apply(cls, volume, **kwargs):
        super(VolumeExtendExecutor, cls).pre_apply(volume, **kwargs)
        if volume.instance:
            volume.instance.schedule_updating()
            volume.instance.save(update_fields=['state'])

    @classmethod
    def get_task_signature(cls, volume, serialized_volume, **kwargs):
        new_size = kwargs.pop('new_size')

        if volume.instance is None:
            return chain(
                core_tasks.BackendMethodTask().si(
                    serialized_volume,
                    backend_method='extend_volume',
                    state_transition='begin_updating',
                    new_size=new_size
                ),
                tasks.PollRuntimeStateTask().si(
                    serialized_volume,
                    backend_pull_method='pull_volume_runtime_state',
                    success_state='available',
                    erred_state='error'
                )
            )

        return chain(
            core_tasks.StateTransitionTask().si(
                core_utils.serialize_instance(volume.instance),
                state_transition='begin_resizing'
            ),
            core_tasks.BackendMethodTask().si(
                serialized_volume,
                backend_method='detach_volume',
                state_transition='begin_updating'
            ),
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
            ),
            tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='available',
                erred_state='error'
            ),
            core_tasks.BackendMethodTask().si(
                serialized_volume,
                instance_uuid=volume.instance.uuid.hex,
                device=volume.device,
                backend_method='attach_volume',
            ),
            tasks.PollRuntimeStateTask().si(
                serialized_volume,
                backend_pull_method='pull_volume_runtime_state',
                success_state='in-use',
                erred_state='error'
            ),
        )


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
