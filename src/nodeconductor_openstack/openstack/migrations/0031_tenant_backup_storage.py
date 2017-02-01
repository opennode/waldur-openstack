# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib.contenttypes.models import ContentType
from django.db import migrations

from nodeconductor.quotas import models as quotas_models

from .. import models


def delete_backup_storage_quota_from_tenant(apps, schema_editor):
    tenant_content_type = ContentType.objects.get_for_model(models.Tenant)
    quota_name = 'backup_storage'
    quotas_models.Quota.objects.filter(name=quota_name, content_type=tenant_content_type).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0030_subnet_dns_nameservers'),
    ]

    operations = [
        migrations.RunPython(delete_backup_storage_quota_from_tenant),
    ]
