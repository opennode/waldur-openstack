from django.apps import AppConfig
from django.db.models import signals


class OpenStackConfig(AppConfig):
    """ OpenStack is a toolkit for building private and public clouds.
        This application adds support for managing OpenStack deployments -
        tenants, instances, security groups and networks.
    """
    name = 'nodeconductor_openstack.openstack'
    label = 'openstack'
    verbose_name = 'OpenStack'
    service_name = 'OpenStack'

    def ready(self):
        from nodeconductor.core import models as core_models
        from nodeconductor.structure import SupportedServices, signals as structure_signals, models as structure_models
        from . import handlers

        FloatingIP = self.get_model('FloatingIP')
        Tenant = self.get_model('Tenant')

        # structure
        from .backend import OpenStackBackend
        SupportedServices.register_backend(OpenStackBackend)

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
            dispatch_uid='openstack.handlers.create_initial_security_groups',
        )

        signals.post_save.connect(
            handlers.change_floating_ip_quota_on_status_change,
            sender=FloatingIP,
            dispatch_uid='openstack.handlers.change_floating_ip_quota_on_status_change',
        )

        for model in (structure_models.Project, structure_models.Customer):
            structure_signals.structure_role_revoked.connect(
                handlers.remove_ssh_key_from_tenants,
                sender=model,
                dispatch_uid='openstack.handlers.remove_ssh_key_from_tenants__%s' % model.__name__,
            )

        signals.pre_delete.connect(
            handlers.remove_ssh_key_from_all_tenants_on_it_deletion,
            sender=core_models.SshPublicKey,
            dispatch_uid='openstack.handlers.remove_ssh_key_from_all_tenants_on_it_deletion',
        )

        from nodeconductor.quotas.models import Quota
        signals.post_save.connect(
            handlers.log_tenant_quota_update,
            sender=Quota,
            dispatch_uid='openstack.handlers.log_tenant_quota_update',
        )
