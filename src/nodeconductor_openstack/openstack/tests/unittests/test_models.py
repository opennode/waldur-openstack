from ddt import ddt, data
from django.test import TestCase

from nodeconductor.structure import models as structure_models
from nodeconductor_assembly_waldur.packages.tests import factories as packages_factories
from nodeconductor_assembly_waldur.packages import models as packages_models

from .. import factories


@ddt
class TenantTest(TestCase):
    def setUp(self):
        self.tenant = factories.TenantFactory()

    def test_quota_format_returns_integer_for_vcpu_quota(self):
        result = self.tenant.format_quota(self.tenant.Quotas.vcpu.name, 10.0)

        self.assertEqual(result, 10)

    @data('ram', 'storage')
    def test_quota_format_returns_units_for_storage_quotas(self, name):
        result = self.tenant.format_quota(name, 15 * 1024)

        self.assertEqual(result, '15 GB')

    def test_set_package_sets_tenant_quota(self):
        template = packages_factories.PackageTemplateFactory()

        self.tenant.set_package(template)

        components = {c.type: c.amount for c in template.components.all()}
        for quota_name, component_type in packages_models.OpenStackPackage.get_quota_to_component_mapping().items():
            self.assertEquals(self.tenant.quotas.get(name=quota_name).limit, components[component_type])

    def test_set_package_sets_extra_configuration(self):
        template = packages_factories.PackageTemplateFactory()

        self.tenant.set_package(template)

        self.assertEquals(self.tenant.extra_configuration['package_name'], template.name)
        self.assertEquals(self.tenant.extra_configuration['package_uuid'], template.uuid.hex)
        self.assertEquals(self.tenant.extra_configuration['package_category'], template.get_category_display())
        for component in template.components.all():
            self.assertEquals(self.tenant.extra_configuration[component.type], component.amount)

    def test_set_package_create_service_settings_if_not_passed(self):
        template = packages_factories.PackageTemplateFactory()
        self.tenant.availability_zone = 'availability_zone'
        self.tenant.save()
        self.assertFalse(structure_models.ServiceSettings.objects.filter(scope=self.tenant).exists())

        self.tenant.set_package(template)

        self.assertTrue(structure_models.ServiceSettings.objects.filter(scope=self.tenant).exists())
        service_settings = structure_models.ServiceSettings.objects.get(scope=self.tenant)
        admin_settings = self.tenant.service_project_link.service.settings
        self.assertEquals(service_settings.domain, admin_settings.domain)
        self.assertEquals(service_settings.backend_url, admin_settings.backend_url)
        self.assertEquals(service_settings.options['availability_zone'], self.tenant.availability_zone)
        self.assertEquals(service_settings.options['tenant_id'], self.tenant.backend_id)
