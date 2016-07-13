from django.test import TestCase
from mock import patch
from permission.utils.autodiscover import autodiscover

from nodeconductor.core import utils as core_utils
from nodeconductor.structure import models as structure_models
from nodeconductor.structure.tests import factories as structure_factories

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


@patch('nodeconductor.core.tasks.BackendMethodTask.delay')
class SshKeysHandlersTest(TestCase):

    def setUp(self):
        autodiscover()  # permissions could be not discovered in unittests
        self.user = structure_factories.UserFactory()
        self.ssh_key = structure_factories.SshPublicKeyFactory(user=self.user)
        self.tenant = factories.TenantFactory()

    def test_ssh_key_will_be_removed_if_user_lost_connection_to_tennant(self, mocked_task_call):
        project = self.tenant.service_project_link.project
        project.add_user(self.user, structure_models.ProjectRole.ADMINISTRATOR)
        project.remove_user(self.user)

        serialized_tenant = core_utils.serialize_instance(self.tenant)
        mocked_task_call.assert_called_once_with(
            serialized_tenant, 'remove_ssh_key_from_tenant', self.ssh_key.name, self.ssh_key.fingerprint)

    def test_ssh_key_will_not_be_removed_if_user_still_has_connection_to_tennant(self, mocked_task_call):
        project = self.tenant.service_project_link.project
        project.add_user(self.user, structure_models.ProjectRole.ADMINISTRATOR)
        project.customer.add_user(self.user, structure_models.CustomerRole.OWNER)
        project.remove_user(self.user)

        self.assertEqual(mocked_task_call.call_count, 0)

    def test_ssh_key_will_be_deleted_from_tenant_on_user_deletion(self, mocked_task_call):
        project = self.tenant.service_project_link.project
        project.add_user(self.user, structure_models.ProjectRole.ADMINISTRATOR)
        self.user.delete()

        serialized_tenant = core_utils.serialize_instance(self.tenant)
        mocked_task_call.assert_called_once_with(
            serialized_tenant, 'remove_ssh_key_from_tenant', self.ssh_key.name, self.ssh_key.fingerprint)

    def test_ssh_key_will_be_deleted_from_tenant_on_ssh_key_deletion(self, mocked_task_call):
        project = self.tenant.service_project_link.project
        project.add_user(self.user, structure_models.ProjectRole.ADMINISTRATOR)
        self.ssh_key.delete()

        serialized_tenant = core_utils.serialize_instance(self.tenant)
        mocked_task_call.assert_called_once_with(
            serialized_tenant, 'remove_ssh_key_from_tenant', self.ssh_key.name, self.ssh_key.fingerprint)


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
