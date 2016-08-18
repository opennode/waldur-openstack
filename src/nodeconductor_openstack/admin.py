import urllib

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse

from nodeconductor.core.admin import ExecutorAdminAction
from nodeconductor.quotas.admin import QuotaInline
from nodeconductor.structure import admin as structure_admin

from . import executors, models
from .forms import BackupScheduleForm, InstanceForm


def _get_obj_admin_url(obj):
    return reverse('admin:%s_%s_change' % (obj._meta.app_label, obj._meta.model_name), args=[obj.id])


def _get_list_admin_url(model):
    return reverse('admin:%s_%s_changelist' % (model._meta.app_label, model._meta.model_name))


class ServiceProjectLinkAdmin(structure_admin.ServiceProjectLinkAdmin):
    readonly_fields = ('get_service_settings_username', 'get_service_settings_password') + \
        structure_admin.ServiceProjectLinkAdmin.readonly_fields

    def get_service_settings_username(self, obj):
        return obj.service.settings.username

    get_service_settings_username.short_description = 'Username'

    def get_service_settings_password(self, obj):
        return obj.service.settings.password

    get_service_settings_password.short_description = 'Password'


class BackupAdmin(admin.ModelAdmin):
    readonly_fields = ('created_at', 'kept_until')
    list_filter = ('uuid', 'state')
    list_display = ('uuid', 'instance', 'state', 'project')

    def project(self, obj):
        return obj.instance.service_project_link.project

    project.short_description = 'Project'


class BackupScheduleAdmin(admin.ModelAdmin):
    form = BackupScheduleForm
    readonly_fields = ('next_trigger_at',)
    list_filter = ('is_active',)
    list_display = ('uuid', 'next_trigger_at', 'is_active', 'instance', 'timezone')


class InstanceAdmin(structure_admin.VirtualMachineAdmin):

    actions = structure_admin.VirtualMachineAdmin.actions + ['pull']
    form = InstanceForm

    class Pull(ExecutorAdminAction):
        executor = executors.InstancePullExecutor
        short_description = 'Pull'

        def validate(self, instance):
            if instance.state not in (models.Instance.States.ONLINE, models.Instance.States.OFFLINE, models.Instance.States.ERRED):
                raise ValidationError('Instance has to be in ONLINE, OFFLINE or ERRED state.')

    pull = Pull()


class TenantAdmin(structure_admin.ResourceAdmin):

    actions = ('pull', 'detect_external_networks', 'allocate_floating_ip', 'pull_security_groups',
               'pull_floating_ips', 'pull_quotas')
    inlines = [QuotaInline]

    class OKTenantAction(ExecutorAdminAction):
        """ Execute action with tenant that is in state OK """

        def validate(self, tenant):
            if tenant.state != models.Tenant.States.OK:
                raise ValidationError('Tenant has to be in state OK to pull security groups.')

    class PullSecurityGroups(OKTenantAction):
        executor = executors.TenantPullSecurityGroupsExecutor
        short_description = 'Pull security groups'

    pull_security_groups = PullSecurityGroups()

    class AllocateFloatingIP(OKTenantAction):
        executor = executors.TenantAllocateFloatingIPExecutor
        short_description = 'Allocate floating IPs'

        def validate(self, tenant):
            super(TenantAdmin.AllocateFloatingIP, self).validate(tenant)
            if not tenant.external_network_id:
                raise ValidationError('Tenant has to have external network to allocate floating IP.')

    allocate_floating_ip = AllocateFloatingIP()

    class DetectExternalNetworks(OKTenantAction):
        executor = executors.TenantDetectExternalNetworkExecutor
        short_description = 'Attempt to lookup and set external network id of the connected router'

    detect_external_networks = DetectExternalNetworks()

    class PullFloatingIPs(OKTenantAction):
        executor = executors.TenantPullFloatingIPsExecutor
        short_description = 'Pull floating IPs'

    pull_floating_ips = PullFloatingIPs()

    class PullQuotas(OKTenantAction):
        executor = executors.TenantPullQuotasExecutor
        short_description = 'Pull quotas'

    pull_quotas = PullQuotas()

    class Pull(ExecutorAdminAction):
        executor = executors.TenantPullExecutor
        short_description = 'Pull'

        def validate(self, tenant):
            if tenant.state not in (models.Tenant.States.OK, models.Tenant.States.ERRED):
                raise ValidationError('Tenant has to be OK or erred.')
            if not tenant.service_project_link.service.is_admin_tenant():
                raise ValidationError('Tenant pull is only possible for admin service.')

    pull = Pull()


class FlavorAdmin(admin.ModelAdmin):
    list_filter = ('settings',)
    list_display = ('name', 'settings', 'cores', 'ram', 'disk')


class ImageAdmin(admin.ModelAdmin):
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

    get_tenant.short_description = 'Tenant'
    get_tenant.allow_tags = True


class VolumeAdmin(TenantResourceAdmin):
    pass


class SnapshotAdmin(TenantResourceAdmin):
    pass


class VolumeBackupAdmin(TenantResourceAdmin):
    list_display = TenantResourceAdmin.list_display + ('get_source_volume', 'get_restorations')

    def get_source_volume(self, obj):
        source_volume = obj.source_volume
        if source_volume:
            return '<a href="%s">%s</a>' % (_get_obj_admin_url(source_volume), source_volume.name)
        return

    get_source_volume.short_description = 'Source volume'
    get_source_volume.allow_tags = True

    def get_restorations(self, obj):
        url = _get_list_admin_url(models.VolumeBackupRestoration)
        url += '?' + urllib.urlencode({'volume_backup_id__exact': obj.id})
        return '<a href="%s">restorations (%s)</a>' % (url, obj.restorations.count())

    get_restorations.short_description = 'Restorations'
    get_restorations.allow_tags = True


class VolumeBackupRestorationAdmin(admin.ModelAdmin):
    list_filter = ('tenant', )
    list_display = ('uuid', 'volume_backup', 'mirorred_volume_backup', 'volume', 'get_tenant')

    def get_tenant(self, obj):
        tenant = obj.tenant
        return '<a href="%s">%s</a>' % (_get_obj_admin_url(tenant), tenant.name)

    get_tenant.short_description = 'Tenant'
    get_tenant.allow_tags = True


class DRBackupAdmin(TenantResourceAdmin):
    list_display = TenantResourceAdmin.list_display + ('get_volume_backups', 'get_restorations')

    def get_volume_backups(self, obj):
        text = ''
        for vb in obj.volume_backups.all():
            text += '<a href="%s">%s</a><br>' % (_get_obj_admin_url(vb), vb.name)
        return text

    get_volume_backups.short_description = 'Volume backups'
    get_volume_backups.allow_tags = True

    def get_restorations(self, obj):
        url = _get_list_admin_url(models.DRBackupRestoration)
        url += '?' + urllib.urlencode({'dr_backup_id__exact': obj.id})
        return '<a href="%s">restorations (%s)</a>' % (url, obj.restorations.count())

    get_restorations.short_description = 'Restorations'
    get_restorations.allow_tags = True


class DRBackupRestorationAdmin(admin.ModelAdmin):
    list_filter = ('tenant', )
    list_display = ('uuid', 'backup', 'instance', 'get_tenant', 'created')

    def get_tenant(self, obj):
        tenant = obj.tenant
        return '<a href="%s">%s</a>' % (_get_obj_admin_url(tenant), tenant.name)

    get_tenant.short_description = 'Tenant'
    get_tenant.allow_tags = True


admin.site.register(models.Instance, InstanceAdmin)
admin.site.register(models.Tenant, TenantAdmin)
admin.site.register(models.Flavor, FlavorAdmin)
admin.site.register(models.Image, ImageAdmin)
admin.site.register(models.OpenStackService, structure_admin.ServiceAdmin)
admin.site.register(models.OpenStackServiceProjectLink, ServiceProjectLinkAdmin)
admin.site.register(models.Backup, BackupAdmin)
admin.site.register(models.BackupSchedule, BackupScheduleAdmin)
admin.site.register(models.Volume, VolumeAdmin)
admin.site.register(models.Snapshot, SnapshotAdmin)
admin.site.register(models.VolumeBackup, VolumeBackupAdmin)
admin.site.register(models.VolumeBackupRestoration, VolumeBackupRestorationAdmin)
admin.site.register(models.DRBackup, DRBackupAdmin)
admin.site.register(models.DRBackupRestoration, DRBackupRestorationAdmin)
admin.site.register(models.FloatingIP)
