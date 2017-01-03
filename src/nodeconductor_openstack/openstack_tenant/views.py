from django.utils import six
from rest_framework import decorators, response, status, permissions, filters as rf_filters, exceptions

from nodeconductor.core import (views as core_views, exceptions as core_exceptions, mixins as core_mixins,
                                permissions as core_permissions)
from nodeconductor.structure import views as structure_views, filters as structure_filters

from . import models, serializers, filters, executors


class TelemetryMixin(object):
    """
    This mixin adds /meters endpoint to the resource.

    List of available resource meters must be specified in separate JSON file in meters folder. In addition,
    mapping between resource model and meters file path must be specified
    in "_get_meters_file_name" method in "backend.py" file.
    """

    telemetry_serializers = {
        'meter_samples': serializers.MeterSampleSerializer
    }

    @decorators.detail_route(methods=['get'])
    def meters(self, request, uuid=None):
        """
        To list available meters for the resource, make **GET** request to
        */api/<resource_type>/<uuid>/meters/*.
        """
        resource = self.get_object()
        backend = resource.get_backend()

        meters = backend.list_meters(resource)

        page = self.paginate_queryset(meters)
        if page is not None:
            return self.get_paginated_response(page)

        return response.Response(meters)

    @decorators.detail_route(methods=['get'], url_path='meter-samples/(?P<name>[a-z0-9_.]+)')
    def meter_samples(self, request, name, uuid=None):
        """
        To get resource meter samples make **GET** request to */api/<resource_type>/<uuid>/meter-samples/<meter_name>/*.
        Note that *<meter_name>* must be from meters list.

        In order to get a list of samples for the specific period of time, *start* timestamp and *end* timestamp query
        parameters can be provided:

            - start - timestamp (default: one hour ago)
            - end - timestamp (default: current datetime)

        Example of a valid request:

        .. code-block:: http

            GET /api/openstack-instances/1143357799fc4cb99636c767136bef86/meter-samples/memory/?start=1470009600&end=1470843282
            Content-Type: application/json
            Accept: application/json
            Authorization: Token c84d653b9ec92c6cbac41c706593e66f567a7fa4
            Host: example.com
        """
        resource = self.get_object()
        backend = resource.get_backend()

        meters = backend.list_meters(resource)
        names = [meter['name'] for meter in meters]
        if name not in names:
            raise exceptions.ValidationError('Meter must be from meters list.')
        if not resource.backend_id:
            raise exceptions.ValidationError('%s must have backend_id.' % resource.__class__.__name__)

        serializer = serializers.MeterTimestampIntervalSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        start = serializer.validated_data['start']
        end = serializer.validated_data['end']

        samples = backend.get_meter_samples(resource, name, start=start, end=end)
        serializer = self.get_serializer(samples, many=True)

        return response.Response(serializer.data)

    def get_serializer_class(self):
        serializer = self.telemetry_serializers.get(self.action)
        return serializer or super(TelemetryMixin, self).get_serializer_class()


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
            if volume.bootable:
                raise core_exceptions.IncorrectStateException('It is impossible to detach bootable volume.')
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
    pull_executor = executors.InstancePullExecutor
    update_executor = executors.InstanceUpdateExecutor

    serializers = {
        'assign_floating_ip': serializers.AssignFloatingIpSerializer,
        'change_flavor': serializers.InstanceFlavorChangeSerializer,
        'destroy': serializers.InstanceDeleteSerializer,
        'update_security_groups': serializers.InstanceSecurityGroupsUpdateSerializer,
        'backup': serializers.BackupSerializer,
        'create_backup_schedule': serializers.BackupScheduleSerializer,
    }

    def get_serializer_context(self):
        context = super(InstanceViewSet, self).get_serializer_context()
        if self.action in ('backup', 'create_backup_schedule'):
            context['instance'] = self.get_object()
        return context

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
        if action == 'assign_floating_ip' and instance.external_ips:
            raise core_exceptions.IncorrectStateException('Instance already has floating IP.')
        if action == 'destroy':
            if instance.state not in (States.OK, States.ERRED):
                raise core_exceptions.IncorrectStateException('Instance state has to be OK or erred.')
            if instance.state == States.OK and instance.runtime_state != RuntimeStates.SHUTOFF:
                raise core_exceptions.IncorrectStateException('Instance has to be shutoff.')
        return super(InstanceViewSet, self).check_operation(request, resource, action)

    def list(self, request, *args, **kwargs):
        """
        To get a list of instances, run **GET** against */api/openstack-instances/* as authenticated user.
        Note that a user can only see connected instances:
        - instances that belong to a project where a user has a role.
        - instances that belong to a customer that a user owns.
        """
        return super(InstanceViewSet, self).list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """
        A new instance can be created by users with project administrator role or with staff privilege (is_staff=True).
        Example of a valid request:
        .. code-block:: http
            POST /api/openstack-instances/ HTTP/1.1
            Content-Type: application/json
            Accept: application/json
            Authorization: Token c84d653b9ec92c6cbac41c706593e66f567a7fa4
            Host: example.com
            {
                "name": "test VM",
                "description": "sample description",
                "image": "http://example.com/api/openstack-images/1ee380602b6283c446ad9420b3230bf0/",
                "flavor": "http://example.com/api/openstack-flavors/1ee385bc043249498cfeb8c7e3e079f0/",
                "ssh_public_key": "http://example.com/api/keys/6fbd6b24246f4fb38715c29bafa2e5e7/",
                "service_project_link": "http://example.com/api/openstack-service-project-link/674/",
                "tenant": "http://example.com/api/openstack-tenants/33bf0f83d4b948119038d6e16f05c129/",
                "data_volume_size": 1024,
                "system_volume_size": 20480,
                "security_groups": [
                    { "url": "http://example.com/api/security-groups/16c55dad9b3048db8dd60e89bd4d85bc/"},
                    { "url": "http://example.com/api/security-groups/232da2ad9b3048db8dd60eeaa23d8123/"}
                ]
            }
        """
        return super(InstanceViewSet, self).create(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        """
        To stop/start/restart an instance, run an authorized **POST** request against the instance UUID,
        appending the requested command.
        Examples of URLs:
        - POST /api/openstack-instances/6c9b01c251c24174a6691a1f894fae31/start/
        - POST /api/openstack-instances/6c9b01c251c24174a6691a1f894fae31/stop/
        - POST /api/openstack-instances/6c9b01c251c24174a6691a1f894fae31/restart/
        If instance is in the state that does not allow this transition, error code will be returned.
        """
        return super(InstanceViewSet, self).retrieve(request, *args, **kwargs)

    def perform_provision(self, serializer):
        instance = serializer.save()
        executors.InstanceCreateExecutor.execute(
            instance,
            ssh_key=serializer.validated_data.get('ssh_public_key'),
            flavor=serializer.validated_data['flavor'],
            allocate_floating_ip=serializer.validated_data['allocate_floating_ip'],
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

            DELETE /api/openstacktenant-instances/abceed63b8e844afacd63daeac855474/ HTTP/1.1
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

            DELETE /api/openstacktenant-instances/abceed63b8e844afacd63daeac855474/?delete_volumes=false HTTP/1.1
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
        */api/openstacktenant-instances/<uuid>/assign_floating_ip/* with link to the floating IP.
        Make empty POST request to allocate new floating IP and assign it to instance.
        Note that instance should be in stable state, service project link of the instance should be in stable state
        and have external network.

        Example of a valid request:

        .. code-block:: http

            POST /api/openstacktenant-instances/6c9b01c251c24174a6691a1f894fae31/assign_floating_ip/ HTTP/1.1
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
        floating_ip = serializer.save()
        if floating_ip:
            executors.InstanceAssignFloatingIpExecutor.execute(instance, floating_ip_uuid=floating_ip.uuid)
        else:
            executors.InstanceAssignFloatingIpExecutor.execute(instance)

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

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Instance.States.OK)
    def update_security_groups(self, request, instance, uuid=None):
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        executors.InstanceUpdateSecurityGroupsExecutor().execute(instance)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Instance.States.OK)
    def backup(self, request, instance, uuid=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        backup = serializer.save()

        executors.BackupCreateExecutor().execute(backup)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Instance.States.OK)
    def create_backup_schedule(self, request, instance, uuid=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)


class BackupViewSet(core_mixins.DeleteExecutorMixin, core_views.UpdateOnlyViewSet):
    queryset = models.Backup.objects.all()
    serializer_class = serializers.BackupSerializer
    lookup_field = 'uuid'
    filter_class = filters.BackupFilter
    delete_executor = executors.BackupDeleteExecutor
    filter_backends = (structure_filters.GenericRoleFilter, rf_filters.DjangoFilterBackend)
    permission_classes = (permissions.IsAuthenticated, permissions.DjangoObjectPermissions)
    serializers = {
        'restore': serializers.BackupRestorationSerializer,
    }

    def list(self, request, *args, **kwargs):
        """
        To create a backup, issue the following **POST** request:

        .. code-block:: http

            POST /api/openstack-backups/ HTTP/1.1
            Content-Type: application/json
            Accept: application/json
            Authorization: Token c84d653b9ec92c6cbac41c706593e66f567a7fa4
            Host: example.com

            {
                "instance": "http://example.com/api/openstack-instances/a04a26e46def4724a0841abcb81926ac/",
                "description": "a new manual backup"
            }

        On creation of backup it's projected size is validated against a remaining storage quota.
        """
        return super(BackupViewSet, self).list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        """
        Created backups support several operations. Only users with write access to backup source
        are allowed to perform these operations:

        - */api/openstack-backup/<backup_uuid>/restore/* - restore a specified backup.
        - */api/openstack-backup/<backup_uuid>/delete/* - delete a specified backup.

        If a backup is in a state that prohibits this operation, it will be returned in error message of the response.
        """
        return super(BackupViewSet, self).retrieve(request, *args, **kwargs)

    def get_serializer_class(self):
        serializer = self.serializers.get(self.action)
        return serializer or super(BackupViewSet, self).get_serializer_class()

    def get_serializer_context(self):
        context = super(BackupViewSet, self).get_serializer_context()
        if self.action == 'restore':
            context['backup'] = self.get_object()
        return context

    @decorators.detail_route(methods=['post'])
    @structure_views.safe_operation(valid_state=models.Backup.States.OK)
    def restore(self, request, instance, uuid=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        backup_restoration = serializer.save()

        executors.BackupRestorationExecutor().execute(backup_restoration)
        instance_serialiser = serializers.InstanceSerializer(
            backup_restoration.instance, context={'request': self.request})
        return response.Response(instance_serialiser.data, status=status.HTTP_201_CREATED)


class BackupScheduleViewSet(core_views.UpdateOnlyViewSet):
    queryset = models.BackupSchedule.objects.all()
    serializer_class = serializers.BackupScheduleSerializer
    lookup_field = 'uuid'
    filter_class = filters.BackupScheduleFilter
    filter_backends = (structure_filters.GenericRoleFilter, rf_filters.DjangoFilterBackend)
    permission_classes = (permissions.IsAuthenticated, permissions.DjangoObjectPermissions)

    def perform_update(self, serializer):
        instance = self.get_object().instance
        if not core_permissions.has_user_permission_for_instance(self.request.user, instance):
            raise exceptions.PermissionDenied()
        super(BackupScheduleViewSet, self).perform_update(serializer)

    def perform_destroy(self, schedule):
        if not core_permissions.has_user_permission_for_instance(self.request.user, schedule.instance):
            raise exceptions.PermissionDenied()
        super(BackupScheduleViewSet, self).perform_destroy(schedule)

    def get_backup_schedule(self):
        schedule = self.get_object()
        if not core_permissions.has_user_permission_for_instance(self.request.user, schedule.instance):
            raise exceptions.PermissionDenied()
        return schedule

    def list(self, request, *args, **kwargs):
        """
        For schedule to work, it should be activated - it's flag is_active set to true. If it's not, it won't be used
        for triggering the next backups. Schedule will be deactivated if backup fails.

        - **retention time** is a duration in days during which backup is preserved.
        - **maximal_number_of_backups** is a maximal number of active backups connected to this schedule.
        - **schedule** is a backup schedule defined in a cron format.
        - **timezone** is used for calculating next run of the backup (optional).

        A schedule can be it two states: active or not. Non-active states are not used for scheduling the new tasks.
        Only users with write access to backup schedule source can activate or deactivate schedule.
        """
        return super(BackupScheduleViewSet, self).list(self, request, *args, **kwargs)

    @decorators.detail_route(methods=['post'])
    def activate(self, request, uuid):
        """
        Activate a backup schedule. Note that
        if a schedule is already active, this will result in **409 CONFLICT** code.
        """
        schedule = self.get_backup_schedule()
        if schedule.is_active:
            return response.Response(
                {'status': 'Backup schedule is already activated'}, status=status.HTTP_409_CONFLICT)
        schedule.is_active = True
        schedule.error_message = ''
        schedule.save()
        return response.Response({'status': 'Backup schedule was activated'})

    @decorators.detail_route(methods=['post'])
    def deactivate(self, request, uuid):
        """
        Deactivate a backup schedule. Note that
        if a schedule was already deactivated, this will result in **409 CONFLICT** code.
        """
        schedule = self.get_backup_schedule()
        if not schedule.is_active:
            return response.Response(
                {'status': 'Backup schedule is already deactivated'}, status=status.HTTP_409_CONFLICT)
        schedule.is_active = False
        schedule.save()
        return response.Response({'status': 'Backup schedule was deactivated'})
