import mock
from django.test import override_settings
from novaclient import exceptions as nova_exceptions
from rest_framework import status, test

from nodeconductor.structure.models import CustomerRole
from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.tests.test_import import BaseBackendTestCase

from .. import models, views
from ..apps import OpenStackConfig
from . import factories


class BaseFloatingIpInstanceProvisionTest(test.APITransactionTestCase):
    def setUp(self):
        self.customer = structure_factories.CustomerFactory()

        self.settings = structure_factories.ServiceSettingsFactory(
            customer=self.customer, type=OpenStackConfig.service_name)
        self.service = factories.OpenStackServiceFactory(customer=self.customer, settings=self.settings)

        self.image = factories.ImageFactory(settings=self.settings, min_disk=10240, min_ram=1024)
        self.flavor = factories.FlavorFactory(settings=self.settings)

        self.project = structure_factories.ProjectFactory(customer=self.customer)
        self.link = factories.OpenStackServiceProjectLinkFactory(service=self.service, project=self.project)
        self.tenant = factories.TenantFactory(service_project_link=self.link)

        self.customer_owner = structure_factories.UserFactory()
        self.customer.add_user(self.customer_owner, CustomerRole.OWNER)

        self.client.force_authenticate(user=self.customer_owner)
        self.url = factories.InstanceFactory.get_list_url()

    def get_valid_data(self, **extra):
        default = {
            'service_project_link': factories.OpenStackServiceProjectLinkFactory.get_url(self.link),
            'tenant': factories.TenantFactory.get_url(self.tenant),
            'flavor': factories.FlavorFactory.get_url(self.flavor),
            'image': factories.ImageFactory.get_url(self.image),
            'name': 'Valid name',
            'system_volume_size': self.image.min_disk
        }
        default.update(extra)
        return default


class FixedIpInstanceProvisionTest(BaseFloatingIpInstanceProvisionTest):
    def test_user_can_provision_instance_with_internal_ip_only(self):
        response = self.client.post(self.url, self.get_valid_data(
            skip_external_ip_assignment=True
        ))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)


class ManualFloatingIpInstanceProvisionTest(BaseFloatingIpInstanceProvisionTest):
    def test_user_can_provision_instance_with_manual_external_ip(self):
        self.floating_ip = factories.FloatingIPFactory(
            service_project_link=self.link, tenant=self.tenant, status='DOWN')
        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_user_can_not_provision_instance_if_external_ip_is_not_available(self):
        self.floating_ip = factories.FloatingIPFactory(
            service_project_link=self.link, tenant=self.tenant, status='ACTIVE')
        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['floating_ip'], ['Floating IP status must be DOWN.'])

    def test_user_can_not_provision_instance_if_external_ip_belongs_to_another_tenant(self):
        another_tenant = factories.TenantFactory(service_project_link=self.link)
        self.floating_ip = factories.FloatingIPFactory(
            service_project_link=self.link, tenant=another_tenant, status='DOWN')
        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['floating_ip'], ['Floating IP must belong to the same tenant.'])

    def get_response(self):
        return self.client.post(self.url, self.get_valid_data(
            floating_ip=factories.FloatingIPFactory.get_url(self.floating_ip),
        ))


class AutomaticFloatingIpInstanceProvisionTest(BaseFloatingIpInstanceProvisionTest):

    def test_user_can_provision_instance_with_automatic_external_ip(self):
        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_user_can_not_provision_instance_if_tenant_quota_exceeded(self):
        quota = self.tenant.quotas.get(name='floating_ip_count')
        quota.limit = quota.usage
        quota.save()

        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['tenant'], ['Can not allocate floating IP - quota has been filled.'])

    def test_user_can_not_provision_instance_if_tenant_is_not_in_stable_state(self):
        self.tenant.state = models.Tenant.States.ERRED
        self.tenant.save()

        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['tenant'], ['Can not assign external IP if tenant is not in stable state.'])

    def test_user_can_not_provision_instance_if_tenant_does_not_have_external_network(self):
        self.tenant.external_network_id = ''
        self.tenant.save()

        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data['tenant'], ['Can not assign external IP if tenant has no external network.'])

    def get_response(self):
        return self.client.post(self.url, self.get_valid_data(
            skip_external_ip_assignment=False
        ))


views.InstanceViewSet.async_executor = False


class BaseInstanceDeletionTest(BaseBackendTestCase):
    def setUp(self):
        super(BaseInstanceDeletionTest, self).setUp()
        self.instance = factories.InstanceFactory(
            state=models.Instance.States.OFFLINE,
            backend_id='VALID_ID'
        )
        self.url = factories.InstanceFactory.get_url(self.instance)

        for index, volume in enumerate(self.instance.volumes.all()):
            volume.backend_id = 'volume-%s' % index
            volume.state = models.Volume.States.OK
            volume.save(update_fields=['backend_id', 'state'])

        self.mocked_nova().servers.get.side_effect = nova_exceptions.NotFound(code=404)

        mocked_volume = mock.Mock()
        mocked_volume.status = 'available'
        self.mocked_cinder().volumes.get.return_value = mocked_volume

    def delete_instance(self, data=None):
        staff = structure_factories.UserFactory(is_staff=True)
        self.client.force_authenticate(user=staff)

        with override_settings(CELERY_ALWAYS_EAGER=True, CELERY_EAGER_PROPAGATES_EXCEPTIONS=True):
            response = self.client.delete(self.url, data)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)

    def assert_quotas_diff(self, old_quotas, new_quotas, name, change):
        self.assertEqual(new_quotas.get(name=name).usage,
                         old_quotas.get(name=name).usage + change)


class InstanceDeletedWithVolumesTest(BaseInstanceDeletionTest):
    def test_nova_methods_are_called(self):
        self.delete_instance()

        nova = self.mocked_nova()
        nova.servers.delete.assert_called_once_with(self.instance.backend_id)
        nova.servers.get.assert_called_once_with(self.instance.backend_id)
        self.assertFalse(nova.volumes.delete_server_volume.called)

    def test_database_models_deleted(self):
        self.delete_instance()

        self.assertFalse(models.Instance.objects.filter(id=self.instance.id).exists())
        for volume in self.instance.volumes.all():
            self.assertFalse(models.Volume.objects.filter(id=volume.id).exists())

    def test_quotas_updated(self):
        old_quotas = self.instance.tenant.quotas

        self.delete_instance()

        self.instance.tenant.refresh_from_db()
        new_quotas = self.instance.tenant.quotas
        self.assert_quotas_diff(old_quotas, new_quotas, 'instances', -1)
        self.assert_quotas_diff(old_quotas, new_quotas, 'vcpu', -self.instance.cores)
        self.assert_quotas_diff(old_quotas, new_quotas, 'ram', -self.instance.ram)

        self.assert_quotas_diff(old_quotas, new_quotas, 'volumes', -2)
        total_volume_size = sum(volume.size for volume in self.instance.volumes.all())
        self.assert_quotas_diff(old_quotas, new_quotas, 'storage', -total_volume_size)


class InstanceDeletedWithoutVolumesTest(BaseInstanceDeletionTest):

    def test_backend_methods_are_called(self):
        self.delete_instance({
            'delete_volumes': False
        })

        nova = self.mocked_nova()
        cinder = self.mocked_cinder()

        nova.volumes.delete_server_volume.assert_has_calls([
            mock.call(self.instance.backend_id, volume.backend_id)
            for volume in self.instance.volumes.all()
        ])

        cinder.volumes.get.assert_has_calls([
            mock.call(volume.backend_id)
            for volume in self.instance.volumes.all()
        ])

        nova.servers.delete.assert_called_once_with(self.instance.backend_id)
        nova.servers.get.assert_called_once_with(self.instance.backend_id)

    def test_volume_model_is_not_deleted(self):
        self.delete_instance({
            'delete_volumes': False
        })

        self.assertFalse(models.Instance.objects.filter(id=self.instance.id).exists())
        for volume in self.instance.volumes.all():
            self.assertTrue(models.Volume.objects.filter(id=volume.id).get())

    def test_quotas_updated(self):
        old_quotas = self.instance.tenant.quotas

        self.delete_instance()

        self.instance.tenant.refresh_from_db()
        new_quotas = self.instance.tenant.quotas
        self.assert_quotas_diff(old_quotas, new_quotas, 'instances', -1)
        self.assert_quotas_diff(old_quotas, new_quotas, 'vcpu', -self.instance.cores)
        self.assert_quotas_diff(old_quotas, new_quotas, 'ram', -self.instance.ram)

        self.assert_quotas_diff(old_quotas, new_quotas, 'volumes', 0)
        self.assert_quotas_diff(old_quotas, new_quotas, 'storage', 0)
