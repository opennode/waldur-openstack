from rest_framework import test, status

from nodeconductor_openstack.openstack_tenant import models

from . import factories, fixtures


class SnapshotRestoreTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()
        self.client.force_authenticate(self.fixture.owner)

    def test_snapshot_restore_created_snapshot_restoration_object(self):
        url = factories.SnapshotFactory.get_url(snapshot=self.fixture.openstack_snapshot, action='restore')

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(models.SnapshotRestoration.objects.count(), 1)
        restoration = models.SnapshotRestoration.objects.first()
        self.assertEqual(self.fixture.openstack_snapshot, restoration.snapshot)
        self.assertEqual(self.fixture.openstack_snapshot.source_volume, restoration.volume)

    def test_user_is_able_to_specify_name_of_the_restored_volume(self):
        self.assertTrue(False)

    def test_user_is_able_to_specify_description_of_the_restored_volume(self):
        self.assertTrue(False)
