from django.test import TestCase
from mock import patch

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


# TODO: Move this test to assembly.
@patch('nodeconductor_openstack.log.event_logger.openstack_tenant_quota.warning')
class QuotaThresholdBreachHandlerTest(TestCase):

    def setUp(self):
        self.tenant = factories.TenantFactory()
        self.quota = self.tenant.quotas.get(name='instances')

    def test_tenant_quota_warning_is_raised_on_threshold_breach(self, mocked_log_method):
        self.tenant.set_quota_usage(self.quota.name, self.quota.limit)
        mocked_log_method.assert_called_once()

    def test_tenant_quota_warning_is_raised_only_once(self, mocked_log_method):
        self.tenant.set_quota_usage(self.quota.name, self.quota.limit)
        self.tenant.set_quota_usage(self.quota.name, self.quota.limit + 1)
        mocked_log_method.assert_called_once()
