import datetime

import mock
from croniter import croniter
from ddt import ddt, data
from django.conf import settings
from nodeconductor.core.tests import helpers
from nodeconductor.structure.tests import factories as structure_factories
from pytz import timezone
from rest_framework import status
from rest_framework import test

from nodeconductor_openstack.openstack_tenant import models

from . import factories, fixtures


class BaseSnapshotScheduleTest(test.APITransactionTestCase):

    def setUp(self):
        self.fixture = fixtures.OpenStackTenantFixture()


class SnapshotScheduleActivateTest(BaseSnapshotScheduleTest):

    def setUp(self):
        super(SnapshotScheduleActivateTest, self).setUp()
        self.url = factories.SnapshotScheduleFactory.get_url(self.fixture.openstack_snapshot_schedule, 'activate')
        self.client.force_authenticate(self.fixture.owner)

    def test_snapshot_schedule_do_not_start_activation_of_active_schedule(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_snapshot_schedule_is_activated(self):
        snapshot_schedule = self.fixture.openstack_snapshot_schedule
        snapshot_schedule.is_active = False
        snapshot_schedule.save()

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(models.SnapshotSchedule.objects.get(pk=snapshot_schedule.pk).is_active)


class SnapshotScheduleDeactivateTest(BaseSnapshotScheduleTest):

    def setUp(self):
        super(SnapshotScheduleDeactivateTest, self).setUp()
        self.url = factories.SnapshotScheduleFactory.get_url(self.fixture.openstack_snapshot_schedule, 'deactivate')
        self.client.force_authenticate(self.fixture.owner)

    def test_snapshot_schedule_do_not_start_deactivation_of_not_active_schedule(self):
        snapshot = self.fixture.openstack_snapshot_schedule
        snapshot.is_active = False
        snapshot.save()
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_snapshot_schedule_is_deactivated(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(models.SnapshotSchedule.objects.get(pk=self.fixture.openstack_snapshot_schedule.pk).is_active)


@ddt
class SnapshotScheduleRetrieveTest(BaseSnapshotScheduleTest):

    def setUp(self):
        super(SnapshotScheduleRetrieveTest, self).setUp()
        self.url = factories.SnapshotScheduleFactory.get_list_url()

    @data('owner', 'global_support', 'admin', 'manager', 'staff')
    def user_has_permissions_to_list_snapshot_schedules(self, user):
        self.fixture.openstack_snapshot_schedule
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status=status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['uuid'], self.fixture.openstack_snapshot_schedule.uuid.hex)

    @data('user')
    def user_has_no_permissions_to_list_snapshot_schedules(self, user):
        self.fixture.openstack_snapshot_schedule
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status=status.HTTP_403_FORBIDDEN)


@ddt
class SnapshotScheduleDeleteTest(BaseSnapshotScheduleTest):

    def setUp(self):
        super(SnapshotScheduleDeleteTest, self).setUp()
        self.url = factories.SnapshotScheduleFactory.get_url(self.fixture.openstack_snapshot_schedule)

    @data('owner', 'admin', 'staff')
    def user_can_delete_snapshot(self, user):
        self.client.force_authenticate(getattr(self.fixture, user))

        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status=status.HTTP_204_NO_CONTENT)
        self.assertFalse(models.SnapshotSchedule.objects.filter(pk=self.fixture.openstack_snapshot_schedule.pk).exists())
