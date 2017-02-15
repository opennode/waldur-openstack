from nodeconductor.logging.loggers import EventLogger, event_logger


class TenantQuotaLogger(EventLogger):
    quota = 'quotas.Quota'
    tenant = 'openstack.Tenant'
    limit = float

    class Meta:
        event_types = ('openstack_tenant_quota_limit_updated',)
        event_groups = {
            'resources': event_types,
        }


class TenantLogger(EventLogger):
    tenant = 'openstack.Tenant'

    class Meta:
        event_types = ('openstack_tenant_user_password_changed',)
        event_groups = {
            'resources': event_types,
        }


event_logger.register('openstack_tenant_quota', TenantQuotaLogger)
event_logger.register('openstack_tenant', TenantLogger)
