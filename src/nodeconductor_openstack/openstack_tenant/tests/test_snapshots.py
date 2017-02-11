from rest_framework import test, status

from nodeconductor_openstack.openstack_tenant import models

from . import factories, fixtures


class SnapshotRestoreTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()
        self.client.force_authenticate(self.fixture.owner)

    def test_snapshot_restore_creates_snapshot_restoration(self):
        url = factories.SnapshotFactory.get_url(snapshot=self.fixture.openstack_snapshot, action='restore')

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(models.SnapshotRestoration.objects.count(), 1)
        restoration = models.SnapshotRestoration.objects.first()
        restored_volume = models.Volume.objects.exclude(pk=self.fixture.openstack_snapshot.source_volume.pk).first()
        self.assertEqual(self.fixture.openstack_snapshot, restoration.snapshot)
        self.assertEqual(restored_volume, restoration.volume)
        self.assertIn(self.fixture.openstack_snapshot.name, restoration.volume.name)
        self.assertIn(self.fixture.openstack_snapshot.uuid.hex, restoration.volume.description)

    def test_user_is_able_to_specify_a_name_of_the_restored_volume(self):
        url = factories.SnapshotFactory.get_url(snapshot=self.fixture.openstack_snapshot, action='restore')

        expected_name = 'C:/ Drive'
        request_data = {
            'name': expected_name
        }

        response = self.client.post(url, request_data)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        restoration = models.SnapshotRestoration.objects.first()
        self.assertIn(expected_name, restoration.volume.name)

    def test_user_is_able_to_specify_a_description_of_the_restored_volume(self):
        url = factories.SnapshotFactory.get_url(snapshot=self.fixture.openstack_snapshot, action='restore')

        expected_description = 'Restored after blue screen.'
        request_data = {
            'description': expected_description
        }

        response = self.client.post(url, request_data)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        restoration = models.SnapshotRestoration.objects.first()
        self.assertIn(expected_description, restoration.volume.description)

    def test_restore_is_not_available_if_snapshot_is_not_in_OK_state(self):
        snapshot = factories.SnapshotFactory(
            service_project_link=self.fixture.openstack_tenant_spl,
            source_volume=self.fixture.openstack_volume,
            state=models.Snapshot.States.ERRED)
        url = factories.SnapshotFactory.get_url(snapshot=snapshot, action='restore')

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)


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
        restored_volume = response.data['restorations'][0]
        self.assertEqual(restored_volume['volume_name'], snapshot_restoration.volume.name)
        self.assertEqual(restored_volume['volume_state'], snapshot_restoration.volume.state)
        self.assertEqual(restored_volume['volume_runtime_state'], snapshot_restoration.volume.runtime_state)
        self.assertEqual(restored_volume['volume_size'], snapshot_restoration.volume.size)
        self.assertEqual(restored_volume['volume_device'], snapshot_restoration.volume.device)

