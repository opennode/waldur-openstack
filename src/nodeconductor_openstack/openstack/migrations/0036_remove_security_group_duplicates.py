# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.db.models import Count


def remove_duplicates(apps, schema_editor):
    SecurityGroup = apps.get_model('openstack', 'SecurityGroup')
    OK_STATE = 3

    for duplicate_id in SecurityGroup.objects.values_list('backend_id', flat=True).annotate(
            duplicates_count=Count('backend_id')).filter(duplicates_count__gt=1):
        duplicates_query = SecurityGroup.objects.filter(backend_id=duplicate_id)
        # try to leave only support groups in OK state
        if duplicates_query.filter(state=OK_STATE).count() > 0:
            security_group = duplicates_query.filter(state=OK_STATE).first()
        else:
            security_group = duplicates_query.first()

        duplicates_query.exclude(id=security_group.id).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0035_remove_ipmapping'),
    ]

    operations = [
        migrations.RunPython(remove_duplicates),
    ]
