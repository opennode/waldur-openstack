from nodeconductor_openstack.openstack_base.backend import BaseOpenStackBackend


class OpenStackTenantBackend(BaseOpenStackBackend):

    def __init__(self, settings):
        super(OpenStackTenantBackend, self).__init__(settings, settings.options['tenant_id'])

    def sync(self):
        pass  # TODO: get settings properties here.
