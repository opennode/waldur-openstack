from nodeconductor.core import NodeConductorExtension


class OpenStackTenantExtension(NodeConductorExtension):

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
        }
