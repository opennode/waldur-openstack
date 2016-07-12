from django.test import TestCase

from .. import factories


class FloatingIpHandlersTest(TestCase):

    def test_floating_ip_count_quota_increases_on_floating_ip_creation(self):
        tenant = factories.TenantFactory()
        factories.FloatingIPFactory(
            service_project_link=tenant.service_project_link, tenant=tenant, status='UP')
        self.assertEqual(tenant.quotas.get(name='floating_ip_count').usage, 1)

    def test_floating_ip_count_quota_changes_on_floating_ip_status_change(self):
        tenant = factories.TenantFactory()
        floating_ip = factories.FloatingIPFactory(
            service_project_link=tenant.service_project_link, tenant=tenant, status='DOWN')
        self.assertEqual(tenant.quotas.get(name='floating_ip_count').usage, 0)

        floating_ip.status = 'UP'
        floating_ip.save()
        self.assertEqual(tenant.quotas.get(name='floating_ip_count').usage, 1)

        floating_ip.status = 'DOWN'
        floating_ip.save()
        self.assertEqual(tenant.quotas.get(name='floating_ip_count').usage, 0)
