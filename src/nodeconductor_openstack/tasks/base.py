from celery import shared_task, current_app
from functools import wraps

from nodeconductor.core.tasks import retry_if_false, Task

from .. import models
from ..backend import OpenStackClient


def track_openstack_session(task_fn):
    @wraps(task_fn)
    def wrapped(tracked_session, *args, **kwargs):
        client = OpenStackClient(session=tracked_session)
        task_fn(client, *args, **kwargs)
        return client.session
    return wrapped


def save_error_message_from_task(func):
    @wraps(func)
    def wrapped(task_uuid, *args, **kwargs):
        func(*args, **kwargs)
        result = current_app.AsyncResult(task_uuid)
        transition_entity = kwargs['transition_entity']
        message = result.result['exc_message']
        if message:
            transition_entity.error_message = message
            transition_entity.save(update_fields=['error_message'])
    return wrapped


@shared_task
@track_openstack_session
def nova_server_resize(client, server_id, flavor_id):
    client.nova.servers.resize(server_id, flavor_id, 'MANUAL')


@shared_task
@track_openstack_session
def nova_server_resize_confirm(client, server_id):
    client.nova.servers.confirm_resize(server_id)


@shared_task(max_retries=300, default_retry_delay=3)
@track_openstack_session
@retry_if_false
def nova_wait_for_server_status(client, server_id, status):
    server = client.nova.servers.get(server_id)
    return server.status == status


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
    """ Poll was object deleted from backend """
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
