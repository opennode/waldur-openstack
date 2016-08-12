import datetime
import mock
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


class TenantImportTestCase(BaseImportTestCase):
    def setUp(self):
        super(TenantImportTestCase, self).setUp()
        self.mocked_tenant = mock.Mock()
        self.mocked_tenant.id = '1'
        self.mocked_tenant.name = 'PRD'
        self.mocked_tenant.description = 'Production tenant'

        self.mocked_keystone().tenants.list.return_value = [self.mocked_tenant]
        self.mocked_keystone().tenants.get.return_value = self.mocked_tenant

    def test_user_can_not_list_importable_tenants_from_non_admin_provider(self):
        self.service.settings.options['is_admin'] = False
        self.service.settings.save()

        response = self.client.get(self.url)
        self.assertEqual(response.data, [])

    def test_user_can_not_import_tenants_from_non_admin_provider(self):
        self.service.settings.options['is_admin'] = False
        self.service.settings.save()

        response = self.client.post(self.url, self.get_valid_data())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

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


class InstanceImportTestCase(BaseImportTestCase):
    def setUp(self):
        super(InstanceImportTestCase, self).setUp()
        self.tenant = factories.TenantFactory(service_project_link=self.link, backend_id='VALID_ID')

        self.mocked_flavor = mock.Mock()
        self.mocked_flavor.name = 'standard'
        self.mocked_flavor.disk = 10240
        self.mocked_flavor.ram = 2048
        self.mocked_flavor.vcpus = 3

        self.mocked_instance = mock.Mock()
        self.mocked_instance.id = '1'
        self.mocked_instance.name = 'Webserver'
        self.mocked_instance.status = 'ACTIVE'
        self.mocked_instance.flavor = {'id': 1}
        self.mocked_instance.addresses = {}
        self.mocked_instance.security_groups = []
        self.mocked_instance.created = datetime.datetime.now().isoformat()
        del self.mocked_instance.fault

        self.mocked_nova().flavors.get.return_value = self.mocked_flavor
        self.mocked_nova().servers.get.return_value = self.mocked_instance
        self.mocked_nova().servers.list.return_value = [self.mocked_instance]

    def test_user_can_list_importable_instances(self):
        response = self.client.get(self.url, {
            'tenant_uuid': self.tenant.uuid.hex,
            'resource_type': 'OpenStack.Instance'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data, [{
            'id': self.mocked_instance.id,
            'name': self.mocked_instance.name,
            'runtime_state': self.mocked_instance.status,
            'type': 'OpenStack.Instance'
        }])

    def test_user_can_import_instance(self):
        response = self.client.post(self.url, {
            'backend_id': self.mocked_instance.id,
            'resource_type': 'OpenStack.Instance',
            'tenant': factories.TenantFactory.get_url(self.tenant),
            'project': structure_factories.ProjectFactory.get_url(self.project)
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        instance = models.Instance.objects.get(uuid=response.data['uuid'])
        self.assertEqual(instance.tenant, self.tenant)
        self.assertEqual(instance.service_project_link, self.link)
        self.assertEqual(instance.name, self.mocked_instance.name)
        self.assertEqual(instance.backend_id, self.mocked_instance.id)
        self.assertEqual(instance.state, models.Instance.States.ONLINE)

        self.assertEqual(instance.flavor_name, self.mocked_flavor.name)
        self.assertEqual(instance.flavor_disk, self.mocked_flavor.disk)
        self.assertEqual(instance.cores, self.mocked_flavor.vcpus)
        self.assertEqual(instance.ram, self.mocked_flavor.ram)


class VolumeImportTestCase(BaseImportTestCase):
    def setUp(self):
        super(VolumeImportTestCase, self).setUp()
        self.tenant = factories.TenantFactory(service_project_link=self.link, backend_id='VALID_ID')
        self.mocked_volume = mock.Mock()
        self.mocked_volume.id = '1'
        self.mocked_volume.size = 10
        self.mocked_volume.display_name = 'Webserver data volume'
        self.mocked_volume.status = 'AVAILABLE'
        self.mocked_volume.metadata = {}
        del self.mocked_volume.volume_image_metadata

        self.mocked_cinder().volumes.list.return_value = [self.mocked_volume]
        self.mocked_cinder().volumes.get.return_value = self.mocked_volume

    def test_user_can_list_importable_volumes(self):
        response = self.client.get(self.url, {
            'tenant_uuid': self.tenant.uuid.hex,
            'resource_type': 'OpenStack.Volume'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data, [{
            'id': self.mocked_volume.id,
            'name': self.mocked_volume.display_name,
            'size': self.mocked_volume.size * 1024,
            'runtime_state': self.mocked_volume.status,
            'type': 'OpenStack.Volume'
        }])

    def test_user_can_import_volume(self):
        response = self.client.post(self.url, {
            'backend_id': self.mocked_volume.id,
            'resource_type': 'OpenStack.Volume',
            'tenant': factories.TenantFactory.get_url(self.tenant),
            'project': structure_factories.ProjectFactory.get_url(self.project)
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        volume = models.Volume.objects.get(uuid=response.data['uuid'])
        self.assertEqual(volume.tenant, self.tenant)
        self.assertEqual(volume.service_project_link, self.link)
        self.assertEqual(volume.name, self.mocked_volume.display_name)
        self.assertEqual(volume.size, self.mocked_volume.size * 1024)
        self.assertEqual(volume.backend_id, self.mocked_volume.id)
        self.assertEqual(volume.state, models.Volume.States.OK)
        self.assertEqual(volume.runtime_state, self.mocked_volume.status)
