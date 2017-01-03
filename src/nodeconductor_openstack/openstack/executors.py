import logging

from celery import chain

from nodeconductor.core import tasks as core_tasks, executors as core_executors, utils as core_utils

from . import tasks


logger = logging.getLogger(__name__)


class SecurityGroupCreateExecutor(core_executors.CreateExecutor):

    @classmethod
    def get_task_signature(cls, security_group, serialized_security_group, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_security_group, 'create_security_group', state_transition='begin_creating')


class SecurityGroupUpdateExecutor(core_executors.UpdateExecutor):

    @classmethod
    def get_task_signature(cls, security_group, serialized_security_group, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_security_group, 'update_security_group', state_transition='begin_updating')


class SecurityGroupDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def get_task_signature(cls, security_group, serialized_security_group, **kwargs):
        if security_group.backend_id:
            return core_tasks.BackendMethodTask().si(
                serialized_security_group, 'delete_security_group', state_transition='begin_deleting')
        else:
            return core_tasks.StateTransitionTask().si(serialized_security_group, state_transition='begin_deleting')


class TenantCreateExecutor(core_executors.CreateExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, pull_security_groups=True, **kwargs):
        """ Create tenant, add user to it, create internal network, pull quotas """
        # we assume that tenant one network and subnet after creation
        network = tenant.networks.first()
        subnet = network.subnets.first()
        serialized_network = core_utils.serialize_instance(network)
        serialized_subnet = core_utils.serialize_instance(subnet)
        creation_tasks = [
            core_tasks.BackendMethodTask().si(serialized_tenant, 'create_tenant', state_transition='begin_creating'),
            core_tasks.BackendMethodTask().si(serialized_tenant, 'add_admin_user_to_tenant'),
            core_tasks.BackendMethodTask().si(serialized_tenant, 'create_tenant_user'),
            core_tasks.BackendMethodTask().si(serialized_network, 'create_network', state_transition='begin_creating'),
            core_tasks.BackendMethodTask().si(serialized_subnet, 'create_subnet', state_transition='begin_creating'),
        ]
        quotas = tenant.quotas.all()
        quotas = {q.name: int(q.limit) if q.limit.is_integer() else q.limit for q in quotas}
        creation_tasks.append(core_tasks.BackendMethodTask().si(serialized_tenant, 'push_tenant_quotas', quotas))
        # handle security groups
        # XXX: Create default security groups that was connected to SPL earlier.
        serialized_executor = core_utils.serialize_class(SecurityGroupCreateExecutor)
        for security_group in tenant.security_groups.all():
            serialized_security_group = core_utils.serialize_instance(security_group)
            creation_tasks.append(core_tasks.ExecutorTask().si(serialized_executor, serialized_security_group))

        if pull_security_groups:
            creation_tasks.append(core_tasks.BackendMethodTask().si(serialized_tenant, 'pull_tenant_security_groups'))

        # initialize external network if it defined in service settings
        service_settings = tenant.service_project_link.service.settings
        external_network_id = service_settings.get_option('external_network_id')
        if external_network_id:
            creation_tasks.append(core_tasks.BackendMethodTask().si(
                serialized_tenant, 'connect_tenant_to_external_network', external_network_id=external_network_id))

        return chain(*creation_tasks)

    @classmethod
    def get_success_signature(cls, tenant, serialized_tenant, **kwargs):
        network = tenant.networks.first()
        subnet = network.subnets.first()
        serialized_network = core_utils.serialize_instance(network)
        serialized_subnet = core_utils.serialize_instance(subnet)
        return chain(
            core_tasks.StateTransitionTask().si(serialized_subnet, state_transition='set_ok'),
            core_tasks.StateTransitionTask().si(serialized_network, state_transition='set_ok'),
            core_tasks.StateTransitionTask().si(serialized_tenant, state_transition='set_ok'),
        )

    @classmethod
    def get_failure_signature(cls, tenant, serialized_tenant, **kwargs):
        return tasks.TenantCreateErrorTask().s(serialized_tenant)


class TenantUpdateExecutor(core_executors.UpdateExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        updated_fields = kwargs['updated_fields']
        if 'name' in updated_fields or 'description' in updated_fields:
            return core_tasks.BackendMethodTask().si(
                serialized_tenant, 'update_tenant', state_transition='begin_updating')
        else:
            return core_tasks.StateTransitionTask().si(serialized_tenant, state_transition='begin_updating')


class TenantDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        state_transition = core_tasks.StateTransitionTask().si(serialized_tenant, state_transition='begin_deleting')
        if not tenant.backend_id:
            return state_transition

        cleanup_networks = cls.get_networks_cleanup_tasks(serialized_tenant)
        cleanup_instances = cls.get_instances_cleanup_tasks(serialized_tenant)
        cleanup_identities = cls.get_identity_cleanup_tasks(serialized_tenant)

        return chain([state_transition] + cleanup_networks + cleanup_instances + cleanup_identities)

    @classmethod
    def get_networks_cleanup_tasks(cls, serialized_tenant):
        return [
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant_floating_ips',
            ),
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant_ports',
            ),
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant_routers',
            ),
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant_networks',
            ),
        ]

    @classmethod
    def get_instances_cleanup_tasks(cls, serialized_tenant):
        return [
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant_security_groups',
            ),
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant_instances',
            ),
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant_snapshots',
            ),
            # The countdown is needed for volumes to transit into proper state after instances deletion
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant_volumes',
            ).set(countdown=30),
        ]

    @classmethod
    def get_identity_cleanup_tasks(cls, serialized_tenant):
        return [
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant_user',
            ),
            core_tasks.BackendMethodTask().si(
                serialized_tenant, backend_method='delete_tenant',
            ),
        ]


class TenantAllocateFloatingIPExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'allocate_floating_ip_address', state_transition='begin_updating')


class TenantDeleteExternalNetworkExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'delete_external_network', state_transition='begin_updating')


class TenantCreateExternalNetworkExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, external_network_data=None, **kwargs):
        if external_network_data is None:
            raise core_executors.ExecutorException(
                'Argument `external_network_data` should be specified for TenantCreateExcternalNetworkExecutor')
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'create_external_network',
            state_transition='begin_updating',
            **external_network_data)


class TenantPushQuotasExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, quotas=None, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'push_tenant_quotas', quotas, state_transition='begin_updating')


class TenantPullExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'pull_tenant',
            state_transition='begin_updating')


class TenantPullSecurityGroupsExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'pull_tenant_security_groups',
            state_transition='begin_updating')


class TenantDetectExternalNetworkExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'detect_external_network',
            state_transition='begin_updating')


class TenantPullFloatingIPsExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'pull_tenant_floating_ips',
            state_transition='begin_updating')


class TenantPullQuotasExecutor(core_executors.ActionExecutor):

    @classmethod
    def get_task_signature(cls, tenant, serialized_tenant, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_tenant, 'pull_tenant_quotas',
            state_transition='begin_updating')


class NetworkCreateExecutor(core_executors.CreateExecutor):

    @classmethod
    def get_task_signature(cls, network, serialized_network, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_network, 'create_network', state_transition='begin_creating')


class NetworkUpdateExecutor(core_executors.UpdateExecutor):

    @classmethod
    def get_task_signature(cls, network, serialized_network, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_network, 'update_network', state_transition='begin_updating')


class NetworkDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def get_task_signature(cls, network, serialized_network, **kwargs):
        if network.backend_id:
            return core_tasks.BackendMethodTask().si(
                serialized_network, 'delete_network', state_transition='begin_deleting')
        else:
            return core_tasks.StateTransitionTask().si(serialized_network, state_transition='begin_deleting')


class NetworkPullExecutor(core_executors.ActionExecutor):
    action = 'pull'

    @classmethod
    def get_task_signature(cls, network, serialized_network, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_network, 'pull_network', state_transition='begin_updating')


class SubNetCreateExecutor(core_executors.CreateExecutor):

    @classmethod
    def get_task_signature(cls, subnet, serialized_subnet, **kwargs):
        return core_tasks.BackendMethodTask().si(serialized_subnet, 'create_subnet', state_transition='begin_creating')


class SubNetUpdateExecutor(core_executors.UpdateExecutor):

    @classmethod
    def get_task_signature(cls, subnet, serialized_subnet, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_subnet, 'update_subnet', state_transition='begin_updating')


class SubNetDeleteExecutor(core_executors.DeleteExecutor):

    @classmethod
    def get_task_signature(cls, subnet, serialized_subnet, **kwargs):
        if subnet.backend_id:
            return core_tasks.BackendMethodTask().si(
                serialized_subnet, 'delete_subnet', state_transition='begin_deleting')
        else:
            return core_tasks.StateTransitionTask().si(serialized_subnet, state_transition='begin_deleting')


class SubNetPullExecutor(core_executors.ActionExecutor):
    action = 'pull'

    @classmethod
    def get_task_signature(cls, subnet, serialized_subnet, **kwargs):
        return core_tasks.BackendMethodTask().si(
            serialized_subnet, 'pull_subnet', state_transition='begin_updating')
