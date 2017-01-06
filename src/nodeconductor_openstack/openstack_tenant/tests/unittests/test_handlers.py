from __future__ import unicode_literals

from django.test import TestCase

from nodeconductor.core.models import StateMixin
from nodeconductor_openstack.openstack.tests import factories as openstack_factories
from nodeconductor.structure.tests import factories as structure_factories

from .. import factories
from ... import models, handlers


class TestSecurityGroupHandler(TestCase):
    def setUp(self):
        self.tenant = openstack_factories.TenantFactory()
        self.service_settings = structure_factories.ServiceSettingsFactory(scope=self.tenant)

    def test_security_group_been_created_when_openstack_security_group_is_created(self):
        openstack_security_group = openstack_factories.SecurityGroupFactory(tenant=self.tenant, )
        self.assertEqual(models.SecurityGroup.objects.count(), 0)

        openstack_security_group.state = StateMixin.States.OK
        openstack_security_group.save()
        handlers.on_openstack_security_group_state_changed(
            sender=None,
            name='',
            instance=openstack_security_group,
            source=StateMixin.States.CREATING,
            target=StateMixin.States.OK,
        )

        self.assertEqual(models.SecurityGroup.objects.count(), 1)

    def test_security_group_is_updated_when_openstack_security_group_is_updated(self):
        expected_name = "name"
        expected_description = "description"

        openstack_security_group = openstack_factories.SecurityGroupFactory(tenant=self.tenant,
                                                                            name=expected_name,
                                                                            description=expected_description)
        security_group = factories.SecurityGroupFactory(settings=self.service_settings,
                                                        backend_id=openstack_security_group.backend_id)

        handlers.on_openstack_security_group_state_changed(
            sender=None,
            name='',
            instance=openstack_security_group,
            source=StateMixin.States.UPDATING,
            target=StateMixin.States.OK,
        )

        security_group.refresh_from_db()
        self.assertTrue(openstack_security_group.name in security_group.name)
        self.assertTrue(openstack_security_group.description in security_group.description)

    def test_security_group_is_deleted_when_openstack_security_group_is_deleted(self):
        openstack_security_group = openstack_factories.SecurityGroupFactory(tenant=self.tenant)
        factories.SecurityGroupFactory(settings=self.service_settings, backend_id=openstack_security_group.backend_id)

        openstack_security_group.delete()
        self.assertEqual(models.SecurityGroup.objects.count(), 0)


class TestFloatingIPHandler(TestCase):
    def setUp(self):
        self.tenant = openstack_factories.TenantFactory()
        self.service_settings = structure_factories.ServiceSettingsFactory(scope=self.tenant)

    def test_floating_ip_been_created_when_openstack_floating_ip_is_created(self):
        openstack_floating_ip = openstack_factories.FloatingIPFactory(tenant=self.tenant, )
        self.assertEqual(models.FloatingIP.objects.count(), 0)

        openstack_floating_ip.state = StateMixin.States.OK
        openstack_floating_ip.save()
        handlers.on_openstack_floating_ip_state_changed(
            sender=None,
            name='',
            instance=openstack_floating_ip,
            source=StateMixin.States.CREATING,
            target=StateMixin.States.OK,
        )

        self.assertEqual(models.FloatingIP.objects.count(), 1)

    def test_floating_ip_is_updated_when_openstack_floating_ip_is_updated(self):
        expected_name = "name"

        openstack_floating_ip = openstack_factories.FloatingIPFactory(
            tenant=self.tenant,
            name=expected_name,
        )
        floating_ip = factories.FloatingIPFactory(
            settings=self.service_settings,
            backend_id=openstack_floating_ip.backend_id,
        )

        handlers.on_openstack_floating_ip_state_changed(
            sender=None,
            name='',
            instance=openstack_floating_ip,
            source=StateMixin.States.UPDATING,
            target=StateMixin.States.OK,
        )

        floating_ip.refresh_from_db()
        self.assertTrue(openstack_floating_ip.name in floating_ip.name)
        self.assertEqual(openstack_floating_ip.address, floating_ip.address)
        self.assertEqual(openstack_floating_ip.runtime_state, floating_ip.status)
        self.assertEqual(openstack_floating_ip.backend_network_id, floating_ip.backend_network_id)

    def test_floating_ip_is_deleted_when_openstack_floating_ip_is_deleted(self):
        openstack_floating_ip = openstack_factories.FloatingIPFactory(tenant=self.tenant)
        factories.FloatingIPFactory(settings=self.service_settings, backend_id=openstack_floating_ip.backend_id)

        openstack_floating_ip.delete()
        self.assertEqual(models.FloatingIP.objects.count(), 0)
