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
            'SUBNET': {
                # Allow cidr: 192.168.[1-255].0/24
                'CIDR_REGEX': r'192\.168\.(?:25[0-4]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]?)\.0/24',
                'CIDR_REGEX_EXPLANATION': 'Value should be 192.168.[1-254].0/24',
                'ALLOCATION_POOL_START': '{first_octet}.{second_octet}.{third_octet}.10',
                'ALLOCATION_POOL_END': '{first_octet}.{second_octet}.{third_octet}.200',
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
            'openstack-pull-tenants': {
                'task': 'openstack.TenantListPullTask',
                'schedule': timedelta(minutes=30),
                'args': (),
            },
        }
