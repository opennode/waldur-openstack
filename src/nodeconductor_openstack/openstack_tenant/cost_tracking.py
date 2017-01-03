from nodeconductor.cost_tracking import CostTrackingStrategy, ConsumableItem

from . import models, ApplicationTypes, OsTypes, SupportTypes, PriceItemTypes


class InstanceStrategy(CostTrackingStrategy):
    resource_class = models.Instance

    class Types(object):
        FLAVOR = PriceItemTypes.FLAVOR
        LICENSE_APPLICATION = PriceItemTypes.LICENSE_APPLICATION
        LICENSE_OS = PriceItemTypes.LICENSE_OS
        SUPPORT = PriceItemTypes.SUPPORT

    @classmethod
    def get_consumable_items(cls):
        for os, name in OsTypes.CHOICES:
            yield ConsumableItem(item_type=cls.Types.LICENSE_OS, key=os, name='OS: %s' % os)

        for key, name in ApplicationTypes.CHOICES:
            yield ConsumableItem(
                item_type=cls.Types.LICENSE_APPLICATION, key=key, name='Application: %s' % name)

        for key, name in SupportTypes.CHOICES:
            yield ConsumableItem(item_type=cls.Types.SUPPORT, key=key, name='Support: %s' % name)

        for flavor_name in set(models.Flavor.objects.all().values_list('name', flat=True)):
            yield ConsumableItem(item_type=cls.Types.FLAVOR, key=flavor_name, name='Flavor: %s' % flavor_name)

    @classmethod
    def get_configuration(cls, instance):
        States = models.Instance.States
        RuntimeStates = models.Instance.RuntimeStates
        tags = [t.name for t in instance.tags.all()]

        consumables = {}
        for type in (cls.Types.LICENSE_APPLICATION, cls.Types.LICENSE_OS, cls.Types.SUPPORT):
            try:
                key = [t.split(':')[1] for t in tags if t.startswith('%s:' % type)][0]
            except IndexError:
                continue
            consumables[ConsumableItem(item_type=type, key=key)] = 1

        if instance.state == States.OK and instance.runtime_state == RuntimeStates.ACTIVE:
            consumables[ConsumableItem(item_type=cls.Types.FLAVOR, key=instance.flavor_name)] = 1
        return consumables


class VolumeStrategy(CostTrackingStrategy):
    resource_class = models.Volume

    class Types(object):
        STORAGE = PriceItemTypes.STORAGE

    class Keys(object):
        STORAGE = '1 GB'

    @classmethod
    def get_consumable_items(cls):
        return [ConsumableItem(item_type=cls.Types.STORAGE, key=cls.Keys.STORAGE, name='1 GB of storage', units='GB')]

    @classmethod
    def get_configuration(cls, volume):
        return {ConsumableItem(item_type=cls.Types.STORAGE, key=cls.Keys.STORAGE): float(volume.size) / 1024}


class SnapshotStrategy(CostTrackingStrategy):
    resource_class = models.Snapshot

    class Types(object):
        STORAGE = PriceItemTypes.STORAGE

    class Keys(object):
        STORAGE = '1 GB'

    @classmethod
    def get_consumable_items(cls):
        return [ConsumableItem(item_type=cls.Types.STORAGE, key=cls.Keys.STORAGE, name='1 GB of storage', units='GB')]

    @classmethod
    def get_configuration(cls, snapshot):
        return {ConsumableItem(item_type=cls.Types.STORAGE, key=cls.Keys.STORAGE): float(snapshot.size) / 1024}
