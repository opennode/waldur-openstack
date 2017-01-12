from rest_framework import status, test

from . import factories, fixtures


class BaseSubNetTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackFixture()


class SubNetCreateActionTest(BaseSubNetTest):
    def setUp(self):
        super(SubNetCreateActionTest, self).setUp()
        self.client.force_authenticate(user=self.fixture.user)

    def test_network_create_action_is_not_allowed(self):
        url = factories.SubNetFactory.get_list_url()

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
