import mock
from rest_framework import status, test

from . import factories, fixtures


class BaseSubNetTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackFixture()


class SubNetCreateActionTest(BaseSubNetTest):

    def setUp(self):
        super(SubNetCreateActionTest, self).setUp()
        self.client.force_authenticate(user=self.fixture.user)

    def test_subnet_create_action_is_not_allowed(self):
        url = factories.SubNetFactory.get_list_url()

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class SubNetDeleteActionTest(BaseSubNetTest):

    def setUp(self):
        super(SubNetDeleteActionTest, self).setUp()
        self.client.force_authenticate(user=self.fixture.admin)
        self.url = factories.SubNetFactory.get_url(self.fixture.subnet)

    @mock.patch('nodeconductor_openstack.openstack.executors.SubNetDeleteExecutor.execute')
    def test_subnet_create_action_triggers_create_executor(self, executor_action_mock):

        response = self.client.delete(self.url)
        failure_message = "executor has not been triggered. Response: %s" % response.data
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, failure_message)
        executor_action_mock.assert_called_once()
