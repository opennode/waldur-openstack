from ddt import data, ddt
import mock

from rest_framework import test
from keystoneclient import exceptions as keystone_exceptions

from waldur_openstack.openstack import models
from waldur_openstack.openstack.backend import OpenStackBackend
from waldur_openstack.openstack.tests import fixtures, factories


class MockedSession(mock.MagicMock):
    auth_ref = 'AUTH_REF'


class BaseBackendTestCase(test.APITransactionTestCase):
    def setUp(self):
        self.fixture = fixtures.OpenStackFixture()
        self.tenant = self.fixture.tenant
        self.backend = OpenStackBackend(settings=self.fixture.openstack_service_settings,
                                        tenant_id=self.tenant.id)

        self.mocked_keystone = mock.Mock()
        self.mocked_keystone_admin = mock.Mock()
        self.mocked_neutron = mock.Mock()
        self.mocked_neutron_admin = mock.Mock()
        self.mocked_glance = mock.Mock()

        self.backend.keystone_client = self.mocked_keystone
        self.backend.keystone_admin_client = self.mocked_keystone_admin
        self.backend.neutron_client = self.mocked_neutron
        self.backend.neutron_admin_client = self.mocked_neutron_admin
        self.backend.glance_client = self.mocked_glance

    def tearDown(self):
        super(BaseBackendTestCase, self).tearDown()
        mock.patch.stopall()


@ddt
class PullFloatingIPTest(BaseBackendTestCase):

    def _get_valid_new_backend_ip(self, floating_ip):
        return dict(floatingips=[{
            'floating_ip_address': floating_ip.address,
            'floating_network_id': floating_ip.backend_network_id,
            'status': floating_ip.runtime_state,
            'id': floating_ip.backend_id,
            'description': '',
            'tenant_id': floating_ip.tenant.backend_id,
        }])

    def setup_client(self, is_admin, value):
        client = is_admin and self.mocked_neutron_admin or self.mocked_neutron
        client.list_floatingips.return_value = value

    def call_backend(self, is_admin):
        if is_admin:
            return self.backend.pull_floating_ips()
        else:
            return self.backend.pull_tenant_floating_ips(self.fixture.tenant)

    @data(True, False)
    def test_floating_ip_is_created_if_it_does_not_exist(self, is_admin):
        floating_ip = self.fixture.floating_ip
        floating_ip.backend_network_id = 'new_backend_network_id'
        self.setup_client(is_admin, self._get_valid_new_backend_ip(floating_ip))
        floating_ip.delete()

        self.call_backend(is_admin)

        self.assertEqual(models.FloatingIP.objects.count(), 1)
        created_ip = models.FloatingIP.objects.get(tenant=self.tenant, backend_id=floating_ip.backend_id)
        self.assertEqual(created_ip.runtime_state, floating_ip.runtime_state)
        self.assertEqual(created_ip.backend_network_id, floating_ip.backend_network_id)
        self.assertEqual(created_ip.address, floating_ip.address)

    @data(True, False)
    def test_floating_ip_is_deleted_if_it_is_not_returned_by_neutron(self, is_admin):
        floating_ip = self.fixture.floating_ip
        self.setup_client(is_admin, dict(floatingips=[]))

        self.call_backend(is_admin)

        self.assertRaises(models.FloatingIP.DoesNotExist, floating_ip.refresh_from_db)

    @data(True, False)
    def test_floating_ip_is_not_deleted_if_it_is_in_creating_state(self, is_admin):
        floating_ip = self.fixture.floating_ip
        floating_ip.state = models.FloatingIP.States.CREATING
        floating_ip.backend_id = ''
        floating_ip.save()
        self.setup_client(is_admin, dict(floatingips=[]))

        self.call_backend(is_admin)

        floating_ip.refresh_from_db()

    @data(True, False)
    def test_floating_ip_is_updated(self, is_admin):
        floating_ip = self.fixture.floating_ip
        floating_ip.runtime_state = 'ACTIVE'
        self.setup_client(is_admin, self._get_valid_new_backend_ip(floating_ip))

        floating_ip.runtime_state = 'DOWN'
        floating_ip.save()

        self.call_backend(is_admin)

        floating_ip.refresh_from_db()
        self.assertEqual(floating_ip.runtime_state, 'ACTIVE')


class PullTenantSecurityGroupsTest(BaseBackendTestCase):

    def test_pull_tenant_security_groups_does_not_duplicate_security_groups_in_progress(self):
        original_security_group = factories.SecurityGroupFactory(tenant=self.tenant)
        factories.SecurityGroupRuleFactory(security_group=original_security_group)
        security_group_in_progress = factories.SecurityGroupFactory(state=models.SecurityGroup.States.UPDATING,
                                                                    tenant=self.tenant)
        factories.SecurityGroupRuleFactory(security_group=security_group_in_progress)
        security_groups = [original_security_group, security_group_in_progress]
        backend_security_groups = self._form_backend_security_groups(security_groups)
        self.mocked_neutron.list_security_groups.return_value = {
            'security_groups': backend_security_groups
        }

        self.backend.pull_tenant_security_groups(self.tenant)

        backend_ids = [sg.backend_id for sg in security_groups]
        actual_security_groups_count = models.SecurityGroup.objects.filter(backend_id__in=backend_ids).count()
        self.assertEqual(actual_security_groups_count, len(security_groups))

    def _form_backend_security_groups(self, security_groups):
        result = []

        for security_group in security_groups:
            result.append({
                'name': security_group.name,
                'id': security_group.backend_id,
                'description': security_group.description,
                'security_group_rules': self._form_backend_security_rules(security_group.rules.all())
            })

        return result

    def _form_backend_security_rules(self, rules):
        result = []

        for rule in rules:
            result.append({
                'port_range_min': rule.from_port,
                'port_range_max': rule.to_port,
                'protocol': rule.protocol,
                'remote_ip_prefix': rule.cidr,
                'direction': 'ingress',
                'id': rule.id,
            })

        return result


class CreateOrUpdateTenantUserTest(BaseBackendTestCase):

    def test_change_tenant_user_password_is_called_if_user_exists(self):
        self.mocked_keystone.users.find.return_value = self.fixture.owner

        self.backend.create_or_update_tenant_user(self.tenant)

        self.mocked_keystone.users.update.assert_called_once()

    def test_user_is_created_if_it_is_not_found(self):
        self.mocked_keystone.users.find.side_effect = keystone_exceptions.NotFound

        self.backend.create_or_update_tenant_user(self.tenant)

        self.mocked_keystone.users.create.assert_called_once()


class ImportTenantNetworksTest(BaseBackendTestCase):

    def _generate_backend_networks(self, count=1):
        networks = []

        for i in range(0, count):
            networks.append({
                'name': 'network_%s' % i,
                'tenant_id': self.tenant.backend_id,
                'description': 'network_description_%s' % i,
                'router:external': True,
                'status': 'ONLINE',
                'id': 'backend_id_%s' % i,
            })

        return networks

    def test_import_tenant_networks_imports_network(self):
        backend_network = self._generate_backend_networks()[0]
        self.mocked_neutron.list_networks.return_value = {'networks': [backend_network]}
        self.assertEqual(self.tenant.networks.count(), 0)

        self.backend.import_tenant_networks(self.tenant)

        self.assertEqual(self.tenant.networks.count(), 1)
        network = self.tenant.networks.first()
        self.assertEqual(network.name, backend_network['name'])
        self.assertEqual(network.description, backend_network['description'])
        self.assertEqual(network.is_external, backend_network['router:external'])
        self.assertEqual(network.backend_id, backend_network['id'])
        self.assertEqual(network.tenant.id, self.tenant.id)
        self.assertEqual(self.tenant.internal_network_id, backend_network['id'])

    def test_internal_network_is_not_set_if_networks_are_missing(self):
        self.mocked_neutron.list_networks.return_value = {'networks': []}

        self.backend.import_tenant_networks(self.tenant)

        self.assertEqual(self.tenant.networks.count(), 0)
        self.assertEqual(self.tenant.internal_network_id, '')

    def test_networks_are_updated_if_they_exist(self):
        backend_network = self._generate_backend_networks()[0]
        self.mocked_neutron.list_networks.return_value = {'networks': [backend_network]}
        network = factories.NetworkFactory(tenant=self.tenant,
                                           service_project_link=self.tenant.service_project_link,
                                           backend_id=backend_network['id'])
        self.assertEqual(self.tenant.networks.count(), 1)

        self.backend.import_tenant_networks(self.tenant)

        self.assertEqual(self.tenant.networks.count(), 1)
        network.refresh_from_db()
        self.assertEqual(network.name, backend_network['name'])
        self.assertEqual(network.description, backend_network['description'])
        self.assertEqual(network.is_external, backend_network['router:external'])
        self.assertEqual(network.backend_id, backend_network['id'])
        self.assertEqual(network.tenant.id, self.tenant.id)
        self.assertEqual(self.tenant.internal_network_id, backend_network['id'])


class ImportTenantSubnets(BaseBackendTestCase):

    def setUp(self):
        super(ImportTenantSubnets, self).setUp()
        self.network = self.fixture.network

    def _generate_backend_subnet(self, count=1):
        subnets = []

        for i in range(0, count):
            subnets.append({
                'name': 'network_%s' % i,
                'tenant_id': self.tenant.backend_id,
                'description': 'network_description_%s' % i,
                'allocation_pools': [],
                'cidr': '24',
                'ip_version': 4,
                'enable_dhcp': True,
                'gateway_ip': '127.0.0.1',
                'network_id': self.network.backend_id,
                'dns_nameservers': 'waldur.example',
                'id': self.network.backend_id,
            })

        return subnets

    def test_tenant_subnet_is_imported(self):
        backend_subnet = self._generate_backend_subnet()[0]
        self.mocked_neutron.list_subnets.return_value = {'subnets': [backend_subnet]}
        self.assertEqual(models.SubNet.objects.count(), 0)

        self.backend.import_tenant_subnets(self.tenant)

        self.assertEqual(models.SubNet.objects.count(), 1)
        subnet = models.SubNet.objects.get(network=self.network, backend_id=backend_subnet['id'])
        self.assertEqual(subnet.name, backend_subnet['name'])
        self.assertEqual(subnet.description, backend_subnet['description'])
        self.assertEqual(subnet.cidr, backend_subnet['cidr'])
        self.assertEqual(subnet.ip_version, backend_subnet['ip_version'])
        self.assertEqual(subnet.enable_dhcp, backend_subnet['enable_dhcp'])
        self.assertEqual(subnet.dns_nameservers, backend_subnet['dns_nameservers'])

    def test_tenant_subnets_are_not_imported_if_network_is_missing(self):
        backend_subnet = self._generate_backend_subnet()[0]
        self.tenant.networks.all().delete()
        self.mocked_neutron.list_subnets.return_value = {'subnets': [backend_subnet]}
        self.assertEqual(models.SubNet.objects.count(), 0)

        self.backend.import_tenant_subnets(self.tenant)

        self.assertEqual(models.SubNet.objects.count(), 0)


class PullImagesTest(BaseBackendTestCase):

    def setUp(self):
        super(PullImagesTest, self).setUp()
        self.mocked_glance.images.list.return_value = [
            {
                'status': 'active',
                'id': '1',
                'name': 'CentOS 7',
                'min_ram': 1024,
                'min_disk': 10,
                'visibility': 'public',
            }
        ]

    def test_new_image_is_added(self):
        self.backend.pull_images()
        image = models.Image.objects.filter(
            backend_id='1',
            name='CentOS 7',
            min_ram=1024,
            min_disk=10240,
            settings=self.fixture.openstack_service_settings
        )
        self.assertEqual(models.Image.objects.count(), 1)
        self.assertTrue(image.exists())

    def test_old_image_is_deleted(self):
        models.Image.objects.create(
            backend_id='2',
            name='CentOS 6',
            min_ram=2048,
            min_disk=10240,
            settings=self.fixture.openstack_service_settings
        )
        self.backend.pull_images()
        self.assertEqual(models.Image.objects.count(), 1)
        self.assertFalse(models.Image.objects.filter(backend_id='2').exists())

    def test_existing_image_is_updated(self):
        models.Image.objects.create(
            backend_id='1',
            name='CentOS 7',
            min_ram=2048,
            min_disk=10240,
            settings=self.fixture.openstack_service_settings
        )
        self.backend.pull_images()
        self.assertEqual(models.Image.objects.count(), 1)
        self.assertEqual(models.Image.objects.get(backend_id='1').min_ram, 1024)

    def test_private_images_are_filtered_out(self):
        self.mocked_glance.images.list.return_value[0]['visibility'] = 'private'
        self.backend.pull_images()
        self.assertEqual(models.Image.objects.count(), 0)

    def test_deleted_images_are_filtered_out(self):
        self.mocked_glance.images.list.return_value[0]['status'] = 'deleted'
        self.backend.pull_images()
        self.assertEqual(models.Image.objects.count(), 0)
