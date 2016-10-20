import base64
import datetime
import json
import hashlib
import logging
import os
import time
import uuid

from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import six, dateparse, timezone
from requests import ConnectionError

from keystoneauth1.identity import v2
from keystoneauth1 import session as keystone_session

from ceilometerclient import client as ceilometer_client
from cinderclient.v2 import client as cinder_client
from glanceclient.v1 import client as glance_client
from keystoneclient.v2_0 import client as keystone_client
from neutronclient.v2_0 import client as neutron_client
from novaclient.v2 import client as nova_client

from ceilometerclient import exc as ceilometer_exceptions
from cinderclient import exceptions as cinder_exceptions
from glanceclient import exc as glance_exceptions
from keystoneclient import exceptions as keystone_exceptions
from neutronclient.client import exceptions as neutron_exceptions
from novaclient import exceptions as nova_exceptions

from nodeconductor.core.models import StateMixin
from nodeconductor.core.tasks import send_task
from nodeconductor.structure import ServiceBackend, ServiceBackendError, log_backend_action, SupportedServices

from . import models


logger = logging.getLogger(__name__)


class OpenStackBackendError(ServiceBackendError):
    pass


class OpenStackSessionExpired(OpenStackBackendError):
    pass


class OpenStackAuthorizationFailed(OpenStackBackendError):
    pass


class OpenStackSession(dict):
    """ Serializable session """

    def __init__(self, ks_session=None, verify_ssl=False, **credentials):
        self.keystone_session = ks_session
        if not self.keystone_session:
            auth_plugin = v2.Password(**credentials)
            self.keystone_session = keystone_session.Session(auth=auth_plugin, verify=verify_ssl)

        try:
            # This will eagerly sign in throwing AuthorizationFailure on bad credentials
            self.keystone_session.get_auth_headers()
        except keystone_exceptions.ClientException as e:
            six.reraise(OpenStackAuthorizationFailed, e)

        for opt in ('auth_ref', 'auth_url', 'tenant_id', 'tenant_name'):
            self[opt] = getattr(self.auth, opt)

    def __getattr__(self, name):
        return getattr(self.keystone_session, name)

    @classmethod
    def recover(cls, session, verify_ssl=False):
        if not isinstance(session, dict) or not session.get('auth_ref'):
            raise OpenStackBackendError('Invalid OpenStack session')

        args = {'auth_url': session['auth_url'], 'token': session['auth_ref'].auth_token}
        if session['tenant_id']:
            args['tenant_id'] = session['tenant_id']
        elif session['tenant_name']:
            args['tenant_name'] = session['tenant_name']

        ks_session = keystone_session.Session(auth=v2.Token(**args), verify=verify_ssl)
        return cls(
            ks_session=ks_session,
            tenant_id=session['tenant_id'],
            tenant_name=session['tenant_name'])

    def validate(self):
        if self.auth.auth_ref.expires > timezone.now() + datetime.timedelta(minutes=10):
            return True

        raise OpenStackSessionExpired('OpenStack session is expired')

    def __str__(self):
        return str({k: v if k != 'password' else '***' for k, v in self.items()})


class OpenStackClient(object):
    """ Generic OpenStack client. """

    def __init__(self, session=None, verify_ssl=False, **credentials):
        self.verify_ssl = verify_ssl
        if session:
            if isinstance(session, dict):
                logger.debug('Trying to recover OpenStack session.')
                self.session = OpenStackSession.recover(session, verify_ssl=verify_ssl)
                self.session.validate()
            else:
                self.session = session
        else:
            try:
                self.session = OpenStackSession(verify_ssl=verify_ssl, **credentials)
            except AttributeError as e:
                logger.error('Failed to create OpenStack session.')
                six.reraise(OpenStackBackendError, e)

    @property
    def keystone(self):
        return keystone_client.Client(session=self.session.keystone_session)

    @property
    def nova(self):
        try:
            return nova_client.Client(session=self.session.keystone_session)
        except nova_exceptions.ClientException as e:
            logger.exception('Failed to create nova client: %s', e)
            six.reraise(OpenStackBackendError, e)

    @property
    def neutron(self):
        try:
            return neutron_client.Client(session=self.session.keystone_session)
        except neutron_exceptions.NeutronClientException as e:
            logger.exception('Failed to create neutron client: %s', e)
            six.reraise(OpenStackBackendError, e)

    @property
    def cinder(self):
        try:
            return cinder_client.Client(session=self.session.keystone_session)
        except cinder_exceptions.ClientException as e:
            logger.exception('Failed to create cinder client: %s', e)
            six.reraise(OpenStackBackendError, e)

    @property
    def glance(self):
        try:
            return glance_client.Client(session=self.session.keystone_session)
        except glance_exceptions.ClientException as e:
            logger.exception('Failed to create glance client: %s', e)
            six.reraise(OpenStackBackendError, e)

    @property
    def ceilometer(self):
        try:
            return ceilometer_client.Client('2', session=self.session.keystone_session)
        except ceilometer_exceptions.BaseException as e:
            logger.exception('Failed to create ceilometer client: %s', e)
            six.reraise(OpenStackBackendError, e)


def _update_pulled_fields(instance, imported_instance, fields):
    """ Update instance fields based on imported from backend data.

        Save changes to DB only one or more fields were changed.
    """
    modified = False
    for field in fields:
        pulled_value = getattr(imported_instance, field)
        current_value = getattr(instance, field)
        if current_value != pulled_value:
            setattr(instance, field, pulled_value)
            logger.info("%s's with uuid %s %s field updated from value '%s' to value '%s'",
                        instance.__class__.__name__, instance.uuid.hex, field, current_value, pulled_value)
            modified = True
    if modified:
        instance.save()


class OpenStackBackend(ServiceBackend):

    DEFAULTS = {
        'tenant_name': 'admin',
        'is_admin': True
    }

    def __init__(self, settings, tenant_id=None):
        self.settings = settings
        self.tenant_id = tenant_id

    def _get_cached_session_key(self, admin):
        key = 'OPENSTACK_ADMIN_SESSION' if admin else 'OPENSTACK_SESSION_%s' % self.tenant_id
        settings_key = str(self.settings.backend_url) + str(self.settings.password) + str(self.settings.username)
        hashed_settings_key = hashlib.sha256(settings_key).hexdigest()
        return '%s_%s_%s' % (self.settings.uuid.hex, hashed_settings_key, key)

    def get_client(self, name=None, admin=False):
        credentials = {
            'auth_url': self.settings.backend_url,
            'username': self.settings.username,
            'password': self.settings.password,
        }

        if self.tenant_id:
            credentials['tenant_id'] = self.tenant_id
        else:
            credentials['tenant_name'] = self.settings.get_option('tenant_name')

        # Skip cache if service settings do no exist
        if not self.settings.uuid:
            return OpenStackClient(**credentials)

        client = None
        attr_name = 'admin_session' if admin else 'session'
        key = self._get_cached_session_key(admin)
        if hasattr(self, attr_name):  # try to get client from object
            client = getattr(self, attr_name)
        elif key in cache:  # try to get session from cache
            session = cache.get(key)
            try:
                client = OpenStackClient(session=session)
            except (OpenStackSessionExpired, OpenStackAuthorizationFailed):
                pass

        if client is None:  # create new token if session is not cached or expired
            client = OpenStackClient(**credentials)
            setattr(self, attr_name, client)  # Cache client in the object
            cache.set(key, dict(client.session), 24 * 60 * 60)  # Add session to cache

        if name:
            return getattr(client, name)
        else:
            return client

    def __getattr__(self, name):
        clients = 'keystone', 'nova', 'neutron', 'cinder', 'glance', 'ceilometer'
        for client in clients:
            if name == '{}_client'.format(client):
                return self.get_client(client, admin=False)

            if name == '{}_admin_client'.format(client):
                return self.get_client(client, admin=True)

        raise AttributeError(
            "'%s' object has no attribute '%s'" % (self.__class__.__name__, name))

    def ping(self, raise_exception=False):
        try:
            self.keystone_client
        except keystone_exceptions.ClientException as e:
            if raise_exception:
                six.reraise(OpenStackBackendError, e)
            return False
        else:
            return True

    def ping_resource(self, instance):
        try:
            self.nova_client.servers.get(instance.backend_id)
        except (ConnectionError, nova_exceptions.ClientException):
            return False
        else:
            return True

    def check_admin_tenant(self):
        try:
            self.keystone_admin_client
        except keystone_exceptions.AuthorizationFailure:
            return False
        except keystone_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            return True

    def sync(self):
        self._pull_flavors()
        self._pull_images()
        self._pull_service_settings_quotas()

    def destroy(self, instance, force=False):
        instance.schedule_deletion()
        instance.save()
        send_task('openstack', 'destroy')(instance.uuid.hex, force=force)

    def start(self, instance):
        instance.schedule_starting()
        instance.save()
        send_task('openstack', 'start')(instance.uuid.hex)

    def stop(self, instance):
        instance.schedule_stopping()
        instance.save()
        send_task('openstack', 'stop')(instance.uuid.hex)

    def restart(self, instance):
        instance.schedule_restarting()
        instance.save()
        send_task('openstack', 'restart')(instance.uuid.hex)

    def get_or_create_ssh_key_for_tenant(self, key_name, fingerprint, public_key):
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

    def remove_ssh_key_from_tenant(self, tenant, key_name, fingerprint):
        nova = self.nova_client

        # There could be leftovers of key duplicates: remove them all
        keys = nova.keypairs.findall(fingerprint=fingerprint)
        for key in keys:
            # Remove only keys created with NC
            if key.name == key_name:
                nova.keypairs.delete(key)

        logger.info('Deleted ssh public key %s from backend', key_name)

    def _get_instance_state(self, instance):
        # See http://developer.openstack.org/api-ref-compute-v2.html
        nova_to_nodeconductor = {
            'ACTIVE': models.Instance.States.ONLINE,
            'BUILDING': models.Instance.States.PROVISIONING,
            # 'DELETED': models.Instance.States.DELETING,
            # 'SOFT_DELETED': models.Instance.States.DELETING,
            'ERROR': models.Instance.States.ERRED,
            'UNKNOWN': models.Instance.States.ERRED,

            'HARD_REBOOT': models.Instance.States.STOPPING,  # Or starting?
            'REBOOT': models.Instance.States.STOPPING,  # Or starting?
            'REBUILD': models.Instance.States.STARTING,  # Or stopping?

            'PASSWORD': models.Instance.States.ONLINE,
            'PAUSED': models.Instance.States.OFFLINE,

            'RESCUED': models.Instance.States.ONLINE,
            'RESIZED': models.Instance.States.OFFLINE,
            'REVERT_RESIZE': models.Instance.States.STOPPING,
            'SHUTOFF': models.Instance.States.OFFLINE,
            'STOPPED': models.Instance.States.OFFLINE,
            'SUSPENDED': models.Instance.States.OFFLINE,
            'VERIFY_RESIZE': models.Instance.States.OFFLINE,
        }
        return nova_to_nodeconductor.get(instance.status, models.Instance.States.ERRED)

    def _get_current_properties(self, model):
        return {p.backend_id: p for p in model.objects.filter(settings=self.settings)}

    def _are_rules_equal(self, backend_rule, nc_rule):
        if backend_rule['from_port'] != nc_rule.from_port:
            return False
        if backend_rule['to_port'] != nc_rule.to_port:
            return False
        if backend_rule['ip_protocol'] != nc_rule.protocol:
            return False
        if backend_rule['ip_range'].get('cidr', '') != nc_rule.cidr:
            return False
        return True

    def _are_security_groups_equal(self, backend_security_group, nc_security_group):
        if backend_security_group.name != nc_security_group.name:
            return False
        if len(backend_security_group.rules) != nc_security_group.rules.count():
            return False
        for backend_rule, nc_rule in zip(backend_security_group.rules, nc_security_group.rules.all()):
            if not self._are_rules_equal(backend_rule, nc_rule):
                return False
        return True

    def _normalize_security_group_rule(self, rule):
        if rule['ip_protocol'] is None:
            rule['ip_protocol'] = ''

        if 'cidr' not in rule['ip_range']:
            rule['ip_range']['cidr'] = '0.0.0.0/0'

        return rule

    def _wait_for_instance_status(self, server_id, nova, complete_status,
                                  error_status=None, retries=300, poll_interval=3):
        return self._wait_for_object_status(
            server_id, nova.servers.get, complete_status, error_status, retries, poll_interval)

    def _wait_for_object_status(self, obj_id, client_get_method, complete_status, error_status=None,
                                retries=30, poll_interval=3):
        complete_state_predicate = lambda o: o.status == complete_status
        if error_status is not None:
            error_state_predicate = lambda o: o.status == error_status
        else:
            error_state_predicate = lambda _: False

        for _ in range(retries):
            obj = client_get_method(obj_id)
            logger.debug('Instance %s status: "%s"' % (obj, obj.status))

            if complete_state_predicate(obj):
                return True

            if error_state_predicate(obj):
                return False

            time.sleep(poll_interval)
        else:
            return False

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

    @log_backend_action('check is volume backup deleted')
    def is_volume_backup_deleted(self, volume_backup):
        cinder = self.cinder_client
        try:
            cinder.backups.get(volume_backup.backend_id)
            return False
        except cinder_exceptions.NotFound:
            return True
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

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
            images = glance.images.list()
        except glance_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        with transaction.atomic():
            cur_images = self._get_current_properties(models.Image)
            for backend_image in images:
                if backend_image.is_public and not backend_image.deleted:
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

    @log_backend_action('push quotas for tenant')
    def push_tenant_quotas(self, tenant, quotas):
        cinder_quotas = {
            'gigabytes': self.mb2gb(quotas.get('storage')) if 'storage' in quotas else None,
            'volumes': quotas.get('volumes'),
            'snapshots': quotas.get('snapshots'),
        }
        cinder_quotas = {k: v for k, v in cinder_quotas.items() if v is not None}

        nova_quotas = {
            'instances': quotas.get('instances'),
            'cores': quotas.get('vcpu'),
            'ram': quotas.get('ram'),
        }
        nova_quotas = {k: v for k, v in nova_quotas.items() if v is not None}

        neutron_quotas = {
            'security_group': quotas.get('security_group_count'),
            'security_group_rule': quotas.get('security_group_rule_count'),
        }
        neutron_quotas = {k: v for k, v in neutron_quotas.items() if v is not None}

        try:
            if cinder_quotas:
                self.cinder_client.quotas.update(tenant.backend_id, **cinder_quotas)
            if nova_quotas:
                self.nova_client.quotas.update(tenant.backend_id, **nova_quotas)
            if neutron_quotas:
                self.neutron_client.update_quota(tenant.backend_id, {'quota': neutron_quotas})
        except Exception as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action('pull quotas for tenant')
    def pull_tenant_quotas(self, tenant):
        nova = self.nova_client
        neutron = self.neutron_client
        cinder = self.cinder_client

        try:
            nova_quotas = nova.quotas.get(tenant_id=tenant.backend_id)
            cinder_quotas = cinder.quotas.get(tenant_id=tenant.backend_id)
            neutron_quotas = neutron.show_quota(tenant_id=tenant.backend_id)['quota']
        except (nova_exceptions.ClientException,
                cinder_exceptions.ClientException,
                neutron_exceptions.NeutronClientException) as e:
            six.reraise(OpenStackBackendError, e)

        tenant.set_quota_limit('ram', nova_quotas.ram)
        tenant.set_quota_limit('vcpu', nova_quotas.cores)
        tenant.set_quota_limit('storage', self.gb2mb(cinder_quotas.gigabytes))
        tenant.set_quota_limit('snapshots', cinder_quotas.snapshots)
        tenant.set_quota_limit('volumes', cinder_quotas.volumes)
        tenant.set_quota_limit('instances', nova_quotas.instances)
        tenant.set_quota_limit('security_group_count', neutron_quotas['security_group'])
        tenant.set_quota_limit('security_group_rule_count', neutron_quotas['security_group_rule'])
        tenant.set_quota_limit('floating_ip_count', neutron_quotas['floatingip'])

        try:
            volumes = cinder.volumes.list()
            snapshots = cinder.volume_snapshots.list()
            instances = nova.servers.list()
            security_groups = nova.security_groups.list()
            floating_ips = neutron.list_floatingips(tenant_id=tenant.backend_id)['floatingips']

            flavors = {flavor.id: flavor for flavor in nova.flavors.list()}

            ram, vcpu = 0, 0
            for flavor_id in (instance.flavor['id'] for instance in instances):
                try:
                    flavor = flavors.get(flavor_id, nova.flavors.get(flavor_id))
                except nova_exceptions.NotFound:
                    logger.warning('Cannot find flavor with id %s', flavor_id)
                    continue

                ram += getattr(flavor, 'ram', 0)
                vcpu += getattr(flavor, 'vcpus', 0)

        except (nova_exceptions.ClientException,
                cinder_exceptions.ClientException,
                neutron_exceptions.NeutronClientException) as e:
            six.reraise(OpenStackBackendError, e)

        tenant.set_quota_usage('ram', ram)
        tenant.set_quota_usage('vcpu', vcpu)
        tenant.set_quota_usage('storage', sum(self.gb2mb(v.size) for v in volumes + snapshots))
        tenant.set_quota_usage('volumes', len(volumes))
        tenant.set_quota_usage('snapshots', len(snapshots))
        tenant.set_quota_usage('instances', len(instances), fail_silently=True)
        tenant.set_quota_usage('security_group_count', len(security_groups))
        tenant.set_quota_usage('security_group_rule_count', len(sum([sg.rules for sg in security_groups], [])))
        tenant.set_quota_usage('floating_ip_count', len(floating_ips))

    @log_backend_action('pull floating IPs for tenant')
    def pull_tenant_floating_ips(self, tenant):
        neutron = self.neutron_client

        nc_floating_ips = {ip.backend_id: ip for ip in tenant.floating_ips.all()}
        try:
            backend_floating_ips = {
                ip['id']: ip
                for ip in neutron.list_floatingips(tenant_id=self.tenant_id)['floatingips']
                if ip.get('floating_ip_address') and ip.get('status')
            }
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

        backend_ids = set(backend_floating_ips.keys())
        nc_ids = set(nc_floating_ips.keys())

        with transaction.atomic():
            for ip_id in nc_ids - backend_ids:
                ip = nc_floating_ips[ip_id]
                ip.delete()
                logger.info('Deleted stale floating IP port %s in database', ip.uuid)

            for ip_id in backend_ids - nc_ids:
                ip = backend_floating_ips[ip_id]
                created_ip = tenant.floating_ips.create(
                    status=ip['status'],
                    backend_id=ip['id'],
                    address=ip['floating_ip_address'],
                    backend_network_id=ip['floating_network_id'],
                    service_project_link=tenant.service_project_link
                )
                logger.info('Created new floating IP port %s in database', created_ip.uuid)

            for ip_id in nc_ids & backend_ids:
                nc_ip = nc_floating_ips[ip_id]
                backend_ip = backend_floating_ips[ip_id]
                if nc_ip.status != backend_ip['status'] or nc_ip.address != backend_ip['floating_ip_address']\
                        or nc_ip.backend_network_id != backend_ip['floating_network_id']:
                    # If key is BOOKED by NodeConductor it can be still DOWN in OpenStack
                    if not (nc_ip.status == 'BOOKED' and backend_ip['status'] == 'DOWN'):
                        nc_ip.status = backend_ip['status']
                    nc_ip.address = backend_ip['floating_ip_address']
                    nc_ip.backend_network_id = backend_ip['floating_network_id']
                    nc_ip.save()
                    logger.info('Updated existing floating IP port %s in database', nc_ip.uuid)

    @log_backend_action('pull security groups for tenant')
    def pull_tenant_security_groups(self, tenant):
        nova = self.nova_client

        try:
            backend_security_groups = nova.security_groups.list()
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        states = models.SecurityGroup.States
        # list of openstack security groups that do not exist in nc
        nonexistent_groups = []
        # list of openstack security groups that have wrong parameters in in nc
        unsynchronized_groups = []
        # list of nc security groups that do not exist in openstack
        extra_groups = tenant.security_groups.exclude(backend_id__in=[g.id for g in backend_security_groups])
        extra_groups = extra_groups.exclude(state__in=[states.CREATION_SCHEDULED, states.CREATING])

        with transaction.atomic():
            for backend_group in backend_security_groups:
                try:
                    nc_group = tenant.security_groups.get(backend_id=backend_group.id)
                    if (not self._are_security_groups_equal(backend_group, nc_group) and
                            nc_group.state not in [states.UPDATING, states.UPDATE_SCHEDULED]):
                        unsynchronized_groups.append(backend_group)
                except models.SecurityGroup.DoesNotExist:
                    nonexistent_groups.append(backend_group)

            # deleting extra security groups
            extra_groups.delete()
            if extra_groups:
                logger.debug('Deleted stale security group: %s.',
                             ' ,'.join('%s (PK: %s)' % (sg.name, sg.pk) for sg in extra_groups))

            # synchronizing unsynchronized security groups
            for backend_group in unsynchronized_groups:
                nc_security_group = tenant.security_groups.get(backend_id=backend_group.id)
                if backend_group.name != nc_security_group.name:
                    nc_security_group.name = backend_group.name
                    nc_security_group.state = StateMixin.States.OK
                    nc_security_group.save()
                self.pull_security_group_rules(nc_security_group)
                logger.debug('Updated existing security group %s (PK: %s).',
                             nc_security_group.name, nc_security_group.pk)

            # creating non-existed security groups
            for backend_group in nonexistent_groups:
                nc_security_group = tenant.security_groups.create(
                    backend_id=backend_group.id,
                    name=backend_group.name,
                    state=StateMixin.States.OK,
                    service_project_link=tenant.service_project_link,
                )
                self.pull_security_group_rules(nc_security_group)
                logger.debug('Created new security group %s (PK: %s).',
                             nc_security_group.name, nc_security_group.pk)

    def pull_security_group_rules(self, security_group):
        nova = self.nova_client
        try:
            backend_security_group = nova.security_groups.get(group_id=security_group.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        backend_rules = [
            self._normalize_security_group_rule(r)
            for r in backend_security_group.rules
        ]

        # list of openstack rules, that do not exist in nc
        nonexistent_rules = []
        # list of openstack rules, that have wrong parameters in in nc
        unsynchronized_rules = []
        # list of nc rules, that do not exist in openstack
        extra_rules = security_group.rules.exclude(backend_id__in=[r['id'] for r in backend_rules])

        with transaction.atomic():
            for backend_rule in backend_rules:
                try:
                    nc_rule = security_group.rules.get(backend_id=backend_rule['id'])
                    if not self._are_rules_equal(backend_rule, nc_rule):
                        unsynchronized_rules.append(backend_rule)
                except security_group.rules.model.DoesNotExist:
                    nonexistent_rules.append(backend_rule)

            # deleting extra rules
            # XXX: In Django >= 1.9 delete method returns number of deleted objects, so this could be optimized
            if extra_rules:
                extra_rules.delete()
                logger.info('Deleted stale security group rules in database')

            # synchronizing unsynchronized rules
            for backend_rule in unsynchronized_rules:
                security_group.rules.filter(backend_id=backend_rule['id']).update(
                    from_port=backend_rule['from_port'],
                    to_port=backend_rule['to_port'],
                    protocol=backend_rule['ip_protocol'],
                    cidr=backend_rule['ip_range']['cidr'],
                )
            if unsynchronized_rules:
                logger.debug('Updated existing security group rules in database')

            # creating non-existed rules
            for backend_rule in nonexistent_rules:
                rule = security_group.rules.create(
                    from_port=backend_rule['from_port'],
                    to_port=backend_rule['to_port'],
                    protocol=backend_rule['ip_protocol'],
                    cidr=backend_rule['ip_range']['cidr'],
                    backend_id=backend_rule['id'],
                )
                logger.info('Created new security group rule %s in database', rule.id)

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
                logger.exception('Failed to remove security group %s from instance %s',
                                 group_id, server_id)
            else:
                logger.info('Removed security group %s from instance %s',
                            group_id, server_id)

        # add missing groups
        for group_id in nc_ids - backend_ids:
            try:
                nova.servers.add_security_group(server_id, group_id)
            except nova_exceptions.ClientException:
                logger.exception('Failed to add security group %s to instance %s',
                                 group_id, server_id)
            else:
                logger.info('Added security group %s to instance %s',
                            group_id, server_id)

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
    def create_tenant(self, tenant):
        keystone = self.keystone_admin_client
        try:
            backend_tenant = keystone.tenants.create(tenant_name=tenant.name, description=tenant.description)
            tenant.backend_id = backend_tenant.id
            tenant.save(update_fields=['backend_id'])
        except keystone_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    def import_tenant(self, tenant_backend_id, service_project_link=None, save=True):
        keystone = self.keystone_admin_client
        try:
            backend_tenant = keystone.tenants.get(tenant_backend_id)
        except keystone_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        tenant = models.Tenant()
        tenant.name = backend_tenant.name
        tenant.description = backend_tenant.description
        tenant.backend_id = tenant_backend_id

        if save and service_project_link:
            tenant.service_project_link = service_project_link
            tenant.state = models.Tenant.States.OK
            tenant.save()
        return tenant

    @log_backend_action()
    def pull_tenant(self, tenant):
        import_time = timezone.now()
        imported_tenant = self.import_tenant(tenant.backend_id, save=False)

        tenant.refresh_from_db()
        # if tenant was not modified in NC database after import.
        if tenant.modified < import_time:
            _update_pulled_fields(tenant, imported_tenant, ('name', 'description'))

    @log_backend_action()
    def add_admin_user_to_tenant(self, tenant):
        """ Add user from openstack settings to new tenant """
        keystone = self.keystone_admin_client

        try:
            admin_user = keystone.users.find(name=self.settings.username)
            admin_role = keystone.roles.find(name='admin')
            try:
                keystone.roles.add_user_role(
                    user=admin_user.id,
                    role=admin_role.id,
                    tenant=tenant.backend_id)
            except keystone_exceptions.Conflict:
                pass
        except keystone_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action('add user to tenant')
    def create_tenant_user(self, tenant):
        keystone = self.keystone_client

        try:
            user = keystone.users.create(
                name=tenant.user_username,
                password=tenant.user_password,
            )
            admin_role = keystone.roles.find(name='Member')
            keystone.roles.add_user_role(
                user=user.id,
                role=admin_role.id,
                tenant=tenant.backend_id,
            )
        except keystone_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    def import_instance(self, backend_instance_id, save=True):
        tenant = models.Tenant.objects.get(backend_id=self.tenant_id)
        nova = self.nova_client
        try:
            backend_instance = nova.servers.get(backend_instance_id)
            flavor = nova.flavors.get(backend_instance.flavor['id'])
            attached_volume_ids = [v.volumeId for v in nova.volumes.get_server_volumes(backend_instance_id)]
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        # import and parse IPs.
        ips = {}
        for net_conf in backend_instance.addresses.values():
            for ip in net_conf:
                if ip['OS-EXT-IPS:type'] == 'fixed':
                    ips['internal'] = ip['addr']
                if ip['OS-EXT-IPS:type'] == 'floating':
                    ips['external'] = ip['addr']

        # import launch time.
        try:
            d = dateparse.parse_datetime(backend_instance.to_dict()['OS-SRV-USG:launched_at'])
        except (KeyError, ValueError, TypeError):
            launch_time = None
        else:
            # At the moment OpenStack does not provide any timezone info,
            # but in future it might do.
            if timezone.is_naive(d):
                launch_time = timezone.make_aware(d, timezone.utc)

        with transaction.atomic():
            # import instance volumes, or use existed if they already exist in NodeConductor.
            volumes = []
            for backend_volume_id in attached_volume_ids:
                try:
                    volumes.append(models.Volume.objects.get(tenant=tenant, backend_id=backend_volume_id))
                except models.Volume.DoesNotExist:
                    volumes.append(self.import_volume(backend_volume_id, save=save))

            # security groups should exist in NodeConductor.
            security_groups_names = [sg['name'] for sg in getattr(backend_instance, 'security_groups', [])]
            if tenant.security_groups.filter(name__in=security_groups_names).count() != len(security_groups_names):
                self.pull_tenant_security_groups(tenant)
            security_groups = []
            for name in security_groups_names:
                try:
                    security_groups.append(tenant.security_groups.get(name=name))
                except models.SecurityGroup.DoesNotExist:
                    raise OpenStackBackendError('Security group with name "%s" does not exist in NodeConductor.' % name)

            instance = models.Instance(
                name=backend_instance.name or backend_instance.id,
                tenant=tenant,
                service_project_link=tenant.service_project_link,
                key_name=backend_instance.key_name or '',
                start_time=launch_time,
                state=self._get_instance_state(backend_instance),
                created=dateparse.parse_datetime(backend_instance.created),

                flavor_name=flavor.name,
                flavor_disk=flavor.disk,
                cores=flavor.vcpus,
                ram=flavor.ram,
                disk=sum([v.size for v in volumes]),

                internal_ips=ips.get('internal', ''),
                external_ips=ips.get('external', ''),
                backend_id=backend_instance_id,
            )

            if hasattr(backend_instance, 'fault'):
                instance.error_message = backend_instance.fault['message']

            if save:
                instance.save()
                instance.volumes.add(*volumes)
                instance.security_groups.add(*security_groups)

        return instance

    def get_resources_for_import(self, resource_type=None, tenant=None):
        if tenant:
            if resource_type == SupportedServices.get_name_for_model(models.Instance):
                return self.get_instances_for_import(tenant)
            elif resource_type == SupportedServices.get_name_for_model(models.Volume):
                return self.get_volumes_for_import(tenant)
        elif self.settings.get_option('is_admin'):
            return self.get_tenants_for_import()
        else:
            return []

    def get_instances_for_import(self, tenant):
        cur_instances = set(tenant.instances.values_list('backend_id', flat=True))
        nova = tenant.get_backend().nova_client
        try:
            instances = nova.servers.list()
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        return [{
            'id': instance.id,
            'name': instance.name or instance.id,
            'runtime_state': instance.status,
            'type': SupportedServices.get_name_for_model(models.Instance)
        } for instance in instances
            if instance.id not in cur_instances and
            self._get_instance_state(instance) != models.Instance.States.ERRED]

    def get_volumes_for_import(self, tenant):
        cur_volumes = set(tenant.volumes.values_list('backend_id', flat=True))
        cinder = tenant.get_backend().cinder_client
        try:
            volumes = cinder.volumes.list()
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        return [{
            'id': volume.id,
            'name': volume.name,
            'size': self.gb2mb(volume.size),
            'runtime_state': volume.status,
            'type': SupportedServices.get_name_for_model(models.Volume)
        } for volume in volumes if volume.id not in cur_volumes]

    def get_tenants_for_import(self):
        cur_tenants = set(models.Tenant.objects.filter(
            service_project_link__service__settings=self.settings
        ).values_list('backend_id', flat=True))
        keystone = self.keystone_admin_client
        try:
            tenants = keystone.tenants.list()
        except keystone_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        return [{
            'id': tenant.id,
            'name': tenant.name,
            'description': tenant.description,
            'type': SupportedServices.get_name_for_model(models.Tenant)
        } for tenant in tenants if tenant.id not in cur_tenants]

    def get_managed_resources(self):
        return []

    @log_backend_action()
    def create_instance(self, instance, backend_flavor_id=None,
                        skip_external_ip_assignment=False, public_key=None, floating_ip_uuid=None):
        logger.info('About to create instance %s', instance.uuid)

        nova = self.nova_client
        tenant = instance.tenant

        self._check_tenant_network(tenant)

        floating_ip = None
        if floating_ip_uuid:
            try:
                floating_ip = tenant.floating_ips.get(uuid=floating_ip_uuid)
            except ObjectDoesNotExist:
                raise OpenStackBackendError('Floating IP with id %s does not exist.', floating_ip_uuid)
        elif not skip_external_ip_assignment:
            if tenant.external_network_id:
                floating_ip = self._get_or_create_floating_ip(tenant)
            else:
                logger.warning("Assignment of a floating IP is not possible for instance %s with no external network",
                               instance.uuid)

        if floating_ip:
            floating_ip.status = 'BOOKED'
            floating_ip.save(update_fields=['status'])

        try:
            backend_flavor = nova.flavors.get(backend_flavor_id)

            # instance key name and fingerprint are optional
            if instance.key_name:
                backend_public_key = self.get_or_create_ssh_key_for_tenant(
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
                    {'net-id': tenant.internal_network_id}
                ],
                key_name=backend_public_key.name if backend_public_key is not None else None,
                security_groups=security_group_ids,
            )
            availability_zone = tenant.availability_zone
            if availability_zone:
                server_create_parameters['availability_zone'] = availability_zone
            if instance.user_data:
                server_create_parameters['userdata'] = instance.user_data

            server = nova.servers.create(**server_create_parameters)

            instance.backend_id = server.id
            instance.save()

            if not self._wait_for_instance_status(server.id, nova, 'ACTIVE', 'ERROR'):
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
                self.assign_floating_ip_to_instance(instance, floating_ip)
            else:
                logger.info("Skipping floating IP assignment for instance %s", instance.uuid)

            backend_security_groups = server.list_security_group()
            for bsg in backend_security_groups:
                if instance.security_groups.filter(name=bsg.name).exists():
                    continue
                try:
                    security_group = tenant.security_groups.get(name=bsg.name)
                except models.SecurityGroup.DoesNotExist:
                    logger.error(
                        'Tenant %s (PK: %s) does not have security group "%s", but its instance %s (PK: %s) has.' %
                        (tenant, tenant.pk, bsg.name, instance, instance.pk)
                    )
                else:
                    instance.security_groups.add(security_group)

        except nova_exceptions.ClientException as e:
            logger.exception("Failed to provision instance %s", instance.uuid)
            six.reraise(OpenStackBackendError, e)
        else:
            logger.info("Successfully provisioned instance %s", instance.uuid)

    @log_backend_action()
    def update_instance(self, instance):
        nova = self.nova_client
        try:
            nova.servers.update(instance.backend_id, name=instance.name)
        except keystone_exceptions.NotFound as e:
            logger.error('Instance with id %s does not exist', instance.backend_id)
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def pull_instance(self, instance):
        import_time = timezone.now()
        imported_instance = self.import_instance(instance.backend_id, save=False)

        instance.refresh_from_db()
        if instance.modified < import_time:
            # XXX: It is not right to update instance state here, should be fixed in NC-1207.
            # We should update runtime_state here and state in corresponding task.
            update_fields = ('ram', 'cores', 'disk', 'internal_ips',
                             'external_ips', 'state', 'error_message')
            _update_pulled_fields(instance, imported_instance, update_fields)

    @log_backend_action()
    def cleanup_tenant(self, tenant, dryrun=True):
        if not tenant.backend_id:
            # This method will remove all floating IPs if tenant `backend_id` is not defined.
            raise OpenStackBackendError('Method `cleanup_tenant` should not be called if tenant has no backend_id')
        # floatingips
        neutron = self.neutron_admin_client
        floatingips = neutron.list_floatingips(tenant_id=tenant.backend_id)
        if floatingips:
            for floatingip in floatingips['floatingips']:
                logger.info("Deleting floating IP %s from tenant %s", floatingip['id'], tenant.backend_id)
                if not dryrun:
                    try:
                        neutron.delete_floatingip(floatingip['id'])
                    except neutron_exceptions.NotFound:
                        logger.debug("Floating IP %s is already gone from tenant %s", floatingip['id'], tenant.backend_id)

        # ports
        ports = neutron.list_ports(tenant_id=tenant.backend_id)
        if ports:
            for port in ports['ports']:
                logger.info("Deleting port %s interface_router from tenant %s", port['id'], tenant.backend_id)
                if not dryrun:
                    try:
                        neutron.remove_interface_router(port['device_id'], {'port_id': port['id']})
                    except neutron_exceptions.NotFound:
                        logger.debug("Port %s interface_router is already gone from tenant %s", port['id'], tenant.backend_id)

                logger.info("Deleting port %s from tenant %s", port['id'], tenant.backend_id)
                if not dryrun:
                    try:
                        neutron.delete_port(port['id'])
                    except neutron_exceptions.NotFound:
                        logger.debug("Port %s is already gone from tenant %s", port['id'], tenant.backend_id)

        # routers
        routers = neutron.list_routers(tenant_id=tenant.backend_id)
        if routers:
            for router in routers['routers']:
                logger.info("Deleting router %s from tenant %s", router['id'], tenant.backend_id)
                if not dryrun:
                    try:
                        neutron.delete_router(router['id'])
                    except neutron_exceptions.NotFound:
                        logger.debug("Router %s is already gone from tenant %s", router['id'], tenant.backend_id)

        # networks
        networks = neutron.list_networks(tenant_id=tenant.backend_id)
        if networks:
            for network in networks['networks']:
                if network['router:external']:
                    continue
                for subnet in network['subnets']:
                    logger.info("Deleting subnetwork %s from tenant %s", subnet, tenant.backend_id)
                    if not dryrun:
                        try:
                            neutron.delete_subnet(subnet)
                        except neutron_exceptions.NotFound:
                            logger.info("Subnetwork %s is already gone from tenant %s", subnet, tenant.backend_id)

                logger.info("Deleting network %s from tenant %s", network['id'], tenant.backend_id)
                if not dryrun:
                    try:
                        neutron.delete_network(network['id'])
                    except neutron_exceptions.NotFound:
                        logger.debug("Network %s is already gone from tenant %s", network['id'], tenant.backend_id)

        # security groups
        nova = self.nova_client
        sgroups = nova.security_groups.list()
        for sgroup in sgroups:
            logger.info("Deleting security group %s from tenant %s", sgroup.id, tenant.backend_id)
            if not dryrun:
                try:
                    sgroup.delete()
                except nova_exceptions.ClientException:
                    logger.debug("Cannot delete %s from tenant %s", sgroup, tenant.backend_id)

        # servers (instances)
        servers = nova.servers.list()
        for server in servers:
            logger.info("Deleting server %s from tenant %s", server.id, tenant.backend_id)
            if not dryrun:
                server.delete()

        # snapshots
        cinder = self.cinder_client
        snapshots = cinder.volume_snapshots.list()
        for snapshot in snapshots:
            logger.info("Deleting snapshots %s from tenant %s", snapshot.id, tenant.backend_id)
            if not dryrun:
                snapshot.delete()

        # volumes
        volumes = cinder.volumes.list()
        for volume in volumes:
            logger.info("Deleting volume %s from tenant %s", volume.id, tenant.backend_id)
            if not dryrun:
                volume.delete()

        # user
        keystone = self.keystone_client
        try:
            user = keystone.users.find(name=tenant.user_username)
            logger.info('Deleting user %s that was connected to tenant %s', user.name, tenant.backend_id)
            if not dryrun:
                user.delete()
        except keystone_exceptions.ClientException as e:
            logger.error('Cannot delete user %s from tenant %s. Error: %s', tenant.user_username, tenant.backend_id, e)

        # tenant
        keystone = self.keystone_admin_client
        logger.info("Deleting tenant %s", tenant.backend_id)
        if not dryrun:
            try:
                keystone.tenants.delete(tenant.backend_id)
            except keystone_exceptions.ClientException as e:
                six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def resize_instance(self, instance, flavor_id):
        nova = self.nova_client
        try:
            nova.servers.resize(instance.backend_id, flavor_id, 'MANUAL')
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def confirm_instance_resize(self, instance):
        nova = self.nova_client
        try:
            nova.servers.confirm_resize(instance.backend_id)
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
    def attach_volume(self, volume, device=None):
        nova = self.nova_client
        try:
            nova.volumes.create_server_volume(volume.instance.backend_id, volume.backend_id, device=device)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

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
            volume.save()

    @log_backend_action()
    def extend_volume(self, volume, new_size):
        cinder = self.cinder_client
        try:
            cinder.volumes.extend(volume.backend_id, self.mb2gb(new_size))
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    def _push_security_group_rules(self, security_group):
        """ Helper method  """
        nova = self.nova_client
        backend_security_group = nova.security_groups.get(group_id=security_group.backend_id)
        backend_rules = {
            rule['id']: self._normalize_security_group_rule(rule)
            for rule in backend_security_group.rules
        }

        # list of nc rules, that do not exist in openstack
        nonexistent_rules = []
        # list of nc rules, that have wrong parameters in in openstack
        unsynchronized_rules = []
        # list of os rule ids, that exist in openstack and do not exist in nc
        extra_rule_ids = backend_rules.keys()

        for nc_rule in security_group.rules.all():
            if nc_rule.backend_id not in backend_rules:
                nonexistent_rules.append(nc_rule)
            else:
                backend_rule = backend_rules[nc_rule.backend_id]
                if not self._are_rules_equal(backend_rule, nc_rule):
                    unsynchronized_rules.append(nc_rule)
                extra_rule_ids.remove(nc_rule.backend_id)

        # deleting extra rules
        for backend_rule_id in extra_rule_ids:
            logger.debug('About to delete security group rule with id %s in backend', backend_rule_id)
            try:
                nova.security_group_rules.delete(backend_rule_id)
            except nova_exceptions.ClientException:
                logger.exception('Failed to remove rule with id %s from security group %s in backend',
                                 backend_rule_id, security_group)
            else:
                logger.info('Security group rule with id %s successfully deleted in backend', backend_rule_id)

        # deleting unsynchronized rules
        for nc_rule in unsynchronized_rules:
            logger.debug('About to delete security group rule with id %s', nc_rule.backend_id)
            try:
                nova.security_group_rules.delete(nc_rule.backend_id)
            except nova_exceptions.ClientException:
                logger.exception('Failed to remove rule with id %s from security group %s in backend',
                                 nc_rule.backend_id, security_group)
            else:
                logger.info('Security group rule with id %s successfully deleted in backend',
                            nc_rule.backend_id)

        # creating nonexistent and unsynchronized rules
        for nc_rule in unsynchronized_rules + nonexistent_rules:
            logger.debug('About to create security group rule with id %s in backend', nc_rule.id)
            try:
                # The database has empty strings instead of nulls
                if nc_rule.protocol == '':
                    nc_rule_protocol = None
                else:
                    nc_rule_protocol = nc_rule.protocol

                nova.security_group_rules.create(
                    parent_group_id=security_group.backend_id,
                    ip_protocol=nc_rule_protocol,
                    from_port=nc_rule.from_port,
                    to_port=nc_rule.to_port,
                    cidr=nc_rule.cidr,
                )
            except nova_exceptions.ClientException as e:
                logger.exception('Failed to create rule %s for security group %s in backend',
                                 nc_rule, security_group)
                six.reraise(OpenStackBackendError, e)
            else:
                logger.info('Security group rule with id %s successfully created in backend', nc_rule.id)

    @log_backend_action()
    def create_security_group(self, security_group):
        nova = self.nova_client
        try:
            backend_security_group = nova.security_groups.create(name=security_group.name, description='')
            security_group.backend_id = backend_security_group.id
            security_group.save()
            self._push_security_group_rules(security_group)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_security_group(self, security_group):
        nova = self.nova_client
        try:
            nova.security_groups.delete(security_group.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def update_security_group(self, security_group):
        nova = self.nova_client
        try:
            backend_security_group = nova.security_groups.find(id=security_group.backend_id)
            if backend_security_group.name != security_group.name:
                nova.security_groups.update(
                    backend_security_group, name=security_group.name, description='')
            self._push_security_group_rules(security_group)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action('create external network for tenant')
    def create_external_network(self, tenant, neutron, network_ip, network_prefix,
                                vlan_id=None, vxlan_id=None, ips_count=None):
        if tenant.external_network_id:
            self.connect_tenant_to_external_network(tenant, tenant.external_network_id)

        neutron = self.neutron_admin_client

        # External network creation
        network_name = 'nc-{0}-ext-net'.format(uuid.uuid4().hex)
        network = {
            'name': network_name,
            'tenant_id': tenant.backend_id,
            'router:external': True,
            # XXX: provider:physical_network should be configurable.
            'provider:physical_network': 'physnet1'
        }

        if vlan_id:
            network['provider:network_type'] = 'vlan'
            network['provider:segmentation_id'] = vlan_id
        elif vxlan_id:
            network['provider:network_type'] = 'vxlan'
            network['provider:segmentation_id'] = vxlan_id
        else:
            raise OpenStackBackendError('VLAN or VXLAN ID should be provided.')

        create_response = neutron.create_network({'networks': [network]})
        network_id = create_response['networks'][0]['id']
        logger.info('External network with name %s has been created.', network_name)
        tenant.external_network_id = network_id
        tenant.save(update_fields=['external_network_id'])

        # Subnet creation
        subnet_name = '{0}-sn01'.format(network_name)
        cidr = '{0}/{1}'.format(network_ip, network_prefix)

        subnet_data = {
            'network_id': tenant.external_network_id,
            'tenant_id': tenant.backend_id,
            'cidr': cidr,
            'name': subnet_name,
            'ip_version': 4,
            'enable_dhcp': False,
        }
        create_response = neutron.create_subnet({'subnets': [subnet_data]})
        logger.info('Subnet with name %s has been created.', subnet_name)

        # Router creation
        self.get_or_create_router(network_name, create_response['subnets'][0]['id'])

        # Floating IPs creation
        floating_ip = {
            'floating_network_id': tenant.external_network_id,
        }

        if vlan_id is not None and ips_count is not None:
            for i in range(ips_count):
                ip = neutron.create_floatingip({'floatingip': floating_ip})['floatingip']
                logger.info('Floating ip %s for external network %s has been created.',
                            ip['floating_ip_address'], network_name)

        return tenant.external_network_id

    @log_backend_action()
    def detect_external_network(self, tenant):
        neutron = self.neutron_client
        try:
            routers = neutron.list_routers(tenant_id=tenant.backend_id)['routers']
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)
        if bool(routers):
            router = routers[0]
        else:
            logger.warning('Tenant %s (PK: %s) does not have connected routers.', tenant, tenant.pk)
            return

        ext_gw = router.get('external_gateway_info', {})
        if ext_gw and 'network_id' in ext_gw:
            tenant.external_network_id = ext_gw['network_id']
            tenant.save()
            logger.info('Found and set external network with id %s for tenant %s (PK: %s)',
                        ext_gw['network_id'], tenant, tenant.pk)

    @log_backend_action('delete tenant external network')
    def delete_external_network(self, tenant):
        neutron = self.neutron_admin_client

        try:
            floating_ips = neutron.list_floatingips(
                floating_network_id=tenant.external_network_id)['floatingips']

            for ip in floating_ips:
                neutron.delete_floatingip(ip['id'])
                logger.info('Floating IP with id %s has been deleted.', ip['id'])

            ports = neutron.list_ports(network_id=tenant.external_network_id)['ports']
            for port in ports:
                neutron.remove_interface_router(port['device_id'], {'port_id': port['id']})
                logger.info('Port with id %s has been deleted.', port['id'])

            subnets = neutron.list_subnets(network_id=tenant.external_network_id)['subnets']
            for subnet in subnets:
                neutron.delete_subnet(subnet['id'])
                logger.info('Subnet with id %s has been deleted.', subnet['id'])

            neutron.delete_network(tenant.external_network_id)
            logger.info('External network with id %s has been deleted.', tenant.external_network_id)
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            tenant.external_network_id = ''
            tenant.save()

    @log_backend_action('create internal network for tenant')
    def create_internal_network(self, tenant):
        neutron = self.neutron_admin_client

        network_name = '{0}-int-net'.format(tenant.name)
        try:
            network = {
                'name': network_name,
                'tenant_id': self.tenant_id,
            }

            create_response = neutron.create_network({'networks': [network]})
            internal_network_id = create_response['networks'][0]['id']

            subnet_name = 'nc-{0}-subnet01'.format(network_name)

            logger.info('Creating subnet %s for tenant "%s" (PK: %s).', subnet_name, tenant.name, tenant.pk)
            subnet_data = {
                'network_id': internal_network_id,
                'tenant_id': tenant.backend_id,
                'cidr': '192.168.42.0/24',
                'allocation_pools': [
                    {
                        'start': '192.168.42.10',
                        'end': '192.168.42.250'
                    }
                ],
                'name': subnet_name,
                'ip_version': 4,
                'enable_dhcp': True,
            }
            create_response = neutron.create_subnet({'subnets': [subnet_data]})
            self.get_or_create_router(network_name, create_response['subnets'][0]['id'])
        except neutron_exceptions.NeutronException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            tenant.internal_network_id = internal_network_id
            tenant.save(update_fields=['internal_network_id'])

    def _check_tenant_network(self, tenant):
        neutron = self.neutron_client
        # verify if the internal network to connect to exists
        try:
            neutron.show_network(tenant.internal_network_id)
        except neutron_exceptions.NeutronClientException as e:
            logger.exception('Internal network with id of %s was not found',
                             tenant.internal_network_id)
            six.reraise(OpenStackBackendError, e)

    def _get_or_create_floating_ip(self, tenant):
        # TODO: check availability and quota
        if not tenant.floating_ips.filter(
            status='DOWN',
            backend_network_id=tenant.external_network_id
        ).exists():
            self.allocate_floating_ip_address(tenant)
        return tenant.floating_ips.filter(
            status='DOWN',
            backend_network_id=tenant.external_network_id
        ).first()

    @log_backend_action('allocate floating IP for tenant')
    def allocate_floating_ip_address(self, tenant):
        neutron = self.neutron_client
        try:
            ip_address = neutron.create_floatingip({
                'floatingip': {
                    'floating_network_id': tenant.external_network_id,
                    'tenant_id': tenant.backend_id,
                }
            })['floatingip']
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            tenant.floating_ips.create(
                status='DOWN',
                address=ip_address['floating_ip_address'],
                backend_id=ip_address['id'],
                backend_network_id=ip_address['floating_network_id'],
                service_project_link=tenant.service_project_link
            )

    @log_backend_action()
    def assign_floating_ip_to_instance(self, instance, floating_ip):
        logger.debug('About to assign floating IP %s to the instance with id %s',
                     floating_ip.address, instance.uuid)

        nova = self.nova_client
        try:
            nova.servers.add_floating_ip(
                server=instance.backend_id,
                address=floating_ip.address,
                fixed_address=instance.internal_ips
            )
        except nova_exceptions.ClientException as e:
            logger.exception('Failed to assign floating IP %s to the instance with id %s',
                             floating_ip.address, instance.uuid)

            logger.info('Releasing booked floating IP %s', floating_ip.address)
            floating_ip.status = 'DOWN'
            floating_ip.save(update_fields=['status'])

            six.reraise(OpenStackBackendError, e)
        else:
            floating_ip.status = 'ACTIVE'
            floating_ip.save(update_fields=['status'])

            instance.external_ips = floating_ip.address
            instance.save(update_fields=['external_ips'])

            logger.info('Floating IP %s was successfully assigned to the instance with id %s.',
                        floating_ip.address, instance.uuid)

    @log_backend_action()
    def connect_tenant_to_external_network(self, tenant, external_network_id):
        neutron = self.neutron_admin_client
        logger.debug('About to create external network for tenant "%s" (PK: %s)', tenant.name, tenant.pk)

        try:
            # check if the network actually exists
            response = neutron.show_network(external_network_id)
        except neutron_exceptions.NeutronClientException as e:
            logger.exception('External network %s does not exist. Stale data in database?', external_network_id)
            six.reraise(OpenStackBackendError, e)

        network_name = response['network']['name']
        subnet_id = response['network']['subnets'][0]
        # XXX: refactor function call, split get_or_create_router into more fine grained
        self.get_or_create_router(network_name, subnet_id,
                                  external=True, network_id=response['network']['id'])

        tenant.external_network_id = external_network_id
        tenant.save()

        logger.info('Router between external network %s and tenant %s was successfully created',
                    external_network_id, tenant.backend_id)

        return external_network_id

    def get_or_create_router(self, network_name, subnet_id, external=False, network_id=None):
        neutron = self.neutron_admin_client
        tenant_id = self.tenant_id
        router_name = '{0}-router'.format(network_name)

        try:
            routers = neutron.list_routers(tenant_id=tenant_id)['routers']
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

        if routers:
            logger.info('Router(s) in tenant with id %s already exist(s).', tenant_id)
            router = routers[0]
        else:
            try:
                router = neutron.create_router({'router': {'name': router_name, 'tenant_id': tenant_id}})['router']
                logger.info('Router %s has been created.', router['name'])
            except neutron_exceptions.NeutronClientException as e:
                six.reraise(OpenStackBackendError, e)

        try:
            if not external:
                ports = neutron.list_ports(device_id=router['id'], tenant_id=tenant_id)['ports']
                if not ports:
                    neutron.add_interface_router(router['id'], {'subnet_id': subnet_id})
                    logger.info('Internal subnet %s was connected to the router %s.', subnet_id, router_name)
                else:
                    logger.info('Internal subnet %s is already connected to the router %s.', subnet_id, router_name)
            else:
                if (not router.get('external_gateway_info') or
                        router['external_gateway_info'].get('network_id') != network_id):
                    neutron.add_gateway_router(router['id'], {'network_id': network_id})
                    logger.info('External network %s was connected to the router %s.', network_id, router_name)
                else:
                    logger.info('External network %s is already connected to router %s.', network_id, router_name)
        except neutron_exceptions.NeutronClientException as e:
            logger.warning(e)

        return router['id']

    @log_backend_action()
    def start_instance(self, instance):
        nova = self.nova_client
        try:
            backend_instance = nova.servers.find(id=instance.backend_id)
            backend_instance_state = self._get_instance_state(backend_instance)

            if backend_instance_state == models.Instance.States.ONLINE:
                logger.warning('Instance %s is already started', instance.uuid)
                return

            nova.servers.start(instance.backend_id)

            if not self._wait_for_instance_status(instance.backend_id, nova, 'ACTIVE'):
                raise OpenStackBackendError('Timed out waiting for instance %s to start' % instance.uuid)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def stop_instance(self, instance):
        nova = self.nova_client
        try:
            backend_instance = nova.servers.find(id=instance.backend_id)
            backend_instance_state = self._get_instance_state(backend_instance)

            if backend_instance_state == models.Instance.States.OFFLINE:
                logger.warning('Instance %s is already stopped', instance.uuid)
                return

            nova.servers.stop(instance.backend_id)

            if not self._wait_for_instance_status(instance.backend_id, nova, 'SHUTOFF'):
                raise OpenStackBackendError('Timed out waiting for instance %s to stop' % instance.uuid)
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

            if not self._wait_for_instance_status(instance.backend_id, nova, 'ACTIVE', retries=80):
                raise OpenStackBackendError('Timed out waiting for instance %s to restart' % instance.uuid)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_instance(self, instance):
        nova = self.nova_client
        try:
            nova.servers.delete(instance.backend_id)
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        if instance.tenant.floating_ips.filter(address=instance.external_ips).update(status='DOWN'):
            logger.info('Successfully released floating ip %s from instance %s',
                        instance.external_ips, instance.uuid)
        instance.decrease_backend_quotas_usage()

    @log_backend_action()
    def pull_instance_volumes(self, instance):
        for volume in instance.volumes.all():
            if self.is_volume_deleted(volume):
                with transaction.atomic():
                    volume.decrease_backend_quotas_usage()
                    volume.delete()

    @log_backend_action()
    def update_tenant(self, tenant):
        keystone = self.keystone_admin_client
        try:
            keystone.tenants.update(tenant.backend_id, name=tenant.name, description=tenant.description)
        except keystone_exceptions.NotFound as e:
            logger.error('Tenant with id %s does not exist', tenant.backend_id)
            six.reraise(OpenStackBackendError, e)

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
        # TODO: set backend volume metadata if it is defined in NC.
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
    def pull_volume_runtime_state(self, volume):
        cinder = self.cinder_client
        try:
            backend_volume = cinder.volumes.get(volume.backend_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        if backend_volume.status != volume.runtime_state:
            volume.runtime_state = backend_volume.status
            volume.save(update_fields=['runtime_state'])

    @log_backend_action()
    def update_volume(self, volume):
        # TODO: add metadata update
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

    def import_volume(self, backend_volume_id, save=True):
        """ Restore NC Volume instance based on backend data. """
        cinder = self.cinder_client
        try:
            backend_volume = cinder.volumes.get(backend_volume_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        tenant = models.Tenant.objects.get(backend_id=self.tenant_id)
        spl = tenant.service_project_link
        volume = models.Volume(
            name=backend_volume.name,
            description=backend_volume.description or '',
            size=self.gb2mb(backend_volume.size),
            metadata=backend_volume.metadata,
            backend_id=backend_volume_id,
            type=backend_volume.volume_type or '',
            bootable=backend_volume.bootable == 'true',
            tenant=tenant,
            runtime_state=backend_volume.status,
            service_project_link=spl,
            state=models.Volume.States.OK,
        )
        if hasattr(backend_volume, 'volume_image_metadata'):
            volume.image_metadata = backend_volume.volume_image_metadata
            try:
                volume.image = models.Image.objects.get(
                    settings=spl.service.settings, backend_id=volume.image_metadata['image_id'])
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
    def pull_volume(self, volume):
        import_time = timezone.now()
        imported_volume = self.import_volume(volume.backend_id, save=False)

        volume.refresh_from_db()
        if volume.modified < import_time:
            update_fields = ('name', 'description', 'size', 'metadata', 'type', 'bootable', 'runtime_state')
            _update_pulled_fields(volume, imported_volume, update_fields)

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

    def import_snapshot(self, backend_snapshot_id, save=True):
        """ Restore NC Snapshot instance based on backend data. """
        cinder = self.cinder_client
        try:
            backend_snapshot = cinder.volume_snapshots.get(backend_snapshot_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        tenant = models.Tenant.objects.get(backend_id=self.tenant_id)
        spl = tenant.service_project_link
        snapshot = models.Snapshot(
            name=backend_snapshot.name,
            description=backend_snapshot.description or '',
            size=self.gb2mb(backend_snapshot.size),
            metadata=backend_snapshot.metadata,
            backend_id=backend_snapshot_id,
            tenant=tenant,
            runtime_state=backend_snapshot.status,
            service_project_link=spl,
            state=models.Snapshot.States.OK,
        )
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
            _update_pulled_fields(snapshot, imported_snapshot, update_fields)

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
        # TODO: add metadata update
        cinder = self.cinder_client
        try:
            cinder.volume_snapshots.update(
                snapshot.backend_id, name=snapshot.name, description=snapshot.description)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def create_volume_backup(self, volume_backup):
        cinder = self.cinder_client
        try:
            backend_volume_backup = cinder.backups.create(
                volume_id=volume_backup.source_volume.backend_id,
                name=volume_backup.name,
                description=volume_backup.description,
                container=volume_backup.tenant.backend_id,
            )
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        volume_backup.backend_id = backend_volume_backup.id
        volume_backup.runtime_state = backend_volume_backup.status
        volume_backup.save()
        return volume_backup

    @log_backend_action()
    def pull_volume_backup_record(self, volume_backup):
        cinder = self.cinder_client
        try:
            backend_record = cinder.backups.export_record(volume_backup.backend_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        record = volume_backup.record or models.VolumeBackupRecord()
        record.service = backend_record['backup_service']
        # Store encoded details to have more information about record for debugging.
        record.details = json.loads(base64.b64decode(backend_record['backup_url']))
        record.save()
        volume_backup.record = record
        volume_backup.save(update_fields=['record'])
        return volume_backup

    @log_backend_action()
    def pull_volume_backup_runtime_state(self, volume_backup):
        cinder = self.cinder_client
        try:
            backend_volume_backup = cinder.backups.get(volume_backup.backend_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        if backend_volume_backup.status != volume_backup.runtime_state:
            volume_backup.runtime_state = backend_volume_backup.status
            volume_backup.save(update_fields=['runtime_state'])
        return volume_backup

    @log_backend_action()
    def delete_volume_backup(self, volume_backup):
        cinder = self.cinder_client
        try:
            cinder.backups.delete(volume_backup.backend_id)
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)
        if volume_backup.record:
            volume_backup.record.delete()
            volume_backup.decrease_backend_quotas_usage()

    @log_backend_action()
    def import_volume_backup_from_record(self, volume_backup):
        """ Create volume backup on backend based on its record """
        cinder = self.cinder_client
        try:
            imported_record = cinder.backups.import_record(
                volume_backup.record.service,
                base64.b64encode(json.dumps(volume_backup.record.details))
            )
        except (cinder_exceptions.ClientException, KeyError) as e:
            six.reraise(OpenStackBackendError, e)
        volume_backup.backend_id = imported_record['id']
        volume_backup.save()
        return volume_backup

    @log_backend_action()
    def restore_volume_backup(self, volume_backup, volume):
        cinder = self.cinder_client
        try:
            cinder.restores.restore(volume_id=volume.backend_id, backup_id=volume_backup.backend_id)
        except (cinder_exceptions.ClientException, KeyError) as e:
            six.reraise(OpenStackBackendError, e)
        return volume_backup

    def _get_meters_file_name(self, model_class):
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'meters')
        return {
            models.Instance: os.path.join(base, 'instance.json'),
            models.Volume: os.path.join(base, 'volume.json'),
            models.Snapshot: os.path.join(base, 'snapshot.json'),
        }[model_class]

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

    def _pull_service_settings_quotas(self):
        if isinstance(self.settings.scope, models.Tenant):
            tenant = self.settings.scope
            self.pull_tenant_quotas(tenant)
            self._copy_tenant_quota_to_settings(tenant)
            return
        nova = self.nova_admin_client

        try:
            stats = nova.hypervisor_stats.statistics()
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        self.settings.set_quota_limit(self.settings.Quotas.openstack_vcpu, stats.vcpus)
        self.settings.set_quota_usage(self.settings.Quotas.openstack_vcpu, stats.vcpus_used)

        self.settings.set_quota_limit(self.settings.Quotas.openstack_ram, stats.memory_mb)
        self.settings.set_quota_usage(self.settings.Quotas.openstack_ram, stats.memory_mb_used)

        self.settings.set_quota_usage(self.settings.Quotas.openstack_storage, self.get_storage_usage())

    def get_storage_usage(self):
        cinder = self.cinder_admin_client

        try:
            volumes = cinder.volumes.list()
            snapshots = cinder.volume_snapshots.list()
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        storage = sum(self.gb2mb(v.size) for v in volumes + snapshots)
        return storage

    def _copy_tenant_quota_to_settings(self, tenant):
        quotas = tenant.quotas.values('name', 'limit', 'usage')
        limits = {quota['name']: quota['limit'] for quota in quotas}
        usages = {quota['name']: quota['usage'] for quota in quotas}

        for resource in ('vcpu', 'ram', 'storage'):
            quota_name = 'openstack_%s' % resource
            self.settings.set_quota_limit(quota_name, limits[resource])
            self.settings.set_quota_usage(quota_name, usages[resource])

    def get_stats(self):
        tenants = models.Tenant.objects.filter(service_project_link__service__settings=self.settings)
        quota_names = ('vcpu', 'ram', 'storage')
        quota_values = models.Tenant.get_sum_of_quotas_as_dict(
            tenants, quota_names=quota_names, fields=['limit'])
        quota_stats = {
            'vcpu_quota': quota_values.get('vcpu', -1.0),
            'ram_quota': quota_values.get('ram', -1.0),
            'storage_quota': quota_values.get('storage', -1.0)
        }

        stats = {}
        for quota in self.settings.quotas.all():
            name = quota.name.replace('openstack_', '')
            if name not in quota_names:
                continue
            stats[name] = quota.limit
            stats[name + '_usage'] = quota.usage
        stats.update(quota_stats)
        return stats
