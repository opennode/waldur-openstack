from nodeconductor.core import NodeConductorExtension


class OpenStackTenantExtension(NodeConductorExtension):

    @staticmethod
    def django_app():
        return 'nodeconductor_openstack.openstack_tenant'

    @staticmethod
    def rest_urls():
        from .urls import register_in
        return register_in
