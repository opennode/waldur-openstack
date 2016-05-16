from nodeconductor.core import NodeConductorExtension


class OpenStackExtension(NodeConductorExtension):

    class Settings:
        NODECONDUCTOR_OPENSTACK = {
            'DEFAULT_SECURITY_GROUPS': (
                {
                    'name': 'ssh',
                    'description': 'Security group for secure shell access and ping',
                    'rules': (
                        {
                            'protocol': 'tcp',
                            'cidr': '0.0.0.0/0',
                            'from_port': 22,
                            'to_port': 22,
                        },
                        {
                            'protocol': 'icmp',
                            'cidr': '0.0.0.0/0',
                            'icmp_type': -1,
                            'icmp_code': -1,
                        },
                    ),
                },
            ),
        }

    @staticmethod
    def django_app():
        return 'nodeconductor_openstack'

    @staticmethod
    def rest_urls():
        from .urls import register_in
        return register_in

    @staticmethod
    def celery_tasks():
        from datetime import timedelta
        return {
            'openstack-schedule-backups': {
                'task': 'nodeconductor.openstack.schedule_backups',
                'schedule': timedelta(minutes=10),
                'args': (),
            },

            'openstack-delete-expired-backups': {
                'task': 'nodeconductor.openstack.delete_expired_backups',
                'schedule': timedelta(minutes=10),
                'args': (),
            },

            'openstack-pull-tenants': {
                'task': 'nodeconductor.openstack.pull_tenants',
                'schedule': timedelta(minutes=30),
                'args': (),
            },

            'openstack-pull-tenants-properties': {
                'task': 'nodeconductor.openstack.pull_tenants_properties',
                'schedule': timedelta(minutes=30),
                'args': (),
            },
        }
