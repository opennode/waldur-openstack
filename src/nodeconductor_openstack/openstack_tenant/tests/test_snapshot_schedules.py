import datetime

import mock
from croniter import croniter
from django.conf import settings
from nodeconductor.core.tests import helpers
from nodeconductor.structure.tests import factories as structure_factories
from pytz import timezone
from rest_framework import status
from rest_framework import test

from nodeconductor_openstack.openstack_tenant import models

from . import factories, fixtures


class SnapshotScheduleUsageTest(test.APISimpleTestCase):

    def setUp(self):
        self.user = structure_factories.UserFactory.create(is_staff=True)
        self.client.force_authenticate(user=self.user)
        volume = factories.VolumeFactory(state=models.Volume.States.OK)
        self.create_url = factories.VolumeFactory.get_url(volume, action='create_snapshot_schedule')
        self.snapshot_schedule_data = {
            'name': 'test schedule',
            'retention_time': 3,
            'schedule': '*/5 * * * *',
            'maximal_number_of_resources': 3,
        }

    def test_staff_can_create_snapshot_schedule(self):
        response = self.client.post(self.create_url, self.snapshot_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['retention_time'], self.snapshot_schedule_data['retention_time'])
        self.assertEqual(
            response.data['maximal_number_of_resources'], self.snapshot_schedule_data['maximal_number_of_resources'])
        self.assertEqual(response.data['schedule'], self.snapshot_schedule_data['schedule'])
        snapshot_schedule = models.SnapshotSchedule.objects.first()

    def test_snapshot_schedule_default_state_is_OK(self):
        response = self.client.post(self.create_url, self.snapshot_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        snapshot_schedule = models.SnapshotSchedule.objects.first()
        self.assertIsNotNone(snapshot_schedule)
        self.assertEqual(snapshot_schedule.state, snapshot_schedule.States.OK)

    def test_snapshot_schedule_can_not_be_created_with_wrong_schedule(self):
        # wrong schedule:
        self.snapshot_schedule_data['schedule'] = 'wrong schedule'
        response = self.client.post(self.create_url, self.snapshot_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('schedule', response.content)

    def test_snapshot_schedule_creation_with_correct_timezone(self):
        volume = factories.VolumeFactory(state=models.Volume.States.OK)
        create_url = factories.VolumeFactory.get_url(volume, action='create_snapshot_schedule')
        snapshot_schedule_data = {
            'name': 'test schedule',
            'retention_time': 3,
            'schedule': '*/5 * * * *',
            'timezone': 'Europe/London',
            'maximal_number_of_resources': 3,
        }
        response = self.client.post(create_url, snapshot_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['timezone'], 'Europe/London')

    def test_snapshot_schedule_creation_with_incorrect_timezone(self):
        volume = factories.VolumeFactory(state=models.Volume.States.OK)
        create_url = factories.VolumeFactory.get_url(volume, action='create_snapshot_schedule')

        snapshot_schedule_data = {
            'name': 'test schedule',
            'retention_time': 3,
            'schedule': '*/5 * * * *',
            'timezone': 'incorrect',
            'maximal_number_of_resources': 3,
        }
        response = self.client.post(create_url, snapshot_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('timezone', response.data)

    def test_snapshot_schedule_creation_with_default_timezone(self):
        volume = factories.VolumeFactory(state=models.Volume.States.OK)
        create_url = factories.VolumeFactory.get_url(volume, action='create_snapshot_schedule')
        snapshot_schedule_data = {
            'name': 'test schedule',
            'retention_time': 3,
            'schedule': '*/5 * * * *',
            'maximal_number_of_resources': 3,
        }
        response = self.client.post(create_url, snapshot_schedule_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['timezone'], settings.TIME_ZONE)

    def test_weekly_snapshot_schedule_next_trigger_at_is_correct(self):
        schedule = factories.SnapshotScheduleFactory(schedule='0 2 * * 4')

        cron = croniter('0 2 * * 4', datetime.datetime.now(tz=timezone(settings.TIME_ZONE)))
        next_snapshot = schedule.next_trigger_at
        self.assertEqual(next_snapshot, cron.get_next(datetime.datetime))
        self.assertEqual(next_snapshot.weekday(), 3, 'Must be Thursday')

        for k, v in {'hour': 2, 'minute': 0, 'second': 0}.items():
            self.assertEqual(getattr(next_snapshot, k), v, 'Must be 2:00am')

    def test_daily_snapshot_schedule_next_trigger_at_is_correct(self):
        schedule = '0 2 * * *'

        today = datetime.datetime.now(tz=timezone(settings.TIME_ZONE))
        expected = croniter(schedule, today).get_next(datetime.datetime)

        with mock.patch('nodeconductor.core.models.django_timezone') as mock_django_timezone:
            mock_django_timezone.now.return_value = today
            self.assertEqual(
                expected,
                factories.SnapshotScheduleFactory(schedule=schedule).next_trigger_at)

    def test_schedule_activation_and_deactivation(self):
        schedule = factories.SnapshotScheduleFactory(is_active=False)
        activate_url = factories.SnapshotScheduleFactory.get_url(schedule, 'activate')
        deactivate_url = factories.SnapshotScheduleFactory.get_url(schedule, 'deactivate')

        # activate
        response = self.client.post(activate_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(models.SnapshotSchedule.objects.get(pk=schedule.pk).is_active)
        # deactivate
        response = self.client.post(deactivate_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(models.SnapshotSchedule.objects.get(pk=schedule.pk).is_active)

    def test_snapshot_schedule_do_not_start_activation_of_active_schedule(self):
        schedule = factories.SnapshotScheduleFactory(is_active=True)
        response = self.client.post(factories.SnapshotScheduleFactory.get_url(schedule, 'activate'))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_snapshot_schedule_do_not_start_deactivation_of_not_active_schedule(self):
        schedule = factories.SnapshotScheduleFactory(is_active=False)
        response = self.client.post(factories.SnapshotScheduleFactory.get_url(schedule, 'deactivate'))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)



class SnapshotScheduleListPermissionsTest(helpers.ListPermissionsTest):

    def get_url(self):
        return factories.SnapshotScheduleFactory.get_list_url()

    def get_users_and_expected_results(self):
        schedule = factories.SnapshotScheduleFactory()

        user_with_view_permission = structure_factories.UserFactory.create(is_staff=True, is_superuser=True)
        user_without_view_permission = structure_factories.UserFactory.create()

        return [
            {
                'user': user_with_view_permission,
                'expected_results': [
                    {'url': factories.SnapshotScheduleFactory.get_url(schedule)}
                ]
            },
            {
                'user': user_without_view_permission,
                'expected_results': []
            },
        ]

    def test_anonymous_user_can_not_access_snapshot_schedule(self):
        response = self.client.get(factories.SnapshotScheduleFactory.get_list_url())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class SnapshotSchedulePermissionsTest(helpers.PermissionsTest):

    def setUp(self):
        super(SnapshotSchedulePermissionsTest, self).setUp()
        self.fixture = fixtures.OpenStackTenantFixture()
        self.schedule = factories.SnapshotScheduleFactory(source_volume=self.fixture.openstack_volume)
        self.url = factories.SnapshotScheduleFactory.get_url(self.schedule)

    def get_users_with_permission(self, url, method):
        return [self.fixture.staff, self.fixture.admin, self.fixture.owner]

    def get_users_without_permissions(self, url, method):
        return [self.fixture.user]

    def get_urls_configs(self):
        yield {'url': self.url, 'method': 'GET'}
        yield {'url': factories.SnapshotScheduleFactory.get_url(self.schedule, action='deactivate'), 'method': 'POST'}
        yield {'url': factories.SnapshotScheduleFactory.get_url(self.schedule, action='activate'), 'method': 'POST'}
        yield {'url': self.url, 'method': 'PATCH', 'data': {'retention_time': 5}}
        create_url = factories.VolumeFactory.get_url(self.fixture.openstack_volume, action='create_snapshot_schedule')
        snapshot_schedule_data = {
            'name': 'test schedule',
            'retention_time': 3,
            'schedule': '*/5 * * * *',
            'maximal_number_of_resources': 3,
        }
        yield {'url': create_url, 'method': 'POST', 'data': snapshot_schedule_data}

    # XXX: Current permissions tests helper does not work well with deletion, so we need to test deletion explicitly
    def test_staff_can_delete_schedule(self):
        self.client.force_authenticate(self.fixture.staff)

        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_admin_can_delete_schedule(self):
        self.client.force_authenticate(self.fixture.staff)

        url = factories.SnapshotScheduleFactory.get_url(self.schedule)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_owner_can_delete_schedule(self):
        self.client.force_authenticate(self.fixture.owner)

        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
