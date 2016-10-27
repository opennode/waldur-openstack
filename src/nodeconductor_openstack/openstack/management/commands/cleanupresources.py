from __future__ import unicode_literals

from django.core.management.base import BaseCommand

from nodeconductor.structure import models as structure_models

from ... import models, executors


class Command(BaseCommand):
    help_text = "Pull OpenStack instance from backend, connect it to zabbix and billing."

    def handle(self, *args, **options):
        project_name = 'TST PaaS project'
        service_settings_name = 'TST OpenStack service settings'

        project = structure_models.Project.objects.get(name=project_name)
        service_settings = structure_models.ServiceSettings.objects.get(name=service_settings_name)
        spl = models.OpenStackServiceProjectLink.objects.get(project=project, service__settings=service_settings)

        pulled_models = [
            (models.Instance, executors.InstancePullExecutor),
            (models.Volume, executors.VolumePullExecutor),
            (models.Snapshot, executors.SnapshotPullExecutor),
        ]

        print 'Deleting from DB OpenStack resources that does not belong to SPL: %s' % spl
        for model, _ in pulled_models:
            model.objects.exclude(service_project_link=spl).delete()

        for model, executor in pulled_models:
            for obj in model.objects.filter(service_project_link=spl):
                print 'Pulling %s: %s' % (model.__name__, obj)
                try:
                    executor.execute(obj, async=False)
                except Exception as e:
                    print 'Failed to pull object %s. It will be deleted. Error: %s' % (obj, e)
                    obj.delete()
                else:
                    if hasattr(obj, 'set_ok'):
                        obj.set_ok()
                        obj.save()
        # TODO: correct after instance states migration.
