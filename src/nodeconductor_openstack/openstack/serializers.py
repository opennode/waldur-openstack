from __future__ import unicode_literals

import logging
import re
import urlparse

from django.conf import settings
from django.core import validators
from django.db import transaction
from django.template.defaultfilters import slugify
from netaddr import IPNetwork
from rest_framework import serializers

from nodeconductor.core import utils as core_utils, serializers as core_serializers
from nodeconductor.core.fields import JsonField
from nodeconductor.quotas import serializers as quotas_serializers
from nodeconductor.structure import serializers as structure_serializers
from nodeconductor.structure.managers import filter_queryset_for_user

from . import models
from .backend import OpenStackBackendError


logger = logging.getLogger(__name__)


class ServiceSerializer(core_serializers.ExtraFieldOptionsMixin,
                        core_serializers.RequiredFieldsMixin,
                        structure_serializers.BaseServiceSerializer):

    SERVICE_ACCOUNT_FIELDS = {
        'backend_url': 'Keystone auth URL (e.g. http://keystone.example.com:5000/v2.0)',
        'username': 'Administrative user',
        'password': '',
    }
    SERVICE_ACCOUNT_EXTRA_FIELDS = {
        'tenant_name': '',
        'is_admin': 'Configure service with admin privileges',
        'availability_zone': 'Default availability zone for provisioned instances',
        'external_network_id': 'ID of OpenStack external network that will be connected to tenants',
        'latitude': 'Latitude of the datacenter (e.g. 40.712784)',
        'longitude': 'Longitude of the datacenter (e.g. -74.005941)',
        'access_url': 'Publicly accessible OpenStack dashboard URL',
        'dns_nameservers': 'Default value for new subnets DNS name servers. Should be defined as list.',
    }

    class Meta(structure_serializers.BaseServiceSerializer.Meta):
        model = models.OpenStackService
        required_fields = 'backend_url', 'username', 'password', 'tenant_name'
        fields = structure_serializers.BaseServiceSerializer.Meta.fields + ('is_admin_tenant',)
        extra_field_options = {
            'backend_url': {
                'label': 'API URL',
                'default_value': 'http://keystone.example.com:5000/v2.0',
            },
            'is_admin': {
                'default_value': 'True',
            },
            'username': {
                'default_value': 'admin',
            },
            'tenant_name': {
                'label': 'Tenant name',
                'default_value': 'admin',
            },
            'external_network_id': {
                'label': 'Public/gateway network UUID',
            },
            'availability_zone': {
                'placeholder': 'default',
            },
            'access_url': {
                'label': 'Access URL',
            },
        }

    def _validate_settings(self, settings):
        if settings.get_option('is_admin'):
            backend = settings.get_backend()
            try:
                if not backend.check_admin_tenant():
                    raise serializers.ValidationError({
                        'non_field_errors': 'Provided credentials are not for admin tenant.'
                    })
            except OpenStackBackendError:
                raise serializers.ValidationError({
                    'non_field_errors': 'Unable to validate credentials.'
                })
        elif settings.get_option('tenant_name') == 'admin':
            raise serializers.ValidationError({
                'tenant_name': 'Invalid tenant name for non-admin service.'
            })


class ServiceNameSerializer(serializers.Serializer):
    name = serializers.CharField(required=True)


class FlavorSerializer(structure_serializers.BasePropertySerializer):

    class Meta(object):
        model = models.Flavor
        fields = ('url', 'uuid', 'name', 'cores', 'ram', 'disk', 'display_name')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
        }

    display_name = serializers.SerializerMethodField()

    def get_display_name(self, flavor):
        return "{} ({} CPU, {} MB RAM, {} MB HDD)".format(
            flavor.name, flavor.cores, flavor.ram, flavor.disk)


class ImageSerializer(structure_serializers.BasePropertySerializer):

    class Meta(object):
        model = models.Image
        fields = ('url', 'uuid', 'name', 'min_disk', 'min_ram')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
        }


class ServiceProjectLinkSerializer(structure_serializers.BaseServiceProjectLinkSerializer):

    class Meta(structure_serializers.BaseServiceProjectLinkSerializer.Meta):
        model = models.OpenStackServiceProjectLink
        extra_kwargs = {
            'service': {'lookup_field': 'uuid', 'view_name': 'openstack-detail'},
        }


class TenantQuotaSerializer(serializers.Serializer):
    instances = serializers.IntegerField(min_value=1, required=False)
    volumes = serializers.IntegerField(min_value=1, required=False)
    snapshots = serializers.IntegerField(min_value=1, required=False)
    ram = serializers.IntegerField(min_value=1, required=False)
    vcpu = serializers.IntegerField(min_value=1, required=False)
    storage = serializers.IntegerField(min_value=1, required=False)
    security_group_count = serializers.IntegerField(min_value=1, required=False)
    security_group_rule_count = serializers.IntegerField(min_value=1, required=False)


class NestedServiceProjectLinkSerializer(structure_serializers.PermissionFieldFilteringMixin,
                                         core_serializers.AugmentedSerializerMixin,
                                         core_serializers.HyperlinkedRelatedModelSerializer):

    class Meta(object):
        model = models.OpenStackServiceProjectLink
        fields = (
            'url',
            'project', 'project_name', 'project_uuid',
            'service', 'service_name', 'service_uuid',
        )
        related_paths = 'project', 'service'
        extra_kwargs = {
            'service': {'lookup_field': 'uuid', 'view_name': 'openstack-detail'},
            'project': {'lookup_field': 'uuid'},
        }

    def run_validators(self, value):
        # No need to validate any fields except 'url' that is validated in to_internal_value method
        pass

    def get_filtered_field_names(self):
        return 'project', 'service'


class ExternalNetworkSerializer(serializers.Serializer):
    vlan_id = serializers.CharField(required=False)
    vxlan_id = serializers.CharField(required=False)
    network_ip = serializers.IPAddressField(protocol='ipv4')
    network_prefix = serializers.IntegerField(min_value=0, max_value=32)
    ips_count = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs):
        vlan_id = attrs.get('vlan_id')
        vxlan_id = attrs.get('vxlan_id')

        if vlan_id is None and vxlan_id is None:
            raise serializers.ValidationError("VLAN or VXLAN ID should be provided.")
        elif vlan_id and vxlan_id:
            raise serializers.ValidationError("VLAN and VXLAN networks cannot be created simultaneously.")

        ips_count = attrs.get('ips_count')
        if ips_count is None:
            return attrs

        network_ip = attrs.get('network_ip')
        network_prefix = attrs.get('network_prefix')

        cidr = IPNetwork(network_ip)
        cidr.prefixlen = network_prefix

        # subtract router and broadcast IPs
        if cidr.size < ips_count - 2:
            raise serializers.ValidationError("Not enough Floating IP Addresses available.")

        return attrs


class IpMappingSerializer(core_serializers.AugmentedSerializerMixin,
                          serializers.HyperlinkedModelSerializer):

    class Meta:
        model = models.IpMapping
        fields = ('url', 'uuid', 'public_ip', 'private_ip', 'project')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'project': {'lookup_field': 'uuid', 'view_name': 'project-detail'}
        }


class FloatingIPSerializer(structure_serializers.BaseResourceSerializer):
    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstack-detail',
        read_only=True,
        lookup_field='uuid')
    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstack-spl-detail',
        read_only=True)

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.FloatingIP
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'runtime_state', 'address', 'backend_network_id',
            'tenant', 'tenant_name', 'tenant_uuid')
        related_paths = ('tenant',)
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'runtime_state', 'address', 'description', 'name', 'tenant', 'backend_network_id')
        extra_kwargs = dict(
            tenant={'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
            **structure_serializers.BaseResourceSerializer.Meta.extra_kwargs
        )

    def create(self, validated_data):
        validated_data['tenant'] = tenant = self.context['view'].get_object()
        validated_data['service_project_link'] = tenant.service_project_link
        instance = super(FloatingIPSerializer, self).create(validated_data)
        instance.increase_backend_quotas_usage()
        return instance


class SecurityGroupRuleSerializer(serializers.ModelSerializer):

    class Meta:
        model = models.SecurityGroupRule
        fields = ('id', 'protocol', 'from_port', 'to_port', 'cidr')


class SecurityGroupRuleCreateSerializer(SecurityGroupRuleSerializer):
    """ Create rules on security group creation """

    def to_internal_value(self, data):
        if 'id' in data:
            raise serializers.ValidationError('Cannot add existed rule with id %s to new security group' % data['id'])
        internal_data = super(SecurityGroupRuleSerializer, self).to_internal_value(data)
        return models.SecurityGroupRule(**internal_data)


class SecurityGroupRuleUpdateSerializer(SecurityGroupRuleSerializer):

    def to_internal_value(self, data):
        """ Create new rule if id is not specified, update exist rule if id is specified """
        security_group = self.context['view'].get_object()
        internal_data = super(SecurityGroupRuleSerializer, self).to_internal_value(data)
        if 'id' not in data:
            return models.SecurityGroupRule(security_group=security_group, **internal_data)
        rule_id = data.pop('id')
        try:
            rule = security_group.rules.get(id=rule_id)
        except models.SecurityGroupRule.DoesNotExist:
            raise serializers.ValidationError({'id': 'Security group does not have rule with id %s.' % rule_id})
        for key, value in internal_data.items():
            setattr(rule, key, value)
        return rule


class SecurityGroupRuleListUpdateSerializer(serializers.ListSerializer):
    child = SecurityGroupRuleUpdateSerializer()

    @transaction.atomic()
    def save(self, **kwargs):
        security_group = self.context['view'].get_object()
        old_rules_count = security_group.rules.count()
        rules = self.validated_data
        security_group.rules.exclude(id__in=[r.id for r in rules if r.id]).delete()
        for rule in rules:
            rule.save()
        security_group.change_backend_quotas_usage_on_rules_update(old_rules_count)
        return rules


class SecurityGroupSerializer(structure_serializers.BaseResourceSerializer):
    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstack-detail',
        read_only=True,
        lookup_field='uuid')
    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstack-spl-detail',
        read_only=True)
    rules = SecurityGroupRuleCreateSerializer(many=True)

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.SecurityGroup
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'tenant', 'tenant_name', 'tenant_uuid', 'rules',
        )
        related_paths = ('tenant',)
        protected_fields = structure_serializers.BaseResourceSerializer.Meta.protected_fields + ('rules',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid', 'view_name': 'openstack-sgp-detail'},
            'tenant': {'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail', 'read_only': True},
        }

    def validate_rules(self, value):
        for rule in value:
            if rule.id is not None:
                raise serializers.ValidationError('Cannot add existed rule with id %s to new security group' % rule.id)
            rule.full_clean(exclude=['security_group'])
        return value

    def create(self, validated_data):
        rules = validated_data.pop('rules', [])
        validated_data['tenant'] = tenant = self.context['view'].get_object()
        validated_data['service_project_link'] = tenant.service_project_link
        with transaction.atomic():
            security_group = super(SecurityGroupSerializer, self).create(validated_data)
            for rule in rules:
                security_group.rules.add(rule)
            security_group.increase_backend_quotas_usage()
        return security_group


class TenantImportSerializer(structure_serializers.BaseResourceImportSerializer):

    class Meta(structure_serializers.BaseResourceImportSerializer.Meta):
        model = models.Tenant

    def create(self, validated_data):
        service_project_link = validated_data['service_project_link']
        if not service_project_link.service.is_admin_tenant():
            raise serializers.ValidationError({
                'non_field_errors': 'Tenant import is only possible for admin service.'
            })

        backend = self.context['service'].get_backend()
        backend_id = validated_data['backend_id']

        try:
            tenant = backend.import_tenant(backend_id, service_project_link)
        except OpenStackBackendError as e:
            raise serializers.ValidationError({
                'backend_id': "Can't import tenant with ID %s. Reason: %s" % (backend_id, e)
            })
        return tenant


class BaseTenantImportSerializer(structure_serializers.BaseResourceImportSerializer):
    class Meta(structure_serializers.BaseResourceImportSerializer.Meta):
        fields = structure_serializers.BaseResourceImportSerializer.Meta.fields + ('tenant',)

    tenant = serializers.HyperlinkedRelatedField(
        queryset=models.Tenant.objects.all(),
        view_name='openstack-tenant-detail',
        lookup_field='uuid',
        write_only=True)

    def get_fields(self):
        fields = super(BaseTenantImportSerializer, self).get_fields()
        if 'request' in self.context:
            request = self.context['request']
            fields['tenant'].queryset = filter_queryset_for_user(
                models.Tenant.objects.all(), request.user
            )
        return fields

    def validate(self, attrs):
        attrs = super(BaseTenantImportSerializer, self).validate(attrs)
        tenant = attrs['tenant']
        project = attrs['project']

        if tenant.service_project_link.project != project:
            raise serializers.ValidationError({
                'project': 'Tenant should belong to the same project.'
            })
        return attrs

    def create(self, validated_data):
        tenant = validated_data['tenant']
        backend_id = validated_data['backend_id']
        backend = tenant.get_backend()

        try:
            return self.import_resource(backend, backend_id)
        except OpenStackBackendError as e:
            raise serializers.ValidationError({
                'backend_id': "Can't import resource with ID %s. Reason: %s" % (backend_id, e)
            })

    def import_resource(self, backend, backend_id):
        raise NotImplementedError()


subnet_cidr_validator = validators.RegexValidator(
    re.compile(settings.NODECONDUCTOR_OPENSTACK['SUBNET']['CIDR_REGEX']),
    settings.NODECONDUCTOR_OPENSTACK['SUBNET']['CIDR_REGEX_EXPLANATION'],
)


class TenantSerializer(structure_serializers.PrivateCloudSerializer):
    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstack-detail',
        read_only=True,
        lookup_field='uuid')
    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstack-spl-detail',
        queryset=models.OpenStackServiceProjectLink.objects.all(),
        write_only=True)
    quotas = quotas_serializers.QuotaSerializer(many=True, read_only=True)
    subnet_cidr = serializers.CharField(
        validators=[subnet_cidr_validator], default='192.168.42.0/24', initial='192.168.42.0/24', write_only=True)

    class Meta(structure_serializers.PrivateCloudSerializer.Meta):
        model = models.Tenant
        fields = structure_serializers.PrivateCloudSerializer.Meta.fields + (
            'availability_zone', 'internal_network_id', 'external_network_id',
            'user_username', 'user_password', 'quotas', 'subnet_cidr',
        )
        read_only_fields = structure_serializers.PrivateCloudSerializer.Meta.read_only_fields + (
            'internal_network_id', 'external_network_id', 'user_password',
        )
        protected_fields = structure_serializers.PrivateCloudSerializer.Meta.protected_fields + (
            'user_username',
        )

    def get_access_url(self, tenant):
        settings = tenant.service_project_link.service.settings
        access_url = settings.get_option('access_url')
        if access_url:
            return access_url

        if settings.backend_url:
            parsed = urlparse.urlparse(settings.backend_url)
            return '%s://%s/dashboard' % (parsed.scheme, parsed.hostname)

    def validate(self, attrs):
        if not attrs.get('user_username'):
            attrs['user_username'] = slugify(attrs['name'])[:30] + '-user'

        service_settings = attrs['service_project_link'].service.settings
        neighbour_tenants = models.Tenant.objects.filter(service_project_link__service__settings=service_settings)
        existing_usernames = [service_settings.username] + list(neighbour_tenants.values_list('user_username', flat=True))
        user_username = attrs['user_username']
        if user_username in existing_usernames:
            raise serializers.ValidationError(
                'Name "%s" is already registered. Please choose another one.' % user_username)

        blacklisted_usernames = service_settings.options.get(
            'blacklisted_usernames', settings.NODECONDUCTOR_OPENSTACK['DEFAULT_BLACKLISTED_USERNAMES'])
        if user_username in blacklisted_usernames:
            raise serializers.ValidationError('Name "%s" cannot be used as tenant user username.' % user_username)
        return attrs

    def create(self, validated_data):
        spl = validated_data['service_project_link']
        if not spl.service.is_admin_tenant():
            raise serializers.ValidationError({
                'non_field_errors': 'Tenant provisioning is only possible for admin service.'
            })
        # get availability zone from service settings if it is not defined
        if not validated_data.get('availability_zone'):
            validated_data['availability_zone'] = spl.service.settings.get_option('availability_zone') or ''
        # init tenant user username(if not defined) and password
        slugified_name = slugify(validated_data['name'])[:30]
        if not validated_data.get('user_username'):
            validated_data['user_username'] = slugified_name + '-user'
        validated_data['user_password'] = core_utils.pwgen()

        subnet_cidr = validated_data.pop('subnet_cidr')
        with transaction.atomic():
            tenant = super(TenantSerializer, self).create(validated_data)
            network = models.Network.objects.create(
                name=slugified_name + '-int-net',
                description='Internal network for tenant %s' % tenant.name,
                tenant=tenant,
                service_project_link=tenant.service_project_link,
            )
            models.SubNet.objects.create(
                name=slugified_name + '-sub-net',
                description='SubNet for tenant %s internal network' % tenant.name,
                network=network,
                service_project_link=tenant.service_project_link,
                cidr=subnet_cidr,
                allocation_pools=_generate_subnet_allocation_pool(subnet_cidr),
                dns_nameservers=spl.service.settings.options.get('dns_nameservers', [])
            )
        return tenant


class _NestedSubNetSerializer(serializers.ModelSerializer):

    class Meta(object):
        model = models.SubNet
        fields = ('name', 'description', 'cidr', 'gateway_ip', 'allocation_pools', 'ip_version', 'enable_dhcp')


class NetworkSerializer(structure_serializers.BaseResourceSerializer):
    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstack-detail',
        read_only=True,
        lookup_field='uuid')
    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstack-spl-detail',
        read_only=True)
    subnets = _NestedSubNetSerializer(many=True, read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.Network
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'tenant', 'tenant_name', 'is_external', 'type', 'segmentation_id', 'subnets')
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'tenant', 'is_external', 'type', 'segmentation_id')
        extra_kwargs = dict(
            tenant={'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
            **structure_serializers.BaseResourceSerializer.Meta.extra_kwargs
        )

    def create(self, validated_data):
        validated_data['tenant'] = tenant = self.context['view'].get_object()
        validated_data['service_project_link'] = tenant.service_project_link
        return super(NetworkSerializer, self).create(validated_data)


class SubNetSerializer(structure_serializers.BaseResourceSerializer):
    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstack-detail',
        read_only=True,
        lookup_field='uuid')
    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstack-spl-detail',
        read_only=True)
    cidr = serializers.CharField(
        validators=[subnet_cidr_validator], default='192.168.42.0/24', initial='192.168.42.0/24')
    allocation_pools = JsonField(read_only=True)
    network_name = serializers.CharField(source='network.name', read_only=True)
    tenant = serializers.HyperlinkedRelatedField(
        source='network.tenant',
        view_name='openstack-tenant-detail',
        read_only=True,
        lookup_field='uuid')
    tenant_name = serializers.CharField(source='network.tenant.name', read_only=True)
    dns_nameservers = JsonField(read_only=True)

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.SubNet
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'tenant', 'tenant_name', 'network', 'network_name', 'cidr',
            'gateway_ip', 'allocation_pools', 'ip_version', 'enable_dhcp', 'dns_nameservers')
        protected_fields = structure_serializers.BaseResourceSerializer.Meta.protected_fields + ('cidr',)
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'tenant', 'network', 'gateway_ip', 'ip_version', 'enable_dhcp')
        extra_kwargs = dict(
            network={'lookup_field': 'uuid', 'view_name': 'openstack-network-detail'},
            **structure_serializers.BaseResourceSerializer.Meta.extra_kwargs
        )

    def validate(self, attrs):
        if self.instance is None:
            attrs['network'] = network = self.context['view'].get_object()
            if network.subnets.count() >= 1:
                raise serializers.ValidationError('Internal network cannot have more than one subnet.')
        return attrs

    def create(self, validated_data):
        network = validated_data['network']
        validated_data['service_project_link'] = network.service_project_link
        spl = network.service_project_link
        validated_data['allocation_pools'] = _generate_subnet_allocation_pool(validated_data['cidr'])
        validated_data['dns_nameservers'] = spl.service.settings.options.get('dns_nameservers', [])
        return super(SubNetSerializer, self).create(validated_data)


def _generate_subnet_allocation_pool(cidr):
    first_octet, second_octet, third_octet, _ = cidr.split('.', 3)
    subnet_settings = settings.NODECONDUCTOR_OPENSTACK['SUBNET']
    format_data = {'first_octet': first_octet, 'second_octet': second_octet, 'third_octet': third_octet}
    return [{
        'start': subnet_settings['ALLOCATION_POOL_START'].format(**format_data),
        'end': subnet_settings['ALLOCATION_POOL_END'].format(**format_data),
    }]
