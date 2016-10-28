from django.apps import AppConfig


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
        for quota_name in Tenant.get_quotas_names():
            ServiceSettings.add_quota_field(
                name=quota_name,
                quota_field=QuotaField(
                    is_backend=True,
                    creation_condition=lambda service_settings:
                        service_settings.type == OpenStackTenantConfig.service_name
                )
            )
