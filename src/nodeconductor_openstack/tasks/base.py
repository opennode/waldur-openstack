from celery import shared_task

from nodeconductor.core.tasks import Task

from .. import models


# TODO: move this signal to itacloud assembly application
@shared_task
def register_instance_in_zabbix(instance_uuid):
    from nodeconductor.template.zabbix import register_instance
    instance = models.Instance.objects.get(uuid=instance_uuid)
    register_instance(instance)


class RuntimeStateException(Exception):
    pass


class PollRuntimeStateTask(Task):
    max_retries = 300
    default_retry_delay = 5

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
                'Instance %s (PK: %s) runtime state become erred: %s' % (instance, instance.pk, erred_state))
        return instance


class PollBackendCheckTask(Task):
    max_retries = 60
    default_retry_delay = 5

    def get_backend(self, instance):
        return instance.get_backend()

    def execute(self, instance, backend_check_method):
        # backend_check_method should return True if object does not exist at backend
        backend = self.get_backend(instance)
        if not getattr(backend, backend_check_method)(instance):
            self.retry()
        return instance
