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
