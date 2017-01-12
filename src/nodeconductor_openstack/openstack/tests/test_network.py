import mock
from rest_framework import status, test

from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor.structure import models as structure_models

from . import factories
from .. import models


class TestNetworkCreateAction(test.APISimpleTestCase):
    def setUp(self):
        self.user = structure_factories.UserFactory()
        self.client.force_authenticate(user=self.user)

    def test_network_create_action_is_not_allowed(self):
        url = factories.NetworkFactory.get_list_url()

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class TestNetworkCreateSubnetAction(test.APISimpleTestCase):
    action_name = 'create_subnet'

    def setUp(self):
        self.user = structure_factories.UserFactory()
        self.customer = structure_factories.CustomerFactory()
        self.customer.add_user(self.user, structure_models.CustomerRole.OWNER)

        self.client.force_authenticate(user=self.user)

    def test_create_subnet_is_not_allowed_when_state_is_not_OK(self):
        network = factories.NetworkFactory(state=models.Network.States.ERRED,
                                           service_project_link__project__customer=self.customer)
        url = factories.NetworkFactory.get_url(network=network, action=self.action_name)

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_cannot_create_subnet_when_network_has_one_already(self):
        network = factories.NetworkFactory(state=models.Network.States.OK,
                                           service_project_link__project__customer=self.customer)
        factories.SubNetFactory(network=network)
        url = factories.NetworkFactory.get_url(network=network, action=self.action_name)
        data = {
            'name': 'test_subnet_name'
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch('nodeconductor_openstack.openstack.executors.SubNetCreateExecutor.execute')
    def test_create_subnet_triggers_create_executor(self, executor_action_mock):
        network = factories.NetworkFactory(service_project_link__project__customer=self.customer)
        url = factories.NetworkFactory.get_url(network=network, action=self.action_name)
        data = {
            'name': 'test_subnet_name'
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        executor_action_mock.assert_called_once()

