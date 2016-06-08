from django.apps import AppConfig
from django.conf import settings
from django.db.models import signals
from django_fsm import signals as fsm_signals


class OpenStackConfig(AppConfig):
    """ OpenStack is a toolkit for building private and public clouds.
        This application adds support for managing OpenStack deployments -
        tenants, instances, security groups and networks.
    """
    name = 'nodeconductor_openstack'
    label = 'openstack'
    verbose_name = 'OpenStack'
    service_name = 'OpenStack'

    def ready(self):
        from nodeconductor.cost_tracking import CostTrackingRegister
        from nodeconductor.structure import SupportedServices
        from nodeconductor.quotas.models import Quota
        from . import handlers

        Instance = self.get_model('Instance')
        FloatingIP = self.get_model('FloatingIP')
        BackupSchedule = self.get_model('BackupSchedule')
        Tenant = self.get_model('Tenant')

        # structure
        from .backend import OpenStackBackend
        SupportedServices.register_backend(OpenStackBackend)

        # cost tracking
        from .cost_tracking import OpenStackCostTrackingBackend
        CostTrackingRegister.register(self.label, OpenStackCostTrackingBackend)

        # template
        from nodeconductor.template import TemplateRegistry
        from .template import InstanceProvisionTemplateForm
        TemplateRegistry.register(InstanceProvisionTemplateForm)

        from nodeconductor.structure.models import ServiceSettings
        from nodeconductor.quotas.fields import QuotaField

        for resource in ('vcpu', 'ram', 'storage'):
            ServiceSettings.add_quota_field(
                name='openstack_%s' % resource,
                quota_field=QuotaField(
                    creation_condition=lambda service_settings:
                        service_settings.type == OpenStackConfig.service_name
                )
            )

        signals.post_save.connect(
            handlers.create_initial_security_groups,
            sender=Tenant,
            dispatch_uid='nodeconductor_openstack.handlers.create_initial_security_groups',
        )

        signals.post_save.connect(
            handlers.change_floating_ip_quota_on_status_change,
            sender=FloatingIP,
            dispatch_uid='nodeconductor_openstack.handlers.change_floating_ip_quota_on_status_change',
        )

        signals.post_save.connect(
            handlers.log_backup_schedule_save,
            sender=BackupSchedule,
            dispatch_uid='nodeconductor_openstack.handlers.log_backup_schedule_save',
        )

        signals.post_delete.connect(
            handlers.log_backup_schedule_delete,
            sender=BackupSchedule,
            dispatch_uid='nodeconductor_openstack.handlers.log_backup_schedule_delete',
        )

        # TODO: this should be moved to itacloud assembly application
        if getattr(settings, 'NODECONDUCTOR', {}).get('IS_ITACLOUD', False):
            fsm_signals.post_transition.connect(
                handlers.create_host_for_instance,
                sender=Instance,
                dispatch_uid='nodeconductor.template.handlers.create_host_for_instance',
            )

            signals.post_save.connect(
                handlers.check_quota_threshold_breach,
                sender=Quota,
                dispatch_uid='nodeconductor.quotas.handlers.check_quota_threshold_breach',
            )
