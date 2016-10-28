from django.db import transaction
from django.utils import six

from glanceclient import exc as glance_exceptions
from neutronclient.client import exceptions as neutron_exceptions
from novaclient import exceptions as nova_exceptions

from nodeconductor_openstack.openstack_base.backend import BaseOpenStackBackend, OpenStackBackendError
from . import models


class OpenStackTenantBackend(BaseOpenStackBackend):

    def __init__(self, settings):
        super(OpenStackTenantBackend, self).__init__(settings, settings.options['tenant_id'])

    def sync(self):
        self._pull_flavors()
        self._pull_images()
        self._pull_floating_ips()
        self._pull_security_groups()
        self._pull_quotas()

    def _pull_flavors(self):
        nova = self.nova_client
        try:
            flavors = nova.flavors.findall(is_public=True)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        with transaction.atomic():
            cur_flavors = self._get_current_properties(models.Flavor)
            for backend_flavor in flavors:
                cur_flavors.pop(backend_flavor.id, None)
                models.Flavor.objects.update_or_create(
                    settings=self.settings,
                    backend_id=backend_flavor.id,
                    defaults={
                        'name': backend_flavor.name,
                        'cores': backend_flavor.vcpus,
                        'ram': backend_flavor.ram,
                        'disk': self.gb2mb(backend_flavor.disk),
                    })

            models.Flavor.objects.filter(backend_id__in=cur_flavors.keys()).delete()

    def _pull_images(self):
        glance = self.glance_client
        try:
            images = [image for image in glance.images.list() if image.is_public and not image.deleted]
        except glance_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        with transaction.atomic():
            cur_images = self._get_current_properties(models.Image)
            for backend_image in images:
                cur_images.pop(backend_image.id, None)
                models.Image.objects.update_or_create(
                    settings=self.settings,
                    backend_id=backend_image.id,
                    defaults={
                        'name': backend_image.name,
                        'min_ram': backend_image.min_ram,
                        'min_disk': self.gb2mb(backend_image.min_disk),
                    })

            models.Image.objects.filter(backend_id__in=cur_images.keys()).delete()

    def _pull_floating_ips(self):
        neutron = self.neutron_client
        try:
            ips = [ip for ip in neutron.list_floatingips(tenant_id=self.tenant_id)['floatingips']
                   if ip.get('floating_ip_address') and ip.get('status')]
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

        with transaction.atomic():
            cur_ips = self._get_current_properties(models.FloatingIP)
            for backend_ip in ips:
                cur_ips.pop(backend_ip['id'], None)
                models.FloatingIP.objects.update_or_create(
                    settings=self.settings,
                    backend_id=backend_ip['id'],
                    defaults={
                        'status': ip['status'],
                        'address': ip['floating_ip_address'],
                        'backend_network_id': ip['floating_network_id'],
                    })

            models.FloatingIP.objects.filter(backend_id__in=cur_ips.keys()).delete()

    def _pull_security_groups(self):
        nova = self.nova_client
        try:
            security_groups = nova.security_groups.list()
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        with transaction.atomic():
            cur_security_groups = self._get_current_properties(models.SecurityGroup)
            for backend_security_group in security_groups:
                cur_security_groups.pop(backend_security_group.id, None)
                security_group, _ = models.SecurityGroup.objects.update_or_create(
                    settings=self.settings,
                    backend_id=backend_security_group.id,
                    defaults={
                        'name': backend_security_group.name,
                        'description': backend_security_group.description,
                    })
                self._pull_security_group_rules(security_group, backend_security_group)

            models.SecurityGroup.objects.filter(backend_id__in=cur_security_groups.keys()).delete()

    def _pull_security_group_rules(self, security_group, backend_security_group):
        backend_rules = [self._normalize_security_group_rule(r) for r in backend_security_group.rules]
        cur_rules = {rule.backend_id: rule for rule in security_group.rules.all()}
        for backend_rule in backend_rules:
            cur_rules.pop(backend_rule['id'], None)
            security_group.rules.update_or_create(
                backend_id=backend_rule['id'],
                defaults={
                    'from_port': backend_rule['from_port'],
                    'to_port': backend_rule['to_port'],
                    'protocol': backend_rule['ip_protocol'],
                    'cidr': backend_rule['ip_range']['cidr'],
                })
        security_group.rules.filter(backend_id__in=cur_rules.keys()).delete()

    def _pull_quotas(self):
        for quota_name, limit in self.get_tenant_quotas_limits(self.tenant_id).items():
            self.settings.set_quota_limit(quota_name, limit)
        for quota_name, usage in self.get_tenant_quotas_usage(self.tenant_id).items():
            self.settings.set_quota_usage(quota_name, limit, fail_silently=True)

    def _normalize_security_group_rule(self, rule):
        if rule['ip_protocol'] is None:
            rule['ip_protocol'] = ''

        if 'cidr' not in rule['ip_range']:
            rule['ip_range']['cidr'] = '0.0.0.0/0'

        return rule

    def _get_current_properties(self, model):
        return {p.backend_id: p for p in model.objects.filter(settings=self.settings)}
