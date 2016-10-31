from django.db import transaction
from django.utils import six, timezone

from glanceclient import exc as glance_exceptions
from neutronclient.client import exceptions as neutron_exceptions
from novaclient import exceptions as nova_exceptions
from cinderclient import exceptions as cinder_exceptions

from nodeconductor.structure import log_backend_action

from nodeconductor_openstack.openstack_base.backend import (
    BaseOpenStackBackend, OpenStackBackendError, update_pulled_fields)
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
            self.settings.set_quota_usage(quota_name, usage, fail_silently=True)

    def _normalize_security_group_rule(self, rule):
        if rule['ip_protocol'] is None:
            rule['ip_protocol'] = ''

        if 'cidr' not in rule['ip_range']:
            rule['ip_range']['cidr'] = '0.0.0.0/0'

        return rule

    def _get_current_properties(self, model):
        return {p.backend_id: p for p in model.objects.filter(settings=self.settings)}

    @log_backend_action()
    def create_volume(self, volume):
        kwargs = {
            'size': self.mb2gb(volume.size),
            'name': volume.name,
            'description': volume.description,
        }
        if volume.source_snapshot:
            kwargs['snapshot_id'] = volume.source_snapshot.backend_id
        if volume.type:
            kwargs['volume_type'] = volume.type
        if volume.image:
            kwargs['imageRef'] = volume.image.backend_id
        cinder = self.cinder_client
        try:
            backend_volume = cinder.volumes.create(**kwargs)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        volume.backend_id = backend_volume.id
        if hasattr(backend_volume, 'volume_image_metadata'):
            volume.image_metadata = backend_volume.volume_image_metadata
        volume.bootable = backend_volume.bootable == 'true'
        volume.runtime_state = backend_volume.status
        volume.save()
        return volume

    @log_backend_action()
    def update_volume(self, volume):
        cinder = self.cinder_client
        try:
            cinder.volumes.update(volume.backend_id, name=volume.name, description=volume.description)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_volume(self, volume):
        cinder = self.cinder_client
        try:
            cinder.volumes.delete(volume.backend_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        volume.decrease_backend_quotas_usage()

    @log_backend_action()
    def attach_volume(self, volume, instance_uuid, device=None):
        instance = models.Instance.objects.get(uuid=instance_uuid)
        nova = self.nova_client
        try:
            nova.volumes.create_server_volume(instance.backend_id, volume.backend_id, device=device)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            volume.instance = instance
            volume.device = device
            volume.save(update_fields=['instance', 'device'])

    @log_backend_action()
    def detach_volume(self, volume):
        nova = self.nova_client
        try:
            nova.volumes.delete_server_volume(volume.instance.backend_id, volume.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            volume.instance = None
            volume.device = ''
            volume.save(update_fields=['instance', 'device'])

    @log_backend_action()
    def extend_volume(self, volume, new_size):
        cinder = self.cinder_client
        try:
            cinder.volumes.extend(volume.backend_id, self.mb2gb(new_size))
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    def import_volume(self, backend_volume_id, save=True, service_project_link=None):
        """ Restore NC Volume instance based on backend data. """
        cinder = self.cinder_client
        try:
            backend_volume = cinder.volumes.get(backend_volume_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        volume = models.Volume(
            name=backend_volume.name,
            description=backend_volume.description or '',
            size=self.gb2mb(backend_volume.size),
            metadata=backend_volume.metadata,
            backend_id=backend_volume_id,
            type=backend_volume.volume_type or '',
            bootable=backend_volume.bootable == 'true',
            runtime_state=backend_volume.status,
            state=models.Volume.States.OK,
        )
        if service_project_link is not None:
            volume.service_project_link = service_project_link
        if hasattr(backend_volume, 'volume_image_metadata'):
            volume.image_metadata = backend_volume.volume_image_metadata
            try:
                volume.image = models.Image.objects.get(
                    settings=self.settings, backend_id=volume.image_metadata['image_id'])
            except models.Image.DoesNotExist:
                pass
        # In our setup volume could be attached only to one instance.
        if getattr(backend_volume, 'attachments', False):
            if 'device' in backend_volume.attachments[0]:
                volume.device = backend_volume.attachments[0]['device']
        if save:
            volume.save()
        return volume

    @log_backend_action()
    def pull_volume(self, volume, update_fields=None):
        import_time = timezone.now()
        imported_volume = self.import_volume(volume.backend_id, save=False)

        volume.refresh_from_db()
        if volume.modified < import_time:
            if not update_fields:
                update_fields = ('name', 'description', 'size', 'metadata',
                                 'type', 'bootable', 'runtime_state', 'device')

            update_pulled_fields(volume, imported_volume, update_fields)

    @log_backend_action()
    def pull_volume_runtime_state(self, volume):
        cinder = self.cinder_client
        try:
            backend_volume = cinder.volumes.get(volume.backend_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        if backend_volume.status != volume.runtime_state:
            volume.runtime_state = backend_volume.status
            volume.save(update_fields=['runtime_state'])

    @log_backend_action('check is volume deleted')
    def is_volume_deleted(self, volume):
        cinder = self.cinder_client
        try:
            cinder.volumes.get(volume.backend_id)
            return False
        except cinder_exceptions.NotFound:
            return True
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def create_snapshot(self, snapshot, force=False):
        kwargs = {
            'name': snapshot.name,
            'description': snapshot.description,
            'force': force,
        }
        # TODO: set backend snapshot metadata if it is defined in NC.
        cinder = self.cinder_client
        try:
            backend_snapshot = cinder.volume_snapshots.create(snapshot.source_volume.backend_id, **kwargs)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        snapshot.backend_id = backend_snapshot.id
        snapshot.runtime_state = backend_snapshot.status
        snapshot.size = self.gb2mb(backend_snapshot.size)
        snapshot.save()
        return snapshot

    def import_snapshot(self, backend_snapshot_id, save=True, service_project_link=None):
        """ Restore NC Snapshot instance based on backend data. """
        cinder = self.cinder_client
        try:
            backend_snapshot = cinder.volume_snapshots.get(backend_snapshot_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        snapshot = models.Snapshot(
            name=backend_snapshot.name,
            description=backend_snapshot.description or '',
            size=self.gb2mb(backend_snapshot.size),
            metadata=backend_snapshot.metadata,
            backend_id=backend_snapshot_id,
            runtime_state=backend_snapshot.status,
            state=models.Snapshot.States.OK,
        )
        if service_project_link is not None:
            snapshot.service_project_link = service_project_link
        if hasattr(backend_snapshot, 'volume_id'):
            snapshot.source_volume = models.Volume.objects.filter(backend_id=backend_snapshot.volume_id).first()

        if save:
            snapshot.save()
        return snapshot

    @log_backend_action()
    def pull_snapshot(self, snapshot):
        import_time = timezone.now()
        imported_snapshot = self.import_snapshot(snapshot.backend_id, save=False)

        snapshot.refresh_from_db()
        if snapshot.modified < import_time:
            update_fields = ('name', 'description', 'size', 'metadata', 'source_volume', 'runtime_state')
            update_pulled_fields(snapshot, imported_snapshot, update_fields)

    @log_backend_action()
    def pull_snapshot_runtime_state(self, snapshot):
        cinder = self.cinder_client
        try:
            backend_snapshot = cinder.volume_snapshots.get(snapshot.backend_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        if backend_snapshot.status != snapshot.runtime_state:
            snapshot.runtime_state = backend_snapshot.status
            snapshot.save(update_fields=['runtime_state'])
        return snapshot

    @log_backend_action()
    def delete_snapshot(self, snapshot):
        cinder = self.cinder_client
        try:
            cinder.volume_snapshots.delete(snapshot.backend_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        snapshot.decrease_backend_quotas_usage()

    @log_backend_action()
    def update_snapshot(self, snapshot):
        cinder = self.cinder_client
        try:
            cinder.volume_snapshots.update(
                snapshot.backend_id, name=snapshot.name, description=snapshot.description)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action('check is snapshot deleted')
    def is_snapshot_deleted(self, snapshot):
        cinder = self.cinder_client
        try:
            cinder.volume_snapshots.get(snapshot.backend_id)
            return False
        except cinder_exceptions.NotFound:
            return True
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
