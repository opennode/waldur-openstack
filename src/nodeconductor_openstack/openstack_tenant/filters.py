from nodeconductor.core import filters as core_filters
from nodeconductor.structure import filters as structure_filters

from . import models


class OpenStackTenantServiceProjectLinkFilter(structure_filters.BaseServiceProjectLinkFilter):
    service = core_filters.URLFilter(view_name='openstack-detail', name='service__uuid')

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
    # TODO: Add filtration by source instance.
    class Meta(structure_filters.BaseResourceStateFilter.Meta):
        model = models.Volume


class SnapshotFilter(structure_filters.BaseResourceFilter):
    source_volume_uuid = core_filters.UUIDFilter(name='source_volume__uuid')
    source_volume = core_filters.URLFilter(view_name='openstacktenant-volume-detail', name='source_volume__uuid')

    class Meta(structure_filters.BaseResourceStateFilter.Meta):
        model = models.Snapshot
        fields = structure_filters.BaseResourceStateFilter.Meta.fields + ('source_volume_uuid', 'source_volume')