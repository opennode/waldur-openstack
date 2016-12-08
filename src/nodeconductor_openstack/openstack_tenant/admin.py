import pytz

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from nodeconductor.core.admin import ExecutorAdminAction
from nodeconductor.structure import admin as structure_admin

from . import executors, models


class FlavorAdmin(admin.ModelAdmin):
    list_filter = ('settings',)
    list_display = ('name', 'settings', 'cores', 'ram', 'disk')


class ImageAdmin(admin.ModelAdmin):
    list_filter = ('settings', )
    list_display = ('name', 'settings', 'min_disk', 'min_ram')


class FloatingIPAdmin(admin.ModelAdmin):
    list_filter = ('settings',)
    list_display = ('address', 'settings', 'status', 'backend_network_id', 'is_booked')


class SecurityGroupRule(admin.TabularInline):
    model = models.SecurityGroupRule
    fields = ('protocol', 'from_port', 'to_port', 'cidr', 'backend_id')
    readonly_fields = fields
    extra = 0
    can_delete = False


class SecurityGroupAdmin(admin.ModelAdmin):
    inlines = [SecurityGroupRule]
    list_filter = ('settings',)
    list_display = ('name', 'settings')


class VolumeAdmin(structure_admin.ResourceAdmin):

    class Pull(ExecutorAdminAction):
        executor = executors.SnapshotPullExecutor
        short_description = 'Pull'

        def validate(self, instance):
            if instance.state not in (models.Snapshot.States.OK, models.Snapshot.States.ERRED):
                raise ValidationError('Snapshot has to be in OK or ERRED state.')

    pull = Pull()


class SnapshotAdmin(structure_admin.ResourceAdmin):

    class Pull(ExecutorAdminAction):
        executor = executors.SnapshotPullExecutor
        short_description = 'Pull'

        def validate(self, instance):
            if instance.state not in (models.Snapshot.States.OK, models.Snapshot.States.ERRED):
                raise ValidationError('Snapshot has to be in OK or ERRED state.')

    pull = Pull()


class InstanceAdmin(structure_admin.VirtualMachineAdmin):
    actions = structure_admin.VirtualMachineAdmin.actions + ['pull']

    class Pull(ExecutorAdminAction):
        executor = executors.InstancePullExecutor
        short_description = 'Pull'

        def validate(self, instance):
            if instance.state not in (models.Instance.States.OK, models.Instance.States.ERRED):
                raise ValidationError('Instance has to be in OK or ERRED state.')

    pull = Pull()


class BackupAdmin(admin.ModelAdmin):
    readonly_fields = ('created', 'kept_until')
    list_filter = ('uuid', 'state')
    list_display = ('uuid', 'instance', 'state', 'project')

    def project(self, obj):
        return obj.instance.service_project_link.project

    project.short_description = 'Project'


class BackupScheduleForm(forms.ModelForm):
    def clean_timezone(self):
        tz = self.cleaned_data['timezone']
        if tz not in pytz.all_timezones:
            raise ValidationError('Invalid timezone', code='invalid')

        return self.cleaned_data['timezone']


class BackupScheduleAdmin(admin.ModelAdmin):
    form = BackupScheduleForm
    readonly_fields = ('next_trigger_at',)
    list_filter = ('is_active',)
    list_display = ('uuid', 'next_trigger_at', 'is_active', 'instance', 'timezone')


admin.site.register(models.OpenStackTenantService, structure_admin.ServiceAdmin)
admin.site.register(models.OpenStackTenantServiceProjectLink, structure_admin.ServiceProjectLinkAdmin)
admin.site.register(models.Flavor, FlavorAdmin)
admin.site.register(models.Image, ImageAdmin)
admin.site.register(models.FloatingIP, FloatingIPAdmin)
admin.site.register(models.SecurityGroup, SecurityGroupAdmin)
admin.site.register(models.Volume, VolumeAdmin)
admin.site.register(models.Snapshot, SnapshotAdmin)
admin.site.register(models.Instance, InstanceAdmin)
admin.site.register(models.Backup, BackupAdmin)
admin.site.register(models.BackupSchedule, BackupScheduleAdmin)
