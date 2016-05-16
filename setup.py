#!/usr/bin/env python
import sys
from setuptools import setup, find_packages


dev_requires = [
    'Sphinx==1.2.2',
]

install_requires = [
    'iptools>=0.6.1',
    'nodeconductor>=0.96.0',
    'python-ceilometerclient==1.0.12',
    'python-cinderclient==1.1.1',
    'python-glanceclient==0.15.0',
    'python-keystoneclient==0.11.1',
    'python-neutronclient==2.3.9',
    'python-novaclient==2.20.0',
]


# RPM installation does not need oslo, cliff and stevedore libs -
# they are required only for installation with setuptools
try:
    action = sys.argv[1]
except IndexError:
    pass
else:
    if action in ['develop', 'install', 'test', 'bdist_egg']:
        install_requires += [
            'cliff==1.7.0',
            'oslo.config==1.4.0',
            'oslo.i18n==1.0.0',
            'oslo.utils==1.0.0',
            'stevedore==1.0.0',
        ]


setup(
    name='nodeconductor-openstack',
    version='0.2.0',
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
    },
    entry_points={
        'nodeconductor_extensions': (
            'nodeconductor_openstack = nodeconductor_openstack.extension:OpenStackExtension',
        ),
    },
    include_package_data=True,
    classifiers=[
        'Framework :: Django',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: Apache Software License',
    ],
)
