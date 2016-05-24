#!/usr/bin/env python
import sys
from setuptools import setup, find_packages


dev_requires = [
    'Sphinx==1.2.2',
]

install_requires = [
    'iptools>=0.6.1',
    'nodeconductor>=0.97.0',
    'python-ceilometerclient==2.0.1',
    'python-cinderclient==1.5.0',
    'python-glanceclient==1.1.1',
    'python-keystoneclient==1.8.1',
    'python-neutronclient==4.0.0',
    'python-novaclient==2.35.0',
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
