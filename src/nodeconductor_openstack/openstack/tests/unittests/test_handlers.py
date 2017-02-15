from django.test import TestCase
from mock import patch
from permission.utils.autodiscover import autodiscover

from nodeconductor.core import utils as core_utils
from nodeconductor.structure import models as structure_models
from nodeconductor.structure.tests import factories as structure_factories

from .. import factories


@patch('nodeconductor.core.tasks.BackendMethodTask.delay')
class SshKeysHandlersTest(TestCase):

    def setUp(self):
        autodiscover()  # permissions could be not discovered in unittests
        self.user = structure_factories.UserFactory()
        self.ssh_key = structure_factories.SshPublicKeyFactory(user=self.user)
        self.tenant = factories.TenantFactory()

    def test_ssh_key_will_be_removed_if_user_lost_connection_to_tenant(self, mocked_task_call):
        project = self.tenant.service_project_link.project
        project.add_user(self.user, structure_models.ProjectRole.ADMINISTRATOR)
        project.remove_user(self.user)

        serialized_tenant = core_utils.serialize_instance(self.tenant)
        mocked_task_call.assert_called_once_with(
            serialized_tenant, 'remove_ssh_key_from_tenant', self.ssh_key.name, self.ssh_key.fingerprint)

    def test_ssh_key_will_not_be_removed_if_user_still_has_connection_to_tenant(self, mocked_task_call):
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


class TenantChangePasswordTest(TestCase):

    def test_service_settings_password_updates_when_tenant_user_password_changes(self):
        tenant = factories.TenantFactory()
        service_settings = structure_models.ServiceSettings.objects.first()
        service_settings.scope = tenant
        service_settings.password = tenant.user_password
        service_settings.save()

        new_password = 'new_password'

        tenant.user_password = new_password
        tenant.save()
        service_settings.refresh_from_db()
        self.assertEqual(service_settings.password, new_password)
