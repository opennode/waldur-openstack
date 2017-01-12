import mock
from rest_framework import status, test

from . import factories, fixtures
from .. import models


class BaseNetworkTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackFixture()


class NetworkCreateActionTest(BaseNetworkTest):

    def test_network_create_action_is_not_allowed(self):
        self.client.force_authenticate(user=self.fixture.user)
        url = factories.NetworkFactory.get_list_url()

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class NetworkCreateSubnetActionTest(BaseNetworkTest):
    action_name = 'create_subnet'

    def setUp(self):
        super(NetworkCreateSubnetActionTest, self).setUp()
        self.user = self.fixture.owner
        self.client.force_authenticate(self.user)
        self.url = factories.NetworkFactory.get_url(network=self.fixture.network, action=self.action_name)
        self.request_data = {
            'name': 'test_subnet_name',
            'tenant_name': 'test_tenant_name',
            'network_name': 'test_network_name',
        }

    def test_create_subnet_is_not_allowed_when_state_is_not_OK(self):
        self.fixture.network.state = models.Network.States.ERRED
        self.fixture.network.save()

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_cannot_create_subnet_when_network_has_one_already(self):
        factories.SubNetFactory(network=self.fixture.network)
        self.assertEqual(self.fixture.network.subnets.count(), 1)

        response = self.client.post(self.url, self.request_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @mock.patch('nodeconductor_openstack.openstack.executors.SubNetCreateExecutor.execute')
    def test_create_subnet_triggers_create_executor(self, executor_action_mock):
        url = factories.NetworkFactory.get_url(network=self.fixture.network, action=self.action_name)

        response = self.client.post(self.url, self.request_data)
        failure_message = "executor has not been triggered. Response: %s" % response.data
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, failure_message)
        executor_action_mock.assert_called_once()

