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
            'service': {'lookup_field': 'uuid', 'view_name': 'openstack-detail'},
        }
