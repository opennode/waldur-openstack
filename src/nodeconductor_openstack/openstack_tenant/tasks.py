import logging

from django.conf import settings

from nodeconductor.core import tasks as core_tasks, models as core_models, utils as core_utils
from nodeconductor.structure import SupportedServices, models as structure_models, ServiceBackendError

from nodeconductor_openstack.openstack_base.backend import update_pulled_fields
from . import models, apps


logger = logging.getLogger(__name__)


class RuntimeStateException(Exception):
    pass


class PollRuntimeStateTask(core_tasks.Task):
    max_retries = 300
    default_retry_delay = 5

    @classmethod
    def get_description(cls, instance, backend_pull_method, *args, **kwargs):
        return 'Poll instance "%s" with method "%s"' % (instance, backend_pull_method)

    def get_backend(self, instance):
        return instance.get_backend()

    def execute(self, instance, backend_pull_method, success_state, erred_state):
        backend = self.get_backend(instance)
        getattr(backend, backend_pull_method)(instance)
        instance.refresh_from_db()
        if instance.runtime_state not in (success_state, erred_state):
            self.retry()
        elif instance.runtime_state == erred_state:
            raise RuntimeStateException(
                '%s %s (PK: %s) runtime state become erred: %s' % (
                    instance.__class__.__name__, instance, instance.pk, erred_state))
        return instance


class PollBackendCheckTask(core_tasks.Task):
    max_retries = 60
    default_retry_delay = 5

    @classmethod
    def get_description(cls, instance, backend_check_method, *args, **kwargs):
        return 'Check instance "%s" with method "%s"' % (instance, backend_check_method)

    def get_backend(self, instance):
        return instance.get_backend()

    def execute(self, instance, backend_check_method):
        # backend_check_method should return True if object does not exist at backend
        backend = self.get_backend(instance)
        if not getattr(backend, backend_check_method)(instance):
            self.retry()
        return instance


class RetryUntilAvailableTask(core_tasks.Task):
    max_retries = 300
    default_retry_delay = 5

    def pre_execute(self, instance):
        if not self.is_available(instance):
            self.retry()
        super(RetryUntilAvailableTask, self).pre_execute(instance)

    def is_available(self, instance):
        return True


class BaseThrottleProvisionTask(RetryUntilAvailableTask):
    """
    One OpenStack settings does not support provisioning of more than
    4 instances together, also there are limitations for volumes and snapshots.
    Before starting resource provisioning we need to count how many resources
    are already in "creating" state and delay provisioning if there are too many of them.
    """
    DEFAULT_LIMIT = 4

    def is_available(self, instance):
        usage = self.get_usage(instance)
        limit = self.get_limit(instance)
        return usage <= limit

    def get_usage(self, instance):
        service_settings = instance.service_project_link.service.settings
        model_class = instance._meta.model
        return model_class.objects.filter(
            state=core_models.StateMixin.States.CREATING,
            service_project_link__service__settings=service_settings
        ).count()

    def get_limit(self, instance):
        nc_settings = getattr(settings, 'NODECONDUCTOR_OPENSTACK', {})
        limit_per_type = nc_settings.get('MAX_CONCURRENT_PROVISION', {})
        model_name = SupportedServices.get_name_for_model(instance)
        return limit_per_type.get(model_name, self.DEFAULT_LIMIT)


class ThrottleProvisionTask(BaseThrottleProvisionTask, core_tasks.BackendMethodTask):
    pass


class ThrottleProvisionStateTask(BaseThrottleProvisionTask, core_tasks.StateTransitionTask):
    pass


class SetInstanceErredTask(core_tasks.ErrorStateTransitionTask):
    """ Mark instance as erred and delete resources that were not created. """

    def execute(self, instance):
        super(SetInstanceErredTask, self).execute(instance)

        # delete volumes if they were not created on backend,
        # mark as erred if creation was started, but not ended,
        # leave as is, if they are OK.
        for volume in instance.volumes.all():
            if volume.state == models.Volume.States.CREATION_SCHEDULED:
                volume.delete()
            elif volume.state == models.Volume.States.OK:
                pass
            else:
                volume.set_erred()
                volume.save(update_fields=['state'])


# CELERYBEAT

class PullResources(core_tasks.BackgroundTask):
    name = 'openstack_tenant.PullResources'

    def is_equal(self, other_task):
        return self.name == other_task.get('name')

    def run(self):
        type = apps.OpenStackTenantConfig.service_name
        ok_state = structure_models.ServiceSettings.States.OK
        for service_settings in structure_models.ServiceSettings.objects.filter(type=type, state=ok_state):
            serialized_service_settings = core_utils.serialize_instance(service_settings)
            PullServiceSettingsResources().delay(serialized_service_settings)


class PullServiceSettingsResources(core_tasks.BackgroundTask):
    name = 'openstack_tenant.PullServiceSettingsResources'
    stable_states = (core_models.StateMixin.States.OK, core_models.StateMixin.States.ERRED)

    def is_equal(self, other_task, serialized_service_settings):
        return self.name == other_task.get('name') and serialized_service_settings in other_task.get('args', [])

    def run(self, serialized_service_settings):
        service_settings = core_utils.deserialize_instance(serialized_service_settings)
        backend = service_settings.get_backend()
        try:
            self.pull_volumes(service_settings, backend)
        except ServiceBackendError as e:
            logger.error('Failed to pull resources for service settings: %s. Error: %s' % service_settings, e)
            service_settings.set_erred()
            service_settings.error_message = str(e)
            service_settings.save()

    def pull_volumes(self, service_settings, backend):
        backend_volumes = backend.get_volumes()
        volumes = models.Volume.objects.filter(
            service_project_link__service__settings=service_settings, state__in=self.stable_states)
        backend_volumes_map = {backend_volume.backend_id: backend_volume for backend_volume in backend_volumes}
        for volume in volumes:
            try:
                backend_volume = backend_volumes_map[volume.backend_id]
            except KeyError:
                self._set_erred(volume)
            else:
                self._update(volume, backend_volume, backend.VOLUME_UPDATE_FIELDS)

    def pull_snapshots(self, service_settings, backend):
        backend_snapshots = backend.get_snapshots()
        snapshots = models.Volume.objects.filter(
            service_project_link__service__settings=service_settings, state__in=self.stable_states)
        backend_snapshots_map = {backend_snapshot.backend_id: backend_snapshot
                                 for backend_snapshot in backend_snapshots}
        for snapshot in snapshots:
            try:
                backend_snapshot = backend_snapshots_map[snapshot.backend_id]
            except KeyError:
                self._set_erred(snapshot)
            else:
                self._update(snapshot, backend_snapshot, backend.SNAPSHOT_UPDATE_FIELDS)

    # TODO: provide backend method to get instances.

    def pull_instances(self, service_settings, backend):
        backend_instances = backend.get_instances()
        instances = models.Volume.objects.filter(
            service_project_link__service__settings=service_settings, state__in=self.stable_states)
        backend_instances_map = {backend_instance.backend_id: backend_instance
                                 for backend_instance in backend_instances}
        for instance in instances:
            try:
                backend_instance = backend_instances_map[instance.backend_id]
            except KeyError:
                self._set_erred(instance)
            else:
                self._update(instance, backend_instance, backend.INSTANCE_UPDATE_FIELDS)

    def _set_erred(self, resource):
        resource.set_erred()
        resource.runtime_state = ''
        resource.error_message = 'Does not exist at backend.'
        resource.save()
        logger.warning('%s %s (PK: %s) does not exist at backend.' % (
            resource.__class__.__name__, resource, resource.pk))

    def _update(self, resource, backend_resource, fields):
        update_pulled_fields(resource, backend_resource, fields)
        if resource.state == core_models.StateMixin.States.ERRED:
            resource.recover()
            resource.save(update_fields=['state'])
        logger.info('%s %s (PK: %s) successfully pulled from backend.' % (
            resource.__class__.__name__, resource, resource.pk))
