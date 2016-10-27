from __future__ import unicode_literals
import logging

from django.conf import settings
from django.core.exceptions import ValidationError

from nodeconductor.core import models as core_models, tasks as core_tasks, utils as core_utils
from nodeconductor.structure import filters as structure_filters

from .log import event_logger
from .models import SecurityGroup, SecurityGroupRule, Tenant


logger = logging.getLogger(__name__)


class SecurityGroupCreateException(Exception):
    pass


def create_initial_security_groups(sender, instance=None, created=False, **kwargs):
    if not created:
        return

    nc_settings = getattr(settings, 'NODECONDUCTOR_OPENSTACK', {})
    config_groups = nc_settings.get('DEFAULT_SECURITY_GROUPS', [])

    for group in config_groups:
        try:
            create_security_group(instance, group)
        except SecurityGroupCreateException as e:
            logger.error(e)


def create_security_group(tenant, group):
    sg_name = group.get('name')
    if sg_name in (None, ''):
        raise SecurityGroupCreateException(
            'Skipping misconfigured security group: parameter "name" not found or is empty.')

    rules = group.get('rules')
    if type(rules) not in (list, tuple):
        raise SecurityGroupCreateException(
            'Skipping misconfigured security group: parameter "rules" should be list or tuple.')

    sg_description = group.get('description', None)
    sg = SecurityGroup.objects.get_or_create(
        service_project_link=tenant.service_project_link,
        tenant=tenant,
        description=sg_description,
        name=sg_name)[0]

    for rule in rules:
        if 'icmp_type' in rule:
            rule['from_port'] = rule.pop('icmp_type')
        if 'icmp_code' in rule:
            rule['to_port'] = rule.pop('icmp_code')

        try:
            rule = SecurityGroupRule(security_group=sg, **rule)
            rule.full_clean()
        except ValidationError as e:
            logger.error('Failed to create rule for security group %s: %s.' % (sg_name, e))
        else:
            rule.save()
    return sg


def change_floating_ip_quota_on_status_change(sender, instance, created=False, **kwargs):
    floating_ip = instance
    add_quota = floating_ip.tenant.add_quota_usage
    if floating_ip.status != 'DOWN' and (created or floating_ip.tracker.previous('status') == 'DOWN'):
        add_quota('floating_ip_count', 1)
    if floating_ip.status == 'DOWN' and not created and floating_ip.tracker.previous('status') != 'DOWN':
        add_quota('floating_ip_count', -1)


def log_backup_schedule_save(sender, instance, created=False, **kwargs):
    if created:
        event_logger.openstack_backup.info(
            'Backup schedule for {resource_name} has been created.',
            event_type='resource_backup_schedule_creation_succeeded',
            event_context={'resource': instance.instance})
    else:
        event_logger.openstack_backup.info(
            'Backup schedule for {resource_name} has been updated.',
            event_type='resource_backup_schedule_update_succeeded',
            event_context={'resource': instance.instance})


def log_backup_schedule_delete(sender, instance, **kwargs):
    event_logger.openstack_backup.info(
        'Backup schedule for {resource_name} has been deleted.',
        event_type='resource_backup_schedule_deletion_succeeded',
        event_context={'resource': instance.instance})


def remove_ssh_key_from_tenants(sender, structure, user, role, **kwargs):
    """ Delete user ssh keys from tenants that he does not have access now. """
    tenants = Tenant.objects.filter(**{sender.__name__.lower(): structure})
    ssh_keys = core_models.SshPublicKey.objects.filter(user=user)
    for tenant in tenants:
        if user.has_perm('openstack.change_tenant', tenant):
            continue  # no need to delete ssh keys if user still have permissions for tenant.
        serialized_tenant = core_utils.serialize_instance(tenant)
        for key in ssh_keys:
            core_tasks.BackendMethodTask().delay(
                serialized_tenant, 'remove_ssh_key_from_tenant', key.name, key.fingerprint)


def remove_ssh_key_from_all_tenants_on_it_deletion(sender, instance, **kwargs):
    """ Delete key from all tenants that are accessible for user on key deletion. """
    ssh_key = instance
    user = ssh_key.user
    tenants = structure_filters.filter_queryset_for_user(Tenant.objects.all(), user)
    for tenant in tenants:
        if not user.has_perm('openstack.change_tenant', tenant):
            continue
        serialized_tenant = core_utils.serialize_instance(tenant)
        core_tasks.BackendMethodTask().delay(
            serialized_tenant, 'remove_ssh_key_from_tenant', ssh_key.name, ssh_key.fingerprint)
