from django.conf import settings

from nodeconductor.core import tasks as core_tasks
from nodeconductor.structure import SupportedServices, models as structure_models


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
        state = self.get_provisioning_state(instance)
        service_settings = instance.service_project_link.service.settings
        model_class = instance._meta.model
        return model_class.objects.filter(
            state=state,
            service_project_link__service__settings=service_settings
        ).count()

    def get_provisioning_state(self, instance):
        if isinstance(instance, structure_models.Resource):
            return structure_models.Resource.States.PROVISIONING
        elif isinstance(instance, structure_models.NewResource):
            return structure_models.NewResource.States.CREATING

    def get_limit(self, instance):
        nc_settings = getattr(settings, 'NODECONDUCTOR_OPENSTACK', {})
        limit_per_type = nc_settings.get('MAX_CONCURRENT_PROVISION', {})
        model_name = SupportedServices.get_name_for_model(instance)
        return limit_per_type.get(model_name, self.DEFAULT_LIMIT)


class ThrottleProvisionTask(BaseThrottleProvisionTask, core_tasks.BackendMethodTask):
    pass


class ThrottleProvisionStateTask(BaseThrottleProvisionTask, core_tasks.StateTransitionTask):
    pass
