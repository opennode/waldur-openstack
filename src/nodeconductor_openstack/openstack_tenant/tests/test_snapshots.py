from rest_framework import test, status

from nodeconductor_openstack.openstack_tenant import models

from . import factories, fixtures


class SnapshotRestoreTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()
        self.client.force_authenticate(self.fixture.owner)
        self.url = factories.SnapshotFactory.get_url(snapshot=self.fixture.openstack_snapshot, action='restore')

    def test_snapshot_restore_created_snapshot_restoration_object(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(models.SnapshotRestoration.objects.count(), 1)
        restoration = models.SnapshotRestoration.objects.first()
        restored_volume = models.Volume.objects.exclude(pk=self.fixture.openstack_snapshot.source_volume.pk).first()
        self.assertEqual(self.fixture.openstack_snapshot, restoration.snapshot)
        self.assertEqual(restored_volume, restoration.volume)
        self.assertIn(self.fixture.openstack_snapshot.name, restoration.volume.name)
        self.assertIn(self.fixture.openstack_snapshot.uuid.hex, restoration.volume.description)

    def test_user_is_able_to_specify_name_of_the_restored_volume(self):
        expected_name = 'C:/ Drive'
        request_data = {
            'name': expected_name
        }

        response = self.client.post(self.url, request_data)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        restoration = models.SnapshotRestoration.objects.first()
        self.assertIn(expected_name, restoration.volume.name)

    def test_user_is_able_to_specify_description_of_the_restored_volume(self):
        expected_description = 'Restored after blue screen.'
        request_data = {
            'description': expected_description
        }

        response = self.client.post(self.url, request_data)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        restoration = models.SnapshotRestoration.objects.first()
        self.assertIn(expected_description, restoration.volume.description)
