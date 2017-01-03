import logging
import uuid

from django.db import transaction
from django.utils import six, timezone

from cinderclient import exceptions as cinder_exceptions
from glanceclient import exc as glance_exceptions
from keystoneclient import exceptions as keystone_exceptions
from neutronclient.client import exceptions as neutron_exceptions
from novaclient import exceptions as nova_exceptions

from nodeconductor.core.models import StateMixin
from nodeconductor.structure import log_backend_action, SupportedServices

from nodeconductor_openstack.openstack_base.backend import (
    OpenStackBackendError, BaseOpenStackBackend, update_pulled_fields)
from . import models


logger = logging.getLogger(__name__)


class OpenStackBackend(BaseOpenStackBackend):

    DEFAULTS = {
        'tenant_name': 'admin',
        'is_admin': True,
    }

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
        for quota_name, limit in self.get_tenant_quotas_limits(tenant.backend_id).items():
            tenant.set_quota_limit(quota_name, limit)
        for quota_name, usage in self.get_tenant_quotas_usage(tenant.backend_id).items():
            tenant.set_quota_usage(quota_name, usage, fail_silently=True)

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
            update_pulled_fields(tenant, imported_tenant, ('name', 'description'))

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
            try:
                role = keystone.roles.find(name='Member')
            except keystone_exceptions.NotFound:
                role = keystone.roles.find(name='_member_')
            keystone.roles.add_user_role(
                user=user.id,
                role=role.id,
                tenant=tenant.backend_id,
            )
        except keystone_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

    def get_resources_for_import(self, resource_type=None):
        if self.settings.get_option('is_admin'):
            return self.get_tenants_for_import()
        else:
            return []

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
    def delete_tenant_floating_ips(self, tenant):
        if not tenant.backend_id:
            # This method will remove all floating IPs if tenant `backend_id` is not defined.
            raise OpenStackBackendError('This method should not be called if tenant has no backend_id')

        neutron = self.neutron_admin_client

        try:
            floatingips = neutron.list_floatingips(tenant_id=tenant.backend_id)
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

        for floatingip in floatingips.get('floatingips', []):
            logger.info("Deleting floating IP %s from tenant %s", floatingip['id'], tenant.backend_id)
            try:
                neutron.delete_floatingip(floatingip['id'])
            except neutron_exceptions.NotFound:
                logger.debug("Floating IP %s is already gone from tenant %s", floatingip['id'], tenant.backend_id)
            except neutron_exceptions.NeutronClientException as e:
                six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_tenant_ports(self, tenant):
        if not tenant.backend_id:
            # This method will remove all ports if tenant `backend_id` is not defined.
            raise OpenStackBackendError('This method should not be called if tenant has no backend_id')

        neutron = self.neutron_admin_client

        try:
            ports = neutron.list_ports(tenant_id=tenant.backend_id)
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

        for port in ports.get('ports', []):
            logger.info("Deleting port %s interface_router from tenant %s", port['id'], tenant.backend_id)
            try:
                neutron.remove_interface_router(port['device_id'], {'port_id': port['id']})
            except neutron_exceptions.NotFound:
                logger.debug("Port %s interface_router is already gone from tenant %s", port['id'],
                             tenant.backend_id)
            except neutron_exceptions.NeutronClientException as e:
                six.reraise(OpenStackBackendError, e)

            logger.info("Deleting port %s from tenant %s", port['id'], tenant.backend_id)
            try:
                neutron.delete_port(port['id'])
            except neutron_exceptions.NotFound:
                logger.debug("Port %s is already gone from tenant %s", port['id'], tenant.backend_id)
            except neutron_exceptions.NeutronClientException as e:
                six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_tenant_routers(self, tenant):
        if not tenant.backend_id:
            # This method will remove all routers if tenant `backend_id` is not defined.
            raise OpenStackBackendError('This method should not be called if tenant has no backend_id')

        neutron = self.neutron_admin_client

        try:
            routers = neutron.list_routers(tenant_id=tenant.backend_id)
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

        for router in routers.get('routers', []):
            logger.info("Deleting router %s from tenant %s", router['id'], tenant.backend_id)
            try:
                neutron.delete_router(router['id'])
            except neutron_exceptions.NotFound:
                logger.debug("Router %s is already gone from tenant %s", router['id'], tenant.backend_id)
            except neutron_exceptions.NeutronClientException as e:
                six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_tenant_networks(self, tenant):
        if not tenant.backend_id:
            # This method will remove all networks if tenant `backend_id` is not defined.
            raise OpenStackBackendError('This method should not be called if tenant has no backend_id')

        neutron = self.neutron_admin_client

        try:
            networks = neutron.list_networks(tenant_id=tenant.backend_id)
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

        for network in networks.get('networks', []):
            if network['router:external']:
                continue
            for subnet in network['subnets']:
                logger.info("Deleting subnetwork %s from tenant %s", subnet, tenant.backend_id)
                try:
                    neutron.delete_subnet(subnet)
                except neutron_exceptions.NotFound:
                    logger.info("Subnetwork %s is already gone from tenant %s", subnet, tenant.backend_id)
                except neutron_exceptions.NeutronClientException as e:
                    six.reraise(OpenStackBackendError, e)

            logger.info("Deleting network %s from tenant %s", network['id'], tenant.backend_id)
            try:
                neutron.delete_network(network['id'])
            except neutron_exceptions.NotFound:
                logger.debug("Network %s is already gone from tenant %s", network['id'], tenant.backend_id)
            except neutron_exceptions.NeutronClientException as e:
                six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_tenant_security_groups(self, tenant):
        nova = self.nova_client

        try:
            sgroups = nova.security_groups.list()
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        for sgroup in sgroups:
            logger.info("Deleting security group %s from tenant %s", sgroup.id, tenant.backend_id)
            try:
                sgroup.delete()
            except nova_exceptions.NotFound:
                logger.debug("Security group %s is already gone from tenant %s", sgroup.id, tenant.backend_id)
            except nova_exceptions.ClientException as e:
                six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_tenant_instances(self, tenant):
        nova = self.nova_client

        try:
            servers = nova.servers.list()
        except nova_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        for server in servers:
            logger.info("Deleting instance %s from tenant %s", server.id, tenant.backend_id)
            try:
                server.delete()
            except nova_exceptions.NotFound:
                logger.debug("Instance %s is already gone from tenant %s", server.id, tenant.backend_id)
            except nova_exceptions.ClientException as e:
                six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_tenant_snapshots(self, tenant):
        cinder = self.cinder_client

        try:
            snapshots = cinder.volume_snapshots.list()
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        for snapshot in snapshots:
            logger.info("Deleting snapshot %s from tenant %s", snapshot.id, tenant.backend_id)
            try:
                snapshot.delete()
            except cinder_exceptions.NotFound:
                logger.debug("Snapshot %s is already gone from tenant %s", snapshot.id, tenant.backend_id)
            except cinder_exceptions.ClientException as e:
                six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_tenant_volumes(self, tenant):
        cinder = self.cinder_client

        try:
            volumes = cinder.volumes.list()
        except cinder_exceptions.ClientException as e:
            six.reraise(OpenStackBackendError, e)

        for volume in volumes:
            logger.info("Deleting volume %s from tenant %s", volume.id, tenant.backend_id)
            try:
                volume.delete()
            except cinder_exceptions.NotFound:
                logger.debug("Volume %s is already gone from tenant %s", volume.id, tenant.backend_id)
            except cinder_exceptions.ClientException as e:
                six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_tenant_user(self, tenant):
        keystone = self.keystone_client
        try:
            user = keystone.users.find(name=tenant.user_username)
            logger.info('Deleting user %s that was connected to tenant %s', user.name, tenant.backend_id)
            user.delete()
        except keystone_exceptions.NotFound:
            logger.debug("User %s is already gone from tenant %s", tenant.user_username, tenant.backend_id)
        except keystone_exceptions.ClientException as e:
            logger.error('Cannot delete user %s from tenant %s. Error: %s', tenant.user_username, tenant.backend_id, e)

    @log_backend_action()
    def delete_tenant(self, tenant):
        if not tenant.backend_id:
            raise OpenStackBackendError('This method should not be called if tenant has no backend_id')

        keystone = self.keystone_admin_client

        logger.info("Deleting tenant %s", tenant.backend_id)
        try:
            keystone.tenants.delete(tenant.backend_id)
        except keystone_exceptions.NotFound:
            logger.debug("Tenant %s is already gone", tenant.backend_id)
        except keystone_exceptions.ClientException as e:
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

    @log_backend_action()
    def create_network(self, network):
        neutron = self.neutron_admin_client

        data = {'name': network.name, 'description': network.description, 'tenant_id': network.tenant.backend_id}
        try:
            response = neutron.create_network({'networks': [data]})
        except neutron_exceptions.NeutronException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            backend_network = response['networks'][0]
            network.backend_id = backend_network['id']
            network.runtime_state = backend_network['status']
            if backend_network.get('provider:network_type'):
                network.type = backend_network['provider:network_type']
            if backend_network.get('provider:segmentation_id'):
                network.segmentation_id = backend_network['provider:segmentation_id']
            network.save()

    @log_backend_action()
    def update_network(self, network):
        neutron = self.neutron_admin_client

        data = {'name': network.name, 'description': network.description}
        try:
            neutron.update_network(network.backend_id, {'network': data})
        except neutron_exceptions.NeutronException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_network(self, network):
        for subnet in network.subnets.all():
            self.delete_subnet(subnet)

        neutron = self.neutron_admin_client
        try:
            neutron.delete_network(network.backend_id)
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

    def import_network(self, network_backend_id):
        neutron = self.neutron_admin_client
        try:
            backend_network = neutron.show_network(network_backend_id)['network']
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

        network = models.Network(
            name=backend_network['name'],
            description=backend_network['description'] or '',
            type=backend_network.get('provider:network_type'),
            segmentation_id=backend_network.get('provider:segmentation_id'),
            runtime_state=backend_network['status'],
            state=models.Network.States.OK,
        )
        return network

    @log_backend_action()
    def pull_network(self, network):
        import_time = timezone.now()
        imported_network = self.import_network(network.backend_id)

        network.refresh_from_db()
        if network.modified < import_time:
            update_fields = ('name', 'description', 'type', 'segmentation_id', 'runtime_state')
            update_pulled_fields(network, imported_network, update_fields)

    @log_backend_action()
    def create_subnet(self, subnet):
        neutron = self.neutron_admin_client

        data = {
            'name': subnet.name,
            'description': subnet.description,
            'network_id': subnet.network.backend_id,
            'tenant_id': subnet.network.tenant.backend_id,
            'cidr': subnet.cidr,
            'allocation_pools': subnet.allocation_pools,
            'ip_version': subnet.ip_version,
            'enable_dhcp': subnet.enable_dhcp,
        }
        try:
            response = neutron.create_subnet({'subnets': [data]})
            # Automatically create router for subnet
            # TODO: Ideally: Create separate model for router and create it separately.
            #       Good enough: refactor `get_or_create_router` method: split it into several method.
            self.get_or_create_router(subnet.network.name, response['subnets'][0]['id'])
        except neutron_exceptions.NeutronException as e:
            six.reraise(OpenStackBackendError, e)
        else:
            backend_subnet = response['subnets'][0]
            subnet.backend_id = backend_subnet['id']
            if backend_subnet.get('gateway_ip'):
                subnet.gateway_ip = backend_subnet['gateway_ip']
            subnet.save()

    @log_backend_action()
    def update_subnet(self, subnet):
        neutron = self.neutron_admin_client

        data = {'name': subnet.name, 'description': subnet.description}
        try:
            neutron.update_subnet(subnet.backend_id, {'subnet': data})
        except neutron_exceptions.NeutronException as e:
            six.reraise(OpenStackBackendError, e)

    @log_backend_action()
    def delete_subnet(self, subnet):
        neutron = self.neutron_admin_client
        try:
            neutron.delete_subnet(subnet.backend_id)
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

    def import_subnet(self, subnet_backend_id):
        neutron = self.neutron_admin_client
        try:
            backend_subnet = neutron.show_subnet(subnet_backend_id)['subnet']
        except neutron_exceptions.NeutronClientException as e:
            six.reraise(OpenStackBackendError, e)

        subnet = models.SubNet(
            name=backend_subnet['name'],
            description=backend_subnet['description'] or '',
            allocation_pools=backend_subnet['allocation_pools'],
            cidr=backend_subnet['cidr'],
            ip_version=backend_subnet.get('ip_version'),
            gateway_ip=backend_subnet.get('gateway_ip'),
            enable_dhcp=backend_subnet.get('enable_dhcp', False),
            state=models.Network.States.OK,
        )
        return subnet

    @log_backend_action()
    def pull_subnet(self, subnet):
        import_time = timezone.now()
        imported_subnet = self.import_subnet(subnet.backend_id)

        subnet.refresh_from_db()
        if subnet.modified < import_time:
            update_fields = ('name', 'description', 'cidr', 'allocation_pools', 'ip_version', 'gateway_ip',
                             'enable_dhcp')
            update_pulled_fields(subnet, imported_subnet, update_fields)

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
    def update_tenant(self, tenant):
        keystone = self.keystone_admin_client
        try:
            keystone.tenants.update(tenant.backend_id, name=tenant.name, description=tenant.description)
        except keystone_exceptions.NotFound as e:
            logger.error('Tenant with id %s does not exist', tenant.backend_id)
            six.reraise(OpenStackBackendError, e)

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
