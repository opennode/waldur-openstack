from nodeconductor.cost_tracking import CostTrackingRegister, CostTrackingStrategy, ConsumableItem

from . import models


class InstanceStrategy(CostTrackingStrategy):
    ''' Describes all methods that should be implemented to enable cost
        tracking for particular resource.
    '''
    resource_class = models.Instance

    class Types(object):
        FLAVOR = 'flavor'
        LICENSE_APPLICATION = 'license-application'
        LICENSE_OS = 'license-os'
        SUPPORT = 'support'

    @classmethod
    def get_configuration(cls, resource):
        States = models.Instance.States
        if resource.state == States.ERRED:
            return {}
        tags = [t.name for t in resource.tags.all()]

        consumables = {}
        for type in (cls.Types.LICENSE_APPLICATION, cls.Types.LICENSE_OS, cls.Types.SUPPORT):
            try:
                key = [t.split(':')[1] for t in tags if t.startswith('%s:' % type)][0]
            except IndexError:
                continue
            consumables[ConsumableItem(item_type=type, key=key)] = 1

        if resource.state == States.ONLINE:
            consumables[ConsumableItem(item_type=cls.Types.FLAVOR, key=resource.flavor_name)] = 1
        return consumables

    # XXX: Need to decide where to store applications, support and os constants.
    @classmethod
    def get_consumable_items(cls):
        for os in ['centos6', 'centos7', 'ubuntu', 'rhel6', 'rhel7', 'freebsd', 'windows', 'other']:
            yield ConsumableItem(item_type=cls.Types.LICENSE_OS, key=os, name='OS: %s' % os)

        for application in ['wordpress', 'postgresql', 'zabbix', 'zimbra', 'sugar']:
            yield ConsumableItem(
                item_type=cls.Types.LICENSE_APPLICATION, key=application, name='Application: %s' % application)

        for support in ['basic', 'premium', 'advanced']:
            yield ConsumableItem(item_type=cls.Types.SUPPORT, key=support, name='Support: %s' % support)

        for flavor_name in set(models.Flavor.objects.all().values_list('name', flat=True)):
            yield ConsumableItem(item_type=cls.Types.FLAVOR, key=flavor_name, name='Flavor: %s' % flavor_name)


CostTrackingRegister.register_strategy(InstanceStrategy)
