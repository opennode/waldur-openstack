from django.contrib import admin
from django.core.exceptions import ValidationError
# XXX:  Django 1.10 deprecation, import from django.urls
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _

from nodeconductor.core.admin import ExecutorAdminAction
from nodeconductor.quotas.admin import QuotaInline
from nodeconductor.structure import admin as structure_admin

from . import executors, models


def _get_obj_admin_url(obj):
    return reverse('admin:%s_%s_change' % (obj._meta.app_label, obj._meta.model_name), args=[obj.id])


def _get_list_admin_url(model):
    return reverse('admin:%s_%s_changelist' % (model._meta.app_label, model._meta.model_name))


class ServiceProjectLinkAdmin(structure_admin.ServiceProjectLinkAdmin):
    readonly_fields = ('get_service_settings_username', 'get_service_settings_password') + \
        structure_admin.ServiceProjectLinkAdmin.readonly_fields

    def get_service_settings_username(self, obj):
        return obj.service.settings.username

    get_service_settings_username.short_description = _('Username')

    def get_service_settings_password(self, obj):
        return obj.service.settings.password

    get_service_settings_password.short_description = _('Password')


class TenantAdmin(structure_admin.ResourceAdmin):

    actions = ('pull', 'detect_external_networks', 'allocate_floating_ip', 'pull_security_groups',
               'pull_floating_ips', 'pull_quotas')
    inlines = [QuotaInline]

    class OKTenantAction(ExecutorAdminAction):
        """ Execute action with tenant that is in state OK """

        def validate(self, tenant):
            if tenant.state != models.Tenant.States.OK:
                raise ValidationError(_('Tenant has to be in state OK to pull security groups.'))

    class PullSecurityGroups(OKTenantAction):
        executor = executors.TenantPullSecurityGroupsExecutor
        short_description = _('Pull security groups')

    pull_security_groups = PullSecurityGroups()

    class AllocateFloatingIP(OKTenantAction):
        executor = executors.TenantAllocateFloatingIPExecutor
        short_description = _('Allocate floating IPs')

        def validate(self, tenant):
            super(TenantAdmin.AllocateFloatingIP, self).validate(tenant)
            if not tenant.external_network_id:
                raise ValidationError(_('Tenant has to have external network to allocate floating IP.'))

    allocate_floating_ip = AllocateFloatingIP()

    class DetectExternalNetworks(OKTenantAction):
        executor = executors.TenantDetectExternalNetworkExecutor
        short_description = _('Attempt to lookup and set external network id of the connected router')

    detect_external_networks = DetectExternalNetworks()

    class PullFloatingIPs(OKTenantAction):
        executor = executors.TenantPullFloatingIPsExecutor
        short_description = _('Pull floating IPs')

    pull_floating_ips = PullFloatingIPs()

    class PullQuotas(OKTenantAction):
        executor = executors.TenantPullQuotasExecutor
        short_description = _('Pull quotas')

    pull_quotas = PullQuotas()

    class Pull(ExecutorAdminAction):
        executor = executors.TenantPullExecutor
        short_description = _('Pull')

        def validate(self, tenant):
            if tenant.state not in (models.Tenant.States.OK, models.Tenant.States.ERRED):
                raise ValidationError(_('Tenant has to be OK or erred.'))

    pull = Pull()


class FlavorAdmin(structure_admin.BackendModelAdmin):
    list_filter = ('settings',)
    list_display = ('name', 'settings', 'cores', 'ram', 'disk')


class ImageAdmin(structure_admin.BackendModelAdmin):
    list_filter = ('settings', )
    list_display = ('name', 'min_disk', 'min_ram')


class TenantResourceAdmin(structure_admin.ResourceAdmin):
    """ Admin model for resources that are connected to tenant.

        Expects that resource has attribute `tenant`.
    """
    list_display = structure_admin.ResourceAdmin.list_display + ('get_tenant', )
    list_filter = structure_admin.ResourceAdmin.list_filter + ('tenant', )

    def get_tenant(self, obj):
        tenant = obj.tenant
        return '<a href="%s">%s</a>' % (_get_obj_admin_url(tenant), tenant.name)

    get_tenant.short_description = _('Tenant')
    get_tenant.allow_tags = True


class NetworkAdmin(structure_admin.ResourceAdmin):
    list_display_links = None
    list_display = ('is_external', 'type') + structure_admin.ResourceAdmin.list_display
    fields = ('name', 'tenant', 'is_external', 'type', 'segmentation_id', 'state')


class SubNetAdmin(structure_admin.ResourceAdmin):
    list_display_links = None
    list_display = ('network', 'gateway_ip') + structure_admin.ResourceAdmin.list_display

    fields = ('name', 'network', 'cidr', 'gateway_ip', 'allocation_pools',
              'ip_version', 'enable_dhcp', 'dns_nameservers', 'state')


admin.site.register(models.Network, NetworkAdmin)
admin.site.register(models.SubNet, SubNetAdmin)
admin.site.register(models.SecurityGroup, structure_admin.ResourceAdmin)

admin.site.register(models.Tenant, TenantAdmin)
admin.site.register(models.Flavor, FlavorAdmin)
admin.site.register(models.Image, ImageAdmin)
admin.site.register(models.OpenStackService, structure_admin.ServiceAdmin)
admin.site.register(models.OpenStackServiceProjectLink, ServiceProjectLinkAdmin)
admin.site.register(models.FloatingIP, structure_admin.ResourceAdmin)
