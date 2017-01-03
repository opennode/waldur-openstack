from nodeconductor.core import tasks as core_tasks

from .. import models


class TenantCreateErrorTask(core_tasks.ErrorStateTransitionTask):

    def execute(self, tenant):
        super(TenantCreateErrorTask, self).execute(tenant)
        # Delete network and subnet if they were not created on backend,
        # mark as erred if they were created
        network = tenant.networks.first()
        subnet = network.subnets.first()
        if subnet.state == models.SubNet.States.CREATION_SCHEDULED:
            subnet.delete()
        else:
            super(TenantCreateErrorTask, self).execute(subnet)
        if network.state == models.Network.States.CREATION_SCHEDULED:
            network.delete()
        else:
            super(TenantCreateErrorTask, self).execute(network)
