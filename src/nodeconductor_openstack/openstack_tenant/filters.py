import django_filters

from nodeconductor.core import filters as core_filters
from nodeconductor.structure import filters as structure_filters

from . import models


class OpenStackTenantServiceProjectLinkFilter(structure_filters.BaseServiceProjectLinkFilter):
    service = core_filters.URLFilter(view_name='openstacktenant-detail', name='service__uuid')

    class Meta(object):
        model = models.OpenStackTenantServiceProjectLink


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


class VolumeFilter(structure_filters.BaseResourceStateFilter):
    instance = core_filters.URLFilter(view_name='openstacktenant-instance-detail', name='instance__uuid')
    instance_uuid = core_filters.UUIDFilter(name='instance__uuid')

    class Meta(structure_filters.BaseResourceStateFilter.Meta):
        model = models.Volume
        fields = structure_filters.BaseResourceStateFilter.Meta.fields + ('instance', 'instance_uuid')


class SnapshotFilter(structure_filters.BaseResourceFilter):
    source_volume_uuid = core_filters.UUIDFilter(name='source_volume__uuid')
    source_volume = core_filters.URLFilter(view_name='openstacktenant-volume-detail', name='source_volume__uuid')

    backup_uuid = core_filters.UUIDFilter(name='backups__uuid')
    backup = core_filters.URLFilter(view_name='openstacktenant-backup-detail', name='backups__uuid')

    class Meta(structure_filters.BaseResourceStateFilter.Meta):
        model = models.Snapshot
        fields = structure_filters.BaseResourceStateFilter.Meta.fields


class BackupFilter(structure_filters.BaseResourceFilter):
    instance = core_filters.URLFilter(view_name='openstacktenant-instance-detail', name='instance__uuid')
    instance_uuid = core_filters.UUIDFilter(name='instance__uuid')
    backup_schedule = core_filters.URLFilter(
        view_name='openstacktenant-backup-schedule-detail', name='backup_schedule__uuid')
    backup_schedule_uuid = core_filters.UUIDFilter(name='backup_schedule__uuid')

    class Meta(structure_filters.BaseResourceStateFilter.Meta):
        model = models.Backup
        fields = structure_filters.BaseResourceStateFilter.Meta.fields + (
            'instance', 'instance_uuid', 'backup_schedule', 'backup_schedule_uuid')


class BackupScheduleFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_type='icontains')
    description = django_filters.CharFilter(lookup_type='icontains')
    instance = core_filters.URLFilter(view_name='openstacktenant-instance-detail', name='instance__uuid')
    instance_uuid = core_filters.UUIDFilter(name='instance__uuid')

    class Meta(object):
        model = models.BackupSchedule
