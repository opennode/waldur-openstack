from rest_framework import test

from nodeconductor.structure.models import CustomerRole
from nodeconductor.structure.tests import factories as structure_factories
from nodeconductor_openstack.tests import factories


class ResourceQuotasTest(test.APITransactionTestCase):

    def setUp(self):
        self.user = structure_factories.UserFactory()
        self.customer = structure_factories.CustomerFactory()
        self.customer.add_user(self.user, CustomerRole.OWNER)
        self.project = structure_factories.ProjectFactory(customer=self.customer)

    def test_auto_quotas_update(self):
        settings = structure_factories.ServiceSettingsFactory(customer=self.customer, shared=False)
        service = factories.OpenStackServiceFactory(customer=self.customer, settings=settings)

        data = {'cores': 4, 'ram': 1024, 'disk': 20480}

        service_project_link = factories.OpenStackServiceProjectLinkFactory(service=service, project=self.project)
        tenant = factories.TenantFactory(service_project_link=service_project_link)
        resource = factories.InstanceFactory(service_project_link=service_project_link, cores=data['cores'])

        self.assertEqual(tenant.quotas.get(name='instances').usage, 1)
        self.assertEqual(tenant.quotas.get(name='vcpu').usage, data['cores'])
        self.assertEqual(tenant.quotas.get(name='ram').usage, 0)
        self.assertEqual(tenant.quotas.get(name='storage').usage, 0)

        resource.ram = data['ram']
        resource.disk = data['disk']
        resource.save()

        self.assertEqual(tenant.quotas.get(name='ram').usage, data['ram'])
        self.assertEqual(tenant.quotas.get(name='storage').usage, data['disk'])

        resource.delete()
        self.assertEqual(tenant.quotas.get(name='instances').usage, 0)
        self.assertEqual(tenant.quotas.get(name='vcpu').usage, 0)
        self.assertEqual(tenant.quotas.get(name='ram').usage, 0)
        self.assertEqual(tenant.quotas.get(name='storage').usage, 0)
