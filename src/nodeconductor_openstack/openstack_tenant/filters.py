from nodeconductor.core import filters as core_filters
from nodeconductor.structure import filters as structure_filters

from . import models


class OpenStackTenantServiceProjectLinkFilter(structure_filters.BaseServiceProjectLinkFilter):
    service = core_filters.URLFilter(view_name='openstack-detail', name='service__uuid')

    class Meta(object):
        model = models.OpenStackTenantServiceProjectLink
