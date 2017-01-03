import django_filters

from nodeconductor.core import filters as core_filters
from nodeconductor.core.filters import UUIDFilter
from nodeconductor.structure import filters as structure_filters

from . import models


class OpenStackServiceProjectLinkFilter(structure_filters.BaseServiceProjectLinkFilter):
    service = core_filters.URLFilter(view_name='openstack-detail', name='service__uuid')

    class Meta(object):
        model = models.OpenStackServiceProjectLink


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


class NetworkFilter(structure_filters.BaseResourceFilter):
    tenant_uuid = UUIDFilter(name='tenant__uuid')
    tenant = core_filters.URLFilter(view_name='openstack-tenant-detail', name='tenant__uuid')

    class Meta(structure_filters.BaseResourceStateFilter.Meta):
        model = models.Network


class SubNetFilter(structure_filters.BaseResourceFilter):
    tenant_uuid = UUIDFilter(name='network__tenant__uuid')
    tenant = core_filters.URLFilter(view_name='openstack-tenant-detail', name='network__tenant__uuid')
    network__uuid = UUIDFilter(name='network__uuid')
    network = core_filters.URLFilter(view_name='openstack-network-detail', name='network__uuid')

    class Meta(structure_filters.BaseResourceStateFilter.Meta):
        model = models.SubNet
