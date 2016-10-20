import logging
import pytz
import re
import urlparse

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.template.defaultfilters import slugify
from django.utils import timezone
from netaddr import IPNetwork
from rest_framework import serializers, reverse
from taggit.models import Tag

from nodeconductor.core import (utils as core_utils, models as core_models, serializers as core_serializers,
                                NodeConductorExtension)
from nodeconductor.core.fields import JsonField, MappedChoiceField
from nodeconductor.quotas import serializers as quotas_serializers
from nodeconductor.structure import serializers as structure_serializers
from nodeconductor.structure.managers import filter_queryset_for_user

from . import models, fields
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
    }

    class Meta(structure_serializers.BaseServiceSerializer.Meta):
        model = models.OpenStackService
        view_name = 'openstack-detail'
        required_fields = 'backend_url', 'username', 'password', 'tenant_name'
        fields = structure_serializers.BaseServiceSerializer.Meta.fields + ('is_admin_tenant',)
        extra_field_options = {
            'backend_url': {
                'label': 'API URL',
                'default_value': 'http://keystone.example.com:5000/v2.0',
            },
            'is_admin': {
                'default_value': True,
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
            }
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
        view_name = 'openstack-flavor-detail'
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
        view_name = 'openstack-image-detail'
        fields = ('url', 'uuid', 'name', 'min_disk', 'min_ram')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
        }


class ServiceProjectLinkSerializer(structure_serializers.BaseServiceProjectLinkSerializer):

    class Meta(structure_serializers.BaseServiceProjectLinkSerializer.Meta):
        model = models.OpenStackServiceProjectLink
        view_name = 'openstack-spl-detail'
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
    backup_storage = serializers.IntegerField(min_value=1, required=False)
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
        view_name = 'openstack-spl-detail'
        extra_kwargs = {
            'service': {'lookup_field': 'uuid', 'view_name': 'openstack-detail'},
            'project': {'lookup_field': 'uuid'},
        }

    def run_validators(self, value):
        # No need to validate any fields except 'url' that is validated in to_internal_value method
        pass

    def get_filtered_field_names(self):
        return 'project', 'service'


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


class ExternalNetworkSerializer(serializers.Serializer):
    vlan_id = serializers.CharField(required=False)
    vxlan_id = serializers.CharField(required=False)
    network_ip = core_serializers.IPAddressField()
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


class AssignFloatingIpSerializer(serializers.Serializer):
    floating_ip = serializers.HyperlinkedRelatedField(
        label='Floating IP',
        required=True,
        view_name='openstack-fip-detail',
        lookup_field='uuid',
        queryset=models.FloatingIP.objects.all()
    )

    def get_fields(self):
        fields = super(AssignFloatingIpSerializer, self).get_fields()
        if self.instance:
            query_params = {
                'status': 'DOWN',
                'tenant_uuid': self.instance.tenant.uuid.hex,
            }

            field = fields['floating_ip']
            field.query_params = query_params
            field.value_field = 'url'
            field.display_name_field = 'address'
        return fields

    def get_floating_ip_uuid(self):
        return self.validated_data.get('floating_ip').uuid.hex

    def validate_floating_ip(self, value):
        if value is not None:
            if value.status != 'DOWN':
                raise serializers.ValidationError("Floating IP status must be DOWN.")
            elif value.tenant != self.instance.tenant:
                raise serializers.ValidationError("Floating IP must belong to same tenant as instance.")
        return value

    def validate(self, attrs):
        tenant = self.instance.tenant

        if not tenant.external_network_id:
            raise serializers.ValidationError("Tenant should have external network ID.")

        if tenant.state != core_models.StateMixin.States.OK:
            raise serializers.ValidationError("Tenant should be in stable state.")

        return attrs


class IpMappingSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = models.IpMapping
        fields = ('url', 'uuid', 'public_ip', 'private_ip', 'project')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'project': {'lookup_field': 'uuid', 'view_name': 'project-detail'}
        }
        view_name = 'openstack-ip-mapping-detail'


class FloatingIPSerializer(serializers.HyperlinkedModelSerializer):
    service_project_link = NestedServiceProjectLinkSerializer(read_only=True)

    class Meta:
        model = models.FloatingIP
        fields = ('url', 'uuid', 'status', 'address', 'tenant',
                  'service_project_link', 'backend_id', 'backend_network_id')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'tenant': {'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
        }
        view_name = 'openstack-fip-detail'


class SecurityGroupSerializer(core_serializers.AugmentedSerializerMixin,
                              structure_serializers.BasePropertySerializer):

    state = MappedChoiceField(
        choices=[(v, k) for k, v in core_models.StateMixin.States.CHOICES],
        choice_mappings={v: k for k, v in core_models.StateMixin.States.CHOICES},
        read_only=True,
    )
    rules = NestedSecurityGroupRuleSerializer(many=True)
    service_project_link = NestedServiceProjectLinkSerializer(read_only=True)

    class Meta(object):
        model = models.SecurityGroup
        fields = ('url', 'uuid', 'state', 'name', 'description', 'rules',
                  'service_project_link', 'tenant')
        read_only_fields = ('url', 'uuid',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'service_project_link': {'view_name': 'openstack-spl-detail'},
            'tenant': {'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
        }
        view_name = 'openstack-sgp-detail'
        protected_fields = ('tenant',)

    def validate(self, attrs):
        if self.instance is None:
            # Check security groups quotas on creation
            tenant = attrs.get('tenant')

            security_group_count_quota = tenant.quotas.get(name='security_group_count')
            if security_group_count_quota.is_exceeded(delta=1):
                raise serializers.ValidationError('Can not create new security group - amount quota exceeded')
            security_group_rule_count_quota = tenant.quotas.get(name='security_group_rule_count')
            if security_group_rule_count_quota.is_exceeded(delta=len(attrs.get('rules', []))):
                raise serializers.ValidationError('Can not create new security group - rules amount quota exceeded')
        else:
            # Check security_groups quotas on update
            tenant = self.instance.tenant
            new_rules_count = len(attrs.get('rules', [])) - self.instance.rules.count()
            if new_rules_count > 0:
                security_group_rule_count_quota = tenant.quotas.get(name='security_group_rule_count')
                if security_group_rule_count_quota.is_exceeded(delta=new_rules_count):
                    raise serializers.ValidationError(
                        'Can not update new security group rules - rules amount quota exceeded')
        return attrs

    def validate_rules(self, value):
        for rule in value:
            rule.full_clean(exclude=['security_group'])
            if rule.id is not None and self.instance is None:
                raise serializers.ValidationError('Cannot add existed rule with id %s to new security group' % rule.id)
            elif rule.id is not None and self.instance is not None and rule.security_group != self.instance:
                raise serializers.ValidationError('Cannot add rule with id {} to group {} - it already belongs to '
                                                  'other group' % (rule.id, self.isntance.name))
        return value

    def create(self, validated_data):
        rules = validated_data.pop('rules', [])
        tenant = validated_data['tenant']
        validated_data['service_project_link'] = tenant.service_project_link
        with transaction.atomic():
            security_group = super(SecurityGroupSerializer, self).create(validated_data)
            for rule in rules:
                security_group.rules.add(rule)

        return security_group

    def update(self, instance, validated_data):
        rules = validated_data.pop('rules', [])
        new_rules = [rule for rule in rules if rule.id is None]
        existed_rules = set([rule for rule in rules if rule.id is not None])

        security_group = super(SecurityGroupSerializer, self).update(instance, validated_data)
        old_rules = set(security_group.rules.all())

        with transaction.atomic():
            removed_rules = old_rules - existed_rules
            for rule in removed_rules:
                rule.delete()

            for rule in new_rules:
                security_group.rules.add(rule)

        return security_group


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
        view_name = 'openstack-sgp-detail'
        lookup_field = 'uuid'


class BackupScheduleSerializer(serializers.HyperlinkedModelSerializer):
    instance_name = serializers.ReadOnlyField(source='instance.name')
    timezone = serializers.ChoiceField(choices=[(t, t) for t in pytz.all_timezones],
                                       default=timezone.get_current_timezone_name)

    class Meta(object):
        model = models.BackupSchedule
        view_name = 'openstack-schedule-detail'
        fields = ('url', 'uuid', 'description', 'backups', 'retention_time', 'timezone',
                  'instance', 'maximal_number_of_backups', 'schedule', 'is_active', 'instance_name',
                  'backup_type', 'next_trigger_at', 'dr_backups')
        read_only_fields = ('is_active', 'backups', 'next_trigger_at', 'dr_backups')
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'instance': {'lookup_field': 'uuid', 'view_name': 'openstack-instance-detail'},
            'backups': {'lookup_field': 'uuid', 'view_name': 'openstack-backup-detail'},
            'dr_backups': {'lookup_field': 'uuid', 'view_name': 'openstack-dr-backup-detail'},
        }


class BasicRestorationSerializer(serializers.HyperlinkedModelSerializer):
    """ Basic model for DR backup and regular backup restorations. """
    instance_name = serializers.ReadOnlyField(source='instance.name')
    instance_uuid = serializers.ReadOnlyField(source='instance.uuid')
    instance_state = serializers.ReadOnlyField(source='instance.human_readable_state')

    class Meta(object):
        model = NotImplemented
        view_name = NotImplemented
        fields = ('url', 'uuid', 'instance', 'instance_uuid', 'instance_name', 'instance_state', 'created')
        read_only_fields = ('instance', 'created')
        extra_kwargs = dict(
            url={'lookup_field': 'uuid'},
            instance={'lookup_field': 'uuid', 'view_name': 'openstack-instance-detail'},
        )

    def create_instance_crm(self, instance, backup):
        # XXX: This should be moved to itacloud assembly and refactored.
        nc_settings = getattr(settings, 'NODECONDUCTOR', {})
        metadata = backup.metadata
        if ('crm' in metadata and nc_settings.get('IS_ITACLOUD', False) and
                NodeConductorExtension.is_installed('nodeconductor_sugarcrm')):
            from nodeconductor_sugarcrm.models import SugarCRMServiceProjectLink, CRM
            try:
                crm_data = metadata['crm']
                spl = SugarCRMServiceProjectLink.objects.get(pk=crm_data['service_project_link'])
                instance_url = reverse.reverse(
                    'openstack-instance-detail', kwargs={'uuid': instance.uuid.hex}, request=self.context['request'])
                crm = CRM.objects.create(
                    name=crm_data['name'],
                    service_project_link=spl,
                    description=crm_data['description'],
                    admin_username=crm_data['admin_username'],
                    admin_password=crm_data['admin_password'],
                    state=CRM.States.PROVISIONING,
                    instance_url=instance_url,
                )
                crm.tags.add(*crm_data['tags'])
            except SugarCRMServiceProjectLink.DoesNotExist:
                logger.error('Cannot restore instance %s (PK: %s) CRM. Its SPL does not exist anymore.' %
                             (instance.name, instance.pk))
            except Exception as e:
                logger.error('Cannot restore instance %s (PK: %s) CRM. Error: %s' % (instance.name, instance.pk, e))


class BasicBackupRestorationSerializer(BasicRestorationSerializer):
    class Meta(BasicRestorationSerializer.Meta):
        model = models.BackupRestoration
        view_name = 'openstack-backup-restoration-detail'


class BackupSerializer(core_serializers.AugmentedSerializerMixin, serializers.HyperlinkedModelSerializer):
    state = serializers.ReadOnlyField(source='get_state_display')
    metadata = JsonField(read_only=True)
    instance_name = serializers.ReadOnlyField(source='instance.name')
    restorations = BasicBackupRestorationSerializer(many=True, read_only=True)

    class Meta(object):
        model = models.Backup
        view_name = 'openstack-backup-detail'
        fields = ('url', 'uuid', 'description', 'created_at', 'kept_until', 'instance', 'state', 'backup_schedule',
                  'metadata', 'instance_name', 'tenant', 'restorations')
        read_only_fields = ('created_at', 'kept_until', 'backup_schedule', 'tenant',)
        protected_fields = ('instance',)
        extra_kwargs = {
            'url': {'lookup_field': 'uuid'},
            'instance': {'lookup_field': 'uuid', 'view_name': 'openstack-instance-detail'},
            'tenant': {'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
            'backup_schedule': {'lookup_field': 'uuid', 'view_name': 'openstack-schedule-detail'},
        }

    def validate_instance(self, instance):
        if instance.state not in (models.Instance.States.OFFLINE, models.Instance.States.ONLINE):
            raise serializers.ValidationError('Cannot create backup if instance is not in stable state.')
        return instance

    @transaction.atomic
    def create(self, validated_data):
        instance = validated_data['instance']
        tenant = instance.tenant
        validated_data['tenant'] = tenant
        validated_data['metadata'] = instance.as_dict()
        backup = super(BackupSerializer, self).create(validated_data)
        create_backup_snapshots(backup)
        return backup


def create_backup_snapshots(backup):
    for volume in backup.instance.volumes.all():
        snapshot = models.Snapshot.objects.create(
            name='Snapshot for volume %s' % volume.name,
            service_project_link=backup.tenant.service_project_link,
            tenant=backup.tenant,
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


class BackupRestorationSerializer(BasicBackupRestorationSerializer):
    name = serializers.CharField(
        required=False, help_text='New instance name. Leave blank to use source instance name.')

    class Meta(BasicBackupRestorationSerializer.Meta):
        fields = BasicBackupRestorationSerializer.Meta.fields + ('backup', 'flavor', 'name')
        protected_fields = ('tenant', 'dr_backup', 'flavor', 'name')
        extra_kwargs = dict(
            backup={'lookup_field': 'uuid', 'view_name': 'openstack-backup-detail'},
            tenant={'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
            flavor={'lookup_field': 'uuid', 'view_name': 'openstack-flavor-detail'},
            **BasicBackupRestorationSerializer.Meta.extra_kwargs
        )

    def validate(self, attrs):
        flavor = attrs['flavor']
        backup = attrs['backup']
        if flavor.settings != backup.instance.service_project_link.service.settings:
            raise serializers.ValidationError({'flavor': "Flavor is not within services' settings."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        flavor = validated_data['flavor']
        backup = validated_data['backup']
        source_instance = backup.instance
        # instance that will be restored
        metadata = backup.metadata or {}
        instance = models.Instance.objects.create(
            name=validated_data.pop('name', None) or metadata.get('name', source_instance.name),
            description=metadata.get('description', ''),
            service_project_link=source_instance.service_project_link,
            tenant=source_instance.tenant,
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
        instance.tags.add(*backup.metadata['tags'])
        instance.increase_backend_quotas_usage()
        validated_data['instance'] = instance
        backup_restoration = super(BackupRestorationSerializer, self).create(validated_data)
        # restoration for each instance volume from snapshot.
        for snapshot in backup.snapshots.all():
            volume = models.Volume(
                source_snapshot=snapshot,
                tenant=snapshot.tenant,
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
        # XXX: This should be moved to itacloud assembly
        self.create_instance_crm(instance, backup)
        return backup_restoration


class NestedVolumeSerializer(serializers.HyperlinkedModelSerializer,
                             structure_serializers.BasicResourceSerializer):
    state = serializers.ReadOnlyField(source='get_state_display')

    class Meta:
        model = models.Volume
        fields = 'url', 'uuid', 'name', 'state', 'bootable', 'size', 'resource_type'
        view_name = 'openstack-volume-detail'
        lookup_field = 'uuid'


class InstanceSerializer(structure_serializers.VirtualMachineSerializer):

    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstack-detail',
        read_only=True,
        lookup_field='uuid')

    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstack-spl-detail',
        queryset=models.OpenStackServiceProjectLink.objects.all())

    tenant = serializers.HyperlinkedRelatedField(
        view_name='openstack-tenant-detail',
        queryset=models.Tenant.objects.all(),
        lookup_field='uuid')

    tenant_name = serializers.ReadOnlyField(source='tenant.name')

    flavor = serializers.HyperlinkedRelatedField(
        view_name='openstack-flavor-detail',
        lookup_field='uuid',
        queryset=models.Flavor.objects.all().select_related('settings'),
        write_only=True)

    image = serializers.HyperlinkedRelatedField(
        view_name='openstack-image-detail',
        lookup_field='uuid',
        queryset=models.Image.objects.all().select_related('settings'),
        write_only=True)

    security_groups = NestedSecurityGroupSerializer(
        queryset=models.SecurityGroup.objects.all(), many=True, required=False)

    backups = BackupSerializer(many=True, read_only=True)
    backup_schedules = BackupScheduleSerializer(many=True, read_only=True)

    skip_external_ip_assignment = serializers.BooleanField(write_only=True, default=False)
    system_volume_size = serializers.IntegerField(min_value=1024)
    data_volume_size = serializers.IntegerField(initial=20 * 1024, default=20 * 1024, min_value=1024)

    floating_ip = serializers.HyperlinkedRelatedField(
        label='Floating IP',
        required=False,
        allow_null=True,
        view_name='openstack-fip-detail',
        lookup_field='uuid',
        queryset=models.FloatingIP.objects.all(),
        write_only=True
    )
    volumes = NestedVolumeSerializer(many=True, required=False, read_only=True)

    class Meta(structure_serializers.VirtualMachineSerializer.Meta):
        model = models.Instance
        view_name = 'openstack-instance-detail'
        fields = structure_serializers.VirtualMachineSerializer.Meta.fields + (
            'flavor', 'image', 'system_volume_size', 'data_volume_size', 'skip_external_ip_assignment',
            'security_groups', 'internal_ips', 'backups', 'backup_schedules', 'flavor_disk',
            'tenant', 'tenant_name', 'floating_ip', 'volumes', 'runtime_state'
        )
        protected_fields = structure_serializers.VirtualMachineSerializer.Meta.protected_fields + (
            'flavor', 'image', 'system_volume_size', 'data_volume_size', 'skip_external_ip_assignment',
            'tenant', 'floating_ip'
        )
        read_only_fields = structure_serializers.VirtualMachineSerializer.Meta.read_only_fields + (
            'flavor_disk', 'runtime_state'
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
        queryset = queryset.select_related('tenant')
        return queryset.prefetch_related(
            'security_groups',
            'security_groups__rules',
            'backups',
            'backup_schedules',
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
        tenant = attrs['tenant']

        if any([flavor.settings != settings, image.settings != settings]):
            raise serializers.ValidationError(
                "Flavor and image must belong to the same service settings as service project link.")

        if tenant.service_project_link != service_project_link:
            raise serializers.ValidationError("Tenant must belong to the same service project link as instance.")

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
            if security_group.service_project_link != attrs['service_project_link']:
                raise serializers.ValidationError(
                    "Security group {} has wrong service or project. New instance and its "
                    "security groups have to belong to same project and service".format(security_group.name))

        if not tenant.internal_network_id:
            raise serializers.ValidationError({
                'tenant': 'Tenant does not have an internal network.'
            })

        self._validate_external_ip(attrs)

        return attrs

    def _validate_external_ip(self, attrs):
        tenant = attrs['tenant']
        floating_ip = attrs.get('floating_ip')
        skip_external_ip_assignment = attrs['skip_external_ip_assignment']

        # Case 1. If floating_ip!=None then requested floating IP is assigned to the instance.
        if floating_ip:
            self._validate_tenant(tenant)

            if floating_ip.status != 'DOWN':
                raise serializers.ValidationError({
                    'floating_ip': 'Floating IP status must be DOWN.'
                })

            if floating_ip.tenant != tenant:
                raise serializers.ValidationError({
                    'floating_ip': 'Floating IP must belong to the same tenant.'
                })

        # Case 2. If floating_ip=None and skip_external_ip_assignment=False
        # then new floating IP is allocated and assigned to the instance.
        elif not skip_external_ip_assignment:
            self._validate_tenant(tenant)

            floating_ip_count_quota = tenant.quotas.get(name='floating_ip_count')
            if floating_ip_count_quota.is_exceeded(delta=1):
                raise serializers.ValidationError({
                    'tenant': 'Can not allocate floating IP - quota has been filled.'
                })

        # Case 3. If floating_ip=None and skip_external_ip_assignment=True
        # floating IP allocation is not attempted, only internal IP is created.
        else:
            logger.debug('Floating IP allocation is not attempted.')

    def _validate_tenant(self, tenant):
        if not tenant.external_network_id:
            raise serializers.ValidationError({
                'tenant': 'Can not assign external IP if tenant has no external network.'
            })

        if tenant.state != core_models.StateMixin.States.OK:
            raise serializers.ValidationError({
                'tenant': 'Can not assign external IP if tenant is not in stable state.'
            })

    @transaction.atomic
    def create(self, validated_data):
        """ Store flavor, ssh_key and image details into instance model.
            Create volumes and security groups for instance.
        """
        security_groups = validated_data.pop('security_groups', [])
        tenant = validated_data['tenant']
        spl = tenant.service_project_link
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
            tenant=tenant,
            service_project_link=spl,
            size=system_volume_size,
            image=image,
            bootable=True,
        )
        system_volume.increase_backend_quotas_usage()
        data_volume = models.Volume.objects.create(
            name='{0}-data'.format(instance.name[:145]),  # volume name cannot be longer than 150 symbols
            tenant=tenant,
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
        security_groups = validated_data.pop('security_groups', None)
        with transaction.atomic():
            instance = super(InstanceSerializer, self).update(instance, validated_data)
            if security_groups is not None:
                instance.security_groups.clear()
                instance.security_groups.add(*security_groups)

        return instance


class TenantImportSerializer(structure_serializers.BaseResourceImportSerializer):

    class Meta(structure_serializers.BaseResourceImportSerializer.Meta):
        model = models.Tenant
        view_name = 'openstack-tenant-detail'

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


class InstanceImportSerializer(BaseTenantImportSerializer):

    class Meta(BaseTenantImportSerializer.Meta):
        model = models.Instance
        view_name = 'openstack-instance-detail'

    def import_resource(self, backend, backend_id):
        return backend.import_instance(backend_id)


class VolumeImportSerializer(BaseTenantImportSerializer):

    class Meta(BaseTenantImportSerializer.Meta):
        model = models.Volume
        view_name = 'openstack-volume-detail'

    def import_resource(self, backend, backend_id):
        return backend.import_volume(backend_id)


class VolumeExtendSerializer(serializers.Serializer):
    disk_size = serializers.IntegerField(min_value=1, label='Disk size')

    def get_fields(self):
        fields = super(VolumeExtendSerializer, self).get_fields()
        if self.instance:
            fields['disk_size'].min_value = self.instance.size + 1024
        return fields

    def validate(self, attrs):
        volume = self.instance
        if not volume.backend_id:
            raise serializers.ValidationError({
                'non_field_errors': ['Unable to extend volume without backend_id']
            })
        if volume.instance and volume.instance.state != models.Instance.States.OFFLINE:
            raise serializers.ValidationError({
                'non_field_errors': ['Volume instance should be in OFFLINE state']
            })
        if volume.bootable:
            raise serializers.ValidationError({
                'non_field_errors': ["Can't detach root device volume."]
            })
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        new_size = validated_data.get('disk_size')
        instance.tenant.add_quota_usage('storage', new_size - instance.size, validate=True)
        instance.size = new_size
        instance.save(update_fields=['size'])
        return instance


class VolumeAttachSerializer(structure_serializers.PermissionFieldFilteringMixin, serializers.ModelSerializer):
    class Meta(object):
        model = models.Volume
        fields = ('instance', 'device')
        extra_kwargs = dict(
            instance={'required': True, 'allow_null': False}
        )

    def get_fields(self):
        fields = super(VolumeAttachSerializer, self).get_fields()
        volume = self.instance
        if volume:
            fields['instance'].view_name = 'openstack-instance-detail'
            fields['instance'].display_name_field = 'name'
            fields['instance'].query_params = {'tenant_uuid': volume.tenant.uuid}
        return fields

    def get_filtered_field_names(self):
        return ('instance',)

    def validate_instance(self, instance):
        if instance.state != models.Instance.States.OFFLINE:
            raise serializers.ValidationError('Volume can be attached only to instance that is offline.')
        volume = self.instance
        if instance.tenant != volume.tenant:
            raise serializers.ValidationError('Volume and instance should belong to the same tenant.')
        return instance


class InstanceFlavorChangeSerializer(structure_serializers.PermissionFieldFilteringMixin,
                                     serializers.Serializer):
    flavor = serializers.HyperlinkedRelatedField(
        view_name='openstack-flavor-detail',
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

        instance.tenant.add_quota_usage('ram', flavor.ram - instance.ram, validate=True)
        instance.tenant.add_quota_usage('vcpu', flavor.cores - instance.cores, validate=True)

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

    class Meta(structure_serializers.PrivateCloudSerializer.Meta):
        model = models.Tenant
        view_name = 'openstack-tenant-detail'
        fields = structure_serializers.PrivateCloudSerializer.Meta.fields + (
            'availability_zone', 'internal_network_id', 'external_network_id',
            'user_username', 'user_password', 'quotas', 'runtime_state',
        )
        read_only_fields = structure_serializers.PrivateCloudSerializer.Meta.read_only_fields + (
            'internal_network_id', 'external_network_id', 'user_password', 'runtime_state'
        )
        protected_fields = structure_serializers.PrivateCloudSerializer.Meta.protected_fields + (
            'user_username',
        )

    def get_access_url(self, tenant):
        backend_url = tenant.service_project_link.service.settings.backend_url
        if backend_url:
            parsed = urlparse.urlparse(backend_url)
            return '%s://%s/dashboard' % (parsed.scheme, parsed.hostname)

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
        if not validated_data.get('user_username'):
            name = validated_data['name']
            validated_data['user_username'] = slugify(name)[:30] + '-user'
        validated_data['user_password'] = core_utils.pwgen()
        return super(TenantSerializer, self).create(validated_data)


class LicenseSerializer(serializers.ModelSerializer):

    instance = serializers.SerializerMethodField()
    group = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

    class Meta:
        model = Tag
        fields = ('instance', 'group', 'type', 'name')

    def get_instance(self, obj):
        instance_ct = ContentType.objects.get_for_model(models.Instance)
        instance = obj.taggit_taggeditem_items.filter(tag=obj, content_type=instance_ct).first().content_object
        url_name = instance.get_url_name() + '-detail'
        return reverse.reverse(
            url_name, request=self.context['request'], kwargs={'uuid': instance.uuid.hex})

    def get_group(self, obj):
        try:
            return obj.name.split(':')[0]
        except IndexError:
            return ''

    def get_type(self, obj):
        try:
            return obj.name.split(':')[1]
        except IndexError:
            return ''

    def get_name(self, obj):
        try:
            return obj.name.split(':')[2]
        except IndexError:
            return ''


class VolumeSerializer(structure_serializers.BaseResourceSerializer):

    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstack-detail',
        read_only=True,
        lookup_field='uuid')
    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstack-spl-detail',
        read_only=True)
    instance_name = serializers.ReadOnlyField(source='instance.name')

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.Volume
        view_name = 'openstack-volume-detail'
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'tenant', 'source_snapshot', 'size', 'bootable', 'metadata',
            'image', 'image_metadata', 'type', 'runtime_state', 'instance', 'instance_name',
            'device',
        )
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'image_metadata', 'bootable', 'source_snapshot', 'runtime_state', 'instance', 'device',
        )
        protected_fields = structure_serializers.BaseResourceSerializer.Meta.protected_fields + (
            'tenant', 'size', 'type', 'image'
        )
        extra_kwargs = dict(
            tenant={'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
            instance={'lookup_field': 'uuid', 'view_name': 'openstack-instance-detail'},
            image={'lookup_field': 'uuid', 'view_name': 'openstack-image-detail'},
            source_snapshot={'lookup_field': 'uuid', 'view_name': 'openstack-snapshot-detail'},
            size={'required': False, 'allow_null': True},
            **structure_serializers.BaseResourceSerializer.Meta.extra_kwargs
        )

    def validate(self, attrs):
        if self.instance is None:
            # image validation
            image = attrs.get('image')
            tenant = attrs['tenant']
            if image and image.settings != tenant.service_project_link.service.settings:
                raise serializers.ValidationError('Image and tenant must belong to the same service settings')
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
                raise serializers.ValidationError(
                    'Volume size should be equal or greater than %s for selected image' % image.min_disk)
            # TODO: add tenant quota validation (NC-1405)
        return attrs

    def create(self, validated_data):
        tenant = validated_data['tenant']
        validated_data['service_project_link'] = tenant.service_project_link
        if not validated_data.get('size'):
            validated_data['size'] = validated_data['snapshot'].size
        return super(VolumeSerializer, self).create(validated_data)


class SnapshotSerializer(structure_serializers.BaseResourceSerializer):

    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstack-detail',
        read_only=True,
        lookup_field='uuid')

    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstack-spl-detail',
        read_only=True)

    source_volume_name = serializers.ReadOnlyField(source='source_volume.name')

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.Snapshot
        view_name = 'openstack-snapshot-detail'
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'source_volume', 'size', 'metadata', 'tenant', 'source_volume_name'
        )
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'size', 'tenant', 'source_volume',
        )
        extra_kwargs = dict(
            source_volume={'lookup_field': 'uuid', 'view_name': 'openstack-volume-detail'},
            tenant={'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
            **structure_serializers.BaseResourceSerializer.Meta.extra_kwargs
        )

    def create(self, validated_data):
        # source volume should be added to context on creation
        source_volume = self.context['source_volume']
        validated_data['source_volume'] = source_volume
        validated_data['service_project_link'] = source_volume.service_project_link
        validated_data['tenant'] = source_volume.tenant
        validated_data['size'] = source_volume.size
        return super(SnapshotSerializer, self).create(validated_data)


class BasicDRBackupRestorationSerializer(BasicRestorationSerializer):
    class Meta(BasicRestorationSerializer.Meta):
        model = models.DRBackupRestoration
        view_name = 'openstack-dr-backup-restoration-detail'


class DRBackupSerializer(structure_serializers.BaseResourceSerializer):
    service = serializers.HyperlinkedRelatedField(
        source='service_project_link.service',
        view_name='openstack-detail',
        read_only=True,
        lookup_field='uuid')
    service_project_link = serializers.HyperlinkedRelatedField(
        view_name='openstack-spl-detail',
        read_only=True)
    restorations = BasicDRBackupRestorationSerializer(read_only=True, many=True)
    metadata = JsonField(read_only=True)

    class Meta(structure_serializers.BaseResourceSerializer.Meta):
        model = models.DRBackup
        view_name = 'openstack-dr-backup-detail'
        fields = structure_serializers.BaseResourceSerializer.Meta.fields + (
            'source_instance', 'tenant', 'restorations', 'kept_until', 'runtime_state', 'backup_schedule', 'metadata',
        )
        read_only_fields = structure_serializers.BaseResourceSerializer.Meta.read_only_fields + (
            'tenant', 'kept_until', 'runtime_state', 'backup_schedule',
        )
        protected_fields = structure_serializers.BaseResourceSerializer.Meta.protected_fields + (
            'source_instance',
        )
        extra_kwargs = dict(
            tenant={'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
            source_instance={'lookup_field': 'uuid', 'view_name': 'openstack-instance-detail',
                             'allow_null': False, 'required': True},
            backup_schedule={'lookup_field': 'uuid', 'view_name': 'openstack-schedule-detail'},
            **structure_serializers.BaseResourceSerializer.Meta.extra_kwargs
        )

    @staticmethod
    def eager_load(queryset):
        queryset = structure_serializers.BaseResourceSerializer.eager_load(queryset)
        queryset = queryset.select_related('tenant', 'backup_schedule')
        return queryset.prefetch_related('restorations', 'restorations__instance')

    @transaction.atomic
    def create(self, validated_data):
        source_instance = validated_data['source_instance']
        validated_data['tenant'] = source_instance.tenant
        validated_data['service_project_link'] = source_instance.service_project_link
        validated_data['metadata'] = source_instance.as_dict()
        dr_backup = super(DRBackupSerializer, self).create(validated_data)
        create_dr_backup_related_resources(dr_backup)
        return dr_backup


def create_dr_backup_related_resources(dr_backup):
    """ Create resources that has to be created on backend for DR backup.

    This function is extracted from serializer to create dr backups with scheduler.
    """
    instance = dr_backup.source_instance

    for volume in instance.volumes.all():
        # Create temporary snapshot volume for instance volume.
        snapshot = models.Snapshot.objects.create(
            source_volume=volume,
            tenant=volume.tenant,
            service_project_link=volume.service_project_link,
            size=volume.size,
            name='Temporary snapshot for volume: %s' % volume.name,
            description='Part of DR backup %s' % dr_backup.name,
            metadata={'source_volume_name': volume.name, 'source_volume_description': volume.description},
        )
        snapshot.increase_backend_quotas_usage()
        dr_backup.temporary_snapshots.add(snapshot)

        # Create temporary volume from snapshot.
        tmp_volume = models.Volume.objects.create(
            service_project_link=snapshot.service_project_link,
            tenant=snapshot.tenant,
            source_snapshot=snapshot,
            metadata=snapshot.metadata,
            name='Temporary copy for volume: %s' % volume.name,
            description='Part of DR backup %s' % dr_backup.name,
            size=snapshot.size,
        )
        tmp_volume.increase_backend_quotas_usage()
        dr_backup.temporary_volumes.add(tmp_volume)

        # Create backup for temporary volume.
        volume_backup = models.VolumeBackup.objects.create(
            name=volume.name,
            description=volume.description,
            source_volume=tmp_volume,
            tenant=dr_backup.tenant,
            size=volume.size,
            service_project_link=dr_backup.service_project_link,
            metadata={
                'source_volume_name': volume.name,
                'source_volume_description': volume.description,
                'source_volume_bootable': volume.bootable,
                'source_volume_size': volume.size,
                'source_volume_metadata': volume.metadata,
                'source_volume_image_metadata': volume.image_metadata,
                'source_volume_type': volume.type,
            }
        )
        volume_backup.increase_backend_quotas_usage()
        dr_backup.volume_backups.add(volume_backup)


class DRBackupRestorationSerializer(core_serializers.AugmentedSerializerMixin, BasicDRBackupRestorationSerializer):
    name = serializers.CharField(
        required=False, allow_null=True, write_only=True,
        help_text='New instance name. Leave blank to use source instance name.')

    class Meta(BasicDRBackupRestorationSerializer.Meta):
        fields = BasicDRBackupRestorationSerializer.Meta.fields + ('tenant', 'backup', 'flavor', 'name')
        protected_fields = ('tenant', 'backup', 'flavor', 'name')
        extra_kwargs = dict(
            backup={'lookup_field': 'uuid', 'view_name': 'openstack-dr-backup-detail'},
            tenant={'lookup_field': 'uuid', 'view_name': 'openstack-tenant-detail'},
            flavor={'lookup_field': 'uuid', 'view_name': 'openstack-flavor-detail'},
            **BasicDRBackupRestorationSerializer.Meta.extra_kwargs
        )

    def validate_backup(self, dr_backup):
        if dr_backup.state != models.DRBackup.States.OK:
            raise serializers.ValidationError('Cannot start restoration of DRBackup if it is not in state OK.')
        return dr_backup

    def validate(self, attrs):
        dr_backup = attrs['backup']
        tenant = attrs['tenant']
        flavor = attrs['flavor']
        if flavor.settings != tenant.service_project_link.service.settings:
            raise serializers.ValidationError('Tenant and flavor should belong to the same service settings.')

        min_disk = dr_backup.metadata['min_disk']
        min_ram = dr_backup.metadata['min_ram']
        if flavor.disk < min_disk:
            raise serializers.ValidationError(
                {'flavor': "Disk of flavor is not enough for restoration. Min value: %s" % min_disk})
        if flavor.ram < min_ram:
            raise serializers.ValidationError(
                {'flavor': "RAM of flavor is not enough for restoration. Min value: %s" % min_disk})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        tenant = validated_data['tenant']
        flavor = validated_data['flavor']
        dr_backup = validated_data['backup']
        # instance that will be restored
        instance = models.Instance.objects.create(
            name=validated_data.pop('name', None) or dr_backup.metadata['name'],
            description=dr_backup.metadata['description'],
            service_project_link=tenant.service_project_link,
            tenant=tenant,
            flavor_disk=flavor.disk,
            flavor_name=flavor.name,
            cores=flavor.cores,
            ram=flavor.ram,
            min_ram=dr_backup.metadata['min_ram'],
            min_disk=dr_backup.metadata['min_disk'],
            image_name=dr_backup.metadata['image_name'],
            user_data=dr_backup.metadata['user_data'],
            disk=sum([volume_backup.size for volume_backup in dr_backup.volume_backups.all()]),
        )
        instance.tags.add(*dr_backup.metadata['tags'])
        instance.increase_backend_quotas_usage()
        validated_data['instance'] = instance
        dr_backup_restoration = super(DRBackupRestorationSerializer, self).create(validated_data)
        # restoration for each backuped volume.
        for volume_backup in dr_backup.volume_backups.all():
            # volume for backup restoration.
            volume = models.Volume.objects.create(
                tenant=tenant,
                service_project_link=tenant.service_project_link,
                name=volume_backup.name,
                description=volume_backup.description,
                size=volume_backup.size,
                image_metadata=volume_backup.metadata['source_volume_image_metadata'],
            )
            volume.increase_backend_quotas_usage()
            instance.volumes.add(volume)
            # temporary imported backup
            # no need to increase quotas for mirrored backup - it is just link
            # to the existed record in swift
            mirorred_volume_backup = models.VolumeBackup.objects.create(
                tenant=tenant,
                service_project_link=tenant.service_project_link,
                source_volume=volume_backup.source_volume,
                name='Mirror of backup: %s' % volume_backup.name,
                description='Part of "%s" (%s) instance restoration' % (instance.name, instance.uuid),
                size=volume_backup.size,
                metadata=volume_backup.metadata,
                record=volume_backup.record,
            )
            # volume restoration from backup
            volume_backup_restoration = models.VolumeBackupRestoration.objects.create(
                tenant=tenant,
                volume_backup=volume_backup,
                mirorred_volume_backup=mirorred_volume_backup,
                volume=volume,
            )
            dr_backup_restoration.volume_backup_restorations.add(volume_backup_restoration)
        # XXX: This should be moved to itacloud assembly
        self.create_instance_crm(instance, dr_backup)
        return dr_backup_restoration


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
