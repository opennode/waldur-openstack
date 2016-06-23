import logging

from nodeconductor.core.tasks import ErrorStateTransitionTask, StateTransitionTask
from nodeconductor.structure.log import event_logger

logger = logging.getLogger(__name__)


class LogVolumeExtendSucceeded(StateTransitionTask):
    def execute(self, instance, new_size, *args, **kwargs):
        event_logger.openstack_volume.info(
            'Virtual machine {resource_name} disk has been extended to {volume_size}.',
            event_type='resource_volume_extension_succeeded',
            event_context={'resource': instance, 'volume_size': new_size}
        )


class LogVolumeExtendFailed(ErrorStateTransitionTask):
    def execute(self, instance, new_size):
        super(LogVolumeExtendFailed, self).execute(instance)
        event_logger.openstack_volume.info(
            'Virtual machine {resource_name} disk has been failed.',
            event_type='resource_volume_extension_failed',
            event_context={'resource': instance, 'volume_size': new_size}
        )
