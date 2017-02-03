from django.utils import six
from rest_framework import decorators, response, status, exceptions, serializers as rf_serializers

from nodeconductor.core import exceptions as core_exceptions, validators as core_validators
from nodeconductor.structure import views as structure_views

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
    filter_class = filters.ImageFilter


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
    filter_class = filters.FloatingIPFilter


class SecurityGroupViewSet(structure_views.BaseServicePropertyViewSet):
    queryset = models.SecurityGroup.objects.all().order_by('settings', 'name')
    serializer_class = serializers.SecurityGroupSerializer
    lookup_field = 'uuid'
    filter_class = filters.SecurityGroupFilter


class VolumeViewSet(six.with_metaclass(structure_views.ResourceViewMetaclass,
                                       structure_views.ResourceViewSet)):
    queryset = models.Volume.objects.all()
    serializer_class = serializers.VolumeSerializer
    filter_class = filters.VolumeFilter

    create_executor = executors.VolumeCreateExecutor
    update_executor = executors.VolumeUpdateExecutor
    pull_executor = executors.VolumePullExecutor

    def _volume_snapshots_exist(volume):
        if volume.snapshots.exists():
            raise core_exceptions.IncorrectStateException('Volume has dependent snapshots.')

    delete_executor = executors.VolumeDeleteExecutor
    destroy_validators = [
        _volume_snapshots_exist,
        core_validators.StateValidator(models.Volume.States.OK, models.Volume.States.ERRED),
        core_validators.RuntimeStateValidator('available', 'error', 'error_restoring', 'error_extending', ''),
    ]

    def _is_volume_bootable(volume):
        if volume.bootable:
            raise core_exceptions.IncorrectStateException('Volume cannot be bootable.')

    def _is_volume_instance_shutoff(volume):
        if volume.instance and volume.instance.runtime_state != models.Instance.RuntimeStates.SHUTOFF:
            raise core_exceptions.IncorrectStateException('Volume instance should be in shutoff state.')

    @decorators.detail_route(methods=['post'])
    def extend(self, request, uuid=None):
        """ Increase volume size """
        volume = self.get_object()
        old_size = volume.size
        serializer = self.get_serializer(volume, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        volume.refresh_from_db()
        executors.VolumeExtendExecutor().execute(volume, old_size=old_size, new_size=volume.size)

        return response.Response({'status': 'extend was scheduled'}, status=status.HTTP_202_ACCEPTED)

    extend_validators = [_is_volume_bootable,
                         _is_volume_instance_shutoff,
                         core_validators.StateValidator(models.Instance.States.OK)]
    extend_serializer_class = serializers.VolumeExtendSerializer

    @decorators.detail_route(methods=['post'])
    def snapshot(self, request, uuid=None):
        """ Create snapshot from volume """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        snapshot = serializer.save()

        executors.SnapshotCreateExecutor().execute(snapshot)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    snapshot_serializer_class = serializers.SnapshotSerializer

    @decorators.detail_route(methods=['post'])
    def attach(self, request, uuid=None):
        """ Attach volume to instance """
        volume = self.get_object()
        serializer = self.get_serializer(volume, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        executors.VolumeAttachExecutor().execute(volume)
        return response.Response({'status': 'attach was scheduled'}, status=status.HTTP_202_ACCEPTED)

    attach_validators = [core_validators.RuntimeStateValidator('available'),
                         core_validators.StateValidator(models.Instance.States.OK)]
    attach_serializer_class = serializers.VolumeAttachSerializer

    @decorators.detail_route(methods=['post'])
    def detach(self, request, uuid=None):
        """ Detach instance from volume """
        volume = self.get_object()
        executors.VolumeDetachExecutor().execute(volume)
        return response.Response({'status': 'detach was scheduled'}, status=status.HTTP_202_ACCEPTED)

    detach_validators = [_is_volume_bootable,
                         core_validators.RuntimeStateValidator('in-use'),
                         core_validators.StateValidator(models.Instance.States.OK)]


class SnapshotViewSet(six.with_metaclass(structure_views.ResourceViewMetaclass,
                                         structure_views.ResourceViewSet)):
    queryset = models.Snapshot.objects.all()
    serializer_class = serializers.SnapshotSerializer
    update_executor = executors.SnapshotUpdateExecutor
    delete_executor = executors.SnapshotDeleteExecutor
    pull_executor = executors.SnapshotPullExecutor
    filter_class = filters.SnapshotFilter


class InstanceViewSet(six.with_metaclass(structure_views.ResourceViewMetaclass,
                                         structure_views.ResourceViewSet)):
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
    filter_class = filters.InstanceFilter
    pull_executor = executors.InstancePullExecutor

    update_executor = executors.InstanceUpdateExecutor
    update_validators = partial_update_validators = [core_validators.StateValidator(models.Instance.States.OK)]

    def perform_create(self, serializer):
        instance = serializer.save()
        executors.InstanceCreateExecutor.execute(
            instance,
            ssh_key=serializer.validated_data.get('ssh_public_key'),
            flavor=serializer.validated_data['flavor'],
            allocate_floating_ip=serializer.validated_data['allocate_floating_ip'],
            floating_ip=serializer.validated_data.get('floating_ip'),
            is_heavy_task=True,
        )

    def _has_backups(instance):
        if instance.backups.exists():
            raise core_exceptions.IncorrectStateException('Cannot delete instance that has backups.')

    def destroy(self, request, uuid=None):
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

        resource = self.get_object()
        force = resource.state == models.Instance.States.ERRED
        executors.InstanceDeleteExecutor.execute(
            resource,
            force=force,
            delete_volumes=delete_volumes,
            async=self.async_executor
        )

        return response.Response({'status': 'destroy was scheduled'}, status=status.HTTP_202_ACCEPTED)

    destroy_validators = [core_validators.StateValidator(models.Instance.States.OK, models.Instance.States.ERRED),
                          core_validators.RuntimeStateValidator(models.Instance.RuntimeStates.SHUTOFF),
                          _has_backups]
    destroy_serializer_class = serializers.InstanceDeleteSerializer

    def _instance_has_external_ips(instance):
        if instance.external_ips:
            raise core_exceptions.IncorrectStateException('Instance already has floating IP.')

    @decorators.detail_route(methods=['post'])
    def assign_floating_ip(self, request, uuid=None):
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
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        floating_ip = serializer.save()
        if floating_ip:
            executors.InstanceAssignFloatingIpExecutor.execute(instance, floating_ip_uuid=floating_ip.uuid)
        else:
            executors.InstanceAssignFloatingIpExecutor.execute(instance)

        return response.Response({'status': 'assign_floating_ip was scheduled'}, status=status.HTTP_202_ACCEPTED)

    assign_floating_ip.title = 'Assign floating IP'
    assign_floating_ip_validators = [core_validators.StateValidator(models.Instance.States.OK),
                                     _instance_has_external_ips]
    assign_floating_ip_serializer_class = serializers.AssignFloatingIpSerializer

    def _instance_has_no_floating_ip(instance):
        if not models.FloatingIP.objects.filter(settings=instance.service_project_link.service.settings,
                                                address=instance.external_ips).exists():
            raise core_exceptions.IncorrectStateException('External ips is not assosiated with floating ip.')

    @decorators.detail_route(methods=['post'])
    def unassign_floating_ip(self, request, uuid=None):
        instance = self.get_object()
        floating_ip = models.FloatingIP.objects.get(settings=instance.service_project_link.service.settings,
                                                    address=instance.external_ips)
        executors.InstanceUnassignFloatingIpExecutor.execute(instance, floating_ip=floating_ip)
        return response.Response({'status': 'unassign_floating_ip was scheduled'}, status=status.HTTP_202_ACCEPTED)

    unassign_floating_ip.title = 'Unassign floating IP'
    unassign_floating_ip_validators = [core_validators.StateValidator(models.Instance.States.OK),
                                       _instance_has_no_floating_ip]
    unassign_floating_ip_serializer_class = rf_serializers.Serializer

    @decorators.detail_route(methods=['post'])
    def change_flavor(self, request, uuid=None):
        instance = self.get_object()
        old_flavor_name = instance.flavor_name
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        flavor = serializer.validated_data.get('flavor')
        executors.InstanceFlavorChangeExecutor().execute(instance, flavor=flavor, old_flavor_name=old_flavor_name)
        return response.Response({'status': 'change_flavor was scheduled'}, status=status.HTTP_202_ACCEPTED)

    change_flavor_serializer_class = serializers.InstanceFlavorChangeSerializer
    change_flavor_validators = [core_validators.StateValidator(models.Instance.States.OK),
                                core_validators.RuntimeStateValidator(models.Instance.RuntimeStates.SHUTOFF)]

    @decorators.detail_route(methods=['post'])
    def start(self, request, uuid=None):
        instance = self.get_object()
        executors.InstanceStartExecutor().execute(instance)
        return response.Response({'status': 'start was scheduled'}, status=status.HTTP_202_ACCEPTED)

    start_validators = [core_validators.StateValidator(models.Instance.States.OK),
                        core_validators.RuntimeStateValidator(models.Instance.RuntimeStates.SHUTOFF)]

    @decorators.detail_route(methods=['post'])
    def stop(self, request, uuid=None):
        instance = self.get_object()
        executors.InstanceStopExecutor().execute(instance)
        return response.Response({'status': 'stop was scheduled'}, status=status.HTTP_202_ACCEPTED)

    stop_validators = [core_validators.StateValidator(models.Instance.States.OK),
                       core_validators.RuntimeStateValidator(models.Instance.RuntimeStates.ACTIVE)]

    @decorators.detail_route(methods=['post'])
    def restart(self, request, uuid=None):
        instance = self.get_object()
        executors.InstanceRestartExecutor().execute(instance)
        return response.Response({'status': 'restart was scheduled'}, status=status.HTTP_202_ACCEPTED)

    restart_validators = [core_validators.StateValidator(models.Instance.States.OK),
                          core_validators.RuntimeStateValidator(models.Instance.RuntimeStates.ACTIVE)]

    @decorators.detail_route(methods=['post'])
    def update_security_groups(self, request, uuid=None):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        executors.InstanceUpdateSecurityGroupsExecutor().execute(instance)
        return response.Response({'status': 'security groups update was scheduled'}, status=status.HTTP_202_ACCEPTED)

    update_security_groups_validators = [core_validators.StateValidator(models.Instance.States.OK)]
    update_security_groups_serializer_class = serializers.InstanceSecurityGroupsUpdateSerializer

    @decorators.detail_route(methods=['post'])
    def backup(self, request, uuid=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        backup = serializer.save()

        executors.BackupCreateExecutor().execute(backup)
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    backup_validators = [core_validators.StateValidator(models.Instance.States.OK)]
    backup_serializer_class = serializers.BackupSerializer

    @decorators.detail_route(methods=['post'])
    def create_backup_schedule(self, request, uuid=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    create_backup_schedule_validators = [core_validators.StateValidator(models.Instance.States.OK)]
    create_backup_schedule_serializer_class = serializers.BackupScheduleSerializer


class BackupViewSet(six.with_metaclass(structure_views.ResourceViewMetaclass,
                                       structure_views.ResourceViewSet)):
    queryset = models.Backup.objects.all()
    serializer_class = serializers.BackupSerializer
    filter_class = filters.BackupFilter
    disabled_actions = ['create']

    delete_executor = executors.BackupDeleteExecutor

    # method has to be overridden in order to avoid triggering of UpdateExecutor
    # which is a default action for all ResourceViewSet(s)
    def perform_update(self, serializer):
        serializer.save()

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

    @decorators.detail_route(methods=['post'])
    def restore(self, request, uuid=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        backup_restoration = serializer.save()

        executors.BackupRestorationExecutor().execute(backup_restoration)
        instance_serialiser = serializers.InstanceSerializer(
            backup_restoration.instance, context={'request': self.request})
        return response.Response(instance_serialiser.data, status=status.HTTP_201_CREATED)

    restore_validators = [core_validators.StateValidator(models.Backup.States.OK)]
    restore_serializer_class = serializers.BackupRestorationSerializer


class BackupScheduleViewSet(six.with_metaclass(structure_views.ResourceViewMetaclass,
                                               structure_views.ResourceViewSet)):
    queryset = models.BackupSchedule.objects.all()
    serializer_class = serializers.BackupScheduleSerializer
    filter_class = filters.BackupScheduleFilter
    disabled_actions = ['create']

    # method has to be overridden in order to avoid triggering of UpdateExecutor
    # which is a default action for all ResourceViewSet(s)
    def perform_update(self, serializer):
        serializer.save()

    # method has to be overridden in order to avoid triggering of DeleteExecutor
    # which is a default action for all ResourceViewSet(s)
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)

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

    def _is_backup_schedule_active(backup_schedule):
        if backup_schedule.is_active:
            raise core_exceptions.IncorrectStateException('Backup schedule is already activated.')

    @decorators.detail_route(methods=['post'])
    def activate(self, request, uuid):
        """
        Activate a backup schedule. Note that
        if a schedule is already active, this will result in **409 CONFLICT** code.
        """
        schedule = self.get_object()
        schedule.is_active = True
        schedule.error_message = ''
        schedule.save()
        return response.Response({'status': 'Backup schedule was activated'})

    activate_validators = [_is_backup_schedule_active]

    def _is_backup_schedule_deactived(backup_schedule):
        if not backup_schedule.is_active:
            raise core_exceptions.IncorrectStateException('Backup schedule is already deactivated.')

    @decorators.detail_route(methods=['post'])
    def deactivate(self, request, uuid):
        """
        Deactivate a backup schedule. Note that
        if a schedule was already deactivated, this will result in **409 CONFLICT** code.
        """
        schedule = self.get_object()
        schedule.is_active = False
        schedule.save()
        return response.Response({'status': 'Backup schedule was deactivated'})

    deactivate_validators = [_is_backup_schedule_deactived]
