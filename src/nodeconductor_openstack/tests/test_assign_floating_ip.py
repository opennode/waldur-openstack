from uuid import uuid4

from mock import patch
from rest_framework import test, status

from nodeconductor.structure.tests import factories as structure_factories
from ..models import Instance, Tenant
from . import factories


class AssignFloatingIPTestCase(test.APITransactionTestCase):

    def setUp(self):
        customer = structure_factories.CustomerFactory()
        project = structure_factories.ProjectFactory(customer=customer)
        service = factories.OpenStackServiceFactory(customer=customer)
        self.spl = factories.OpenStackServiceProjectLinkFactory(service=service, project=project)
        self.tenant = factories.TenantFactory(service_project_link=self.spl)

    def test_user_cannot_assign_floating_ip_to_instance_in_unstable_state(self):
        floating_ip = factories.FloatingIPFactory(
            service_project_link=self.spl,
            status='DOWN',
            backend_network_id=self.tenant.external_network_id
        )
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            state=Instance.States.ERRED,
            tenant=self.tenant
        )

        with self.get_task() as mocked_task:
            response = self.get_response(instance, floating_ip)
            self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(response.data['detail'],
                             'Performing assign_floating_ip operation is not allowed for resource in its current state')
            self.assertFalse(mocked_task.called)

    def test_user_cannot_assign_floating_ip_to_instance_with_spl_without_external_network_id(self):
        self.tenant.external_network_id = ''
        self.tenant.save()

        floating_ip = factories.FloatingIPFactory(
            service_project_link=self.spl,
            status='DOWN')
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            tenant=self.tenant,
            state=Instance.States.OFFLINE
        )

        with self.get_task() as mocked_task:
            response = self.get_response(instance, floating_ip)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data['non_field_errors'],
                             ['External network ID of the service project link is missing.'])
            self.assertFalse(mocked_task.called)

    def test_user_cannot_assign_floating_ip_to_instance_with_link_in_unstable_state(self):
        self.tenant.external_network_id = '12345'
        self.tenant.state = Tenant.States.ERRED
        self.tenant.save()

        floating_ip = factories.FloatingIPFactory(
            service_project_link=self.spl,
            status='DOWN',
            backend_network_id=self.tenant.external_network_id
        )
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            tenant=self.tenant,
            state=Instance.States.OFFLINE
        )

        with self.get_task() as mocked_task:
            response = self.get_response(instance, floating_ip)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data['non_field_errors'],
                             ['Service project link of instance should be in stable state.'])
            self.assertFalse(mocked_task.called)

    def test_user_cannot_assign_not_existing_ip_to_the_instance(self):
        class InvalidFloatingIP(object):
            uuid = uuid4()

        invalid_floating_ip = InvalidFloatingIP()
        instance = factories.InstanceFactory(state=Instance.States.OFFLINE, tenant=self.tenant)

        with self.get_task() as mocked_task:
            response = self.get_response(instance, invalid_floating_ip)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data['floating_ip'], ['Invalid hyperlink - Object does not exist.'])
            self.assertFalse(mocked_task.called)

    def test_user_cannot_assign_used_ip_to_the_instance(self):
        self.tenant.external_network_id = '12345'
        self.tenant.save()

        floating_ip = factories.FloatingIPFactory(
            service_project_link=self.spl,
            status='ACTIVE',
            backend_network_id=self.tenant.external_network_id
        )
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            tenant=self.tenant,
            state=Instance.States.OFFLINE
        )

        with self.get_task() as mocked_task:
            response = self.get_response(instance, floating_ip)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data['floating_ip'], ['Floating IP status must be DOWN.'])
            self.assertFalse(mocked_task.called)

    def test_user_cannot_assign_ip_from_different_link_to_the_instance(self):
        self.tenant.external_network_id = '12345'
        self.tenant.save()

        floating_ip = factories.FloatingIPFactory(status='DOWN')
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            tenant=self.tenant,
            state=Instance.States.OFFLINE
        )

        with self.get_task() as mocked_task:
            response = self.get_response(instance, floating_ip)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data['floating_ip'],
                             ['Floating IP must belong to same service project link.'])
            self.assertFalse(mocked_task.called)

    def test_user_can_assign_floating_ip_to_instance_with_satisfied_requirements(self):
        self.tenant.external_network_id = '12345'
        self.tenant.save()

        floating_ip = factories.FloatingIPFactory(
            service_project_link=self.spl,
            status='DOWN',
            backend_network_id=self.tenant.external_network_id
        )
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            tenant=self.tenant,
            state=Instance.States.OFFLINE
        )

        with self.get_task() as mocked_task:
            response = self.get_response(instance, floating_ip)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(response.data['status'], 'assign_floating_ip was scheduled')
            self.assert_task_called(mocked_task, instance, floating_ip)

    def test_user_can_assign_floating_ip_by_url(self):
        self.tenant.external_network_id = '12345'
        self.tenant.save()

        floating_ip = factories.FloatingIPFactory(
            service_project_link=self.spl,
            status='DOWN',
            backend_network_id=self.tenant.external_network_id
        )
        instance = factories.InstanceFactory(
            service_project_link=self.spl,
            tenant=self.tenant,
            state=Instance.States.OFFLINE
        )

        with self.get_task() as mocked_task:
            # authenticate
            staff = structure_factories.UserFactory(is_staff=True)
            self.client.force_authenticate(user=staff)

            url = factories.InstanceFactory.get_url(instance, action='assign_floating_ip')
            data = {'floating_ip': factories.FloatingIPFactory.get_url(floating_ip)}
            response = self.client.post(url, data)

            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(response.data['status'], 'assign_floating_ip was scheduled')
            self.assert_task_called(mocked_task, instance, floating_ip)

    def get_task(self):
        return patch('celery.app.base.Celery.send_task')

    def assert_task_called(self, mocked_task, instance, floating_ip):
        mocked_task.assert_called_once_with(
            'nodeconductor.openstack.assign_floating_ip',
            (instance.uuid.hex, floating_ip.uuid.hex), {}, countdown=2
        )

    def get_response(self, instance, floating_ip):
        # authenticate
        staff = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=staff)

        url = factories.InstanceFactory.get_url(instance, action='assign_floating_ip')
        data = {'floating_ip': factories.FloatingIPFactory.get_url(floating_ip)}
        return self.client.post(url, data)
