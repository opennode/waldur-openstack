# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
import nodeconductor.logging.loggers
import nodeconductor.core.fields
import nodeconductor.core.models
import nodeconductor.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('structure', '0037_remove_customer_billing_backend_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='OpenStackTenantService',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=150, verbose_name='name', validators=[nodeconductor.core.validators.validate_name])),
                ('uuid', nodeconductor.core.fields.UUIDField()),
                ('available_for_all', models.BooleanField(default=False, help_text='Service will be automatically added to all customers projects if it is available for all')),
                ('customer', models.ForeignKey(to='structure.Customer')),
            ],
            options={
                'verbose_name': 'OpenStackTenant service',
                'verbose_name_plural': 'OpenStackTenan services',
            },
            bases=(nodeconductor.core.models.DescendantMixin, nodeconductor.logging.loggers.LoggableMixin, models.Model),
        ),
        migrations.CreateModel(
            name='OpenStackTenantServiceProjectLink',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('project', models.ForeignKey(to='structure.Project')),
                ('service', models.ForeignKey(to='openstack_tenant.OpenStackTenantService')),
            ],
            options={
                'abstract': False,
                'verbose_name': 'OpenStackTenant service project link',
                'verbose_name_plural': 'OpenStackTenant service project links',
            },
            bases=(nodeconductor.core.models.DescendantMixin, nodeconductor.logging.loggers.LoggableMixin, models.Model),
        ),
        migrations.AddField(
            model_name='openstacktenantservice',
            name='projects',
            field=models.ManyToManyField(related_name='openstack_tenant_services', through='openstack_tenant.OpenStackTenantServiceProjectLink', to='structure.Project'),
        ),
        migrations.AddField(
            model_name='openstacktenantservice',
            name='settings',
            field=models.ForeignKey(to='structure.ServiceSettings'),
        ),
        migrations.AlterUniqueTogether(
            name='openstacktenantserviceprojectlink',
            unique_together=set([('service', 'project')]),
        ),
        migrations.AlterUniqueTogether(
            name='openstacktenantservice',
            unique_together=set([('customer', 'settings')]),
        ),
    ]
