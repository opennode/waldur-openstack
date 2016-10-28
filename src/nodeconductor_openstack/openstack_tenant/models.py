from django.core.validators import RegexValidator
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from jsonfield import JSONField

from nodeconductor.core import models as core_models
from nodeconductor.logging.loggers import LoggableMixin
from nodeconductor.structure import models as structure_models

from nodeconductor_openstack.openstack_base import models as openstack_base_models


class OpenStackTenantService(structure_models.Service):
    projects = models.ManyToManyField(
        structure_models.Project, related_name='openstack_tenant_services', through='OpenStackTenantServiceProjectLink')

    class Meta:
        unique_together = ('customer', 'settings')
        verbose_name = 'OpenStackTenant service'
        verbose_name_plural = 'OpenStackTenan services'

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
    # TODO: add FK to Instance WAL-119
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

    def get_backend(self):
        return self.service_project_link.service.settings.get_backend()

    def increase_backend_quotas_usage(self, validate=True):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.volumes, 1, validate=validate)
        settings.add_quota_usage(settings.Quotas.storage, self.size, validate=validate)

    def decrease_backend_quotas_usage(self):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.volumes, -1)
        settings.add_quota_usage(settings.Quotas.storage, -self.size)


class Snapshot(structure_models.Storage):
    service_project_link = models.ForeignKey(
        OpenStackTenantServiceProjectLink, related_name='snapshots', on_delete=models.PROTECT)
    source_volume = models.ForeignKey(Volume, related_name='snapshots', null=True, on_delete=models.PROTECT)
    metadata = JSONField(blank=True)

    def get_backend(self):
        return self.service_project_link.service.settings.get_backend()

    def increase_backend_quotas_usage(self, validate=True):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.snapshots, 1, validate=validate)
        settings.add_quota_usage(settings.Quotas.storage, self.size, validate=validate)

    def decrease_backend_quotas_usage(self):
        settings = self.service_project_link.service.settings
        settings.add_quota_usage(settings.Quotas.snapshots, -1)
        settings.add_quota_usage(settings.Quotas.storage, -self.size)
