# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openstack_tenant', '0016_network_subnet'),
    ]

    operations = [
        migrations.CreateModel(
            name='InternalIP',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('mac_address', models.CharField(max_length=32, blank=True)),
                ('ip4_address', models.GenericIPAddressField(null=True, protocol=b'IPv4', blank=True)),
                ('ip6_address', models.GenericIPAddressField(null=True, protocol=b'IPv6', blank=True)),
                ('instance', models.ForeignKey(related_name='internal_ips_set', to='openstack_tenant.Instance')),
                ('subnet', models.ForeignKey(related_name='internal_ips', to='openstack_tenant.SubNet')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
