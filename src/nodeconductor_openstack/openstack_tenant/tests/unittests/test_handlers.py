from __future__ import unicode_literals

from django.test import TestCase

from nodeconductor.core.models import StateMixin
from nodeconductor_openstack.openstack.tests import factories as openstack_factories
from nodeconductor.structure import models as structure_models
from nodeconductor.structure.tests import factories as structure_factories

from .. import factories
from ... import models, handlers


class SecurityGroupHandlerTest(TestCase):
    def setUp(self):
        self.tenant = openstack_factories.TenantFactory()
        self.service_settings = structure_factories.ServiceSettingsFactory(scope=self.tenant)

    def test_security_group_been_created_when_openstack_security_group_is_created(self):
        openstack_security_group = openstack_factories.SecurityGroupFactory(tenant=self.tenant)
        self.assertEqual(models.SecurityGroup.objects.count(), 0)

        openstack_security_group.state = StateMixin.States.OK
        openstack_security_group.save()
        handlers.create_security_group(
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

        handlers.update_security_group(
            sender=None,
            name='',
            instance=openstack_security_group,
            source=StateMixin.States.UPDATING,
            target=StateMixin.States.OK,
        )

        security_group.refresh_from_db()
        self.assertIn(openstack_security_group.name, security_group.name)
        self.assertIn(openstack_security_group.description, security_group.description)

    def test_security_group_rules_are_updated_when_one_more_rule_is_added(self):
        openstack_security_group = openstack_factories.SecurityGroupFactory(tenant=self.tenant)
        openstack_factories.SecurityGroupRuleFactory(security_group=openstack_security_group)
        security_group = factories.SecurityGroupFactory(settings=self.service_settings,
                                                        backend_id=openstack_security_group.backend_id)

        handlers.update_security_group(
            sender=None,
            name='',
            instance=openstack_security_group,
            source=StateMixin.States.UPDATING,
            target=StateMixin.States.OK,
        )

        self.assertEqual(security_group.rules.count(), 1, "Security group rule has not been added")
        self.assertEqual(security_group.rules.first().protocol, openstack_security_group.rules.first().protocol)
        self.assertEqual(security_group.rules.first().from_port, openstack_security_group.rules.first().from_port)
        self.assertEqual(security_group.rules.first().to_port, openstack_security_group.rules.first().to_port)

    def test_security_group_is_deleted_when_openstack_security_group_is_deleted(self):
        openstack_security_group = openstack_factories.SecurityGroupFactory(tenant=self.tenant)
        factories.SecurityGroupFactory(settings=self.service_settings, backend_id=openstack_security_group.backend_id)

        openstack_security_group.delete()
        self.assertEqual(models.SecurityGroup.objects.count(), 0)


class FloatingIPHandlerTest(TestCase):
    def setUp(self):
        self.tenant = openstack_factories.TenantFactory()
        self.service_settings = structure_factories.ServiceSettingsFactory(scope=self.tenant)

    def test_floating_ip_been_created_when_openstack_floating_ip_is_created(self):
        openstack_floating_ip = openstack_factories.FloatingIPFactory(tenant=self.tenant)
        self.assertEqual(models.FloatingIP.objects.count(), 0)

        openstack_floating_ip.state = StateMixin.States.OK
        openstack_floating_ip.save()
        handlers.create_floating_ip(
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

        handlers.update_floating_ip(
            sender=None,
            name='',
            instance=openstack_floating_ip,
            source=StateMixin.States.UPDATING,
            target=StateMixin.States.OK,
        )

        floating_ip.refresh_from_db()
        self.assertTrue(openstack_floating_ip.name in floating_ip.name)
        self.assertEqual(openstack_floating_ip.address, floating_ip.address)
        self.assertEqual(openstack_floating_ip.runtime_state, floating_ip.runtime_state)
        self.assertEqual(openstack_floating_ip.backend_network_id, floating_ip.backend_network_id)

    def test_floating_ip_is_deleted_when_openstack_floating_ip_is_deleted(self):
        openstack_floating_ip = openstack_factories.FloatingIPFactory(tenant=self.tenant)
        factories.FloatingIPFactory(settings=self.service_settings, backend_id=openstack_floating_ip.backend_id)

        openstack_floating_ip.delete()
        self.assertEqual(models.FloatingIP.objects.count(), 0)


class TenantChangePasswordTest(TestCase):

    def test_service_settings_password_updates_when_tenant_user_password_changes(self):
        tenant = openstack_factories.TenantFactory()
        service_settings = structure_models.ServiceSettings.objects.first()
        service_settings.scope = tenant
        service_settings.password = tenant.user_password
        service_settings.save()

        new_password = 'new_password'

        tenant.user_password = new_password
        tenant.save()
        service_settings.refresh_from_db()
        self.assertEqual(service_settings.password, new_password)


class NetworkHandlerTest(TestCase):
    def setUp(self):
        self.tenant = openstack_factories.TenantFactory()
        self.service_settings = structure_factories.ServiceSettingsFactory(scope=self.tenant)

    def test_network_is_created_when_openstack_network_is_created_and_transitioned_to_the_OK_state(self):
        openstack_network = openstack_factories.NetworkFactory(tenant=self.tenant)
        self.assertEqual(models.Network.objects.count(), 0)

        openstack_network.state = StateMixin.States.OK
        openstack_network.save()
        handlers.create_network(
            sender=None,
            name='',
            instance=openstack_network,
            source=StateMixin.States.CREATING,
            target=StateMixin.States.OK,
        )

        self.assertTrue(models.Network.objects.filter(backend_id=openstack_network.backend_id).exists())

    def test_network_is_updated_when_openstack_network_is_updated(self):
        expected_name = "network #1"

        openstack_network = openstack_factories.NetworkFactory(
            tenant=self.tenant,
            name=expected_name,
        )
        network = factories.NetworkFactory(
            settings=self.service_settings,
            backend_id=openstack_network.backend_id,
        )

        handlers.update_network(
            sender=None,
            name='',
            instance=openstack_network,
            source=StateMixin.States.UPDATING,
            target=StateMixin.States.OK,
        )

        network.refresh_from_db()
        self.assertTrue(openstack_network.name in network.name)
        self.assertEqual(openstack_network.is_external, network.is_external)
        self.assertEqual(openstack_network.type, network.type)
        self.assertEqual(openstack_network.segmentation_id, network.segmentation_id)
        self.assertEqual(openstack_network.backend_id, network.backend_id)

    def test_network_is_deleted_when_openstack_network_is_deleted(self):
        openstack_network = openstack_factories.NetworkFactory(tenant=self.tenant)
        factories.NetworkFactory(settings=self.service_settings, backend_id=openstack_network.backend_id)

        openstack_network.delete()
        self.assertEqual(models.Network.objects.count(), 0)



class SubNetHandlerTest(TestCase):

    def setUp(self):
        self.tenant = openstack_factories.TenantFactory()
        self.service_settings = structure_factories.ServiceSettingsFactory(scope=self.tenant)

    def test_subnet_is_created_when_openstack_subnet_is_created_and_transitioned_to_the_OK_state(self):
        openstack_subnet = openstack_factories.SubNetFactory(network__tenant=self.tenant)
        factories.NetworkFactory(settings=self.service_settings)
        self.assertEqual(models.SubNet.objects.count(), 0)

        openstack_subnet.state = StateMixin.States.OK
        openstack_subnet.save()
        handlers.create_subnet(
            sender=None,
            name='',
            instance=openstack_subnet,
            source=StateMixin.States.CREATING,
            target=StateMixin.States.OK,
        )

        self.assertTrue(models.Network.objects.filter(backend_id=openstack_subnet.backend_id).exists())

    def test_subnet_is_updated_when_openstack_subnet_is_updated(self):
        expected_name = "subnet #1"

        openstack_subnet = openstack_factories.SubNetFactory(
            network__tenant=self.tenant,
            name=expected_name,
        )
        subnet = factories.SubNetFactory(
            settings=self.service_settings,
            backend_id=openstack_subnet.backend_id,
        )

        handlers.update_subnet(
            sender=None,
            name='',
            instance=openstack_subnet,
            source=StateMixin.States.UPDATING,
            target=StateMixin.States.OK,
        )

        subnet.refresh_from_db()
        self.assertTrue(openstack_subnet.name in subnet.name)
        self.assertEqual(openstack_subnet.cidr, subnet.cidr)
        self.assertEqual(openstack_subnet.gateway_ip, subnet.gateway_ip)
        self.assertEqual(openstack_subnet.allocation_pools, subnet.allocation_pools)
        self.assertEqual(openstack_subnet.ip_version, subnet.ip_version)
        self.assertEqual(openstack_subnet.enable_dhcp, subnet.enable_dhcp)
        self.assertEqual(openstack_subnet.dns_nameservers, subnet.dns_nameservers)

    def test_subnet_is_deleted_when_openstack_subnet_is_deleted(self):
        openstack_subnet = openstack_factories.SubNetFactory(network__tenant=self.tenant)
        factories.SubNetFactory(settings=self.service_settings, backend_id=openstack_subnet.backend_id)

        openstack_subnet.delete()
        self.assertEqual(models.SubNet.objects.count(), 0)
