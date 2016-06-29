import logging

from nodeconductor.core.tasks import ErrorStateTransitionTask, StateTransitionTask
from nodeconductor.structure.log import event_logger

logger = logging.getLogger(__name__)


class LogVolumeExtendSucceeded(StateTransitionTask):
    def execute(self, volume, *args, **kwargs):
        new_size = kwargs.pop('new_size')

        for instance in volume.instances.all():
            instance.set_resized()
            instance.save(update_fields=['state'])

            event_logger.openstack_volume.info(
                'Virtual machine {resource_name} disk has been extended to {volume_size}.',
                event_type='resource_volume_extension_succeeded',
                event_context={'resource': instance, 'volume_size': new_size}
            )


class LogVolumeExtendFailed(ErrorStateTransitionTask):
    def execute(self, volume, **kwargs):
        super(LogVolumeExtendFailed, self).execute(volume)
        new_size = kwargs.pop('new_size')

        for instance in volume.instances.all():
            instance.set_erred()
            instance.save(update_fields=['state'])

            event_logger.openstack_volume.info(
                'Virtual machine {resource_name} disk has been failed.',
                event_type='resource_volume_extension_failed',
                event_context={'resource': instance, 'volume_size': new_size}
            )
