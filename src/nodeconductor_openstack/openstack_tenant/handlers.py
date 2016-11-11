from nodeconductor.core.models import StateMixin

from . import log


def _log_scheduled_action(resource, action, action_details):
    class_name = resource.__class__.__name__.lower()
    message = _get_action_message(action, action_details)
    log.event_logger.openstack_resource_action.info(
        'Operation "%s" has been scheduled for %s "%s"' % (message, class_name, resource.name),
        event_type=_get_action_event_type(class_name, action, 'scheduled'),
        event_context={'resource': resource, 'action_details': action_details},
    )


def _log_succeeded_action(resource, action, action_details):
    class_name = resource.__class__.__name__.lower()
    message = _get_action_message(action, action_details)
    log.event_logger.openstack_resource_action.info(
        'Successfully executed "%s" operation for %s "%s"' % (message, class_name, resource.name),
        event_type=_get_action_event_type(class_name, action, 'succeeded'),
        event_context={'resource': resource, 'action_details': action_details},
    )


def _log_failed_action(resource, action, action_details):
    class_name = resource.__class__.__name__.lower()
    message = _get_action_message(action, action_details)
    log.event_logger.openstack_resource_action.warning(
        'Failed to execute "%s" operation for %s "%s"' % (message, class_name, resource.name),
        event_type=_get_action_event_type(class_name, action, 'failed'),
        event_context={'resource': resource, 'action_details': action_details},
    )


def _get_action_message(action, action_details):
    return action_details.pop('message', action)


def _get_action_event_type(class_name, action, event_state):
    return '%s_%s_%s' % (class_name, action.lower(), event_state)


def log_action(sender, instance, created=False, **kwargs):
    resource = instance
    if created or not resource.tracker.has_changed('action'):
        return
    if resource.state == StateMixin.States.UPDATE_SCHEDULED:
        _log_scheduled_action(resource, resource.action, resource.action_details)
    if resource.state == StateMixin.States.OK:
        _log_succeeded_action(
            resource, resource.tracker.previous('action'), resource.tracker.previous('action_details'))
    elif resource.state == StateMixin.States.ERRED:
        _log_failed_action(
            resource, resource.tracker.previous('action'), resource.tracker.previous('action_details'))
