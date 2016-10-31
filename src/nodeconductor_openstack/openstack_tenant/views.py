from django.utils import six
from rest_framework import decorators, response, status

from nodeconductor.core import views as core_views, exceptions as core_exceptions
from nodeconductor.structure import views as structure_views, filters as structure_filters

from . import models, serializers, filters, executors


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


class VolumeViewSet(six.with_metaclass(structure_views.ResourceViewMetaclass,
                                       structure_views.ResourceViewMixin,
                                       structure_views.PullMixin,
                                       core_views.StateExecutorViewSet)):
    queryset = models.Volume.objects.all()
    serializer_class = serializers.VolumeSerializer
    create_executor = executors.VolumeCreateExecutor
    update_executor = executors.VolumeUpdateExecutor
    delete_executor = executors.VolumeDeleteExecutor
    pull_executor = executors.VolumePullExecutor
    filter_class = filters.VolumeFilter
    actions_serializers = {
        'extend': serializers.VolumeExtendSerializer,
        'snapshot': serializers.SnapshotSerializer,
        # TODO: uncomment after instance implementation
        # 'attach': serializers.VolumeAttachSerializer,
    }

    def get_serializer_class(self):
        return self.actions_serializers.get(self.action, super(VolumeViewSet, self).get_serializer_class())

    def get_serializer_context(self):
        context = super(VolumeViewSet, self).get_serializer_context()
        if self.action == 'snapshot':
            context['source_volume'] = self.get_object()
        return context

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Volume.States.OK)
    def extend(self, request, volume, uuid=None):
        """ Increase volume size """
        serializer = self.get_serializer(volume, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        new_size = serializer.validated_data.get('disk_size')
        executors.VolumeExtendExecutor().execute(volume, new_size=new_size)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Volume.States.OK)
    def snapshot(self, request, volume, uuid=None):
        """ Create snapshot from volume """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        snapshot = serializer.save()

        executors.SnapshotCreateExecutor().execute(snapshot)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    # TODO: uncomment after instance implementation
    # @decorators.detail_route(methods=['post'])
    # @structure_views.safe_operation(valid_state=models.Volume.States.OK)
    # def attach(self, request, volume, uuid=None):
    #     """ Attach volume to instance """
    #     serializer = self.get_serializer(volume, data=request.data)
    #     serializer.is_valid(raise_exception=True)
    #     serializer.save()

    #     executors.VolumeAttachExecutor().execute(volume)

    # @decorators.detail_route(methods=['post'])
    # @structure_views.safe_operation(valid_state=models.Volume.States.OK)
    # def detach(self, request, volume, uuid=None):
    #     """ Detach instance from volume """
    #     executors.VolumeDetachExecutor().execute(volume)

    def check_operation(self, request, resource, action):
        volume = resource
        # TODO: uncomment after instance implementation
        # if action == 'attach' and volume.runtime_state != 'available':
        #     raise core_exceptions.IncorrectStateException('Volume runtime state should be "available".')
        # elif action == 'detach':
        #     if volume.runtime_state != 'in-use':
        #         raise core_exceptions.IncorrectStateException('Volume runtime state should be "in-use".')
        #     if not volume.instance:
        #         raise core_exceptions.IncorrectStateException('Volume is not attached to any instance.')
        #     if volume.instance.state != models.Instance.States.OK:
        #         raise core_exceptions.IncorrectStateException('Volume can be detached only if instance is offline.')
        if action == 'extend':
            if not volume.backend_id:
                raise core_exceptions.IncorrectStateException('Unable to extend volume without backend_id.')
            # TODO: uncomment after instance implementation
            # if volume.instance and (volume.instance.state != models.Instance.States.OK or
            #                         volume.instance.runtime_state != models.Instance.RuntimeStates.SHUTOFF):
            #     raise core_exceptions.IncorrectStateException('Volume instance should be shutoff and in OK state.')
            if volume.bootable:
                raise core_exceptions.IncorrectStateException("Can't detach root device volume.")
        if action == 'destroy':
            if volume.snapshots.exists():
                raise core_exceptions.IncorrectStateException('Volume has dependent snapshots.')
        return super(VolumeViewSet, self).check_operation(request, resource, action)


class SnapshotViewSet(six.with_metaclass(structure_views.ResourceViewMetaclass,
                                         structure_views.ResourceViewMixin,
                                         structure_views.PullMixin,
                                         core_views.UpdateOnlyStateExecutorViewSet)):
    queryset = models.Snapshot.objects.all()
    serializer_class = serializers.SnapshotSerializer
    update_executor = executors.SnapshotUpdateExecutor
    delete_executor = executors.SnapshotDeleteExecutor
    pull_executor = executors.SnapshotPullExecutor
    filter_class = filters.SnapshotFilter
