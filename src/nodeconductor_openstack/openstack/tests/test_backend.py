import mock

from rest_framework import test

from nodeconductor_openstack.openstack.backend import OpenStackBackend
from nodeconductor_openstack.openstack import models

from . import fixtures, factories


class MockedSession(mock.MagicMock):
    auth_ref = 'AUTH_REF'


class BaseBackendTestCase(test.APITransactionTestCase):
    def setUp(self):
        self.session_patcher = mock.patch('keystoneauth1.session.Session', MockedSession)
        self.session_patcher.start()

        self.session_recover_patcher = mock.patch('nodeconductor_openstack.openstack_base.backend.OpenStackSession.recover')
        self.session_recover_patcher.start()

        self.keystone_patcher = mock.patch('keystoneclient.v2_0.client.Client')
        self.mocked_keystone = self.keystone_patcher.start()

        self.nova_patcher = mock.patch('novaclient.v2.client.Client')
        self.mocked_nova = self.nova_patcher.start()

        self.neutron_patcher = mock.patch('neutronclient.v2_0.client.Client')
        self.mocked_neutron = self.neutron_patcher.start()

        self.cinder_patcher = mock.patch('cinderclient.v2.client.Client')
        self.mocked_cinder = self.cinder_patcher.start()

    def tearDown(self):
        super(BaseBackendTestCase, self).tearDown()
        mock.patch.stopall()


class PullTenantSecurityGroupsTest(BaseBackendTestCase):

    def setUp(self):
        super(PullTenantSecurityGroupsTest, self).setUp()

        self.fixture = fixtures.OpenStackFixture()
        self.tenant = self.fixture.tenant
        self.backend = OpenStackBackend(settings=self.fixture.openstack_service_settings, tenant_id=self.tenant.id)

    def test_pull_tenant_security_groups_does_not_duplicate_security_groups_in_progresss(self):
        original_security_group = factories.SecurityGroupFactory(tenant=self.tenant)
        factories.SecurityGroupRuleFactory(security_group=original_security_group)
        security_group_in_progress = factories.SecurityGroupFactory(state=models.SecurityGroup.States.UPDATING,
                                                                    tenant=self.tenant)
        factories.SecurityGroupRuleFactory(security_group=security_group_in_progress)
        security_groups = [original_security_group, security_group_in_progress]
        backend_security_groups = self._form_backend_security_groups(security_groups)
        self.mocked_neutron().list_security_groups.return_value = {
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
