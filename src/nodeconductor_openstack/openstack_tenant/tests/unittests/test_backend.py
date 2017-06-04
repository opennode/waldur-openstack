from __future__ import unicode_literals

from django.test import TestCase
from mock import Mock

from nodeconductor_openstack.openstack_tenant.backend import OpenStackTenantBackend
from nodeconductor_openstack.openstack_tenant import models

from .. import fixtures, factories


class PullFloatingIPTest(TestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()
        self.settings = self.fixture.openstack_tenant_service_settings
        self.tenant = self.fixture.openstack_tenant_service_settings.scope
        self.tenant_backend = OpenStackTenantBackend(self.settings)
        self.neutron_client_mock = Mock()
        self.tenant_backend.neutron_client = self.neutron_client_mock

    def test_pull_floating_ips_does_not_create_a_dublicate_floating_ip_for_booked_ips(self):
        internal_ip = factories.InternalIPFactory(instance=self.fixture.instance)
        backend_floating_ips = dict(floatingips=[
            {
                'floating_ip_address': 'new_address',
                'floating_network_id': internal_ip.backend_id,
                'status': 'DOWN',
                'id': 'new_backend_id',
                'port_id': internal_ip.backend_id
            }
        ])
        self.neutron_client_mock.list_floatingips.return_value = backend_floating_ips
        booked_ip = factories.FloatingIPFactory(is_booked=True,
                                                settings=self.settings,
                                                backend_id='booked_ip',
                                                runtime_state='DOWN')
        booked_ip.internal_ip = factories.InternalIPFactory(instance=self.fixture.instance)
        booked_ip.save()
        existing_ip = factories.FloatingIPFactory(settings=self.settings,
                                                  backend_id='existing_ip',
                                                  runtime_state='DOWN')
        existing_ip.internal_ip = factories.InternalIPFactory(instance=self.fixture.instance)
        existing_ip.save()
        for existing_ip in ([booked_ip, existing_ip]):
            backend_floating_ips['floatingips'].append({
                'floating_ip_address': existing_ip.address,
                'floating_network_id': existing_ip.backend_network_id,
                'status': existing_ip.runtime_state,
                'id': existing_ip.backend_id,
                'port_id': existing_ip.internal_ip.backend_id
            })
        new_ip_backned_id = backend_floating_ips['floatingips'][0]['id']
        expected_floating_ids = [
            existing_ip.backend_id,
            booked_ip.backend_id,
            # new floating_ip
            new_ip_backned_id,
        ]
        # assert that new floating ip has not been created yet.
        self.assertFalse(models.FloatingIP.objects.filter(backend_id=new_ip_backned_id).exists())
        # assert only booked and existing ip exist
        self.assertEqual(models.FloatingIP.objects.count(), 2)

        # act
        self.tenant_backend.pull_floating_ips()

        # assert
        actual_ips = models.FloatingIP.objects.filter(backend_id__in=expected_floating_ids).count()
        self.assertEqual(actual_ips, len(expected_floating_ids))
