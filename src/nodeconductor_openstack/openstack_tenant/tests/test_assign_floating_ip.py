from uuid import uuid4

from rest_framework import test, status

from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.openstack.tests import fixtures as openstack_fixtures

from ..models import Instance
from . import factories, fixtures


class AssignFloatingIPTestCase(test.APITransactionTestCase):

    def setUp(self):
        self.openstack_tenant_fixture = fixtures.OpenStackTenantFixture()
        self.openstack_fixture = openstack_fixtures.OpenStackFixture()
        self.openstack_tenant_settings = self.openstack_tenant_fixture.openstack_tenant_service_settings
        self.spl = self.openstack_tenant_fixture.spl
        self.tenant = self.openstack_fixture.tenant

    def test_user_cannot_assign_floating_ip_to_instance_in_unstable_state(self):
        floating_ip = factories.FloatingIPFactory(
            settings=self.openstack_tenant_settings,
            runtime_state='DOWN',
            backend_network_id=self.tenant.external_network_id
        )
        instance = factories.InstanceFactory(
            state=Instance.States.ERRED,
            service_project_link=self.spl,
        )

        response = self.get_response(instance, floating_ip)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_user_cannot_assign_not_existing_ip_to_the_instance(self):
        class InvalidFloatingIP(object):
            uuid = uuid4()

        invalid_floating_ip = InvalidFloatingIP()
        instance = factories.InstanceFactory(
            state=Instance.States.OK,
            runtime_state=Instance.RuntimeStates.SHUTOFF,
            service_project_link=self.spl)

        response = self.get_response(instance, invalid_floating_ip)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['floating_ip'], ['Invalid hyperlink - Object does not exist.'])

    def test_user_cannot_assign_used_ip_to_the_instance(self):
        floating_ip = factories.FloatingIPFactory(
            settings=self.openstack_tenant_settings,
            runtime_state='ACTIVE',
            backend_network_id=self.tenant.external_network_id
        )
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            state=Instance.States.OK,
            runtime_state=Instance.RuntimeStates.SHUTOFF,
        )

        response = self.get_response(instance, floating_ip)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['floating_ip'], ['Floating IP runtime_state must be DOWN.'])

    def test_user_cannot_assign_ip_from_different_settings_to_the_instance(self):
        floating_ip = factories.FloatingIPFactory(runtime_state='DOWN')
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            state=Instance.States.OK,
            runtime_state=Instance.RuntimeStates.SHUTOFF,
        )

        response = self.get_response(instance, floating_ip)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['floating_ip'],
                         ['Floating IP must belong to same settings as instance.'])

    def test_user_can_assign_floating_ip_to_instance_with_satisfied_requirements(self):
        floating_ip = factories.FloatingIPFactory(
            settings=self.openstack_tenant_settings,
            runtime_state='DOWN',
            backend_network_id=self.tenant.external_network_id
        )
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            state=Instance.States.OK,
            runtime_state=Instance.RuntimeStates.SHUTOFF,
        )

        response = self.get_response(instance, floating_ip)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['status'], 'assign_floating_ip was scheduled')

    def test_user_can_assign_floating_ip_by_url(self):
        self.tenant.external_network_id = '12345'
        self.tenant.save()

        floating_ip = factories.FloatingIPFactory(
            settings=self.openstack_tenant_settings,
            runtime_state='DOWN',
            backend_network_id=self.tenant.external_network_id
        )
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            state=Instance.States.OK,
            runtime_state=Instance.RuntimeStates.SHUTOFF,
        )

        # authenticate
        staff = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=staff)

        url = factories.InstanceFactory.get_url(instance, action='assign_floating_ip')
        data = {'floating_ip': factories.FloatingIPFactory.get_url(floating_ip)}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['status'], 'assign_floating_ip was scheduled')

    def get_response(self, instance, floating_ip):
        # authenticate
        staff = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=staff)

        url = factories.InstanceFactory.get_url(instance, action='assign_floating_ip')
        data = {'floating_ip': factories.FloatingIPFactory.get_url(floating_ip)}
        return self.client.post(url, data)
