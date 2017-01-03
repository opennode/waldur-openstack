from __future__ import unicode_literals

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from .. import factories, fixtures
from ... import models


class BackupScheduleTest(TestCase):
    def setUp(self):
        self.openstack_tenant_fixture = fixtures.OpenStackTenantFixture()
        self.instance = self.openstack_tenant_fixture.openstack_instance

    def test_update_next_trigger_at(self):
        now = timezone.now()
        schedule = factories.BackupScheduleFactory()
        schedule.schedule = '*/10 * * * *'
        schedule.update_next_trigger_at()
        self.assertTrue(schedule.next_trigger_at)
        self.assertGreater(schedule.next_trigger_at, now)

    def test_update_next_trigger_at_with_provided_timezone(self):
        schedule = factories.BackupScheduleFactory(timezone='Europe/London')
        schedule.update_next_trigger_at()

        # next_trigger_at timezone and schedule's timezone must be equal.
        self.assertEqual(schedule.timezone, schedule.next_trigger_at.tzinfo.zone)

    def test_update_next_trigger_at_with_default_timezone(self):
        schedule = factories.BackupScheduleFactory()
        schedule.update_next_trigger_at()

        # If timezone is not provided, default timezone must be set.
        self.assertEqual(settings.TIME_ZONE, schedule.timezone)

    def test_save(self):
        # new schedule
        schedule = factories.BackupScheduleFactory(next_trigger_at=None)
        self.assertGreater(schedule.next_trigger_at, timezone.now())
        # schedule become active
        schedule.is_active = False
        schedule.next_trigger_at = None
        schedule.save()
        schedule.is_active = True
        schedule.save()
        self.assertGreater(schedule.next_trigger_at, timezone.now())
        # schedule was changed
        schedule.next_trigger_at = None
        schedule.schedule = '*/10 * * * *'
        schedule.save()
        schedule = models.BackupSchedule.objects.get(id=schedule.id)
        self.assertGreater(schedule.next_trigger_at, timezone.now())
