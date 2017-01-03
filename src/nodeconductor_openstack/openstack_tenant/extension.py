from nodeconductor.core import NodeConductorExtension


class OpenStackTenantExtension(NodeConductorExtension):

    class Settings:
        NODECONDUCTOR_OPENSTACK_TENANT = {
            'MAX_CONCURRENT_PROVISION': {
                'OpenStack.Instance': 4,
                'OpenStack.Volume': 4,
                'OpenStack.Snapshot': 4,
            },
        }

    @staticmethod
    def django_app():
        return 'nodeconductor_openstack.openstack_tenant'

    @staticmethod
    def rest_urls():
        from .urls import register_in
        return register_in

    @staticmethod
    def celery_tasks():
        from datetime import timedelta
        return {
            'openstacktenant-pull-resources': {
                'task': 'openstack_tenant.PullResources',
                'schedule': timedelta(minutes=30),
                'args': (),
            },
            'openstacktenant-schedule-backups': {
                'task': 'openstack_tenant.ScheduleBackups',
                'schedule': timedelta(minutes=10),
                'args': (),
            },
            'openstacktenant-delete-expired-backups': {
                'task': 'openstack_tenant.DeleteExpiredBackups',
                'schedule': timedelta(minutes=10),
                'args': (),
            },
            'openstacktenant-set-erred-stuck-resources': {
                'task': 'openstack_tenant.SetErredStuckResources',
                'schedule': timedelta(minutes=10),
                'args': (),
            },
        }
