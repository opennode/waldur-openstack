from nodeconductor.core.permissions import StaffPermissionLogic, FilteredCollaboratorsPermissionLogic
from nodeconductor.structure import perms as structure_perms, models as structure_models


def prefixed_permission_logic(prefix):
    return FilteredCollaboratorsPermissionLogic(
        collaborators_query=[
            '%s__service_project_link__project__customer__permissions__user' % prefix,
            '%s__service_project_link__project__permissions__user' % prefix,
            '%s__service_project_link__project__permissions__user' % prefix,
        ],
        collaborators_filter=[
            {'%s__service_project_link__project__customer__permissions__role' % prefix:
             structure_models.CustomerRole.OWNER,
             '%s__service_project_link__project__customer__permissions__is_active' % prefix: True},
            {'%s__service_project_link__project__permissions__role' % prefix:
             structure_models.ProjectRole.ADMINISTRATOR,
             '%s__service_project_link__project__permissions__is_active' % prefix: True},
            {'%s__service_project_link__project__permissions__role' % prefix:
             structure_models.ProjectRole.MANAGER,
             '%s__service_project_link__project__permissions__is_active' % prefix: True},
        ],
        any_permission=True,
    )


PERMISSION_LOGICS = (
    ('openstack_tenant.OpenStackTenantService', structure_perms.service_permission_logic),
    ('openstack_tenant.OpenStackTenantServiceProjectLink', structure_perms.service_project_link_permission_logic),
    ('openstack_tenant.Flavor', StaffPermissionLogic(any_permission=True)),
    ('openstack_tenant.Image', StaffPermissionLogic(any_permission=True)),
    ('openstack_tenant.FloatingIP', StaffPermissionLogic(any_permission=True)),
    ('openstack_tenant.SecurityGroup', StaffPermissionLogic(any_permission=True)),
    ('openstack_tenant.SecurityGroupRule', StaffPermissionLogic(any_permission=True)),
    ('openstack_tenant.Volume', structure_perms.resource_permission_logic),
    ('openstack_tenant.Snapshot', structure_perms.resource_permission_logic),
    ('openstack_tenant.Instance', structure_perms.resource_permission_logic),
    ('openstack_tenant.Backup', structure_perms.resource_permission_logic),
    ('openstack_tenant.BackupSchedule', prefixed_permission_logic('instance')),
)
