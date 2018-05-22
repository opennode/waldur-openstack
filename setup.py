#!/usr/bin/env python
from setuptools import setup, find_packages


tests_requires = [
    'ddt>=1.0.0'
]

dev_requires = [
    'Sphinx==1.2.2',
]

install_requires = [
    'pbr!=2.1.0',
    'Babel!=2.4.0,>=2.3.4',
    'iptools>=0.6.1',
    'waldur-core>=0.157.5',
    'python-ceilometerclient>=2.9.0',
    'python-cinderclient>=3.1.0',
    'python-glanceclient>=2.8.0',
    'python-keystoneclient>=3.13.0',
    'python-neutronclient>=6.5.0',
    'python-novaclient>=9.1.0',
]


setup(
    name='waldur-openstack',
    version='0.42.1',
    author='OpenNode Team',
    author_email='info@opennodecloud.com',
    url='http://waldur.com',
    description='Waldur plugin for managing OpenStack resources.',
    long_description=open('README.rst').read(),
    license='MIT',
    package_dir={'': 'src'},
    packages=find_packages('src'),
    install_requires=install_requires,
    zip_safe=False,
    extras_require={
        'dev': dev_requires,
        'tests': tests_requires,
    },
    entry_points={
        'waldur_extensions': (
            'openstack = waldur_openstack.openstack.extension:OpenStackExtension',
            'openstack_tenant = waldur_openstack.openstack_tenant.extension:OpenStackTenantExtension',
        ),
    },
    include_package_data=True,
    classifiers=[
        'Framework :: Django',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: MIT License',
    ],
)
