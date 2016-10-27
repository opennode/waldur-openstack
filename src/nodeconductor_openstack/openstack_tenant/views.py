from nodeconductor.structure import views as structure_views, filters as structure_filters

from . import models, serializers, filters


class OpenStackServiceViewSet(structure_views.BaseServiceViewSet):
    queryset = models.OpenStackTenantService.objects.all()
    serializer_class = serializers.ServiceSerializer


class OpenStackServiceProjectLinkViewSet(structure_views.BaseServiceProjectLinkViewSet):
    queryset = models.OpenStackTenantServiceProjectLink.objects.all()
    serializer_class = serializers.ServiceProjectLinkSerializer
    filter_class = filters.OpenStackTenantServiceProjectLinkFilter


class ImageViewSet(structure_views.BaseServicePropertyViewSet):
    queryset = models.Image.objects.all().order_by('settings', 'name')
    serializer_class = serializers.ImageSerializer
    lookup_field = 'uuid'
    filter_class = structure_filters.ServicePropertySettingsFilter


class FlavorViewSet(structure_views.BaseServicePropertyViewSet):
    """
    VM instance flavor is a pre-defined set of virtual hardware parameters that the instance will use:
    CPU, memory, disk size etc. VM instance flavor is not to be confused with VM template -- flavor is a set of virtual
    hardware parameters whereas template is a definition of a system to be installed on this instance.
    """
    queryset = models.Flavor.objects.all().order_by('settings', 'cores', 'ram', 'disk')
    serializer_class = serializers.FlavorSerializer
    lookup_field = 'uuid'
    filter_class = filters.FlavorFilter


class FloatingIPViewSet(structure_views.BaseServicePropertyViewSet):
    queryset = models.FloatingIP.objects.all().order_by('settings', 'address')
    serializer_class = serializers.FloatingIPSerializer
    lookup_field = 'uuid'
    filter_class = structure_filters.ServicePropertySettingsFilter


class SecurityGroupViewSet(structure_views.BaseServicePropertyViewSet):
    queryset = models.SecurityGroup.objects.all().order_by('settings', 'name')
    serializer_class = serializers.SecurityGroupSerializer
    lookup_field = 'uuid'
    filter_class = structure_filters.ServicePropertySettingsFilter
