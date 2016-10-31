from django.db import transaction
from rest_framework import serializers

from nodeconductor.core import serializers as core_serializers
from nodeconductor.structure import serializers as structure_serializers

from . import models


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

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.Volume
        view_name = 'openstacktenant-volume-detail'
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'source_snapshot', 'size', 'bootable', 'metadata',
            'image', 'image_metadata', 'type', 'runtime_state',
            'device',
        )
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'image_metadata', 'bootable', 'source_snapshot', 'runtime_state', 'device', 'metadata',
        )
        protected_fields = structure_serializers.BaseResourceSerializer.Meta.protected_fields + (
            'size', 'type', 'image',
        )
        extra_kwargs = dict(
            image={'lookup_field': 'uuid', 'view_name': 'openstacktenant-image-detail'},
            source_snapshot={'lookup_field': 'uuid', 'view_name': 'openstacktenant-snapshot-detail'},
            size={'required': False, 'allow_null': True},
            **structure_serializers.BaseResourceSerializer.Meta.extra_kwargs
        )

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
            # TODO: add tenant quota validation (NC-1405)
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

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.Snapshot
        view_name = 'openstacktenant-snapshot-detail'
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'source_volume', 'size', 'metadata', 'runtime_state', 'source_volume_name'
        )
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'size', 'source_volume', 'metadata', 'runtime_state',
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
