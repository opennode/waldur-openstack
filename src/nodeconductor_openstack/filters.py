import django_filters

from nodeconductor.core import filters as core_filters
from nodeconductor.core.filters import UUIDFilter
from nodeconductor.structure import filters as structure_filters

from . import models


class OpenStackServiceProjectLinkFilter(structure_filters.BaseServiceProjectLinkFilter):
    service = core_filters.URLFilter(view_name='openstack-detail', name='service__uuid')

    class Meta(object):
        model = models.OpenStackServiceProjectLink


class InstanceFilter(structure_filters.BaseResourceFilter):
    tenant_uuid = UUIDFilter(name='tenant__uuid')

    class Meta(structure_filters.BaseResourceFilter.Meta):
        model = models.Instance
        fields = structure_filters.BaseResourceFilter.Meta.fields + ('tenant_uuid',)
        order_by = structure_filters.BaseResourceFilter.Meta.order_by + [
            'ram',
            '-ram',
            'cores',
            '-cores',
            'system_volume_size',
            '-system_volume_size',
            'data_volume_size',
            '-data_volume_size',
        ]
        order_by_mapping = dict(
            # Backwards compatibility
            project__customer__name='service_project_link__project__customer__name',
            project__name='service_project_link__project__name',
            project__project_groups__name='service_project_link__project__project_groups__name',

            **structure_filters.BaseResourceFilter.Meta.order_by_mapping
        )


class SecurityGroupFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(
        name='name',
        lookup_type='icontains',
    )
    description = django_filters.CharFilter(
        name='description',
        lookup_type='icontains',
    )
    service = UUIDFilter(
        name='service_project_link__service__uuid',
    )
    project = UUIDFilter(
        name='service_project_link__project__uuid',
    )
    settings_uuid = UUIDFilter(
        name='service_project_link__service__settings__uuid'
    )
    service_project_link = core_filters.URLFilter(
        view_name='openstack-spl-detail',
        name='service_project_link__pk',
        lookup_field='pk',
    )
    tenant_uuid = UUIDFilter(
        name='tenant__uuid'
    )
    state = core_filters.StateFilter()

    class Meta(object):
        model = models.SecurityGroup
        fields = [
            'name',
            'description',
            'service',
            'project',
            'service_project_link',
            'state',
            'settings_uuid',
            'tenant_uuid',
        ]


class IpMappingFilter(django_filters.FilterSet):
    project = UUIDFilter(name='project__uuid')

    # XXX: remove after upgrading to django-filter 0.12
    #      which is still unavailable at https://pypi.python.org/simple/django-filter/
    private_ip = django_filters.CharFilter()
    public_ip = django_filters.CharFilter()

    class Meta(object):
        model = models.IpMapping
        fields = [
            'project',
            'private_ip',
            'public_ip',
        ]


class FloatingIPFilter(django_filters.FilterSet):
    project = UUIDFilter(name='service_project_link__project__uuid')
    service = UUIDFilter(name='service_project_link__service__uuid')
    service_project_link = core_filters.URLFilter(
        view_name='openstack-spl-detail',
        name='service_project_link__pk',
        lookup_field='pk',
    )
    tenant_uuid = UUIDFilter(name='tenant__uuid')

    class Meta(object):
        model = models.FloatingIP
        fields = [
            'project',
            'service',
            'status',
            'service_project_link',
            'tenant_uuid'
        ]


class FlavorFilter(structure_filters.ServicePropertySettingsFilter):

    class Meta(structure_filters.ServicePropertySettingsFilter.Meta):
        model = models.Flavor
        fields = dict({
            'cores': ['exact', 'gte', 'lte'],
            'ram': ['exact', 'gte', 'lte'],
            'disk': ['exact', 'gte', 'lte'],
        }, **{field: ['exact'] for field in structure_filters.ServicePropertySettingsFilter.Meta.fields})
        order_by = [
            'cores',
            '-cores',
            'ram',
            '-ram',
            'disk',
            '-disk',
        ]


class BackupScheduleFilter(django_filters.FilterSet):
    description = django_filters.CharFilter(
        lookup_type='icontains',
    )
    instance = core_filters.URLFilter(
        view_name='openstack-instance-detail',
        name='instance__uuid',
    )
    instance_uuid = UUIDFilter(name='instance__uuid')
    backup_type = django_filters.ChoiceFilter(choices=models.BackupSchedule.BackupTypes.CHOICES)

    class Meta(object):
        model = models.BackupSchedule
        fields = (
            'description', 'instance', 'instance_uuid', 'backup_type',
        )


class BackupFilter(django_filters.FilterSet):
    description = django_filters.CharFilter(
        lookup_type='icontains',
    )
    instance = UUIDFilter(name='instance__uuid')
    project = UUIDFilter(name='instance__service_project_link__project__uuid')

    class Meta(object):
        model = models.Backup
        fields = (
            'description',
            'instance',
            'project',
        )


class DRBackupFilter(structure_filters.BaseResourceFilter):
    source_instance_uuid = UUIDFilter(name='source_instance__uuid')
    source_instance = core_filters.URLFilter(view_name='openstack-instance-detail', name='source_instance__uuid')

    class Meta(structure_filters.BaseResourceFilter.Meta):
        model = models.DRBackup
        fields = structure_filters.BaseResourceFilter.Meta.fields + ('source_instance_uuid', 'source_instance')


class VolumeFilter(structure_filters.BaseResourceStateFilter):
    instance_uuid = UUIDFilter(name='instances__uuid')
    instance = core_filters.URLFilter(view_name='openstack-instance-detail', name='instances__uuid')

    class Meta(structure_filters.BaseResourceStateFilter.Meta):
        model = models.Volume
        fields = structure_filters.BaseResourceStateFilter.Meta.fields + ('instance_uuid', 'instance')


class SnapshotFilter(structure_filters.BaseResourceFilter):
    source_volume_uuid = UUIDFilter(name='source_volume__uuid')
    source_volume = core_filters.URLFilter(view_name='openstack-volume-detail', name='source_volume__uuid')
    backup_uuid = UUIDFilter(name='backups__uuid')
    backup = core_filters.URLFilter(view_name='openstack-backup-detail', name='backups__uuid')

    class Meta(structure_filters.BaseResourceStateFilter.Meta):
        model = models.Snapshot
        fields = structure_filters.BaseResourceStateFilter.Meta.fields + (
            'source_volume_uuid', 'source_volume', 'backup_uuid', 'backup')
