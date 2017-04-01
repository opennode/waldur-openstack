import mock
import unittest

from rest_framework import status

from nodeconductor.structure.tests import factories as structure_factories

from .test_backend import BaseBackendTestCase
from . import factories
from .. import models


class BaseImportTestCase(BaseBackendTestCase):
    def setUp(self):
        super(BaseImportTestCase, self).setUp()
        self.staff = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=self.staff)

        self.link = factories.OpenStackServiceProjectLinkFactory()
        self.service = self.link.service
        self.project = self.link.project
        self.url = factories.OpenStackServiceFactory.get_url(self.service, 'link')


@unittest.skip('Import operation is not supported yet.')
class TenantImportTestCase(BaseImportTestCase):
    def setUp(self):
        super(TenantImportTestCase, self).setUp()
        self.mocked_tenant = mock.Mock()
        self.mocked_tenant.id = '1'
        self.mocked_tenant.name = 'PRD'
        self.mocked_tenant.description = 'Production tenant'

        self.mocked_keystone().tenants.list.return_value = [self.mocked_tenant]
        self.mocked_keystone().tenants.get.return_value = self.mocked_tenant

    def test_user_can_list_importable_tenants(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data, [{
            'id': self.mocked_tenant.id,
            'name': self.mocked_tenant.name,
            'description': self.mocked_tenant.description,
            'type': 'OpenStack.Tenant'
        }])

    def test_user_can_import_tenant(self):
        response = self.client.post(self.url, self.get_valid_data())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        tenant = models.Tenant.objects.get(uuid=response.data['uuid'])
        self.assertEqual(tenant.service_project_link, self.link)
        self.assertEqual(tenant.name, self.mocked_tenant.name)
        self.assertEqual(tenant.backend_id, self.mocked_tenant.id)
        self.assertEqual(tenant.state, models.Tenant.States.OK)

    def get_valid_data(self):
        return {
            'backend_id': self.mocked_tenant.id,
            'resource_type': 'OpenStack.Tenant',
            'project': structure_factories.ProjectFactory.get_url(self.project)
        }
