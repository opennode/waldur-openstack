import mock
from rest_framework import test


class BaseBackendTestCase(test.APITransactionTestCase):
    def setUp(self):
        self.session_patcher = mock.patch('keystoneauth1.session.Session')
        self.session_patcher.start()

        self.keystone_patcher = mock.patch('keystoneclient.v2_0.client.Client')
        self.mocked_keystone = self.keystone_patcher.start()

        self.nova_patcher = mock.patch('novaclient.v2.client.Client')
        self.mocked_nova = self.nova_patcher.start()

        self.cinder_patcher = mock.patch('cinderclient.v1.client.Client')
        self.mocked_cinder = self.cinder_patcher.start()

    def tearDown(self):
        super(BaseBackendTestCase, self).tearDown()
        self.session_patcher.stop()
        self.keystone_patcher.stop()
        self.nova_patcher.stop()
        self.cinder_patcher.stop()
