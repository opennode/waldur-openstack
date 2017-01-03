from nodeconductor.core.permissions import FilteredCollaboratorsPermissionLogic, StaffPermissionLogic
from nodeconductor.structure import models as structure_models, perms as structure_perms


def openstack_permission_logic(prefix):
    return FilteredCollaboratorsPermissionLogic(
        collaborators_query=[
            '%s__service_project_link__project__customer__roles__permission_group__user' % prefix,
            '%s__service_project_link__project__roles__permission_group__user' % prefix,
            '%s__service_project_link__project__roles__permission_group__user' % prefix,
            '%s__service_project_link__project__project_groups__roles__permission_group__user' % prefix,
        ],
        collaborators_filter=[
            {'%s__service_project_link__project__customer__roles__role_type' % prefix:
             structure_models.CustomerRole.OWNER},
            {'%s__service_project_link__project__roles__role_type' % prefix:
             structure_models.ProjectRole.ADMINISTRATOR},
            {'%s__service_project_link__project__roles__role_type' % prefix:
             structure_models.ProjectRole.MANAGER},
            {'%s__service_project_link__project__project_groups__roles__permission_group__user' % prefix:
             structure_models.ProjectGroupRole.MANAGER},
        ],
        any_permission=True,
    )


PERMISSION_LOGICS = (
    ('openstack.OpenStackService', structure_perms.service_permission_logic),
    ('openstack.OpenStackServiceProjectLink', structure_perms.service_project_link_permission_logic),
    ('openstack.SecurityGroup', FilteredCollaboratorsPermissionLogic(
        collaborators_query=[
            'service_project_link__service__customer__roles__permission_group__user',
            'service_project_link__project__roles__permission_group__user',
            'service_project_link__project__roles__permission_group__user',
            'service_project_link__project__project_groups__roles__permission_group__user',
        ],
        collaborators_filter=[
            {'service_project_link__service__customer__roles__role_type': structure_models.CustomerRole.OWNER},
            {'service_project_link__project__roles__role_type': structure_models.ProjectRole.ADMINISTRATOR},
            {'service_project_link__project__roles__role_type': structure_models.ProjectRole.MANAGER},
            {'service_project_link__project__project_groups__roles__role_type':
             structure_models.ProjectGroupRole.MANAGER}
        ],
        any_permission=True,
    )),
    ('openstack.SecurityGroupRule', openstack_permission_logic('security_group')),
    ('openstack.Tenant', structure_perms.resource_permission_logic),
    ('openstack.Flavor', StaffPermissionLogic(any_permission=True)),
    ('openstack.Image', StaffPermissionLogic(any_permission=True)),
    ('openstack.IpMapping', StaffPermissionLogic(any_permission=True)),
    ('openstack.FloatingIP', StaffPermissionLogic(any_permission=True)),
)
