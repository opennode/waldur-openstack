from django.utils.functional import cached_property

from nodeconductor.structure.tests.fixtures import ProjectFixture
from nodeconductor_openstack.openstack.tests import fixtures as openstack_fixtures

from . import factories
from .. import models


class OpenStackTenantFixture(ProjectFixture):
    openstack_fixture = openstack_fixtures.OpenStackFixture()

    @cached_property
    def openstack_tenant_service_settings(self):
        return factories.OpenStackTenantServiceSettingsFactory(
            name=self.openstack_fixture.tenant.name,
            scope=self.openstack_fixture.tenant,
            customer=self.customer,
            backend_url=self.openstack_fixture.openstack_service_settings.backend_url,
            username=self.openstack_fixture.tenant.user_username,
            password=self.openstack_fixture.tenant.user_password,
            options={
                'availability_zone': self.openstack_fixture.tenant.availability_zone,
                'tenant_id': self.openstack_fixture.tenant.backend_id,
            },
        )

    @cached_property
    def openstack_tenant_service(self):
        return factories.OpenStackTenantServiceFactory(
            customer=self.customer,
            settings=self.openstack_tenant_service_settings
        )

    @cached_property
    def subnet(self):
        pass

    @cached_property
    def spl(self):
        return factories.OpenStackTenantServiceProjectLinkFactory(
            project=self.project, service=self.openstack_tenant_service)

    @cached_property
    def volume(self):
        return factories.VolumeFactory(
            service_project_link=self.spl,
            state=models.Volume.States.OK,
            runtime_state=models.Volume.RuntimeStates.OFFLINE,
        )

    @cached_property
    def instance(self):
        return factories.InstanceFactory(
            service_project_link=self.spl,
            state=models.Instance.States.OK,
            runtime_state=models.Instance.RuntimeStates.SHUTOFF,
        )

    @cached_property
    def snapshot(self):
        return factories.SnapshotFactory(
            service_project_link=self.spl,
            state=models.Volume.States.OK,
            runtime_state=models.Volume.RuntimeStates.OFFLINE,
            source_volume=self.volume,
        )

    @cached_property
    def backup_schedule(self):
        return factories.BackupScheduleFactory(
            service_project_link=self.spl,
            state=models.BackupSchedule.States.OK,
            instance=self.instance,
        )

    @cached_property
    def snapshot_schedule(self):
        return factories.SnapshotScheduleFactory(
            service_project_link=self.spl,
            state=models.SnapshotSchedule.States.OK,
            source_volume=self.volume,
        )
