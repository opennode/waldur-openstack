from __future__ import unicode_literals

from nodeconductor.core.models import StateMixin

from . import log


def _log_scheduled_action(resource, action, action_details):
    class_name = resource.__class__.__name__.lower()
    message = _get_action_message(action, action_details)
    log.event_logger.openstack_resource_action.info(
        'Operation "%s" has been scheduled for %s "%s"' % (message, class_name, resource.name),
        event_type=_get_action_event_type(action, 'scheduled'),
        event_context={'resource': resource, 'action_details': action_details},
    )


def _log_succeeded_action(resource, action, action_details):
    class_name = resource.__class__.__name__.lower()
    message = _get_action_message(action, action_details)
    log.event_logger.openstack_resource_action.info(
        'Successfully executed "%s" operation for %s "%s"' % (message, class_name, resource.name),
        event_type=_get_action_event_type(action, 'succeeded'),
        event_context={'resource': resource, 'action_details': action_details},
    )


def _log_failed_action(resource, action, action_details):
    class_name = resource.__class__.__name__.lower()
    message = _get_action_message(action, action_details)
    log.event_logger.openstack_resource_action.warning(
        'Failed to execute "%s" operation for %s "%s"' % (message, class_name, resource.name),
        event_type=_get_action_event_type(action, 'failed'),
        event_context={'resource': resource, 'action_details': action_details},
    )


def _get_action_message(action, action_details):
    return action_details.pop('message', action)


def _get_action_event_type(action, event_state):
    return 'resource_%s_%s' % (action.replace(' ', '_').lower(), event_state)


def log_action(sender, instance, created=False, **kwargs):
    """ Log any resource action.

        Example of logged volume extend action:
        {
            'event_type': 'volume_extend_succeeded',
            'message': 'Successfully executed "Extend volume from 1024 MB to 2048 MB" operation for volume "pavel-test"',
            'action_details': {'old_size': 1024, 'new_size': 2048}
        }
    """
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


def log_backup_schedule_creation(sender, instance, created=False, **kwargs):
    if not created:
        return

    backup_schedule = instance
    log.event_logger.openstack_backup_schedule.info(
        'Backup schedule "%s" has been created' % backup_schedule.name,
        event_type='resource_backup_schedule_created',
        event_context={'resource': backup_schedule.instance, 'backup_schedule': backup_schedule},
    )


def log_backup_schedule_action(sender, instance, created=False, **kwargs):
    backup_schedule = instance
    if created or not backup_schedule.tracker.has_changed('is_active'):
        return

    context = {'resource': backup_schedule.instance, 'backup_schedule': backup_schedule}
    if backup_schedule.is_active:
        log.event_logger.openstack_backup_schedule.info(
            'Backup schedule "%s" has been activated' % backup_schedule.name,
            event_type='resource_backup_schedule_activated',
            event_context=context,
        )
    else:
        if backup_schedule.error_message:
            message = 'Backup schedule "%s" has been deactivated because of error' % backup_schedule.name
        else:
            message = 'Backup schedule "%s" has been deactivated' % backup_schedule.name
        log.event_logger.openstack_backup_schedule.info(
            message,
            event_type='resource_backup_schedule_deactivated',
            event_context=context,
        )


def log_backup_schedule_deletion(sender, instance, **kwargs):
    backup_schedule = instance
    log.event_logger.openstack_backup_schedule.info(
        'Backup schedule "%s" has been deleted' % backup_schedule.name,
        event_type='resource_backup_schedule_deleted',
        event_context={'resource': backup_schedule.instance, 'backup_schedule': backup_schedule},
    )
