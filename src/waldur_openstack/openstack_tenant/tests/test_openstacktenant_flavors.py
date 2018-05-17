from uuid import UUID
from rest_framework import test, status

from waldur_core.structure.tests import factories as structure_factories

from . import factories
from .. import models


class TestOpenstacktenantFlavors(test.APITransactionTestCase):

    def setUp(self):
        self.admin = structure_factories.UserFactory()
        self.instance = factories.InstanceFactory(
            flavor_name='Small',
            runtime_state=models.Instance.RuntimeStates.ACTIVE)
        self.instance = factories.InstanceFactory(
            flavor_name='Small',
            runtime_state=models.Instance.RuntimeStates.SHUTOFF)
        self.instance = factories.InstanceFactory(
            flavor_name='Large',
            runtime_state=models.Instance.RuntimeStates.ACTIVE)
        self.small_flavor = factories.FlavorFactory(
            name='Small',
            uuid='ede6c386795241488d3c3ebf2147541d')
        self.medium_flavor = factories.FlavorFactory(
            name='Medium',
            uuid='67e77ec854564bafb2ef60dd5b6dc2d5')
        self.large_flavor = factories.FlavorFactory(
            name='Large',
            uuid='c76101148fe64621b824e0117ad3b8d8')

    def test_usage_stats(self):
        expected = [
            {
                'uuid': UUID('67e77ec854564bafb2ef60dd5b6dc2d5'),
                'running_instances_count': 0,
                'created_instances_count': 0,
                'name': u'Medium'
            },
            {
                'uuid': UUID('c76101148fe64621b824e0117ad3b8d8'),
                'running_instances_count': 1,
                'created_instances_count': 0,
                'name': u'Large'
            },
            {
                'uuid': UUID('ede6c386795241488d3c3ebf2147541d'),
                'running_instances_count': 1,
                'created_instances_count': 1,
                'name': u'Small'
            }
        ]
        self.client.force_authenticate(user=self.admin)
        url = factories.FlavorFactory.get_list_url(action='usage_stats')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sorted_response_data = sorted(response.data, key=lambda k: k['uuid'])
        self.assertListEqual(expected, sorted_response_data)
