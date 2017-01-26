# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0029_tenant_quotas'),
    ]

    operations = [
        migrations.AddField(
            model_name='subnet',
            name='dns_nameservers',
            field=jsonfield.fields.JSONField(default=[], help_text='List of DNS name servers associated with the subnet.'),
        ),
    ]
