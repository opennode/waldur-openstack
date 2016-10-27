from django.db import models

from nodeconductor.structure import models as structure_models


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
