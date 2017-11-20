import copy

from django.conf import settings
from django.test import override_settings


def override_openstack_settings(**kwargs):
    os_settings = copy.deepcopy(settings.NODECONDUCTOR_OPENSTACK)
    os_settings.update(kwargs)
    return override_settings(NODECONDUCTOR_OPENSTACK=os_settings)
