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

        for handler in handlers.resource_handlers:
            model = handler.resource_model
            name = model.__name__.lower()

            fsm_signals.post_transition.connect(
                handler.create_handler,
                sender=model,
                dispatch_uid='openstack_tenant.handlers.create_%s' % name,
            )

            fsm_signals.post_transition.connect(
                handler.update_handler,
                sender=model,
                dispatch_uid='openstack_tenant.handlers.update_%s' % name,
            )

            signals.post_delete.connect(
                handler.delete_handler,
                sender=model,
                dispatch_uid='openstack_tenant.handlers.delete_%s' % name,
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

        signals.post_save.connect(
            handlers.log_snapshot_schedule_creation,
            sender=models.SnapshotSchedule,
            dispatch_uid='openstack_tenant.handlers.log_snapshot_schedule_creation',
        )

        signals.post_save.connect(
            handlers.log_snapshot_schedule_action,
            sender=models.SnapshotSchedule,
            dispatch_uid='openstack_tenant.handlers.log_snapshot_schedule_action',
        )

        signals.pre_delete.connect(
            handlers.log_snapshot_schedule_deletion,
            sender=models.SnapshotSchedule,
            dispatch_uid='openstack_tenant.handlers.log_snapshot_schedule_deletion',
        )

        signals.post_save.connect(
            handlers.update_service_settings_credentials,
            sender=Tenant,
            dispatch_uid='openstack.handlers.update_service_settings_credentials',
        )

        signals.m2m_changed.connect(
            handlers.sync_certificates_between_openstack_service_with_openstacktenant_service,
            sender=ServiceSettings.certifications.through,
            dispatch_uid='openstack.handlers.sync_certificates_between_openstack_service_with_openstacktenant_service',
        )

        signals.post_save.connect(
            handlers.copy_certifications_from_openstack_service_to_openstacktenant_service,
            sender=ServiceSettings,
            dispatch_uid='openstack.handlers.copy_certifications_from_openstack_service_to_openstacktenant_service',
        )

        signals.post_save.connect(
            handlers.copy_flavor_exclude_regex_to_openstacktenant_service_settings,
            sender=ServiceSettings,
            dispatch_uid='openstack.handlers.copy_flavor_exclude_regex_to_openstacktenant_service_settings',
        )

        signals.post_save.connect(
            handlers.create_service_from_tenant,
            sender=Tenant,
            dispatch_uid='openstack.handlers.create_service_from_tenant',
        )
