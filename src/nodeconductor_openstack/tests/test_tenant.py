from mock import patch
import unittest

from rest_framework import test, status
from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.models import Tenant

from . import factories


class TenantActionsTest(test.APISimpleTestCase):

    def setUp(self):
        self.staff = structure_factories.UserFactory(is_staff=True)
        self.service_project_link = factories.OpenStackServiceProjectLinkFactory()
        self.tenant = factories.TenantFactory(service_project_link=self.service_project_link)

        self.quotas_url = factories.TenantFactory.get_url(self.tenant, 'set_quotas')
        self.network_url = factories.TenantFactory.get_url(self.tenant, 'external_network')
        self.ips_url = factories.TenantFactory.get_url(self.tenant, 'allocate_floating_ip')

    def test_non_staff_user_cannot_set_tenant_quotas(self):
        self.client.force_authenticate(user=structure_factories.UserFactory())
        response = self.client.post(self.quotas_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_set_tenant_quotas(self):
        self.client.force_authenticate(self.staff)
        quotas_data = {'security_group_count': 100, 'security_group_rule_count': 100}

        with patch('nodeconductor_openstack.executors.TenantPushQuotasExecutor.execute') as mocked_task:
            response = self.client.post(self.quotas_url, data=quotas_data)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            mocked_task.assert_called_once_with(self.tenant, quotas=quotas_data)

    @unittest.skip('Skip volume and snapshot test')
    def test_volume_and_snapshot_quotas_are_created_with_max_instances_quota(self):
        self.client.force_authenticate(self.staff)
        nc_settings = {'OPENSTACK_QUOTAS_INSTANCE_RATIOS': {'volumes': 3, 'snapshots': 7}}
        quotas_data = {'instances': 10}

        with patch('celery.app.base.Celery.send_task') as mocked_task:
            with self.settings(NODECONDUCTOR=nc_settings):
                response = self.client.post(self.quotas_url, data=quotas_data)

                quotas_data['volumes'] = 30
                quotas_data['snapshots'] = 70

                self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
                mocked_task.assert_called_once_with(
                    'nodeconductor.structure.sync_service_project_links',
                    (self.service_project_link.to_string(),), {'quotas': quotas_data}, countdown=2)

    @unittest.skip('Skip volume and snapshot test')
    def test_volume_and_snapshot_quotas_are_not_created_without_max_instances_quota(self):
        self.client.force_authenticate(self.staff)
        quotas_data = {'security_group_count': 100}

        with patch('celery.app.base.Celery.send_task') as mocked_task:
            response = self.client.post(self.quotas_url, data=quotas_data)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            mocked_task.assert_called_once_with(
                'nodeconductor.structure.sync_service_project_links',
                (self.service_project_link.to_string(),), {'quotas': quotas_data}, countdown=2)

    @unittest.skip('Skip volume and snapshot test')
    def test_volume_and_snapshot_values_not_provided_in_settings_use_default_values(self):
        self.client.force_authenticate(self.staff)
        quotas_data = {'instances': 10}

        with patch('celery.app.base.Celery.send_task') as mocked_task:
            with self.settings(NODECONDUCTOR={}):
                response = self.client.post(self.quotas_url, data=quotas_data)

                quotas_data['volumes'] = 40
                quotas_data['snapshots'] = 200

                self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
                mocked_task.assert_called_once_with(
                    'nodeconductor.structure.sync_service_project_links',
                    (self.service_project_link.to_string(),), {'quotas': quotas_data}, countdown=2)

    def test_staff_user_can_create_external_network(self):
        self.client.force_authenticate(user=self.staff)
        payload = {
            'vlan_id': '2007',
            'network_ip': '10.7.122.0',
            'network_prefix': 26,
            'ips_count': 6
        }

        with patch('nodeconductor_openstack.executors.TenantCreateExternalNetworkExecutor.execute') as mocked_task:
            response = self.client.post(self.network_url, payload)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            mocked_task.assert_called_once_with(self.tenant, external_network_data=payload)

    def test_staff_user_can_delete_existing_external_network(self):
        self.tenant.external_network_id = 'abcd1234'
        self.tenant.save()
        self.client.force_authenticate(user=self.staff)

        with patch('nodeconductor_openstack.executors.TenantDeleteExternalNetworkExecutor.execute') as mocked_task:
            response = self.client.delete(self.network_url)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            mocked_task.assert_called_once_with(self.tenant)

    def test_staff_user_cannot_delete_not_existing_external_network(self):
        self.client.force_authenticate(user=self.staff)
        self.tenant.external_network_id = ''
        self.tenant.save()

        with patch('nodeconductor_openstack.executors.TenantDeleteExternalNetworkExecutor.execute') as mocked_task:
            response = self.client.delete(self.network_url)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(mocked_task.called)

    def test_user_cannot_allocate_floating_ip_from_tenant_without_external_network_id(self):
        self.client.force_authenticate(user=self.staff)
        self.tenant.external_network_id = ''
        self.tenant.save()

        with patch('nodeconductor_openstack.executors.TenantAllocateFloatingIPExecutor.execute') as mocked_task:
            response = self.client.post(self.ips_url)
            self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(response.data['detail'], 'Tenant should have an external network ID.')
            self.assertFalse(mocked_task.called)

    def test_user_cannot_allocate_floating_ip_from_tenant_in_unstable_state(self):
        self.client.force_authenticate(user=self.staff)
        tenant = factories.TenantFactory(external_network_id='12345', state=Tenant.States.ERRED)
        url = factories.TenantFactory.get_url(tenant, 'allocate_floating_ip')

        with patch('nodeconductor_openstack.executors.TenantAllocateFloatingIPExecutor.execute') as mocked_task:
            response = self.client.post(url)
            self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(response.data['detail'], 'Tenant should be in state OK.')
            self.assertFalse(mocked_task.delay.called)

    def test_user_can_allocate_floating_ip_from_tenant_with_external_network_id(self):
        self.client.force_authenticate(user=self.staff)
        tenant = factories.TenantFactory(external_network_id='12345')
        url = factories.TenantFactory.get_url(tenant, 'allocate_floating_ip')

        with patch('nodeconductor_openstack.executors.TenantAllocateFloatingIPExecutor.execute') as mocked_task:
            response = self.client.post(url)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(response.data['detail'], 'Floating IP allocation has been scheduled.')

            mocked_task.assert_called_once_with(tenant)
