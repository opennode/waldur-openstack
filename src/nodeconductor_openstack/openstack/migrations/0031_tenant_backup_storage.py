# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib.contenttypes.models import ContentType
from django.db import migrations

from nodeconductor.quotas import models as quotas_models

from .. import models


def cleanup_tenant_quotas(apps, schema_editor):
    for obj in models.Tenant.objects.all():
        quotas_names = models.Tenant.QUOTAS_NAMES + [f.name for f in models.Tenant.get_quotas_fields()]
        obj.quotas.exclude(name__in=quotas_names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0030_subnet_dns_nameservers'),
    ]

    operations = [
        migrations.RunPython(cleanup_tenant_quotas),
    ]
