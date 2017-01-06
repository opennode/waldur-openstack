from django.apps import AppConfig
from django.db.models import signals
from django_fsm import signals as fsm_signals


class OpenStackTenantConfig(AppConfig):
    """ OpenStack is a toolkit for building private and public clouds.
        This application adds support for managing OpenStack tenant resources -
        instances, volumes and snapshots.
    """
    name = 'nodeconductor_openstack.openstack_tenant'
    label = 'openstack_tenant'
    verbose_name = 'OpenStackTenant'
    service_name = 'OpenStackTenant'

    def ready(self):
        from nodeconductor.structure import SupportedServices
        from .backend import OpenStackTenantBackend
        SupportedServices.register_backend(OpenStackTenantBackend)

        # Initialize service settings quotas based on tenant.
        from nodeconductor.structure.models import ServiceSettings
        from nodeconductor.quotas.fields import QuotaField
        from nodeconductor_openstack.openstack.models import Tenant
        for quota in Tenant.get_quotas_fields():
            ServiceSettings.add_quota_field(
                name=quota.name,
                quota_field=QuotaField(
                    is_backend=True,
                    default_limit=quota.default_limit,
                    creation_condition=lambda service_settings:
                        service_settings.type == OpenStackTenantConfig.service_name
                )
            )

        from . import handlers, models
        for Resource in (models.Instance, models.Volume, models.Snapshot):
            name = Resource.__name__.lower()
            signals.post_save.connect(
                handlers.log_action,
                sender=Resource,
                dispatch_uid='openstack_tenant.handlers.log_%s_action' % name,
            )

        signals.post_save.connect(
            handlers.log_backup_schedule_creation,
            sender=models.BackupSchedule,
            dispatch_uid='openstack_tenant.handlers.log_backup_schedule_creation',
        )

        signals.post_save.connect(
            handlers.log_backup_schedule_action,
            sender=models.BackupSchedule,
            dispatch_uid='openstack_tenant.handlers.log_backup_schedule_action',
        )

        signals.pre_delete.connect(
            handlers.log_backup_schedule_deletion,
            sender=models.BackupSchedule,
            dispatch_uid='openstack_tenant.handlers.log_backup_schedule_deletion',
        )

        from nodeconductor_openstack.openstack.models import SecurityGroup, FloatingIP

        fsm_signals.post_transition.connect(
            handlers.on_openstack_floating_ip_state_changed,
            sender=FloatingIP,
            dispatch_uid='openstack_tenant.handlers.on_openstack_floating_ip_state_changed',
        )

        fsm_signals.post_transition.connect(
            handlers.on_openstack_security_group_state_changed,
            sender=SecurityGroup,
            dispatch_uid='openstack_tenant.handlers.on_openstack_security_group_state_changed',
        )

        signals.post_delete.connect(
            handlers.on_openstack_security_group_deleted,
            sender=SecurityGroup,
            dispatch_uid='openstack_tenant.handlers.on_openstack_security_group_deleted',
        )

        signals.post_delete.connect(
            handlers.on_openstack_floating_ip_deleted,
            sender=FloatingIP,
            dispatch_uid='openstack_tenant.handlers.on_openstack_floating_ip_deleted',
        )
