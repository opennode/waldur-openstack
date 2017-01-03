from nodeconductor.core.permissions import FilteredCollaboratorsPermissionLogic, StaffPermissionLogic
from nodeconductor.structure import models as structure_models, perms as structure_perms


def openstack_permission_logic(prefix):
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
    ('openstack.OpenStackService', structure_perms.service_permission_logic),
    ('openstack.OpenStackServiceProjectLink', structure_perms.service_project_link_permission_logic),
    ('openstack.SecurityGroup', FilteredCollaboratorsPermissionLogic(
        collaborators_query=[
            'service_project_link__service__customer__permissions__user',
            'service_project_link__project__permissions__user',
            'service_project_link__project__permissions__user',
        ],
        collaborators_filter=[
            {'service_project_link__service__customer__permissions__role': structure_models.CustomerRole.OWNER,
             'service_project_link__service__customer__permissions__is_active': True},
            {'service_project_link__project__permissions__role': structure_models.ProjectRole.ADMINISTRATOR,
             'service_project_link__project__permissions__is_active': True},
            {'service_project_link__project__permissions__role': structure_models.ProjectRole.MANAGER,
             'service_project_link__project__permissions__is_active': True},
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
