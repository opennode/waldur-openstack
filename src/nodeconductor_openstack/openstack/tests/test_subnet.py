from rest_framework import status, test

from nodeconductor.structure.tests import factories as structure_factories

from . import factories


class TestSubNetCreateAction(test.APISimpleTestCase):
    def setUp(self):
        self.user = structure_factories.UserFactory()
        self.client.force_authenticate(user=self.user)

    def test_network_create_action_is_not_allowed(self):
        url = factories.SubNetFactory.get_list_url()

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
