from ddt import ddt, data
from rest_framework import test, status

from nodeconductor.structure.models import ProjectRole
from nodeconductor.structure.tests import factories as structure_factories

from . import factories, fixtures
from .. import models


@ddt
class VolumeExtendTestCase(test.APITransactionTestCase):
    def setUp(self):
        self.admin = structure_factories.UserFactory()
        self.manager = structure_factories.UserFactory()
        self.staff = structure_factories.UserFactory(is_staff=True)
        self.admined_volume = factories.VolumeFactory(state=models.Volume.States.OK)

        admined_project = self.admined_volume.service_project_link.project
        admined_project.add_user(self.admin, ProjectRole.ADMINISTRATOR)
        admined_project.add_user(self.manager, ProjectRole.MANAGER)

    @data('admin', 'manager')
    def test_user_can_resize_size_of_volume_he_has_access_to(self, user):
        self.client.force_authenticate(getattr(self, user))
        new_size = self.admined_volume.size + 1024

        url = factories.VolumeFactory.get_url(self.admined_volume, action='extend')
        response = self.client.post(url, {'disk_size': new_size})
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)

        self.admined_volume.refresh_from_db()
        self.assertEqual(self.admined_volume.size, new_size)

    def test_user_can_not_extend_volume_if_resulting_quota_usage_is_greater_then_limit(self):
        self.client.force_authenticate(user=self.admin)
        settings = self.admined_volume.service_project_link.service.settings
        settings.set_quota_usage('storage', self.admined_volume.size)
        settings.set_quota_limit('storage', self.admined_volume.size + 512)

        new_size = self.admined_volume.size + 1024
        url = factories.VolumeFactory.get_url(self.admined_volume, action='extend')

        response = self.client.post(url, {'disk_size': new_size})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_user_can_not_extend_volume_if_volume_operation_is_performed(self):
        self.client.force_authenticate(user=self.admin)
        self.admined_volume.state = models.Volume.States.UPDATING
        self.admined_volume.save()

        new_size = self.admined_volume.size + 1024
        url = factories.VolumeFactory.get_url(self.admined_volume, action='extend')

        response = self.client.post(url, {'disk_size': new_size})
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.data)

    def test_user_can_not_extend_volume_if_volume_does_not_have_backend_id(self):
        self.client.force_authenticate(user=self.admin)
        self.admined_volume.backend_id = ''
        self.admined_volume.save()

        new_size = self.admined_volume.size + 1024
        url = factories.VolumeFactory.get_url(self.admined_volume, action='extend')

        response = self.client.post(url, {'disk_size': new_size})
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.data)


class VolumeAttachTestCase(test.APITransactionTestCase):
    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()
        self.volume = self.fixture.openstack_volume
        self.instance = self.fixture.openstack_instance
        self.url = factories.VolumeFactory.get_url(self.volume, action='attach')

    def get_response(self):
        self.client.force_authenticate(user=self.fixture.owner)
        payload = {'instance': factories.InstanceFactory.get_url(self.instance)}
        return self.client.post(self.url, payload)

    def test_user_can_attach_volume_to_instance(self):
        self.volume.state = models.Volume.States.OK
        self.volume.runtime_state = 'available'
        self.volume.save()

        self.instance.state = models.Instance.States.OK
        self.instance.runtime_state = models.Instance.RuntimeStates.SHUTOFF
        self.instance.save()

        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.data)

    def test_user_can_not_attach_erred_volume_to_instance(self):
        self.volume.state = models.Volume.States.ERRED
        self.volume.save()

        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_user_can_not_attach_used_volume_to_instance(self):
        self.volume.state = models.Volume.States.OK
        self.volume.runtime_state = 'in-use'
        self.volume.save()

        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_user_can_not_attach_volume_to_instance_in_other_tenant(self):
        self.volume.state = models.Volume.States.OK
        self.volume.runtime_state = 'available'
        self.volume.save()
        self.instance = factories.InstanceFactory()

        response = self.get_response()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class VolumeSnapshotTestCase(test.APITransactionTestCase):
    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()
        self.volume = self.fixture.openstack_volume
        self.url = factories.VolumeFactory.get_url(self.volume, action='snapshot')

    def test_user_can_create_volume_snapshot(self):
        self.volume.state = models.Volume.States.OK
        self.volume.runtime_state = 'available'
        self.volume.save()

        self.client.force_authenticate(self.fixture.owner)
        payload = {'name': '%s snapshot' % self.volume.name}

        response = self.client.post(self.url, data=payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
