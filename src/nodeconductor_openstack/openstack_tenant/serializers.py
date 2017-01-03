from __future__ import unicode_literals

import logging
import pytz
import re

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from nodeconductor.core import serializers as core_serializers, fields as core_fields, utils as core_utils
from nodeconductor.structure import serializers as structure_serializers

from . import models, fields


logger = logging.getLogger(__name__)


class ServiceSerializer(core_serializers.ExtraFieldOptionsMixin,
                        core_serializers.RequiredFieldsMixin,
                        structure_serializers.BaseServiceSerializer):

    SERVICE_ACCOUNT_FIELDS = {
        'backend_url': 'Keystone auth URL (e.g. http://keystone.example.com:5000/v2.0)',
        'username': 'Tenant user username',
        'password': 'Tenant user password',
    }
    SERVICE_ACCOUNT_EXTRA_FIELDS = {
        'tenant_id': 'Tenant ID in OpenStack',
        'availability_zone': 'Default availability zone for provisioned instances',
    }

    class Meta(structure_serializers.BaseServiceSerializer.Meta):
        model = models.OpenStackTenantService
        view_name = 'openstacktenant-detail'
        required_fields = ('backend_url', 'username', 'password', 'tenant_id')
        extra_field_options = {
            'backend_url': {
                'label': 'API URL',
                'default_value': 'http://keystone.example.com:5000/v2.0',
            },
            'tenant_id': {
                'label': 'Tenant ID',
            },
            'availability_zone': {
                'placeholder': 'default',
            },
        }


class ServiceProjectLinkSerializer(structure_serializers.BaseServiceProjectLinkSerializer):

    class Meta(structure_serializers.BaseServiceProjectLinkSerializer.Meta):
        model = models.OpenStackTenantServiceProjectLink
        view_name = 'openstacktenant-spl-detail'
        extra_kwargs = {
            'url': {'view_name': 'openstacktenant-spl-detail'},
            'service': {'lookup_field': 'uuid', 'view_name': 'openstacktenant-detail'},
        }


class ImageSerializer(structure_serializers.BasePropertySerializer):

    class Meta(structure_serializers.BasePropertySerializer.Meta):
        model = models.Image
        fields = ('url', 'uuid', 'name', 'settings', 'min_disk', 'min_ram',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid', 'view_name': 'openstacktenant-image-detail'},
            'settings': {'lookup_field': 'uuid'},
        }


class FlavorSerializer(structure_serializers.BasePropertySerializer):

    class Meta(structure_serializers.BasePropertySerializer.Meta):
        model = models.Flavor
        fields = ('url', 'uuid', 'name', 'settings', 'cores', 'ram', 'disk',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid', 'view_name': 'openstacktenant-flavor-detail'},
            'settings': {'lookup_field': 'uuid'},
        }


class FloatingIPSerializer(structure_serializers.BasePropertySerializer):

    class Meta(structure_serializers.BasePropertySerializer.Meta):
        model = models.FloatingIP
        fields = ('url', 'uuid', 'settings', 'address', 'status', 'is_booked',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid', 'view_name': 'openstacktenant-fip-detail'},
            'settings': {'lookup_field': 'uuid'},
        }


class SecurityGroupSerializer(structure_serializers.BasePropertySerializer):
    rules = serializers.SerializerMethodField()

    class Meta(structure_serializers.BasePropertySerializer.Meta):
        model = models.SecurityGroup
        fields = ('url', 'uuid', 'name', 'settings', 'description', 'rules')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid', 'view_name': 'openstacktenant-sgp-detail'},
            'settings': {'lookup_field': 'uuid'},
        }

    def get_rules(self, security_group):
        rules = []
        for rule in security_group.rules.all():
            rules.append({
                'protocol': rule.protocol,
                'from_port': rule.from_port,
                'to_port': rule.to_port,
                'cidr': rule.cidr,
            })
        return rules


class VolumeSerializer(structure_serializers.BaseResourceSerializer):

    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstacktenant-detail',
        read_only=True,
        lookup_field='uuid')
    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstacktenant-spl-detail',
        queryset=models.OpenStackTenantServiceProjectLink.objects.all(),
    )
    action_details = core_serializers.JSONField(read_only=True)
    instance_name = serializers.SerializerMethodField()

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.Volume
        view_name = 'openstacktenant-volume-detail'
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'source_snapshot', 'size', 'bootable', 'metadata',
            'image', 'image_metadata', 'type', 'runtime_state',
            'device', 'action', 'action_details', 'instance', 'instance_name',
        )
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'image_metadata', 'bootable', 'source_snapshot', 'runtime_state', 'device', 'metadata',
            'action', 'instance',
        )
        protected_fields = structure_serializers.BaseResourceSerializer.Meta.protected_fields + (
            'size', 'type', 'image',
        )
        extra_kwargs = dict(
            instance={'lookup_field': 'uuid', 'view_name': 'openstacktenant-instance-detail'},
            image={'lookup_field': 'uuid', 'view_name': 'openstacktenant-image-detail'},
            source_snapshot={'lookup_field': 'uuid', 'view_name': 'openstacktenant-snapshot-detail'},
            size={'required': False, 'allow_null': True},
            **structure_serializers.BaseResourceSerializer.Meta.extra_kwargs
        )

    def get_instance_name(self, volume):
        if volume.instance:
            return volume.instance.name

    def validate(self, attrs):
        if self.instance is None:
            # image validation
            image = attrs.get('image')
            spl = attrs['service_project_link']
            if image and image.settings != spl.service.settings:
                raise serializers.ValidationError({'image': 'Image must belong to the same service settings'})
            # snapshot & size validation
            size = attrs.get('size')
            snapshot = attrs.get('snapshot')
            if not size and not snapshot:
                raise serializers.ValidationError('Snapshot or size should be defined')
            if size and snapshot:
                raise serializers.ValidationError('It is impossible to define both snapshot and size')
            # image & size validation
            size = size or snapshot.size
            if image and image.min_disk > size:
                raise serializers.ValidationError({
                    'size': 'Volume size should be equal or greater than %s for selected image' % image.min_disk
                })
        return attrs

    def create(self, validated_data):
        if not validated_data.get('size'):
            validated_data['size'] = validated_data['snapshot'].size
        return super(VolumeSerializer, self).create(validated_data)


class VolumeExtendSerializer(serializers.Serializer):
    disk_size = serializers.IntegerField(min_value=1, label='Disk size')

    def validate_disk_size(self, disk_size):
        if disk_size < self.instance.size + 1024:
            raise serializers.ValidationError(
                'Disk size should be greater or equal to %s' % (self.instance.size + 1024))
        return disk_size

    @transaction.atomic
    def update(self, instance, validated_data):
        new_size = validated_data.get('disk_size')
        instance.service_project_link.service.settings.add_quota_usage(
            'storage', new_size - instance.size, validate=True)
        instance.size = new_size
        instance.save(update_fields=['size'])
        return instance


class VolumeAttachSerializer(structure_serializers.PermissionFieldFilteringMixin,
                             serializers.HyperlinkedModelSerializer):
    class Meta(object):
        model = models.Volume
        fields = ('instance', 'device')
        extra_kwargs = dict(
            instance={
                'required': True,
                'allow_null': False,
                'view_name': 'openstacktenant-instance-detail',
                'lookup_field': 'uuid',
            }
        )

    def get_fields(self):
        fields = super(VolumeAttachSerializer, self).get_fields()
        volume = self.instance
        if volume:
            fields['instance'].display_name_field = 'name'
            fields['instance'].query_params = {
                'project_uuid': volume.service_project_link.project.uuid.hex,
                'service_uuid': volume.service_project_link.service.uuid.hex,
            }
        return fields

    def get_filtered_field_names(self):
        return ('instance',)

    def validate_instance(self, instance):
        States, RuntimeStates = models.Instance.States, models.Instance.RuntimeStates
        if instance.state != States.OK or instance.runtime_state != RuntimeStates.SHUTOFF:
            raise serializers.ValidationError(
                'Volume can be attached only to instance that is shutoff and in state OK.')
        volume = self.instance
        if instance.service_project_link != volume.service_project_link:
            raise serializers.ValidationError('Volume and instance should belong to the same service and project.')
        return instance

    def validate(self, attrs):
        instance = attrs['instance']
        device = attrs.get('device')
        if device and instance.volumes.filter(device=device).exists():
            raise serializers.ValidationError({'device': 'The supplied device path (%s) is in use.' % device})
        return attrs


class SnapshotSerializer(structure_serializers.BaseResourceSerializer):

    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstacktenant-detail',
        read_only=True,
        lookup_field='uuid')

    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstacktenant-spl-detail',
        read_only=True)

    source_volume_name = serializers.ReadOnlyField(source='source_volume.name')
    action_details = core_serializers.JSONField(read_only=True)

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.Snapshot
        view_name = 'openstacktenant-snapshot-detail'
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'source_volume', 'size', 'metadata', 'runtime_state', 'source_volume_name', 'action', 'action_details',
        )
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'size', 'source_volume', 'metadata', 'runtime_state', 'action',
        )
        extra_kwargs = dict(
            source_volume={'lookup_field': 'uuid', 'view_name': 'openstacktenant-volume-detail'},
            **structure_serializers.BaseResourceSerializer.Meta.extra_kwargs
        )

    def create(self, validated_data):
        # source volume should be added to context on creation
        source_volume = self.context['source_volume']
        validated_data['source_volume'] = source_volume
        validated_data['service_project_link'] = source_volume.service_project_link
        validated_data['size'] = source_volume.size
        return super(SnapshotSerializer, self).create(validated_data)


class NestedVolumeSerializer(serializers.HyperlinkedModelSerializer, structure_serializers.BasicResourceSerializer):
    state = serializers.ReadOnlyField(source='get_state_display')

    class Meta:
        model = models.Volume
        fields = 'url', 'uuid', 'name', 'state', 'bootable', 'size', 'resource_type'
        view_name = 'openstacktenant-volume-detail'
        lookup_field = 'uuid'


class NestedSecurityGroupRuleSerializer(serializers.ModelSerializer):

    class Meta:
        model = models.SecurityGroupRule
        fields = ('id', 'protocol', 'from_port', 'to_port', 'cidr')

    def to_internal_value(self, data):
        # Return exist security group as internal value if id is provided
        if 'id' in data:
            try:
                return models.SecurityGroupRule.objects.get(id=data['id'])
            except models.SecurityGroup:
                raise serializers.ValidationError('Security group with id %s does not exist' % data['id'])
        else:
            internal_data = super(NestedSecurityGroupRuleSerializer, self).to_internal_value(data)
            return models.SecurityGroupRule(**internal_data)


class NestedSecurityGroupSerializer(core_serializers.HyperlinkedRelatedModelSerializer):
    rules = NestedSecurityGroupRuleSerializer(
        many=True,
        read_only=True,
    )
    state = serializers.ReadOnlyField(source='human_readable_state')

    class Meta(object):
        model = models.SecurityGroup
        fields = ('url', 'name', 'rules', 'description', 'state')
        read_only_fields = ('name', 'rules', 'description', 'state')
        view_name = 'openstacktenant-sgp-detail'
        lookup_field = 'uuid'


class InstanceSerializer(structure_serializers.VirtualMachineSerializer):

    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstacktenant-detail',
        read_only=True,
        lookup_field='uuid')

    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstacktenant-spl-detail',
        queryset=models.OpenStackTenantServiceProjectLink.objects.all())

    flavor = serializers.HyperlinkedRelatedField(
        view_name='openstacktenant-flavor-detail',
        lookup_field='uuid',
        queryset=models.Flavor.objects.all().select_related('settings'),
        write_only=True)

    image = serializers.HyperlinkedRelatedField(
        view_name='openstacktenant-image-detail',
        lookup_field='uuid',
        queryset=models.Image.objects.all().select_related('settings'),
        write_only=True)

    security_groups = NestedSecurityGroupSerializer(
        queryset=models.SecurityGroup.objects.all(), many=True, required=False)

    allocate_floating_ip = serializers.BooleanField(write_only=True, default=False)
    system_volume_size = serializers.IntegerField(min_value=1024, write_only=True)
    data_volume_size = serializers.IntegerField(initial=20 * 1024, default=20 * 1024, min_value=1024, write_only=True)

    floating_ip = serializers.HyperlinkedRelatedField(
        label='Floating IP',
        required=False,
        allow_null=True,
        view_name='openstacktenant-fip-detail',
        lookup_field='uuid',
        queryset=models.FloatingIP.objects.all(),
        write_only=True
    )
    volumes = NestedVolumeSerializer(many=True, required=False, read_only=True)
    action_details = core_serializers.JSONField(read_only=True)

    class Meta(structure_serializers.VirtualMachineSerializer.Meta):
        model = models.Instance
        view_name = 'openstacktenant-instance-detail'
        fields = structure_serializers.VirtualMachineSerializer.Meta.fields + (
            'flavor', 'image', 'system_volume_size', 'data_volume_size', 'allocate_floating_ip',
            'security_groups', 'internal_ips', 'flavor_disk', 'flavor_name',
            'floating_ip', 'volumes', 'runtime_state', 'action', 'action_details',
        )
        protected_fields = structure_serializers.VirtualMachineSerializer.Meta.protected_fields + (
            'flavor', 'image', 'system_volume_size', 'data_volume_size', 'allocate_floating_ip',
            'floating_ip', 'security_groups',
        )
        read_only_fields = structure_serializers.VirtualMachineSerializer.Meta.read_only_fields + (
            'flavor_disk', 'runtime_state', 'flavor_name', 'action',
        )

    def get_fields(self):
        fields = super(InstanceSerializer, self).get_fields()
        field = fields.get('floating_ip')
        if field:
            field.query_params = {'status': 'DOWN'}
            field.value_field = 'url'
            field.display_name_field = 'address'

        return fields

    @staticmethod
    def eager_load(queryset):
        queryset = structure_serializers.VirtualMachineSerializer.eager_load(queryset)
        return queryset.prefetch_related(
            'security_groups',
            'security_groups__rules',
            'volumes',
        )

    def validate(self, attrs):
        # skip validation on object update
        if self.instance is not None:
            return attrs

        service_project_link = attrs['service_project_link']
        settings = service_project_link.service.settings
        flavor = attrs['flavor']
        image = attrs['image']

        if any([flavor.settings != settings, image.settings != settings]):
            raise serializers.ValidationError(
                "Flavor and image must belong to the same service settings as service project link.")

        if image.min_ram > flavor.ram:
            raise serializers.ValidationError(
                {'flavor': "RAM of flavor is not enough for selected image %s" % image.min_ram})

        if image.min_disk > flavor.disk:
            raise serializers.ValidationError({
                'flavor': "Flavor's disk is too small for the selected image."
            })

        if image.min_disk > attrs['system_volume_size']:
            raise serializers.ValidationError(
                {'system_volume_size': "System volume size has to be greater than %s" % image.min_disk})

        for security_group in attrs.get('security_groups', []):
            if security_group.settings != settings:
                raise serializers.ValidationError(
                    "Security group {} does not belong to the same service settings as service project link.".format(
                        security_group.name))

        self._validate_external_ip(attrs)

        return attrs

    def _validate_external_ip(self, attrs):
        floating_ip = attrs.get('floating_ip')
        spl = attrs['service_project_link']
        allocate_floating_ip = attrs['allocate_floating_ip']

        # Case 1. If floating_ip!=None then requested floating IP is assigned to the instance.
        if floating_ip:

            if floating_ip.status != 'DOWN':
                raise serializers.ValidationError({'floating_ip': 'Floating IP status must be DOWN.'})

            if floating_ip.settings != spl.service.settings:
                raise serializers.ValidationError({
                    'floating_ip': 'Floating IP must belong to the same service settings.'
                })

        # Case 2. If floating_ip=None and allocate_floating_ip=True
        # then new floating IP is allocated and assigned to the instance.
        elif allocate_floating_ip:

            floating_ip_count_quota = spl.service.settings.quotas.get(name='floating_ip_count')
            if floating_ip_count_quota.is_exceeded(delta=1):
                raise serializers.ValidationError({
                    'allocate_floating_ip': 'Can not allocate floating IP - quota has been filled.'
                })

        # Case 3. If floating_ip=None and allocate_floating_ip=False
        # floating IP allocation is not attempted, only internal IP is created.
        else:
            logger.debug('Floating IP allocation is not attempted.')

    @transaction.atomic
    def create(self, validated_data):
        """ Store flavor, ssh_key and image details into instance model.
            Create volumes and security groups for instance.
        """
        security_groups = validated_data.pop('security_groups', [])
        spl = validated_data['service_project_link']
        ssh_key = validated_data.get('ssh_public_key')
        if ssh_key:
            # We want names to be human readable in backend.
            # OpenStack only allows latin letters, digits, dashes, underscores and spaces
            # as key names, thus we mangle the original name.
            safe_name = re.sub(r'[^-a-zA-Z0-9 _]+', '_', ssh_key.name)[:17]
            validated_data['key_name'] = '{0}-{1}'.format(ssh_key.uuid.hex, safe_name)
            validated_data['key_fingerprint'] = ssh_key.fingerprint

        flavor = validated_data['flavor']
        validated_data['flavor_name'] = flavor.name
        validated_data['cores'] = flavor.cores
        validated_data['ram'] = flavor.ram
        validated_data['flavor_disk'] = flavor.disk

        image = validated_data['image']
        validated_data['image_name'] = image.name
        validated_data['min_disk'] = image.min_disk
        validated_data['min_ram'] = image.min_ram

        system_volume_size = validated_data['system_volume_size']
        data_volume_size = validated_data['data_volume_size']
        validated_data['disk'] = data_volume_size + system_volume_size

        instance = super(InstanceSerializer, self).create(validated_data)

        instance.security_groups.add(*security_groups)

        system_volume = models.Volume.objects.create(
            name='{0}-system'.format(instance.name[:143]),  # volume name cannot be longer than 150 symbols
            service_project_link=spl,
            size=system_volume_size,
            image=image,
            bootable=True,
        )
        system_volume.increase_backend_quotas_usage()
        data_volume = models.Volume.objects.create(
            name='{0}-data'.format(instance.name[:145]),  # volume name cannot be longer than 150 symbols
            service_project_link=spl,
            size=data_volume_size,
        )
        data_volume.increase_backend_quotas_usage()
        instance.volumes.add(system_volume, data_volume)

        return instance

    def update(self, instance, validated_data):
        # DRF adds data_volume_size to validated_data, because it has default value.
        # This field is protected, so it should not be used for update.
        del validated_data['data_volume_size']
        return super(InstanceSerializer, self).update(instance, validated_data)


class AssignFloatingIpSerializer(serializers.Serializer):
    floating_ip = serializers.HyperlinkedRelatedField(
        label='Floating IP',
        required=False,
        allow_null=True,
        view_name='openstacktenant-fip-detail',
        lookup_field='uuid',
        queryset=models.FloatingIP.objects.all()
    )

    def get_fields(self):
        fields = super(AssignFloatingIpSerializer, self).get_fields()
        if self.instance:
            query_params = {
                'status': 'DOWN',
                'settings_uuid': self.instance.service_project_link.service.settings.uuid.hex,
            }

            field = fields['floating_ip']
            field.query_params = query_params
            field.value_field = 'url'
            field.display_name_field = 'address'
        return fields

    def validate_floating_ip(self, floating_ip):
        if floating_ip is not None:
            if floating_ip.status != 'DOWN':
                raise serializers.ValidationError("Floating IP status must be DOWN.")
            elif floating_ip.settings != self.instance.service_project_link.service.settings:
                raise serializers.ValidationError("Floating IP must belong to same settings as instance.")
        return floating_ip

    def save(self):
        # Increase service settings quota on floating IP quota if new one will be created.
        if not self.validated_data.get('floating_ip'):
            settings = self.instance.service_project_link.service.settings
            settings.add_quota_usage(settings.Quotas.floating_ip_count, 1, validate=True)
        return self.validated_data.get('floating_ip')


class InstanceFlavorChangeSerializer(structure_serializers.PermissionFieldFilteringMixin, serializers.Serializer):
    flavor = serializers.HyperlinkedRelatedField(
        view_name='openstacktenant-flavor-detail',
        lookup_field='uuid',
        queryset=models.Flavor.objects.all(),
    )

    def get_fields(self):
        fields = super(InstanceFlavorChangeSerializer, self).get_fields()
        if self.instance:
            fields['flavor'].query_params = {
                'settings_uuid': self.instance.service_project_link.service.settings.uuid
            }
        return fields

    def get_filtered_field_names(self):
        return ('flavor',)

    def validate_flavor(self, value):
        if value is not None:
            spl = self.instance.service_project_link

            if value.name == self.instance.flavor_name:
                raise serializers.ValidationError(
                    "New flavor is the same as current.")

            if value.settings != spl.service.settings:
                raise serializers.ValidationError(
                    "New flavor is not within the same service settings")

            if value.disk < self.instance.flavor_disk:
                raise serializers.ValidationError(
                    "New flavor disk should be greater than the previous value")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        flavor = validated_data.get('flavor')

        settings = instance.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.ram, flavor.ram - instance.ram, validate=True)
        settings.add_quota_usage(settings.Quotas.vcpu, flavor.cores - instance.cores, validate=True)

        instance.ram = flavor.ram
        instance.cores = flavor.cores
        instance.flavor_disk = flavor.disk
        instance.flavor_name = flavor.name
        instance.save(update_fields=['ram', 'cores', 'flavor_name', 'flavor_disk'])
        return instance


class InstanceDeleteSerializer(serializers.Serializer):
    delete_volumes = serializers.BooleanField(default=True)

    def validate(self, attrs):
        if self.instance.backups.exists():
            raise serializers.ValidationError('Cannot delete instance that has backups.')
        return attrs


class InstanceSecurityGroupsUpdateSerializer(serializers.Serializer):
    security_groups = NestedSecurityGroupSerializer(
        queryset=models.SecurityGroup.objects.all(),
        many=True,
    )

    def get_fields(self):
        fields = super(InstanceSecurityGroupsUpdateSerializer, self).get_fields()
        instance = self.instance
        if instance:
            fields['security_groups'].display_name_field = 'name'
            fields['security_groups'].view_name = 'openstacktenant-sgp-detail'
            fields['security_groups'].query_params = {
                'settings_uuid': instance.service_project_link.service.settings.uuid
            }
        return fields

    def validate_security_groups(self, security_groups):
        spl = self.instance.service_project_link

        for security_group in security_groups:
            if security_group.settings != spl.service.settings:
                raise serializers.ValidationError(
                    "Security group %s is not within the same service settings" % security_group.name)

        return security_groups

    @transaction.atomic
    def update(self, instance, validated_data):
        security_groups = validated_data.pop('security_groups', None)
        if security_groups is not None:
            instance.security_groups.clear()
            instance.security_groups.add(*security_groups)

        return instance


class BackupRestorationSerializer(serializers.HyperlinkedModelSerializer):
    # requires backup in context on creation
    name = serializers.CharField(
        required=False, help_text='New instance name. Leave blank to use source instance name.')

    class Meta(object):
        model = models.BackupRestoration
        fields = ('uuid', 'instance', 'created', 'flavor', 'name')
        read_only_fields = ('url', 'uuid', 'instance', 'created', 'backup')
        extra_kwargs = dict(
            instance={'lookup_field': 'uuid', 'view_name': 'openstacktenant-instance-detail'},
            flavor={'lookup_field': 'uuid', 'view_name': 'openstacktenant-flavor-detail', 'allow_null': False,
                    'required': True},
        )

    def validate(self, attrs):
        flavor = attrs['flavor']
        backup = self.context['backup']
        if flavor.settings != backup.instance.service_project_link.service.settings:
            raise serializers.ValidationError({'flavor': "Flavor is not within services' settings."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        flavor = validated_data['flavor']
        validated_data['backup'] = backup = self.context['backup']
        source_instance = backup.instance
        # instance that will be restored
        metadata = backup.metadata or {}
        instance = models.Instance.objects.create(
            name=validated_data.pop('name', None) or metadata.get('name', source_instance.name),
            description=metadata.get('description', ''),
            service_project_link=backup.service_project_link,
            flavor_disk=flavor.disk,
            flavor_name=flavor.name,
            cores=flavor.cores,
            ram=flavor.ram,
            min_ram=metadata.get('min_ram', 0),
            min_disk=metadata.get('min_disk', 0),
            image_name=metadata.get('image_name', ''),
            user_data=metadata.get('user_data', ''),
            disk=sum([snapshot.size for snapshot in backup.snapshots.all()]),
        )
        instance.increase_backend_quotas_usage()
        validated_data['instance'] = instance
        backup_restoration = super(BackupRestorationSerializer, self).create(validated_data)
        # restoration for each instance volume from snapshot.
        for snapshot in backup.snapshots.all():
            volume = models.Volume(
                source_snapshot=snapshot,
                service_project_link=snapshot.service_project_link,
                name='{0}-volume'.format(instance.name[:143]),
                description='Restored from backup %s' % backup.uuid.hex,
                size=snapshot.size,
            )
            if 'source_volume_image_metadata' in snapshot.metadata:
                volume.image_metadata = snapshot.metadata['source_volume_image_metadata']
            volume.save()
            volume.increase_backend_quotas_usage()
            instance.volumes.add(volume)
        return backup_restoration


class BackupSerializer(structure_serializers.BaseResourceSerializer):
    # Serializer requires OpenStack Instance in context on creation
    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstacktenant-detail',
        read_only=True,
        lookup_field='uuid')
    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstacktenant-spl-detail',
        read_only=True,
    )
    metadata = core_fields.JsonField(read_only=True)
    instance_name = serializers.ReadOnlyField(source='instance.name')
    restorations = BackupRestorationSerializer(many=True, read_only=True)

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.Backup
        view_name = 'openstacktenant-backup-detail'
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'kept_until', 'metadata', 'instance', 'instance_name', 'restorations')
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'instance', 'service_project_link')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'instance': {'lookup_field': 'uuid', 'view_name': 'openstacktenant-instance-detail'},
            # 'backup_schedule': {'lookup_field': 'uuid', 'view_name': 'openstack-schedule-detail'},
        }

    @transaction.atomic
    def create(self, validated_data):
        validated_data['instance'] = instance = self.context['instance']
        validated_data['service_project_link'] = instance.service_project_link
        validated_data['metadata'] = self.get_backup_metadata(instance)
        backup = super(BackupSerializer, self).create(validated_data)
        self.create_backup_snapshots(backup)
        return backup

    @staticmethod
    def get_backup_metadata(instance):
        return {
            'name': instance.name,
            'description': instance.description,
            'min_ram': instance.min_ram,
            'min_disk': instance.min_disk,
            'key_name': instance.key_name,
            'key_fingerprint': instance.key_fingerprint,
            'user_data': instance.user_data,
            'flavor_name': instance.flavor_name,
            'image_name': instance.image_name,
        }

    @staticmethod
    def create_backup_snapshots(backup):
        for volume in backup.instance.volumes.all():
            snapshot = models.Snapshot.objects.create(
                name='Snapshot for volume %s' % volume.name,
                service_project_link=backup.service_project_link,
                size=volume.size,
                source_volume=volume,
                description='Part of backup %s' % backup.uuid.hex,
                metadata={
                    'source_volume_name': volume.name,
                    'source_volume_description': volume.description,
                    'source_volume_image_metadata': volume.image_metadata,
                },
            )
            snapshot.increase_backend_quotas_usage()
            backup.snapshots.add(snapshot)


class BackupScheduleSerializer(serializers.HyperlinkedModelSerializer):
    instance_name = serializers.ReadOnlyField(source='instance.name')
    timezone = serializers.ChoiceField(choices=[(t, t) for t in pytz.all_timezones],
                                       initial=timezone.get_current_timezone_name(),
                                       default=timezone.get_current_timezone_name())

    class Meta(object):
        model = models.BackupSchedule
        view_name = 'openstacktenant-backup-schedule-detail'
        fields = ('url', 'uuid', 'name', 'description', 'retention_time', 'timezone', 'instance', 'instance_name',
                  'maximal_number_of_backups', 'schedule', 'is_active', 'error_message', 'next_trigger_at')
        read_only_fields = ('url', 'uuid', 'is_active', 'backups', 'next_trigger_at', 'instance')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'instance': {'lookup_field': 'uuid', 'view_name': 'openstacktenant-instance-detail'},
        }

    def create(self, validated_data):
        validated_data['instance'] = self.context['instance']
        return super(BackupScheduleSerializer, self).create(validated_data)


class MeterSampleSerializer(serializers.Serializer):
    name = serializers.CharField(source='counter_name')
    value = serializers.FloatField(source='counter_volume')
    type = serializers.CharField(source='counter_type')
    unit = serializers.CharField(source='counter_unit')
    timestamp = fields.StringTimestampField(formats=('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'))
    recorded_at = fields.StringTimestampField(formats=('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'))


class MeterTimestampIntervalSerializer(core_serializers.TimestampIntervalSerializer):
    def get_fields(self):
        fields = super(MeterTimestampIntervalSerializer, self).get_fields()
        fields['start'].default = core_utils.timeshift(hours=-1)
        fields['end'].default = core_utils.timeshift()
        return fields
