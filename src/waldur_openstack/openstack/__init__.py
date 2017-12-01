from waldur_core import _get_version

__version__ = _get_version('waldur_openstack')

default_app_config = 'waldur_openstack.openstack.apps.OpenStackConfig'
