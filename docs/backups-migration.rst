Backups endpoints migration
---------------------------

1. States migrations:
     * READY -> OK
     * BACKING_UP -> CREATING
     * RESTORING -> OK
     * DELETING -> DELETING
     * ERRED -> ERRED

   Additionally states CREATION_SCHEDULED, UPDATE_SCHEDULED and DELETION_SCHEDULED were added. It is possible to start 
   several restoration projects simultaneously, so you need to check restoration state in instance. 

2. Endpoints migrations:
     * POST to **/api/openstack-backups/<uuid>/delete/** -> DELETE to **/api/openstack-backups/<uuid>/**
     * POST to **/api/openstack-backups/<uuid>/restore/** -> POST to **/api/openstack-backup-restorations/**
     * Now backups have field "restorations" with restorations details.
