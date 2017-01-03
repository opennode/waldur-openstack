import json
import logging
import time

from django.db import transaction
from django.utils import six, timezone, dateparse

from ceilometerclient import exc as ceilometer_exceptions
from cinderclient import exceptions as cinder_exceptions
from glanceclient import exc as glance_exceptions
from keystoneclient import exceptions as keystone_exceptions
from neutronclient.client import exceptions as neutron_exceptions
from novaclient import exceptions as nova_exceptions

from nodeconductor.structure import log_backend_action

from nodeconductor_openstack.openstack_base.backend import (
    BaseOpenStackBackend, OpenStackBackendError, update_pulled_fields)
from . import models


logger = logging.getLogger(__name__)


class OpenStackTenantBackend(BaseOpenStackBackend):
    VOLUME_UPDATE_FIELDS = ('name', 'description', 'size', 'metadata', 'type', 'bootable', 'runtime_state', 'device')
    SNAPSHOT_UPDATE_FIELDS = ('name', 'description', 'size', 'metadata', 'source_volume', 'runtime_state')
    INSTANCE_UPDATE_FIELDS = ('name', 'flavor_name', 'flavor_disk', 'ram', 'cores', 'disk', 'internal_ips',
                              'external_ips', 'runtime_state', 'error_message')

    def __init__(self, settings):
        super(OpenStackTenantBackend, self).__init__(settings, settings.options['tenant_id'])

    @property
    def external_network_id(self):
        return self.settings.options['external_network_id']

    @property
    def internal_network_id(self):
        return self.settings.options['internal_network_id']

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
                        'status': backend_ip['status'],
                        'address': backend_ip['floating_ip_address'],
                        'backend_network_id': backend_ip['floating_network_id'],
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
    def extend_volume(self, volume):
        cinder = self.cinder_client
        try:
            cinder.volumes.extend(volume.backend_id, self.mb2gb(volume.size))
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    def import_volume(self, backend_volume_id, save=True, service_project_link=None):
        """ Restore NC Volume instance based on backend data. """
        cinder = self.cinder_client
        try:
            backend_volume = cinder.volumes.get(backend_volume_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        volume = self._backend_volume_to_volume(backend_volume)
        if service_project_link is not None:
            volume.service_project_link = service_project_link
        if save:
            volume.save()
        return volume

    def _backend_volume_to_volume(self, backend_volume):
        volume = models.Volume(
            name=backend_volume.name,
            description=backend_volume.description or '',
            size=self.gb2mb(backend_volume.size),
            metadata=backend_volume.metadata,
            backend_id=backend_volume.id,
            type=backend_volume.volume_type or '',
            bootable=backend_volume.bootable == 'true',
            runtime_state=backend_volume.status,
            state=models.Volume.States.OK,
        )
        if getattr(backend_volume, 'volume_image_metadata', False):
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
        return volume

    def get_volumes(self):
        cinder = self.cinder_client
        try:
            backend_volumes = cinder.volumes.list()
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        return [self._backend_volume_to_volume(backend_volume) for backend_volume in backend_volumes]

    @log_backend_action()
    def pull_volume(self, volume, update_fields=None):
        import_time = timezone.now()
        imported_volume = self.import_volume(volume.backend_id, save=False)

        volume.refresh_from_db()
        if volume.modified < import_time:
            if not update_fields:
                update_fields = self.VOLUME_UPDATE_FIELDS

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
        snapshot = self._backend_snapshot_to_snapshot(backend_snapshot)
        if service_project_link is not None:
            snapshot.service_project_link = service_project_link
        if save:
            snapshot.save()
        return snapshot

    def _backend_snapshot_to_snapshot(self, backend_snapshot):
        snapshot = models.Snapshot(
            name=backend_snapshot.name,
            description=backend_snapshot.description or '',
            size=self.gb2mb(backend_snapshot.size),
            metadata=backend_snapshot.metadata,
            backend_id=backend_snapshot.id,
            runtime_state=backend_snapshot.status,
            state=models.Snapshot.States.OK,
        )
        if hasattr(backend_snapshot, 'volume_id'):
            snapshot.source_volume = models.Volume.objects.filter(
                service_project_link__service__settings=self.settings, backend_id=backend_snapshot.volume_id).first()
        return snapshot

    def get_snapshots(self):
        cinder = self.cinder_client
        try:
            backend_snapshots = cinder.volume_snapshots.list()
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        return [self._backend_snapshot_to_snapshot(backend_snapshot) for backend_snapshot in backend_snapshots]

    @log_backend_action()
    def pull_snapshot(self, snapshot, update_fields=None):
        import_time = timezone.now()
        imported_snapshot = self.import_snapshot(snapshot.backend_id, save=False)

        snapshot.refresh_from_db()
        if snapshot.modified < import_time:
            if update_fields is None:
                update_fields = self.SNAPSHOT_UPDATE_FIELDS
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

    @log_backend_action()
    def create_instance(self, instance, backend_flavor_id=None,
                        allocate_floating_ip=False, public_key=None, floating_ip_uuid=None):
        nova = self.nova_client

        floating_ip = None
        if floating_ip_uuid:
            floating_ip = models.FloatingIP.objects.get(uuid=floating_ip_uuid)
        elif allocate_floating_ip:
            floating_ip = self._get_or_create_floating_ip()

        if floating_ip:
            floating_ip.status = 'BOOKED'
            floating_ip.save(update_fields=['status'])

        try:
            backend_flavor = nova.flavors.get(backend_flavor_id)

            # instance key name and fingerprint are optional
            if instance.key_name:
                backend_public_key = self._get_or_create_ssh_key(
                    instance.key_name, instance.key_fingerprint, public_key)
            else:
                backend_public_key = None

            if instance.volumes.count() != 2:
                raise OpenStackBackendError('Current installation can create instance with 2 volumes only.')
            try:
                system_volume = instance.volumes.get(bootable=True)
                data_volume = instance.volumes.get(bootable=False)
            except models.Volume.DoesNotExist:
                raise OpenStackBackendError(
                    'Current installation can create only instance with 1 system volume and 1 data volume.')

            security_group_ids = instance.security_groups.values_list('backend_id', flat=True)

            server_create_parameters = dict(
                name=instance.name,
                image=None,  # Boot from volume, see boot_index below
                flavor=backend_flavor,
                block_device_mapping_v2=[
                    {
                        'boot_index': 0,
                        'destination_type': 'volume',
                        'device_type': 'disk',
                        'source_type': 'volume',
                        'uuid': system_volume.backend_id,
                        'delete_on_termination': True,
                    },
                    {
                        'destination_type': 'volume',
                        'device_type': 'disk',
                        'source_type': 'volume',
                        'uuid': data_volume.backend_id,
                        'delete_on_termination': True,
                    },
                ],
                nics=[
                    {'net-id': self.internal_network_id}
                ],
                key_name=backend_public_key.name if backend_public_key is not None else None,
                security_groups=security_group_ids,
            )
            availability_zone = self.settings.options['availability_zone']
            if availability_zone:
                server_create_parameters['availability_zone'] = availability_zone
            if instance.user_data:
                server_create_parameters['userdata'] = instance.user_data

            server = nova.servers.create(**server_create_parameters)

            instance.backend_id = server.id
            instance.save()

            if not self._wait_for_instance_status(instance, nova, 'ACTIVE', 'ERROR'):
                logger.error(
                    "Failed to provision instance %s: timed out waiting "
                    "for instance to become online",
                    instance.uuid)
                raise OpenStackBackendError("Timed out waiting for instance %s to provision" % instance.uuid)

            logger.debug("About to infer internal ip addresses of instance %s", instance.uuid)
            try:
                server = nova.servers.get(server.id)
                fixed_address = server.addresses.values()[0][0]['addr']
            except (nova_exceptions.ClientException, KeyError, IndexError):
                logger.exception(
                    "Failed to infer internal ip addresses of instance %s", instance.uuid)
            else:
                instance.internal_ips = fixed_address
                instance.save()
                logger.info(
                    "Successfully inferred internal ip addresses of instance %s", instance.uuid)

            if floating_ip:
                self.assign_floating_ip_to_instance(instance, floating_ip.uuid)
            else:
                logger.info("Skipping floating IP assignment for instance %s", instance.uuid)

            backend_security_groups = server.list_security_group()
            for bsg in backend_security_groups:
                if instance.security_groups.filter(name=bsg.name).exists():
                    continue
                try:
                    security_group = models.SecurityGroup.objects.get(name=bsg.name, settings=self.settings)
                except models.SecurityGroup.DoesNotExist:
                    logger.error(
                        'Security group "%s" does not exist, but instance %s (PK: %s) has it.' %
                        (bsg.name, instance, instance.pk)
                    )
                else:
                    instance.security_groups.add(security_group)

        except nova_exceptions.ClientException as e:
            logger.exception("Failed to provision instance %s", instance.uuid)
            six.reraise(OpenStackBackendError, e)
        else:
            logger.info("Successfully provisioned instance %s", instance.uuid)

    def _get_or_create_floating_ip(self):
        # TODO: check availability and quota
        filters = {'status': 'DOWN', 'backend_network_id': self.external_network_id, 'settings': self.settings}
        if not models.FloatingIP.objects.filter(**filters).exists():
            self._allocate_floating_ip()
        return models.FloatingIP.objects.filter(**filters).first()

    def _allocate_floating_ip(self):
        neutron = self.neutron_client
        try:
            ip_address = neutron.create_floatingip({
                'floatingip': {
                    'floating_network_id': self.external_network_id,
                    'tenant_id': self.tenant_id,
                }
            })['floatingip']
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            return models.FloatingIP.objects.create(
                status='DOWN',
                settings=self.settings,
                address=ip_address['floating_ip_address'],
                backend_id=ip_address['id'],
                backend_network_id=ip_address['floating_network_id'],
            )

    @log_backend_action()
    def allocate_and_assign_floating_ip_to_instance(self, instance):
        floating_ip = self._allocate_floating_ip()
        self.assign_floating_ip_to_instance(instance, floating_ip.uuid)

    @log_backend_action()
    def assign_floating_ip_to_instance(self, instance, floating_ip_uuid):
        nova = self.nova_client
        floating_ip = models.FloatingIP.objects.get(uuid=floating_ip_uuid)
        try:
            nova.servers.add_floating_ip(
                server=instance.backend_id,
                address=floating_ip.address,
                fixed_address=instance.internal_ips
            )
        except nova_exceptions.ClientException as e:
            floating_ip.status = 'DOWN'
            floating_ip.save(update_fields=['status'])
            six.reraise(OpenStackBackendError, e)
        else:
            floating_ip.status = 'ACTIVE'
            floating_ip.save(update_fields=['status'])
            instance.external_ips = floating_ip.address
            instance.save(update_fields=['external_ips'])

    def _get_or_create_ssh_key(self, key_name, fingerprint, public_key):
        nova = self.nova_client

        try:
            return nova.keypairs.find(fingerprint=fingerprint)
        except nova_exceptions.NotFound:
            # Fine, it's a new key, let's add it
            try:
                logger.info('Propagating ssh public key %s to backend', key_name)
                return nova.keypairs.create(name=key_name, public_key=public_key)
            except nova_exceptions.ClientException as e:
                six.reraise(OpenStackBackendError, e)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    def _wait_for_instance_status(self, instance, nova, complete_status,
                                  error_status=None, retries=300, poll_interval=3):
        complete_state_predicate = lambda o: o.status == complete_status
        if error_status is not None:
            error_state_predicate = lambda o: o.status == error_status
        else:
            error_state_predicate = lambda _: False

        for _ in range(retries):
            obj = nova.servers.get(instance.backend_id)
            logger.debug('Instance %s status: "%s"' % (obj, obj.status))
            if instance.runtime_state != obj.status:
                instance.runtime_state = obj.status
                instance.save(update_fields=['runtime_state'])

            if complete_state_predicate(obj):
                return True

            if error_state_predicate(obj):
                return False

            time.sleep(poll_interval)
        else:
            return False

    @log_backend_action()
    def update_instance(self, instance):
        nova = self.nova_client
        try:
            nova.servers.update(instance.backend_id, name=instance.name)
        except keystone_exceptions.NotFound as e:
            six.reraise(OpenStackBackendError, e)

    def import_instance(self, backend_instance_id, save=True, service_project_link=None):
        nova = self.nova_client
        try:
            backend_instance = nova.servers.get(backend_instance_id)
            flavor = nova.flavors.get(backend_instance.flavor['id'])
            attached_volume_ids = [v.volumeId for v in nova.volumes.get_server_volumes(backend_instance_id)]
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        instance = self._backend_instance_to_instance(backend_instance, flavor)
        with transaction.atomic():
            # import instance volumes, or use existed if they already exist in NodeConductor.
            volumes = []
            for backend_volume_id in attached_volume_ids:
                try:
                    volumes.append(models.Volume.objects.get(
                        service_project_link__service__settings=self.settings, backend_id=backend_volume_id))
                except models.Volume.DoesNotExist:
                    volumes.append(self.import_volume(backend_volume_id, save=save))

            # security groups should exist in NodeConductor.
            security_groups_names = [sg['name'] for sg in getattr(backend_instance, 'security_groups', [])]
            security_groups = models.SecurityGroup.objects.filter(
                settings=self.settings, name__in=security_groups_names)
            if security_groups.count() != len(security_groups_names):
                self._pull_security_groups()
            security_groups = []
            for name in security_groups_names:
                try:
                    security_groups.append(models.SecurityGroup.objects.get(settings=self.settings, name=name))
                except models.SecurityGroup.DoesNotExist:
                    raise OpenStackBackendError('Security group with name "%s" does not exist in NodeConductor.' % name)

            if service_project_link:
                instance.service_project_link = service_project_link
            if hasattr(backend_instance, 'fault'):
                instance.error_message = backend_instance.fault['message']
            if save:
                instance.save()
                instance.volumes.add(*volumes)
                instance.security_groups.add(*security_groups)

        return instance

    def _backend_instance_to_instance(self, backend_instance, backend_flavor):
        # TODO: add security groups and volume definition
        # parse IPs
        ips = {}
        for net_conf in backend_instance.addresses.values():
            for ip in net_conf:
                if ip['OS-EXT-IPS:type'] == 'fixed':
                    ips['internal'] = ip['addr']
                if ip['OS-EXT-IPS:type'] == 'floating':
                    ips['external'] = ip['addr']

        # parse launch time
        try:
            d = dateparse.parse_datetime(backend_instance.to_dict()['OS-SRV-USG:launched_at'])
        except (KeyError, ValueError, TypeError):
            launch_time = None
        else:
            # At the moment OpenStack does not provide any timezone info,
            # but in future it might do.
            if timezone.is_naive(d):
                launch_time = timezone.make_aware(d, timezone.utc)

        instance = models.Instance(
            name=backend_instance.name or backend_instance.id,
            key_name=backend_instance.key_name or '',
            start_time=launch_time,
            state=models.Instance.States.OK,
            runtime_state=backend_instance.status,
            created=dateparse.parse_datetime(backend_instance.created),

            flavor_name=backend_flavor.name,
            flavor_disk=backend_flavor.disk,
            cores=backend_flavor.vcpus,
            ram=backend_flavor.ram,

            internal_ips=ips.get('internal', ''),
            external_ips=ips.get('external', ''),
            backend_id=backend_instance.id,
        )
        backend_security_groups_names = [sg['name'] for sg in backend_instance.security_groups]
        instance._security_groups = models.SecurityGroup.objects.filter(
            name__in=backend_security_groups_names, settings=self.settings)
        return instance

    def get_instances(self):
        nova = self.nova_client
        try:
            backend_instances = nova.servers.list()
            backend_flavors = nova.flavors.list()
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        backend_flavors_map = {flavor.id: flavor for flavor in backend_flavors}
        instances = []
        for backend_instance in backend_instances:
            instance_flavor = backend_flavors_map[backend_instance.flavor['id']]
            instances.append(self._backend_instance_to_instance(backend_instance, instance_flavor))
        return instances

    @log_backend_action()
    def pull_instance(self, instance, update_fields=None):
        import_time = timezone.now()
        imported_instance = self.import_instance(instance.backend_id, save=False)

        instance.refresh_from_db()
        if instance.modified < import_time:
            if update_fields is None:
                update_fields = self.INSTANCE_UPDATE_FIELDS
            update_pulled_fields(instance, imported_instance, update_fields)

    @log_backend_action()
    def pull_instance_security_groups(self, instance):
        nova = self.nova_client
        server_id = instance.backend_id
        try:
            backend_groups = nova.servers.list_security_group(server_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        backend_ids = set(g.id for g in backend_groups)
        nc_ids = set(
            models.SecurityGroup.objects
            .filter(instances=instance)
            .exclude(backend_id='')
            .values_list('backend_id', flat=True)
        )

        # remove stale groups
        stale_groups = models.SecurityGroup.objects.filter(backend_id__in=(nc_ids - backend_ids))
        instance.security_groups.remove(*stale_groups)

        # add missing groups
        for group_id in backend_ids - nc_ids:
            try:
                security_group = models.SecurityGroup.objects.filter(tenant=instance.tenant).get(
                    backend_id=group_id)
            except models.SecurityGroup.DoesNotExist:
                logger.exception(
                    'Security group with id %s does not exist at NC. Tenant : %s' % (group_id, instance.tenant))
            else:
                instance.security_groups.add(security_group)

    @log_backend_action()
    def push_instance_security_groups(self, instance):
        nova = self.nova_client
        server_id = instance.backend_id
        try:
            backend_ids = set(g.id for g in nova.servers.list_security_group(server_id))
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        nc_ids = set(
            models.SecurityGroup.objects
            .filter(instances=instance)
            .exclude(backend_id='')
            .values_list('backend_id', flat=True)
        )

        # remove stale groups
        for group_id in backend_ids - nc_ids:
            try:
                nova.servers.remove_security_group(server_id, group_id)
            except nova_exceptions.ClientException:
                logger.exception('Failed to remove security group %s from instance %s', group_id, server_id)
            else:
                logger.info('Removed security group %s from instance %s', group_id, server_id)

        # add missing groups
        for group_id in nc_ids - backend_ids:
            try:
                nova.servers.add_security_group(server_id, group_id)
            except nova_exceptions.ClientException:
                logger.exception('Failed to add security group %s to instance %s', group_id, server_id)
            else:
                logger.info('Added security group %s to instance %s', group_id, server_id)

    @log_backend_action()
    def delete_instance(self, instance):
        nova = self.nova_client
        try:
            nova.servers.delete(instance.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        floating_ips = models.FloatingIP.objects.filter(
            settings=instance.service_project_link.service.settings, address=instance.external_ips)
        if floating_ips.update(status='DOWN'):
            logger.info('Successfully released floating ip %s from instance %s',
                        instance.external_ips, instance.uuid)
        instance.decrease_backend_quotas_usage()

    @log_backend_action('check is instance deleted')
    def is_instance_deleted(self, instance):
        nova = self.nova_client
        try:
            nova.servers.get(instance.backend_id)
            return False
        except nova_exceptions.NotFound:
            return True
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def pull_instance_volumes(self, instance):
        for volume in instance.volumes.all():
            if self.is_volume_deleted(volume):
                with transaction.atomic():
                    volume.decrease_backend_quotas_usage()
                    volume.delete()

    @log_backend_action()
    def start_instance(self, instance):
        nova = self.nova_client
        try:
            nova.servers.start(instance.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def stop_instance(self, instance):
        nova = self.nova_client
        try:
            nova.servers.stop(instance.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            instance.start_time = None
            instance.save(update_fields=['start_time'])

    @log_backend_action()
    def restart_instance(self, instance):
        nova = self.nova_client
        try:
            nova.servers.reboot(instance.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def resize_instance(self, instance, flavor_id):
        nova = self.nova_client
        try:
            nova.servers.resize(instance.backend_id, flavor_id, 'MANUAL')
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def pull_instance_runtime_state(self, instance):
        nova = self.nova_client
        try:
            backend_instance = nova.servers.get(instance.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        if backend_instance.status != instance.runtime_state:
            instance.runtime_state = backend_instance.status
            instance.save(update_fields=['runtime_state'])

    @log_backend_action()
    def confirm_instance_resize(self, instance):
        nova = self.nova_client
        try:
            nova.servers.confirm_resize(instance.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def list_meters(self, resource):
        try:
            file_name = self._get_meters_file_name(resource.__class__)
            with open(file_name) as meters_file:
                meters = json.load(meters_file)
        except (KeyError, IOError):
            raise OpenStackBackendError("Cannot find meters for the '%s' resources" % resource.__class__.__name__)

        return meters

    @log_backend_action()
    def get_meter_samples(self, resource, meter_name, start=None, end=None):
        query = [dict(field='resource_id', op='eq', value=resource.backend_id)]

        if start is not None:
            query.append(dict(field='timestamp', op='ge', value=start.strftime('%Y-%m-%dT%H:%M:%S')))
        if end is not None:
            query.append(dict(field='timestamp', op='le', value=end.strftime('%Y-%m-%dT%H:%M:%S')))

        ceilometer = self.ceilometer_client
        try:
            samples = ceilometer.samples.list(meter_name=meter_name, q=query)
        except ceilometer_exceptions.BaseException as e:
            six.reraise(OpenStackBackendError, e)

        return samples
