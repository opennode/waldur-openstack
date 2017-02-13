from ddt import ddt, data
from rest_framework import test, status

from nodeconductor_openstack.openstack_tenant import models

from . import factories, fixtures


@ddt
class SnapshotPermissionsTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()

    def _make_restore_request(self):
        url = factories.SnapshotFactory.get_url(snapshot=self.fixture.openstack_snapshot, action='restore')
        request_data = {
            'name': '/dev/sdb1',
        }

        response = self.client.post(url, request_data)
        return response

    @data('global_support', 'customer_support', 'project_support')
    def test_user_cannot_restore_snapshot_if_he_has_not_admin_access(self, user):
        self.client.force_authenticate(user=getattr(self.fixture, user))

        response = self._make_restore_request()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @data('staff', 'owner', 'admin', 'manager')
    def test_user_can_restore_snapshot_only_if_he_has_admin_access(self, user):
        self.client.force_authenticate(user=getattr(self.fixture, user))

        response = self._make_restore_request()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @data('user')
    def test_user_cannot_restore_snapshot_if_he_has_no_project_level_permissions(self, user):
        self.client.force_authenticate(user=getattr(self.fixture, user))

        response = self._make_restore_request()

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @data('user')
    def test_user_cannot_see_snapshot_restoration_if_has_no_project_level_permissions(self, user):
        self.client.force_authenticate(user=getattr(self.fixture, user))
        self.fixture.openstack_snapshot

        url = factories.SnapshotFactory.get_list_url()
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)


class SnapshotRestoreTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()
        self.client.force_authenticate(self.fixture.owner)

    def test_snapshot_restore_creates_snapshot_restoration(self):
        url = factories.SnapshotFactory.get_url(snapshot=self.fixture.openstack_snapshot, action='restore')
        request_data = {
            'name': '/dev/sdb1',
        }

        response = self.client.post(url, request_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(models.SnapshotRestoration.objects.count(), 1)
        restoration = models.SnapshotRestoration.objects.first()
        restored_volume = models.Volume.objects.exclude(pk=self.fixture.openstack_snapshot.source_volume.pk).first()
        self.assertEqual(self.fixture.openstack_snapshot, restoration.snapshot)
        self.assertEqual(restored_volume, restoration.volume)

    def test_user_is_able_to_specify_a_name_of_the_restored_volume(self):
        url = factories.SnapshotFactory.get_url(snapshot=self.fixture.openstack_snapshot, action='restore')

        expected_name = 'C:/ Drive'
        request_data = {
            'name': expected_name,
        }

        response = self.client.post(url, request_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_volume = models.SnapshotRestoration.objects.first().volume
        self.assertIn(expected_name, created_volume.name)
        self.assertEqual(response.data['uuid'], created_volume.uuid.hex)
        self.assertEqual(response.data['name'], created_volume.name)

    def test_user_is_able_to_specify_a_description_of_the_restored_volume(self):
        url = factories.SnapshotFactory.get_url(snapshot=self.fixture.openstack_snapshot, action='restore')

        expected_description = 'Restored after blue screen.'
        request_data = {
            'name': '/dev/sdb2',
            'description': expected_description,
        }

        response = self.client.post(url, request_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_volume = models.SnapshotRestoration.objects.first().volume
        self.assertIn(expected_description, created_volume.description)
        self.assertEqual(response.data['uuid'], created_volume.uuid.hex)
        self.assertEqual(response.data['description'], created_volume.description)

    def test_restore_is_not_available_if_snapshot_is_not_in_OK_state(self):
        snapshot = factories.SnapshotFactory(
            service_project_link=self.fixture.openstack_tenant_spl,
            source_volume=self.fixture.openstack_volume,
            state=models.Snapshot.States.ERRED)
        url = factories.SnapshotFactory.get_url(snapshot=snapshot, action='restore')

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_restore_cannot_be_made_if_volume_exceeds_quota(self):
        quota = self.fixture.openstack_tenant_service_settings.quotas.get(name='volumes')
        quota.limit = quota.usage
        quota.save()
        snapshot = self.fixture.openstack_snapshot
        expected_volumes_amount = models.Volume.objects.count()

        url = factories.SnapshotFactory.get_url(snapshot=snapshot, action='restore')
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.States.OK)
        self.assertEqual(expected_volumes_amount, models.Volume.objects.count())


class SnapshotRetrieveTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()
        self.client.force_authenticate(self.fixture.owner)

    def test_a_list_of_restored_volumes_are_displayed_at_snapshot_endpoint(self):
        snapshot_restoration = factories.SnapshotRestorationFactory(snapshot=self.fixture.openstack_snapshot)
        url = factories.SnapshotFactory.get_url(snapshot=snapshot_restoration.snapshot)

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['uuid'], snapshot_restoration.snapshot.uuid.hex)
        self.assertIn('restorations', response.data)
        self.assertEquals(len(response.data['restorations']), 1)

