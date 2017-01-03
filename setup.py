#!/usr/bin/env python
from setuptools import setup, find_packages


test_requires = [
    'ddt>=1.0.0'
]

dev_requires = [
    'Sphinx==1.2.2',
]

install_requires = [
    'iptools>=0.6.1',
    'nodeconductor>=0.114.0',
    'python-ceilometerclient>=2.3.0',
    'python-cinderclient>=1.6.0',
    'python-glanceclient>=2.0.0',
    'python-keystoneclient>=2.3.1',
    'python-neutronclient>=4.1.1',
    'python-novaclient==3.3.0',
]


setup(
    name='nodeconductor-openstack',
    version='0.12.0',
    author='OpenNode Team',
    author_email='info@opennodecloud.com',
    url='http://nodeconductor.com',
    description='NodeConductor plugin for managing OpenStack resources.',
    long_description=open('README.rst').read(),
    package_dir={'': 'src'},
    packages=find_packages('src', exclude=['*.tests', '*.tests.*', 'tests.*', 'tests']),
    install_requires=install_requires,
    zip_safe=False,
    extras_require={
        'dev': dev_requires,
        'test': test_requires,
    },
    entry_points={
        'nodeconductor_extensions': (
            'openstack = nodeconductor_openstack.openstack.extension:OpenStackExtension',
            'openstack_tenant = nodeconductor_openstack.openstack_tenant.extension:OpenStackTenantExtension',
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
