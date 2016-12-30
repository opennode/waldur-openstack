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
            'MAX_CONCURRENT_PROVISION': {
                'OpenStack.Instance': 4,
                'OpenStack.Volume': 4,
                'OpenStack.Snapshot': 4
            },
            'SUBNET': {
                # Allow cidr: 192.168.[1-255].0/24
                'CIDR_REGEX': r'192\.168\.(?:25[0-4]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]?)\.0/24',
                'CIDR_REGEX_EXPLANATION': 'Value should be 192.168.[1-254].0/24',
                'ALLOCATION_PULL_START': '{first_octet}.{second_octet}.{third_octet}.10',
                'ALLOCATION_PULL_END': '{first_octet}.{second_octet}.{third_octet}.200',
            },
        }

    @staticmethod
    def django_app():
        return 'nodeconductor_openstack.openstack'

    @staticmethod
    def rest_urls():
        from .urls import register_in
        return register_in

    @staticmethod
    def celery_tasks():
        from datetime import timedelta
        return {
            'openstack-schedule-backups': {
                'task': 'openstack.schedule_backups',
                'schedule': timedelta(minutes=10),
                'args': (),
            },

            'openstack-delete-expired-backups': {
                'task': 'openstack.delete_expired_backups',
                'schedule': timedelta(minutes=10),
                'args': (),
            },

            'openstack-set-erred-stuck-resources': {
                'task': 'openstack.set_erred_stuck_resources',
                'schedule': timedelta(minutes=10),
                'args': (),
            },

            'openstack-pull-tenants': {
                'task': 'openstack.TenantListPullTask',
                'schedule': timedelta(minutes=30),
                'args': (),
            },

            'openstack-pull-instances': {
                'task': 'openstack.InstanceListPullTask',
                'schedule': timedelta(minutes=30),
                'args': (),
            },

            'openstack-pull-volumes': {
                'task': 'openstack.VolumeListPullTask',
                'schedule': timedelta(minutes=30),
                'args': (),
            },
        }
