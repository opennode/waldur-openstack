from nodeconductor.logging.loggers import EventLogger, event_logger
from nodeconductor.structure import models as structure_models


class ResourceActionEventLogger(EventLogger):
    resource = structure_models.NewResource
    action_details = dict

    class Meta:
        event_types = (
            # volume
            'volume_pull_scheduled',
            'volume_pull_succeeded',
            'volume_pull_failed',

            'volume_attach_scheduled',
            'volume_attach_succeeded',
            'volume_attach_failed',

            'volume_detach_scheduled',
            'volume_detach_succeeded',
            'volume_detach_failed',

            'volume_extend_scheduled',
            'volume_extend_succeeded',
            'volume_extend_failed',

            # snapshot
            'snapshot_pull_scheduled',
            'snapshot_pull_succeeded',
            'snapshot_pull_failed',

            # instance
            'instance_pull_scheduled',
            'instance_pull_succeeded',
            'instance_pull_failed',

            'instance_update_security_groups_scheduled',
            'instance_update_security_groups_succeeded',
            'instance_update_security_groups_failed',

            'instance_change_flavor_scheduled',
            'instance_change_flavor_succeeded',
            'instance_change_flavor_failed',

            'instance_assign_floating_ip_scheduled',
            'instance_assign_floating_ip_succeeded',
            'instance_assign_floating_ip_failed',

            'instance_stop_scheduled',
            'instance_stop_succeeded',
            'instance_stop_failed',

            'instance_start_scheduled',
            'instance_start_succeeded',
            'instance_start_failed',

            'instance_restart_scheduled',
            'instance_restart_succeeded',
            'instance_restart_failed',
        )


event_logger.register('openstack_resource_action', ResourceActionEventLogger)
