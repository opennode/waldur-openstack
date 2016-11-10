from nodeconductor.core.models import StateMixin

from . import log


def _log_scheduled_action(resource, action, action_details):
    class_name = resource.__class__.__name__.lower()
    message = action_details.pop('message', action)
    event_type = '%s_%s_scheduled' % (class_name, action.lower())
    log.event_logger.resource_action.info(
        'Operation "%s" has been scheduled for %s "%s"' % (message, class_name, resource.name),
        event_type=event_type,
        event_context={'resource': resource, 'action_details': action_details},
    )


def _log_succeeded_action(resource, action, action_details):
    class_name = resource.__class__.__name__.lower()
    message = action_details.pop('message', action)
    event_type = '%s_%s_succeeded' % (class_name, action.lower())
    log.event_logger.resource_action.info(
        'Successfully executed "%s" operation for %s "%s"' % (message, class_name, resource.name),
        event_type=event_type,
        event_context={'resource': resource, 'action_details': action_details},
    )


def _log_failed_action(resource, action, action_details):
    class_name = resource.__class__.__name__.lower()
    message = action_details.pop('message', action)
    event_type = '%s_%s_failed' % (class_name, action.lower())
    log.event_logger.resource_action.info(
        'Failed to execute "%s" operation for %s "%s"' % (message, class_name, resource.name),
        event_type=event_type,
        event_context={'resource': resource, 'action_details': action_details},
    )


def log_action(sender, instance, created=False, **kwargs):
    resource = instance
    if created or not resource.tracker.has_changed('action'):
        return
    if resource.state == StateMixin.States.UPDATE_SCHEDULED:
        _log_scheduled_action(resource, resource.action, resource.action_details)
    elif resource.state == StateMixin.States.OK:
        _log_succeeded_action(
            resource, resource.tracker.previous('action'), resource.tracker.previous('action_details'))
    elif resource.state == StateMixin.States.ERRED:
        _log_failed_action(
            resource, resource.tracker.previous('action'), resource.tracker.previous('action_details'))
