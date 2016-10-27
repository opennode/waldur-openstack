from nodeconductor.core.permissions import StaffPermissionLogic
from nodeconductor.structure import perms as structure_perms


PERMISSION_LOGICS = (
    ('openstack_tenant.OpenStackTenantService', structure_perms.service_permission_logic),
    ('openstack_tenant.OpenStackTenantServiceProjectLink', structure_perms.service_project_link_permission_logic),
    ('openstack_tenant.Flavor', StaffPermissionLogic(any_permission=True)),
    ('openstack_tenant.Image', StaffPermissionLogic(any_permission=True)),
    ('openstack_tenant.FloatingIP', StaffPermissionLogic(any_permission=True)),
    ('openstack_tenant.SecurityGroup', StaffPermissionLogic(any_permission=True)),
)
