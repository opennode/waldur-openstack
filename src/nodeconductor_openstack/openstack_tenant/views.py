from django.utils import six
from rest_framework import decorators, response, status

from nodeconductor.core import views as core_views, exceptions as core_exceptions, mixins as core_mixins
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
        'attach': serializers.VolumeAttachSerializer,
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
        old_size = volume.size
        serializer = self.get_serializer(volume, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        volume.refresh_from_db()
        executors.VolumeExtendExecutor().execute(volume, old_size=old_size, new_size=volume.size)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Volume.States.OK)
    def snapshot(self, request, volume, uuid=None):
        """ Create snapshot from volume """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        snapshot = serializer.save()

        executors.SnapshotCreateExecutor().execute(snapshot)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Volume.States.OK)
    def attach(self, request, volume, uuid=None):
        """ Attach volume to instance """
        serializer = self.get_serializer(volume, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        executors.VolumeAttachExecutor().execute(volume)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Volume.States.OK)
    def detach(self, request, volume, uuid=None):
        """ Detach instance from volume """
        executors.VolumeDetachExecutor().execute(volume)

    def check_operation(self, request, resource, action):
        volume = resource
        if action == 'attach' and volume.runtime_state != 'available':
            raise core_exceptions.IncorrectStateException('Volume runtime state should be "available".')
        elif action == 'detach':
            if volume.runtime_state != 'in-use':
                raise core_exceptions.IncorrectStateException('Volume runtime state should be "in-use".')
            if not volume.instance:
                raise core_exceptions.IncorrectStateException('Volume is not attached to any instance.')
            if volume.instance.state != models.Instance.States.OK:
                raise core_exceptions.IncorrectStateException('Volume can be detached only if instance is offline.')
        if action == 'extend':
            if not volume.backend_id:
                raise core_exceptions.IncorrectStateException('Unable to extend volume without backend_id.')
            if volume.instance and (volume.instance.state != models.Instance.States.OK or
                                    volume.instance.runtime_state != models.Instance.RuntimeStates.SHUTOFF):
                raise core_exceptions.IncorrectStateException('Volume instance should be shutoff and in OK state.')
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


# I have tested create, pull and update. Need to test and implement other actions + volume + celerybeat.

class InstanceViewSet(structure_views.PullMixin,
                      core_mixins.UpdateExecutorMixin,
                      structure_views._BaseResourceViewSet):
    """
    OpenStack instance permissions
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    - Staff members can list all available VM instances in any service.
    - Customer owners can list all VM instances in all the services that belong to any of the customers they own.
    - Project administrators can list all VM instances, create new instances and start/stop/restart instances in all the
      services that are connected to any of the projects they are administrators in.
    - Project managers can list all VM instances in all the services that are connected to any of the projects they are
      managers in.
    """
    queryset = models.Instance.objects.all()
    serializer_class = serializers.InstanceSerializer
    # filter_class = filters.InstanceFilter
    pull_executor = executors.InstancePullExecutor
    update_executor = executors.InstanceUpdateExecutor

    serializers = {
        'assign_floating_ip': serializers.AssignFloatingIpSerializer,
        'change_flavor': serializers.InstanceFlavorChangeSerializer,
        'destroy': serializers.InstanceDeleteSerializer,
    }

    def initial(self, request, *args, **kwargs):
        # Disable old-style checks.
        super(structure_views._BaseResourceViewSet, self).initial(request, *args, **kwargs)

    def check_operation(self, request, resource, action):
        instance = self.get_object()
        States = models.Instance.States
        RuntimeStates = models.Instance.RuntimeStates
        if self.action in ('update', 'partial_update') and instance.state != States.OK:
            raise core_exceptions.IncorrectStateException('Instance should be in state OK.')
        if action == 'start' and (instance.state != States.OK or instance.runtime_state != RuntimeStates.SHUTOFF):
            raise core_exceptions.IncorrectStateException('Instance state has to be shutoff and in state OK.')
        if action == 'stop' and (instance.state != States.OK or instance.runtime_state != RuntimeStates.ACTIVE):
            raise core_exceptions.IncorrectStateException('Instance state has to be active and in state OK.')
        if action == 'restart' and (instance.state != States.OK or instance.runtime_state != RuntimeStates.ACTIVE):
            raise core_exceptions.IncorrectStateException('Instance state has to be active and in state OK.')
        if action == 'change_flavor' and (instance.state != States.OK or instance.runtime_state != RuntimeStates.SHUTOFF):
            raise core_exceptions.IncorrectStateException('Instance state has to be shutoff and in state OK.')
        if action == 'resize' and (instance.state != States.OK or instance.runtime_state != RuntimeStates.SHUTOFF):
            raise core_exceptions.IncorrectStateException('Instance state has to be shutoff and in state OK.')
        if action == 'destroy':
            if instance.state not in (States.OK, States.ERRED):
                raise core_exceptions.IncorrectStateException('Instance state has to be OK or erred.')
            if instance.state == States.OK and instance.runtime_state != RuntimeStates.SHUTOFF:
                raise core_exceptions.IncorrectStateException('Instance has to be shutoff.')
        return super(InstanceViewSet, self).check_operation(request, resource, action)

    def perform_provision(self, serializer):
        instance = serializer.save()
        executors.InstanceCreateExecutor.execute(
            instance,
            ssh_key=serializer.validated_data.get('ssh_public_key'),
            flavor=serializer.validated_data['flavor'],
            skip_external_ip_assignment=serializer.validated_data['skip_external_ip_assignment'],
            floating_ip=serializer.validated_data.get('floating_ip'),
            is_heavy_task=True,
        )

    async_executor = True

    @structure_views.safe_operation(valid_state=(models.Instance.States.OK, models.Instance.States.ERRED))
    def destroy(self, request, resource, uuid=None):
        """
        Deletion of an instance is done through sending a **DELETE** request to the instance URI.
        Valid request example (token is user specific):

        .. code-block:: http

            DELETE /api/openstack-instances/abceed63b8e844afacd63daeac855474/ HTTP/1.1
            Authorization: Token c84d653b9ec92c6cbac41c706593e66f567a7fa4
            Host: example.com

        Only stopped instances or instances in ERRED state can be deleted.

        By default when instance is destroyed, all data volumes
        attached to it are destroyed too. In order to preserve data
        volumes use query parameter ?delete_volumes=false
        In this case data volumes are detached from the instance and
        then instance is destroyed. Note that system volume is deleted anyway.
        For example:

        .. code-block:: http

            DELETE /api/openstack-instances/abceed63b8e844afacd63daeac855474/?delete_volumes=false HTTP/1.1
            Authorization: Token c84d653b9ec92c6cbac41c706593e66f567a7fa4
            Host: example.com

        """
        serializer = self.get_serializer(data=request.query_params, instance=self.get_object())
        serializer.is_valid(raise_exception=True)
        delete_volumes = serializer.validated_data['delete_volumes']

        force = resource.state == models.Instance.States.ERRED
        executors.InstanceDeleteExecutor.execute(
            resource,
            force=force,
            delete_volumes=delete_volumes,
            async=self.async_executor
        )

    def get_serializer_class(self):
        serializer = self.serializers.get(self.action)
        return serializer or super(InstanceViewSet, self).get_serializer_class()

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=(models.Instance.States.OK, models.Instance.States.ERRED))
    def pull(self, request, instance, uuid=None):
        self.pull_executor.execute(instance)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=(models.Instance.States.OK,))
    def assign_floating_ip(self, request, instance, uuid=None):
        """
        To assign floating IP to the instance, make **POST** request to
        */api/openstack-instances/<uuid>/assign_floating_ip/* with link to the floating IP.
        Note that instance should be in stable state, service project link of the instance should be in stable state
        and have external network.

        Example of a valid request:

        .. code-block:: http

            POST /api/openstack-instances/6c9b01c251c24174a6691a1f894fae31/assign_floating_ip/ HTTP/1.1
            Content-Type: application/json
            Accept: application/json
            Authorization: Token c84d653b9ec92c6cbac41c706593e66f567a7fa4
            Host: example.com

            {
                "floating_ip": "http://example.com/api/floating-ips/5e7d93955f114d88981dea4f32ab673d/"
            }
        """
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        executors.InstanceAssignFloatingIpExecutor.execute(instance, floating_ip_uuid=serializer.get_floating_ip_uuid())

    assign_floating_ip.title = 'Assign floating IP'

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Instance.States.OK)
    def change_flavor(self, request, instance, uuid=None):
        old_flavor_name = instance.flavor_name
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        flavor = serializer.validated_data.get('flavor')
        executors.InstanceFlavorChangeExecutor().execute(instance, flavor=flavor, old_flavor_name=old_flavor_name)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Instance.States.OK)
    def start(self, request, instance, uuid=None):
        executors.InstanceStartExecutor().execute(instance)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Instance.States.OK)
    def stop(self, request, instance, uuid=None):
        executors.InstanceStopExecutor().execute(instance)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Instance.States.OK)
    def restart(self, request, instance, uuid=None):
        executors.InstanceRestartExecutor().execute(instance)
