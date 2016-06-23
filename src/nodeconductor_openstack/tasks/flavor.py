import logging

from nodeconductor.core import utils
from nodeconductor.core.tasks import ErrorStateTransitionTask, StateTransitionTask
from nodeconductor.structure.log import event_logger

logger = logging.getLogger(__name__)


class LogFlavorChangeSucceeded(StateTransitionTask):
    def execute(self, instance, serialized_flavor, *args, **kwargs):
        flavor = utils.deserialize_instance(serialized_flavor)
        event_logger.openstack_flavor.info(
            'Virtual machine {resource_name} flavor has been changed to {flavor_name}.',
            event_type='resource_flavor_change_succeeded',
            event_context={'resource': instance, 'flavor': flavor}
        )


class LogFlavorChangeFailed(ErrorStateTransitionTask):
    def execute(self, instance, serialized_flavor):
        super(LogFlavorChangeFailed, self).execute(instance)
        flavor = utils.deserialize_instance(serialized_flavor)
        event_logger.openstack_flavor.error(
            'Virtual machine {resource_name} flavor change has failed.',
            event_type='resource_flavor_change_failed',
            event_context={'resource': instance, 'flavor': flavor}
        )
