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


def log_snapshot_schedule_creation(sender, instance, created=False, **kwargs):
    if not created:
        return

    snapshot_schedule = instance
    log.event_logger.openstack_snapshot_schedule.info(
        'Snapshot schedule "%s" has been created' % snapshot_schedule.name,
        event_type='resource_snapshot_schedule_created',
        event_context={'resource': snapshot_schedule.source_volume, 'snapshot_schedule': snapshot_schedule},
    )


def log_snapshot_schedule_action(sender, instance, created=False, **kwargs):
    snapshot_schedule = instance
    if created or not snapshot_schedule.tracker.has_changed('is_active'):
        return

    context = {'resource': snapshot_schedule.source_volume, 'snapshot_schedule': snapshot_schedule}
    if snapshot_schedule.is_active:
        log.event_logger.openstack_snapshot_schedule.info(
            'Snapshot schedule "%s" has been activated' % snapshot_schedule.name,
            event_type='resource_snapshot_schedule_activated',
            event_context=context,
        )
    else:
        if snapshot_schedule.error_message:
            message = 'Snapshot schedule "%s" has been deactivated because of error' % snapshot_schedule.name
        else:
            message = 'Snapshot schedule "%s" has been deactivated' % snapshot_schedule.name
        log.event_logger.openstack_snapshot_schedule.info(
            message,
            event_type='resource_snapshot_schedule_deactivated',
            event_context=context,
        )


def log_snapshot_schedule_deletion(sender, instance, **kwargs):
    snapshot_schedule = instance
    log.event_logger.openstack_snapshot_schedule.info(
        'Snapshot schedule "%s" has been deleted' % snapshot_schedule.name,
        event_type='resource_snapshot_schedule_deleted',
        event_context={'resource': snapshot_schedule.source_volume, 'snapshot_schedule': snapshot_schedule},
    )


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


def delete_security_group(sender, instance, **kwargs):
    """
    Deletes security group on openstack security group deletion
    :param instance: openstack.models.SecurityGroup instance
    """
    settings = structure_models.ServiceSettings.objects.filter(scope=instance.tenant).first()
    if not settings:
        return

    security_group = models.SecurityGroup.objects.filter(settings=settings, backend_id=instance.backend_id).first()
    if security_group:
        security_group.delete()


def delete_floating_ip(sender, instance, **kwargs):
    """
    Deletes floating ip on openstack floating ip deletion
    :param instance: openstack.models.FloatingIP instance
    """
    settings = structure_models.ServiceSettings.objects.filter(scope=instance.tenant).first()
    if not settings:
        return

    floating_ip = models.FloatingIP.objects.filter(settings=settings, backend_id=instance.backend_id).first()
    if floating_ip:
        floating_ip.delete()


def update_security_group(sender, instance, name, source, target, **kwargs):
    """
    Updates security group and their rules on openstack security group transition from 'UPDATING' state to 'OK'.
    :param instance: openstack.models.SecurityGroup instance
    :param source: transition from state
    :param target: transition to state
    :return:
    """
    if source != StateMixin.States.UPDATING and target != StateMixin.States.OK:
        return

    settings = structure_models.ServiceSettings.objects.filter(scope=instance.tenant).first()
    if not settings:
        return

    security_group = models.SecurityGroup.objects.filter(settings=settings, backend_id=instance.backend_id).first()
    if security_group:
        security_group.name = instance.name
        security_group.description = instance.description
        security_group.save()

        security_group.rules.all().delete()

        group_rules = [models.SecurityGroupRule(
            protocol=rule.protocol,
            from_port=rule.from_port,
            to_port=rule.to_port,
            cidr=rule.cidr,
            backend_id=rule.backend_id,
            security_group=security_group,
        ) for rule in instance.rules.iterator()]

        security_group.rules.bulk_create(group_rules)


def create_security_group(sender, instance, name, source, target, **kwargs):
    """
    Creates security group on openstack security group transition from 'CREATING' state to 'OK'.
    :param instance: openstack.models.SecurityGroup instance
    :param source: transition from state
    :param target: transition to state
    :return:
    """
    if source != StateMixin.States.CREATING and target != StateMixin.States.OK:
        return

    settings = structure_models.ServiceSettings.objects.filter(scope=instance.tenant).first()
    if not settings:
        return

    security_group = models.SecurityGroup.objects.create(
        description=instance.description,
        name=instance.name,
        backend_id=instance.backend_id,
        settings=settings,
    )

    if instance.rules.count() > 0:
        group_rules = [models.SecurityGroupRule(
            protocol=rule.protocol,
            from_port=rule.from_port,
            to_port=rule.to_port,
            cidr=rule.cidr,
            backend_id=rule.backend_id,
            security_group=security_group,
        ) for rule in instance.rules.iterator()]

        security_group.rules.bulk_create(group_rules)


def update_floating_ip(sender, instance, name, source, target, **kwargs):
    """
    Updates floating ip on openstack floating ip transition from 'UPDATING' state to 'OK'.
    :param instance: openstack.models.FloatingIP instance
    :param source: transition from state
    :param target: transition to state
    :return:
    """
    if source != StateMixin.States.UPDATING and target != StateMixin.States.OK:
        return

    settings = structure_models.ServiceSettings.objects.filter(scope=instance.tenant).first()
    if not settings:
        return

    floating_ip = models.FloatingIP.objects.get(settings=settings, backend_id=instance.backend_id)

    if floating_ip:
        floating_ip.name = instance.name
        floating_ip.address = instance.address
        floating_ip.runtime_state = instance.runtime_state
        floating_ip.backend_network_id = instance.backend_network_id

        floating_ip.save()


def create_floating_ip(sender, instance, name, source, target, **kwargs):
    """
    Creates floating ip on openstack floating ip transition from 'CREATING' state to 'OK'.
    :param instance: openstack.models.FloatingIP instance
    :param source: transition from state
    :param target: transition to state
    :return:
    """
    if source != StateMixin.States.CREATING and target != StateMixin.States.OK:
        return

    settings = structure_models.ServiceSettings.objects.filter(scope=instance.tenant).first()
    if not settings:
        return

    models.FloatingIP.objects.create(
        name=instance.name,
        backend_id=instance.backend_id,
        settings=settings,
        address=instance.address,
        runtime_state=instance.runtime_state,
        backend_network_id=instance.backend_network_id,
    )


def update_service_settings_password(sender, instance, created=False, **kwargs):
    """
    Updates service settings password on tenant user_password change.
    It is possible to change a user password in tenant,
    as service settings copies tenant user password on creation it has to be update on change.
    """
    if created:
        return

    tenant = instance
    if tenant.tracker.has_changed('user_password'):
        service_settings = structure_models.ServiceSettings.objects.filter(scope=tenant).first()
        if service_settings:
            service_settings.password = tenant.user_password
            service_settings.save()


def create_network(sender, instance, name, source, target, **kwargs):
    """
    Creates network on openstack network transition from 'CREATING' state to 'OK'.
    :param instance: openstack.models.Network instance
    :param source: transition from state
    :param target: transition to state
    :return:
    """
    if source != StateMixin.States.CREATING and target != StateMixin.States.OK:
        return

    settings = structure_models.ServiceSettings.objects.filter(scope=instance.tenant).first()
    if not settings:
        return

    models.Network.objects.create(
        backend_id=instance.backend_id,
        settings=settings,
        name=instance.name,
        is_external=instance.is_external,
        type=instance.type,
        segmentation_id=instance.segmentation_id,
    )


def update_network(sender, instance, name, source, target, **kwargs):
    """
    Updates network on openstack network transition from 'UPDATING' state to 'OK'.
    :param instance: openstack.models.Network instance
    :param source: transition from state
    :param target: transition to state
    :return:
    """
    if source != StateMixin.States.UPDATING and target != StateMixin.States.OK:
        return

    settings = structure_models.ServiceSettings.objects.filter(scope=instance.tenant).first()
    if not settings:
        return

    network = models.Network.objects.get(settings=settings, backend_id=instance.backend_id)

    if network:
        network.is_external = instance.is_external
        network.segmentation_id = instance.segmentation_id
        network.type = instance.type
        network.name = instance.name
        network.backend_id = instance.backend_id

        network.save()


def delete_network(sender, instance, **kwargs):
    """
    Deletes network on openstack network deletion
    :param instance: openstack.models.Network instance
    """
    settings = structure_models.ServiceSettings.objects.filter(scope=instance.tenant).first()
    if not settings:
        return

    network = models.Network.objects.filter(settings=settings, backend_id=instance.backend_id).first()
    if network:
        network.delete()


def create_subnet(sender, instance, name, source, target, **kwargs):
    """
    Creates subnet on openstack subnet transition from 'CREATING' state to 'OK'.
    :param instance: openstack.models.SubNet instance
    :param source: transition from state
    :param target: transition to state
    :return:
    """
    if source != StateMixin.States.CREATING and target != StateMixin.States.OK:
        return

    settings = structure_models.ServiceSettings.objects.filter(scope=instance.network.tenant).first()
    if not settings:
        return

    network = models.Network.objects.get(backend_id=instance.network.backend_id)

    models.SubNet.objects.create(
        backend_id=instance.backend_id,
        settings=settings,
        name=instance.name,
        cidr=instance.cidr,
        allocation_pools=instance.allocation_pools,
        ip_version=instance.ip_version,
        enable_dhcp=instance.enable_dhcp,
        dns_nameservers=instance.dns_nameservers,
        network=network,
    )


def update_subnet(sender, instance, name, source, target, **kwargs):
    """
    Updates subnet on openstack subnet transition from 'UPDATING' state to 'OK'.
    :param instance: openstack.models.SubNet instance
    :param source: transition from state
    :param target: transition to state
    :return:
    """
    if source != StateMixin.States.UPDATING and target != StateMixin.States.OK:
        return

    settings = structure_models.ServiceSettings.objects.filter(scope=instance.network.tenant).first()
    if not settings:
        return

    subnet = models.SubNet.objects.get(settings=settings, backend_id=instance.backend_id)

    if subnet:
        network = models.Network.objects.get(backend_id=instance.network.backend_id)

        subnet.network = network

        subnet.cidr = instance.cidr
        subnet.allocation_pools = instance.allocation_pools
        subnet.ip_version = instance.ip_version
        subnet.enable_dhcp = instance.enable_dhcp
        subnet.dns_nameservers = instance.dns_nameservers

        subnet.name = instance.name
        subnet.backend_id = instance.backend_id

        subnet.save()


def delete_subnet(sender, instance, **kwargs):
    """
    Deletes subnet on openstack subnet deletion
    :param instance: openstack.models.SubNet instance
    """
    settings = structure_models.ServiceSettings.objects.filter(scope=instance.network.tenant).first()
    if not settings:
        return

    subnet = models.SubNet.objects.filter(settings=settings, backend_id=instance.backend_id).first()
    if subnet:
        subnet.delete()
