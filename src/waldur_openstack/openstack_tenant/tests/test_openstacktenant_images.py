from uuid import UUID
from rest_framework import test, status

from waldur_core.structure.tests import factories as structure_factories

from . import factories
from .. import models


class TestOpenstacktenantImages(test.APITransactionTestCase):

    def setUp(self):
        self.admin = structure_factories.UserFactory()
        self.instance = factories.InstanceFactory(
            volumes__image_name='Ubuntu 16.04',
            runtime_state=models.Instance.RuntimeStates.ACTIVE)
        self.instance = factories.InstanceFactory(
            volumes__image_name='Ubuntu 16.04',
            runtime_state=models.Instance.RuntimeStates.SHUTOFF)
        self.instance = factories.InstanceFactory(
            volumes__image_name='Windows 10',
            runtime_state=models.Instance.RuntimeStates.ACTIVE)
        self.ubuntu_image = factories.ImageFactory(
            name='Ubuntu 16.04',
            uuid='ede6c386795241488d3c3ebf2147541d')
        self.centos_image = factories.ImageFactory(
            name='Centos 10.04',
            uuid='67e77ec854564bafb2ef60dd5b6dc2d5')
        self.windows_image = factories.ImageFactory(
            name='Windows 10',
            uuid='c76101148fe64621b824e0117ad3b8d8')

    def test_usage_stats(self):
        expected = [
            {
                'uuid': UUID('67e77ec854564bafb2ef60dd5b6dc2d5'),
                'running_instances_count': 0,
                'name': u'Centos 10.04',
                'created_instances_count': 0
            },
            {
                'uuid': UUID('c76101148fe64621b824e0117ad3b8d8'),
                'running_instances_count': 1,
                'name': u'Windows 10',
                'created_instances_count': 0
            },
            {
                'uuid': UUID('ede6c386795241488d3c3ebf2147541d'),
                'running_instances_count': 1,
                'name': u'Ubuntu 16.04',
                'created_instances_count': 1
            }
        ]
        self.client.force_authenticate(user=self.admin)
        url = factories.ImageFactory.get_list_url(action='usage_stats')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sorted_response_data = sorted(response.data, key=lambda k: k['uuid'])
        self.assertListEqual(expected, sorted_response_data)
