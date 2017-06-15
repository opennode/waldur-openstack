from __future__ import unicode_literals

from django.test import TestCase
from mock import Mock

from nodeconductor_openstack.openstack_tenant.backend import OpenStackTenantBackend
from nodeconductor_openstack.openstack_tenant import models

from .. import fixtures, factories


class BaseBackendTest(TestCase):
    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()
        self.settings = self.fixture.openstack_tenant_service_settings
        self.tenant = self.fixture.openstack_tenant_service_settings.scope
        self.tenant_backend = OpenStackTenantBackend(self.settings)
        self.neutron_client_mock = Mock()
        self.tenant_backend.neutron_client = self.neutron_client_mock


class PullFloatingIPTest(BaseBackendTest):

    def _get_valid_new_backend_ip(self, internal_ip):
        return dict(floatingips=[{
                'floating_ip_address': '0.0.0.0',
                'floating_network_id': 'new_backend_network_id',
                'status': 'DOWN',
                'id': 'new_backend_id',
                'port_id': internal_ip.backend_id
        }])

    def test_pull_floating_ips_does_not_create_ip_if_internal_ip_is_missing(self):
        internal_ip = factories.InternalIPFactory(instance=self.fixture.instance)
        backend_floating_ips = self._get_valid_new_backend_ip(internal_ip)
        internal_ip.delete()
        self.neutron_client_mock.list_floatingips.return_value = backend_floating_ips
        self.assertEqual(models.FloatingIP.objects.count(), 0)

        self.tenant_backend.pull_floating_ips()

        self.assertEqual(models.FloatingIP.objects.count(), 0)

    def test_pull_floating_ips_does_not_update_ip_if_internal_ip_is_missing(self):
        internal_ip = factories.InternalIPFactory(instance=self.fixture.instance)
        backend_floating_ips = self._get_valid_new_backend_ip(internal_ip)
        internal_ip.delete()
        self.neutron_client_mock.list_floatingips.return_value = backend_floating_ips
        backend_ip = backend_floating_ips['floatingips'][0]
        floating_ip = factories.FloatingIPFactory(settings=self.settings,
                                                  backend_id=backend_ip['id'],
                                                  name='old_name',
                                                  runtime_state='old_status',
                                                  backend_network_id='old_backend_network_id',
                                                  address='127.0.0.1')
        self.assertEqual(models.FloatingIP.objects.count(), 1)

        self.tenant_backend.pull_floating_ips()

        self.assertEqual(models.FloatingIP.objects.count(), 1)
        floating_ip.refresh_from_db()
        self.assertNotEqual(floating_ip.address, backend_ip['floating_ip_address'])
        self.assertNotEqual(floating_ip.name, backend_ip['floating_ip_address'])
        self.assertNotEqual(floating_ip.runtime_state, backend_ip['status'])
        self.assertNotEqual(floating_ip.backend_network_id, backend_ip['floating_network_id'])

    def test_floating_ip_is_created_if_it_does_not_exist(self):
        internal_ip = factories.InternalIPFactory(instance=self.fixture.instance)
        backend_floating_ips = self._get_valid_new_backend_ip(internal_ip)
        backend_ip = backend_floating_ips['floatingips'][0]
        self.neutron_client_mock.list_floatingips.return_value = backend_floating_ips

        self.tenant_backend.pull_floating_ips()

        self.assertEqual(models.FloatingIP.objects.count(), 1)
        created_ip = models.FloatingIP.objects.get(backend_id=backend_ip['id'])
        self.assertEqual(created_ip.runtime_state, backend_ip['status'])
        self.assertEqual(created_ip.backend_network_id, backend_ip['floating_network_id'])
        self.assertEqual(created_ip.address, backend_ip['floating_ip_address'])

    def test_floating_ip_is_deleted_if_it_is_not_returned_by_neutron(self):
        floating_ip = factories.FloatingIPFactory(settings=self.settings)
        self.neutron_client_mock.list_floatingips.return_value = dict(floatingips=[])

        self.tenant_backend.pull_floating_ips()

        self.assertFalse(models.FloatingIP.objects.filter(id=floating_ip.id).exists())

    def test_floating_ip_is_not_updated_if_it_is_in_booked_state(self):
        internal_ip = factories.InternalIPFactory(instance=self.fixture.instance)
        backend_floating_ips = self._get_valid_new_backend_ip(internal_ip)
        self.neutron_client_mock.list_floatingips.return_value = backend_floating_ips
        backend_ip = backend_floating_ips['floatingips'][0]
        expected_name = 'booked ip'
        expected_address = '127.0.0.1'
        expected_runtime_state = 'booked_state'
        booked_ip = factories.FloatingIPFactory(is_booked=True,
                                                settings=self.settings,
                                                backend_id=backend_ip['id'],
                                                name=expected_name,
                                                address=expected_address,
                                                runtime_state=expected_runtime_state)

        self.tenant_backend.pull_floating_ips()

        booked_ip.refresh_from_db()
        self.assertEqual(booked_ip.name, expected_name)
        self.assertEqual(booked_ip.address, expected_address)
        self.assertEqual(booked_ip.runtime_state, expected_runtime_state)

    def test_floating_ip_is_not_duplicated_if_it_is_in_booked_state(self):
        internal_ip = factories.InternalIPFactory(instance=self.fixture.instance)
        backend_floating_ips = self._get_valid_new_backend_ip(internal_ip)
        self.neutron_client_mock.list_floatingips.return_value = backend_floating_ips
        backend_ip = backend_floating_ips['floatingips'][0]
        factories.FloatingIPFactory(
            is_booked=True,
            settings=self.settings,
            backend_id=backend_ip['id'],
            name='booked ip',
            address=backend_ip['floating_ip_address'],
            runtime_state='booked_state')

        self.tenant_backend.pull_floating_ips()

        backend_ip_address = backend_ip['floating_ip_address']
        self.assertEqual(models.FloatingIP.objects.filter(address=backend_ip_address).count(), 1)

    def test_floating_ip_name_is_not_update_if_it_was_set_by_user(self):
        internal_ip = factories.InternalIPFactory(instance=self.fixture.instance)
        backend_floating_ips = self._get_valid_new_backend_ip(internal_ip)
        self.neutron_client_mock.list_floatingips.return_value = backend_floating_ips
        backend_ip = backend_floating_ips['floatingips'][0]
        expected_name = 'user defined ip'
        floating_ip = factories.FloatingIPFactory(
            settings=self.settings,
            backend_id=backend_ip['id'],
            name=expected_name)

        self.tenant_backend.pull_floating_ips()

        floating_ip.refresh_from_db()
        self.assertNotEqual(floating_ip.address, floating_ip.name)
        self.assertEqual(floating_ip.name, expected_name)


class PullSecurityGroupsTest(BaseBackendTest):

    def setUp(self):
        super(PullSecurityGroupsTest, self).setUp()
        self.backend_security_groups = {
            'security_groups': [
                {
                    'id': 'backend_id',
                    'name': 'Default',
                    'description': 'Default security group',
                    'security_group_rules': [],
                }
            ]
        }
        self.neutron_client_mock.list_security_groups.return_value = self.backend_security_groups

    def test_pull_creates_missing_security_group(self):
        self.tenant_backend.pull_security_groups()

        self.neutron_client_mock.list_security_groups.assert_called_once_with(
            tenant_id=self.tenant.backend_id
        )
        self.assertEqual(models.SecurityGroup.objects.count(), 1)
        security_group = models.SecurityGroup.objects.get(
            settings=self.settings,
            backend_id='backend_id',
        )
        self.assertEqual(security_group.name, 'Default')
        self.assertEqual(security_group.description, 'Default security group')

    def test_pull_creates_missing_security_group_rule(self):
        self.backend_security_groups['security_groups'][0]['security_group_rules'] = [
            {
                'id': 'security_group_id',
                'direction': 'ingress',
                'port_range_min': 80,
                'port_range_max': 80,
                'protocol': 'tcp',
                'remote_ip_prefix': '0.0.0.0/0',
            }
        ]
        self.tenant_backend.pull_security_groups()

        self.assertEqual(models.SecurityGroupRule.objects.count(), 1)
        security_group = models.SecurityGroup.objects.get(
            settings=self.settings,
            backend_id='backend_id',
        )
        security_group_rule = models.SecurityGroupRule.objects.get(
            security_group=security_group,
            backend_id='security_group_id',
        )
        self.assertEqual(security_group_rule.from_port, 80)
        self.assertEqual(security_group_rule.to_port, 80)
        self.assertEqual(security_group_rule.protocol, 'tcp')
        self.assertEqual(security_group_rule.cidr, '0.0.0.0/0')

    def test_stale_security_groups_are_deleted(self):
        factories.SecurityGroupFactory(settings=self.settings)
        self.neutron_client_mock.list_security_groups.return_value = dict(security_groups=[])
        self.tenant_backend.pull_security_groups()
        self.assertEqual(models.SecurityGroup.objects.count(), 0)

    def test_security_groups_are_updated(self):
        security_group = factories.SecurityGroupFactory(
            settings=self.settings,
            backend_id='backend_id',
            name='Old name',
        )
        self.tenant_backend.pull_security_groups()
        security_group.refresh_from_db()
        self.assertEqual(security_group.name, 'Default')


class PullNetworksTest(BaseBackendTest):

    def setUp(self):
        super(PullNetworksTest, self).setUp()
        self.backend_networks = {
            'networks': [
                {
                    'id': 'backend_id',
                    'name': 'Private',
                    'description': 'Internal network',
                }
            ]
        }
        self.neutron_client_mock.list_networks.return_value = self.backend_networks

    def test_missing_networks_are_created(self):
        self.tenant_backend.pull_networks()

        self.assertEqual(models.Network.objects.count(), 1)
        network = models.Network.objects.get(
            settings=self.settings,
            backend_id='backend_id',
        )
        self.assertEqual(network.name, 'Private')
        self.assertEqual(network.description, 'Internal network')

    def test_stale_networks_are_deleted(self):
        factories.NetworkFactory(settings=self.settings)
        self.neutron_client_mock.list_networks.return_value = dict(networks=[])
        self.tenant_backend.pull_networks()
        self.assertEqual(models.Network.objects.count(), 0)

    def test_existing_networks_are_updated(self):
        network = factories.NetworkFactory(
            settings=self.settings,
            backend_id='backend_id',
            name='Old name',
        )
        self.tenant_backend.pull_networks()
        network.refresh_from_db()
        self.assertEqual(network.name, 'Private')


class PullSubnetsTest(BaseBackendTest):

    def setUp(self):
        super(PullSubnetsTest, self).setUp()
        self.network = factories.NetworkFactory(
            settings=self.settings,
            backend_id='network_id'
        )
        self.backend_subnets = {
            'subnets': [
                {
                    'id': 'backend_id',
                    'network_id': 'network_id',
                    'name': 'subnet-1',
                    'description': '',
                    'cidr': '192.168.42.0/24',
                    'ip_version': 4,
                    'allocation_pools': [
                        {
                            'start': '192.168.42.10',
                            'end': '192.168.42.100',
                        }
                    ],
                }
            ]
        }
        self.neutron_client_mock.list_subnets.return_value = self.backend_subnets

    def test_missing_subnets_are_created(self):
        self.tenant_backend.pull_subnets()

        self.neutron_client_mock.list_subnets.assert_called_once_with(
            tenant_id=self.tenant.backend_id
        )
        self.assertEqual(models.SubNet.objects.count(), 1)
        subnet = models.SubNet.objects.get(
            settings=self.settings,
            backend_id='backend_id',
            network=self.network,
        )
        self.assertEqual(subnet.name, 'subnet-1')
        self.assertEqual(subnet.cidr, '192.168.42.0/24')
        self.assertEqual(subnet.allocation_pools, [
            {
                'start': '192.168.42.10',
                'end': '192.168.42.100',
            }
        ])

    def test_subnet_is_not_pulled_if_network_is_not_pulled_yet(self):
        self.network.delete()
        self.tenant_backend.pull_subnets()
        self.assertEqual(models.SubNet.objects.count(), 0)

    def test_stale_subnets_are_deleted(self):
        factories.NetworkFactory(settings=self.settings)
        self.neutron_client_mock.list_subnets.return_value = dict(subnets=[])
        self.tenant_backend.pull_subnets()
        self.assertEqual(models.SubNet.objects.count(), 0)

    def test_existing_subnets_are_updated(self):
        subnet = factories.SubNetFactory(
            settings=self.settings,
            backend_id='backend_id',
            name='Old name',
            network=self.network,
        )
        self.tenant_backend.pull_subnets()
        subnet.refresh_from_db()
        self.assertEqual(subnet.name, 'subnet-1')
