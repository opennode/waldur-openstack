from rest_framework import test, status

from nodeconductor.structure import models as structure_models
from nodeconductor.structure.tests import factories as structure_factories
from .. import models
from . import factories


def _instance_data(user, instance=None):
    if instance is None:
        instance = factories.InstanceFactory()
    factories.FloatingIPFactory(service_project_link=instance.service_project_link, status='DOWN')
    image = factories.ImageFactory(settings=instance.service_project_link.service.settings)
    flavor = factories.FlavorFactory(settings=instance.service_project_link.service.settings)
    ssh_public_key = structure_factories.SshPublicKeyFactory(user=user)
    tenant = factories.TenantFactory(service_project_link=instance.service_project_link)
    return {
        'name': 'test_host',
        'description': 'test description',
        'flavor': factories.FlavorFactory.get_url(flavor),
        'image': factories.ImageFactory.get_url(image),
        'service_project_link': factories.OpenStackServiceProjectLinkFactory.get_url(instance.service_project_link),
        'ssh_public_key': structure_factories.SshPublicKeyFactory.get_url(ssh_public_key),
        'system_volume_size': max(image.min_disk, 1024),
        'skip_external_ip_assignment': True,
        'tenant': factories.TenantFactory.get_url(tenant)
    }


class InstanceSecurityGroupsTest(test.APISimpleTestCase):

    def setUp(self):
        self.user = structure_factories.UserFactory.create()
        self.client.force_authenticate(self.user)

        self.instance = factories.InstanceFactory(state=models.Instance.States.OFFLINE)
        self.spl = self.instance.service_project_link
        self.spl.project.add_user(self.user, structure_models.ProjectRole.ADMINISTRATOR)

        self.security_groups = factories.SecurityGroupFactory.create_batch(2, service_project_link=self.spl)
        self.instance.security_groups.add(*self.security_groups)

    def test_groups_list_in_instance_response(self):
        response = self.client.get(factories.InstanceFactory.get_url(self.instance))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        fields = ('name',)
        for field in fields:
            expected_security_groups = [getattr(g, field) for g in self.security_groups]
            self.assertItemsEqual([g[field] for g in response.data['security_groups']], expected_security_groups)

    def test_add_instance_with_security_groups(self):
        data = _instance_data(self.user, self.instance)
        data['security_groups'] = [factories.SecurityGroupFactory.get_url(sg)
                                   for sg in self.security_groups]

        response = self.client.post(factories.InstanceFactory.get_list_url(), data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        reread_instance = models.Instance.objects.get(pk=self.instance.pk)
        reread_security_groups = list(reread_instance.security_groups.all())
        self.assertEquals(reread_security_groups, self.security_groups)

    def test_change_instance_security_groups_single_field(self):
        new_security_group = factories.SecurityGroupFactory(
            name='test-group',
            service_project_link=self.spl,
        )

        data = {
            'security_groups': [
                factories.SecurityGroupFactory.get_url(new_security_group),
            ]
        }

        response = self.client.patch(factories.InstanceFactory.get_url(self.instance), data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        reread_instance = models.Instance.objects.get(pk=self.instance.pk)
        reread_security_groups = list(reread_instance.security_groups.all())

        self.assertEquals(reread_security_groups, [new_security_group],
                          'Security groups should have changed')

    def test_change_instance_security_groups(self):
        response = self.client.get(factories.InstanceFactory.get_url(self.instance))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        security_group = factories.SecurityGroupFactory(service_project_link=self.spl)
        data = _instance_data(self.user, self.instance)
        data['security_groups'] = [factories.SecurityGroupFactory.get_url(security_group)]

        response = self.client.put(factories.InstanceFactory.get_url(self.instance), data=data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        reread_instance = models.Instance.objects.get(pk=self.instance.pk)
        reread_security_groups = list(reread_instance.security_groups.all())

        self.assertEquals(reread_security_groups, [security_group])

    def test_security_groups_is_not_required(self):
        data = _instance_data(self.user, self.instance)
        self.assertNotIn('security_groups', data)
        response = self.client.post(factories.InstanceFactory.get_list_url(), data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
