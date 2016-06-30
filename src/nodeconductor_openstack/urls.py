from . import views


def register_in(router):
    router.register(r'openstack', views.OpenStackServiceViewSet, base_name='openstack')
    router.register(r'openstack-images', views.ImageViewSet, base_name='openstack-image')
    router.register(r'openstack-flavors', views.FlavorViewSet, base_name='openstack-flavor')
    router.register(r'openstack-instances', views.InstanceViewSet, base_name='openstack-instance')
    router.register(r'openstack-tenants', views.TenantViewSet, base_name='openstack-tenant')
    router.register(r'openstack-service-project-link', views.OpenStackServiceProjectLinkViewSet, base_name='openstack-spl')
    router.register(r'openstack-security-groups', views.SecurityGroupViewSet, base_name='openstack-sgp')
    router.register(r'openstack-ip-mappings', views.IpMappingViewSet, base_name='openstack-ip-mapping')
    router.register(r'openstack-floating-ips', views.FloatingIPViewSet, base_name='openstack-fip')
    router.register(r'openstack-backup-schedules', views.BackupScheduleViewSet, base_name='openstack-schedule')
    router.register(r'openstack-backups', views.BackupViewSet, base_name='openstack-backup')
    router.register(r'openstack-backup-restorations', views.BackupRestorationViewSet,
                    base_name='openstack-backup-restoration')
    router.register(r'openstack-licenses', views.LicenseViewSet, base_name='openstack-license')
    router.register(r'openstack-volumes', views.VolumeViewSet, base_name='openstack-volume')
    router.register(r'openstack-snapshots', views.SnapshotViewSet, base_name='openstack-snapshot')
    router.register(r'openstack-dr-backups', views.DRBackupViewSet, base_name='openstack-dr-backup')
    router.register(r'openstack-dr-backup-restorations', views.DRBackupRestorationViewSet,
                    base_name='openstack-dr-backup-restoration')
