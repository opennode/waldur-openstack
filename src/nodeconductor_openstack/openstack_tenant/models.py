from __future__ import unicode_literals

from urlparse import urlparse

from django.core.validators import RegexValidator
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from jsonfield import JSONField
from model_utils import FieldTracker
from model_utils.models import TimeStampedModel

from nodeconductor.core import models as core_models
from nodeconductor.logging.loggers import LoggableMixin
from nodeconductor.structure import models as structure_models, utils as structure_utils

from nodeconductor_openstack.openstack_base import models as openstack_base_models


class OpenStackTenantService(structure_models.Service):
    projects = models.ManyToManyField(
        structure_models.Project, related_name='openstack_tenant_services', through='OpenStackTenantServiceProjectLink')

    class Meta:
        unique_together = ('customer', 'settings')
        verbose_name = 'OpenStackTenant service'
        verbose_name_plural = 'OpenStackTenant services'

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant'


class OpenStackTenantServiceProjectLink(structure_models.ServiceProjectLink):
    service = models.ForeignKey(OpenStackTenantService)

    class Meta(structure_models.ServiceProjectLink.Meta):
        verbose_name = 'OpenStackTenant service project link'
        verbose_name_plural = 'OpenStackTenant service project links'

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-spl'


class Flavor(LoggableMixin, structure_models.ServiceProperty):
    cores = models.PositiveSmallIntegerField(help_text='Number of cores in a VM')
    ram = models.PositiveIntegerField(help_text='Memory size in MiB')
    disk = models.PositiveIntegerField(help_text='Root disk size in MiB')

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-flavor'


class Image(structure_models.ServiceProperty):
    min_disk = models.PositiveIntegerField(default=0, help_text='Minimum disk size in MiB')
    min_ram = models.PositiveIntegerField(default=0, help_text='Minimum memory size in MiB')

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-image'


class SecurityGroup(core_models.DescribableMixin, structure_models.ServiceProperty):
    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-sgp'


class SecurityGroupRule(openstack_base_models.BaseSecurityGroupRule):
    security_group = models.ForeignKey(SecurityGroup, related_name='rules')


@python_2_unicode_compatible
class FloatingIP(structure_models.ServiceProperty):
    address = models.GenericIPAddressField(protocol='IPv4')
    status = models.CharField(max_length=30)
    backend_network_id = models.CharField(max_length=255, editable=False)
    is_booked = models.BooleanField(default=False, help_text='Defines is FloatingIP booked by NodeConductor.')

    def __str__(self):
        return '%s:%s | %s' % (self.address, self.status, self.settings)

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-fip'


class Volume(structure_models.Storage):
    service_project_link = models.ForeignKey(
        OpenStackTenantServiceProjectLink, related_name='volumes', on_delete=models.PROTECT)
    instance = models.ForeignKey('Instance', related_name='volumes', blank=True, null=True)
    device = models.CharField(
        max_length=50, blank=True,
        validators=[RegexValidator('^/dev/[a-zA-Z0-9]+$', message='Device should match pattern "/dev/alphanumeric+"')],
        help_text='Name of volume as instance device e.g. /dev/vdb.')
    bootable = models.BooleanField(default=False)
    metadata = JSONField(blank=True)
    image = models.ForeignKey(Image, null=True)
    image_metadata = JSONField(blank=True)
    type = models.CharField(max_length=100, blank=True)
    source_snapshot = models.ForeignKey('Snapshot', related_name='volumes', null=True, on_delete=models.SET_NULL)
    # TODO: Move this fields to resource model.
    action = models.CharField(max_length=50, blank=True)
    action_details = JSONField(default={})

    tracker = FieldTracker()

    def increase_backend_quotas_usage(self, validate=True):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.volumes, 1, validate=validate)
        settings.add_quota_usage(settings.Quotas.storage, self.size, validate=validate)

    def decrease_backend_quotas_usage(self):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.volumes, -1)
        settings.add_quota_usage(settings.Quotas.storage, -self.size)

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-volume'


class Snapshot(structure_models.Storage):
    service_project_link = models.ForeignKey(
        OpenStackTenantServiceProjectLink, related_name='snapshots', on_delete=models.PROTECT)
    source_volume = models.ForeignKey(Volume, related_name='snapshots', null=True, on_delete=models.PROTECT)
    metadata = JSONField(blank=True)
    # TODO: Move this fields to resource model.
    action = models.CharField(max_length=50, blank=True)
    action_details = JSONField(default={})

    tracker = FieldTracker()

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-snapshot'

    def increase_backend_quotas_usage(self, validate=True):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.snapshots, 1, validate=validate)
        settings.add_quota_usage(settings.Quotas.storage, self.size, validate=validate)

    def decrease_backend_quotas_usage(self):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.snapshots, -1)
        settings.add_quota_usage(settings.Quotas.storage, -self.size)


class Instance(structure_models.VirtualMachineMixin, core_models.RuntimeStateMixin, structure_models.NewResource):

    class RuntimeStates(object):
        # All possible OpenStack Instance states on backend.
        # See http://developer.openstack.org/api-ref-compute-v2.html
        ACTIVE = 'ACTIVE'
        BUILDING = 'BUILDING'
        DELETED = 'DELETED'
        SOFT_DELETED = 'SOFT_DELETED'
        ERROR = 'ERROR'
        UNKNOWN = 'UNKNOWN'
        HARD_REBOOT = 'HARD_REBOOT'
        REBOOT = 'REBOOT'
        REBUILD = 'REBUILD'
        PASSWORD = 'PASSWORD'
        PAUSED = 'PAUSED'
        RESCUED = 'RESCUED'
        RESIZED = 'RESIZED'
        REVERT_RESIZE = 'REVERT_RESIZE'
        SHUTOFF = 'SHUTOFF'
        STOPPED = 'STOPPED'
        SUSPENDED = 'SUSPENDED'
        VERIFY_RESIZE = 'VERIFY_RESIZE'

    service_project_link = models.ForeignKey(
        OpenStackTenantServiceProjectLink, related_name='instances', on_delete=models.PROTECT)

    flavor_name = models.CharField(max_length=255, blank=True)
    flavor_disk = models.PositiveIntegerField(default=0, help_text='Flavor disk size in MiB')
    security_groups = models.ManyToManyField(SecurityGroup, related_name='instances')
    # TODO: Move this fields to resource model.
    action = models.CharField(max_length=50, blank=True)
    action_details = JSONField(default={})

    tracker = FieldTracker()

    @property
    def size(self):
        return self.volumes.aggregate(models.Sum('size'))['size']

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-instance'

    def get_log_fields(self):
        return ('uuid', 'name', 'type', 'service_project_link', 'ram', 'cores',)

    def detect_coordinates(self):
        settings = self.service_project_link.service.settings
        options = settings.options or {}
        if 'latitude' in options and 'longitude' in options:
            return structure_utils.Coordinates(latitude=settings['latitude'], longitude=settings['longitude'])
        else:
            hostname = urlparse(settings.backend_url).hostname
            if hostname:
                return structure_utils.get_coordinates_by_ip(hostname)

    def increase_backend_quotas_usage(self, validate=True):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.instances, 1)
        settings.add_quota_usage(settings.Quotas.ram, self.ram)
        settings.add_quota_usage(settings.Quotas.vcpu, self.cores)

    def decrease_backend_quotas_usage(self):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.instances, -1)
        settings.add_quota_usage(settings.Quotas.ram, -self.ram)
        settings.add_quota_usage(settings.Quotas.vcpu, -self.cores)


class Backup(structure_models.NewResource):
    service_project_link = models.ForeignKey(
        OpenStackTenantServiceProjectLink, related_name='backups', on_delete=models.PROTECT)
    instance = models.ForeignKey(Instance, related_name='backups', on_delete=models.PROTECT)
    backup_schedule = models.ForeignKey('BackupSchedule', blank=True, null=True,
                                        on_delete=models.SET_NULL,
                                        related_name='backups')
    kept_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Guaranteed time of backup retention. If null - keep forever.')
    metadata = JSONField(
        blank=True,
        help_text='Additional information about backup, can be used for backup restoration or deletion',
    )
    snapshots = models.ManyToManyField('Snapshot', related_name='backups')

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-backup'


class BackupRestoration(core_models.UuidMixin, TimeStampedModel):
    """ This model corresponds to instance restoration from backup. """
    backup = models.ForeignKey(Backup, related_name='restorations')
    instance = models.OneToOneField(Instance, related_name='+')
    flavor = models.ForeignKey(Flavor, related_name='+', null=True, blank=True, on_delete=models.SET_NULL)

    class Permissions(object):
        customer_path = 'backup__service_project_link__project__customer'
        project_path = 'backup__service_project_link__project'

    def get_backend(self):
        return self.backup.get_backend()

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-backup-restoration'


class BackupSchedule(core_models.UuidMixin,
                     core_models.NameMixin,
                     core_models.DescribableMixin,
                     core_models.ScheduleMixin,
                     core_models.ErrorMessageMixin,
                     LoggableMixin):

    class Permissions(object):
        customer_path = 'instance__service_project_link__project__customer'
        project_path = 'instance__service_project_link__project'

    instance = models.ForeignKey(Instance, related_name='backup_schedules')
    retention_time = models.PositiveIntegerField(
        help_text='Retention time in days, if 0 - backup will be kept forever')
    maximal_number_of_backups = models.PositiveSmallIntegerField()

    tracker = FieldTracker()

    def __str__(self):
        return 'BackupSchedule of %s. Active: %s' % (self.instance, self.is_active)

    @classmethod
    def get_url_name(cls):
        return 'openstacktenant-backup-schedule'
