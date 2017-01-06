from __future__ import unicode_literals

from nodeconductor.core.models import StateMixin
from nodeconductor.structure import models as structure_models

from . import log, models


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


def _get_settings(tenant):
    try:
        result = structure_models.ServiceSettings.objects.get(scope=tenant)
    except structure_models.ServiceSettings.DoesNotExist:
        pass
    else:
        return result


def _get_floating_ip(service_settings, backend_id):
    try:
        result = models.FloatingIP.objects.get(settings=service_settings, backend_id=backend_id)
    except models.FloatingIP.DoesNotExist:
        pass
    else:
        return result


def _get_security_group(service_settings, backend_id):
    try:
        result = models.SecurityGroup.objects.get(settings=service_settings, backend_id=backend_id)
    except models.SecurityGroup.DoesNotExist:
        pass
    else:
        return result


def on_openstack_security_group_deleted(sender, instance, **kwargs):
    settings = _get_settings(instance.tenant)
    if not settings:
        return

    security_group = _get_security_group(settings, instance.backend_id)
    if security_group:
        security_group.delete()


def on_openstack_floating_ip_deleted(sender, instance, **kwargs):
    settings = _get_settings(instance.tenant)
    if not settings:
        return

    floating_ip = _get_floating_ip(settings, instance.backend_id)
    if floating_ip:
        floating_ip.delete()



def on_openstack_security_group_state_changed(sender, instance, name, source, target, **kwargs):
    settings = _get_settings(instance.tenant)
    if not settings:
        return

    if source == StateMixin.States.CREATING and target == StateMixin.States.OK:
        models.SecurityGroup.objects.create(
            description=instance.description,
            name=instance.name,
            backend_id=instance.backend_id,
            settings=settings,
        )

    elif source == StateMixin.States.UPDATING and target == StateMixin.States.OK:
        security_group = _get_security_group(settings, instance.backend_id)

        if security_group:
            security_group.name = instance.name,
            security_group.description = instance.description
            security_group.save()


def on_openstack_floating_ip_state_changed(sender, instance, name, source, target, **kwargs):
    settings = _get_settings(instance.tenant)
    if not settings:
        return

    if source == StateMixin.States.CREATING and target == StateMixin.States.OK:
        models.FloatingIP.objects.create(
            name=instance.name,
            backend_id=instance.backend_id,
            settings=settings,
            address=instance.address,
            status=instance.runtime_state,
            backend_network_id=instance.backend_network_id,
        )

    elif source == StateMixin.States.UPDATING and target == StateMixin.States.OK:
        floating_ip = _get_floating_ip(settings, instance.backend_id)

        if floating_ip:
            floating_ip.name = instance.name
            floating_ip.address = instance.address
            floating_ip.status = instance.runtime_state
            floating_ip.backend_network_id = instance.backend_network_id

            floating_ip.save()
