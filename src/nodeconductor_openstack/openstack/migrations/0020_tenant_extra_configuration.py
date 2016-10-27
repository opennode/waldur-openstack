# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('openstack', '0019_remove_payable_mixin'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='extra_configuration',
            field=jsonfield.fields.JSONField(default={}, help_text='Configuration details that are not represented on backend.'),
        ),
    ]
