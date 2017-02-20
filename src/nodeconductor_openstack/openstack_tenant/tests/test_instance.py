from ddt import ddt, data
import mock
import urllib

from cinderclient import exceptions as cinder_exceptions
from django.test import override_settings
from novaclient import exceptions as nova_exceptions
from rest_framework import status, test

from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.openstack.tests.test_backend import BaseBackendTestCase

from .. import models, views
from . import factories, fixtures


@ddt
class InstanceCreateTest(test.APITransactionTestCase):
    def setUp(self):
        self.openstack_tenant_fixture = fixtures.OpenStackTenantFixture()
        self.openstack_settings = self.openstack_tenant_fixture.openstack_tenant_service_settings
        self.openstack_spl = self.openstack_tenant_fixture.openstack_tenant_spl
        self.image = factories.ImageFactory(settings=self.openstack_settings, min_disk=10240, min_ram=1024)
        self.flavor = factories.FlavorFactory(settings=self.openstack_settings)

        self.client.force_authenticate(user=self.openstack_tenant_fixture.owner)
        self.url = factories.InstanceFactory.get_list_url()

    def get_valid_data(self, **extra):
        default = {
            'service_project_link': factories.OpenStackTenantServiceProjectLinkFactory.get_url(self.openstack_spl),
            'flavor': factories.FlavorFactory.get_url(self.flavor),
            'image': factories.ImageFactory.get_url(self.image),
            'name': 'Valid name',
            'system_volume_size': self.image.min_disk,
        }
        default.update(extra)
        return default

    def test_quotas_update(self):
        response = self.client.post(self.url, self.get_valid_data())

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = models.Instance.objects.get(uuid=response.data['uuid'])
        Quotas = self.openstack_settings.Quotas
        self.assertEqual(self.openstack_settings.quotas.get(name=Quotas.ram).usage, instance.ram)
        self.assertEqual(self.openstack_settings.quotas.get(name=Quotas.storage).usage, instance.disk)
        self.assertEqual(self.openstack_settings.quotas.get(name=Quotas.vcpu).usage, instance.cores)
        self.assertEqual(self.openstack_settings.quotas.get(name=Quotas.instances).usage, 1)

    @data('instances')
    def test_quota_validation(self, quota_name):
        self.openstack_settings.quotas.filter(name=quota_name).update(limit=0)
        response = self.client.post(self.url, self.get_valid_data())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_can_provision_instance_with_internal_ip_only(self):
        response = self.client.post(self.url, self.get_valid_data())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_user_can_provision_instance_with_manual_external_ip(self):
        self.floating_ip = factories.FloatingIPFactory(settings=self.openstack_settings, runtime_state='DOWN')
        response = self.client.post(self.url, self.get_valid_data(
            floating_ip=factories.FloatingIPFactory.get_url(self.floating_ip),
        ))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_user_can_not_provision_instance_if_external_ip_is_not_available(self):
        self.floating_ip = factories.FloatingIPFactory(settings=self.openstack_settings, runtime_state='ACTIVE')

        response = self.client.post(self.url, self.get_valid_data(
            floating_ip=factories.FloatingIPFactory.get_url(self.floating_ip),
        ))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['floating_ip'], ['Floating IP runtime_state must be DOWN.'])

    def test_user_can_not_provision_instance_if_external_ip_belongs_to_another_service_project_link(self):
        another_settings = factories.OpenStackTenantServiceSettingsFactory()
        floating_ip = factories.FloatingIPFactory(settings=another_settings, runtime_state='DOWN')

        response = self.client.post(self.url, self.get_valid_data(
            floating_ip=factories.FloatingIPFactory.get_url(floating_ip),
        ))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['floating_ip'], ['Floating IP must belong to the same service settings.'])

    def test_user_can_not_provision_instance_if_tenant_quota_exceeded(self):
        quota = self.openstack_settings.quotas.get(name='floating_ip_count')
        quota.limit = quota.usage
        quota.save()

        response = self.client.post(self.url, self.get_valid_data(
            allocate_floating_ip=True
        ))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['allocate_floating_ip'],
                         ['Can not allocate floating IP - quota has been filled.'])


class InstanceDeleteTest(BaseBackendTestCase):
    def setUp(self):
        super(InstanceDeleteTest, self).setUp()
        self.instance = factories.InstanceFactory(
            state=models.Instance.States.OK,
            runtime_state=models.Instance.RuntimeStates.SHUTOFF,
            backend_id='VALID_ID'
        )
        self.instance.increase_backend_quotas_usage()
        self.mocked_nova().servers.get.side_effect = nova_exceptions.NotFound(code=404)
        views.InstanceViewSet.async_executor = False

    def tearDown(self):
        super(InstanceDeleteTest, self).tearDown()
        views.InstanceViewSet.async_executor = True

    def mock_volumes(self, delete_data_volume=True):
        self.data_volume = self.instance.volumes.get(bootable=False)
        self.data_volume.backend_id = 'DATA_VOLUME_ID'
        self.data_volume.state = models.Volume.States.OK
        self.data_volume.save()
        self.data_volume.increase_backend_quotas_usage()

        self.system_volume = self.instance.volumes.get(bootable=True)
        self.system_volume.backend_id = 'SYSTEM_VOLUME_ID'
        self.system_volume.state = models.Volume.States.OK
        self.system_volume.save()
        self.system_volume.increase_backend_quotas_usage()

        def get_volume(backend_id):
            if not delete_data_volume and backend_id == self.data_volume.backend_id:
                mocked_volume = mock.Mock()
                mocked_volume.status = 'available'
                return mocked_volume
            raise cinder_exceptions.NotFound(code=404)

        self.mocked_cinder().volumes.get.side_effect = get_volume

    def delete_instance(self, query_params=None):
        staff = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=staff)

        url = factories.InstanceFactory.get_url(self.instance)
        if query_params:
            url += '?' + urllib.urlencode(query_params)

        with override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True):
            response = self.client.delete(url)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)

    def assert_quota_usage(self, quotas, name, value):
        self.assertEqual(quotas.get(name=name).usage, value)

    def test_nova_methods_are_called_if_instance_is_deleted_with_volumes(self):
        self.mock_volumes(True)
        self.delete_instance()

        nova = self.mocked_nova()
        nova.servers.delete.assert_called_once_with(self.instance.backend_id)
        nova.servers.get.assert_called_once_with(self.instance.backend_id)

        self.assertFalse(nova.volumes.delete_server_volume.called)

    def test_database_models_deleted(self):
        self.mock_volumes(True)
        self.delete_instance()

        self.assertFalse(models.Instance.objects.filter(id=self.instance.id).exists())
        for volume in self.instance.volumes.all():
            self.assertFalse(models.Volume.objects.filter(id=volume.id).exists())

    def test_quotas_updated_if_instance_is_deleted_with_volumes(self):
        self.mock_volumes(True)
        self.delete_instance()

        self.instance.service_project_link.service.settings.refresh_from_db()
        quotas = self.instance.service_project_link.service.settings.quotas

        self.assert_quota_usage(quotas, 'instances', 0)
        self.assert_quota_usage(quotas, 'vcpu', 0)
        self.assert_quota_usage(quotas, 'ram', 0)

        self.assert_quota_usage(quotas, 'volumes', 0)
        self.assert_quota_usage(quotas, 'storage', 0)

    def test_backend_methods_are_called_if_instance_is_deleted_without_volumes(self):
        self.mock_volumes(False)
        self.delete_instance({
            'delete_volumes': False
        })

        nova = self.mocked_nova()
        nova.volumes.delete_server_volume.assert_called_once_with(
            self.instance.backend_id, self.data_volume.backend_id)

        nova.servers.delete.assert_called_once_with(self.instance.backend_id)
        nova.servers.get.assert_called_once_with(self.instance.backend_id)

    def test_system_volume_is_deleted_but_data_volume_exists(self):
        self.mock_volumes(False)
        self.delete_instance({
            'delete_volumes': False
        })

        self.assertFalse(models.Instance.objects.filter(id=self.instance.id).exists())
        self.assertTrue(models.Volume.objects.filter(id=self.data_volume.id).exists())
        self.assertFalse(models.Volume.objects.filter(id=self.system_volume.id).exists())

    def test_quotas_updated_if_instance_is_deleted_without_volumes(self):
        self.mock_volumes(False)
        self.delete_instance({
            'delete_volumes': False
        })

        settings = self.instance.service_project_link.service.settings
        settings.refresh_from_db()

        self.assert_quota_usage(settings.quotas, 'instances', 0)
        self.assert_quota_usage(settings.quotas, 'vcpu', 0)
        self.assert_quota_usage(settings.quotas, 'ram', 0)

        self.assert_quota_usage(settings.quotas, 'volumes', 1)
        self.assert_quota_usage(settings.quotas, 'storage', self.data_volume.size)

    def test_instance_cannot_be_deleted_if_it_has_backups(self):
        self.instance = factories.InstanceFactory(
            state=models.Instance.States.OK,
            runtime_state=models.Instance.RuntimeStates.SHUTOFF,
            backend_id='VALID_ID'
        )
        staff = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=staff)

        factories.BackupFactory(instance=self.instance, state=models.Backup.States.OK)
        url = factories.InstanceFactory.get_url(self.instance)

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.data)