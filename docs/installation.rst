Installation from source
------------------------

* `Install NodeConductor <http://nodeconductor.readthedocs.org/en/latest/guide/intro.html#installation-from-source>`_

* Clone Waldur OpenStack repository

  .. code-block:: bash

    git clone https://github.com/opennode/waldur-openstack.git

* Install Waldur OpenStack into Waldur virtual environment

  .. code-block:: bash

    cd /path/to/waldur-openstack/
    python setup.py install

Configuration
+++++++++++++

OpenStack plugin settings should be defined in Waldur's settings.py file
under **WALDUR_OPENSTACK** section.

For example,

.. code-block:: python

      WALDUR_OPENSTACK = {
          'DEFAULT_SECURITY_GROUPS': (
              {
                  'name': 'ssh',
                  'description': 'Security group for secure shell access',
                  'rules': (
                      {
                          'protocol': 'tcp',
                          'cidr': '0.0.0.0/0',
                          'from_port': 22,
                          'to_port': 22,
                      },
                      {
                          'protocol': 'icmp',
                          'cidr': '0.0.0.0/0',
                          'icmp_type': -1,
                          'icmp_code': -1,
                      },
                  ),
              },
          ),
          'OPENSTACK_QUOTAS_INSTANCE_RATIOS': {
              'volumes': 4,
              'snapshots': 20,
          },
      }

Available settings:

.. glossary::

    DEFAULT_SECURITY_GROUPS
      A list of security groups that will be created for all tenants.

      Each entry is a dictionary with the following keys:

        name
          Short name of the security group.

        description
          Detailed description of the security group.

        rules
          List of firewall rules that make up the security group.

          Each entry is a dictionary with the following keys:

        protocol
          Transport layer protocol the rule applies to.
          Must be one of *tcp*, *udp* or *icmp*.

        cidr
          IPv4 network of packet source.
          Must be a string in `CIDR notation <https://en.wikipedia.org/wiki/Classless_Inter-Domain_Routing>`_.

        from_port
          Start of packet destination port range.
          Must be a number in range from 1 to 65535.

          For *tcp* and *udp* protocols only.

        to_port
          End of packet destination port range.
          Must be a number in range from 1 to 65535.
          Must not be less than **from_port**.

          For *tcp* and *udp* protocols only.

        icmp_type
          ICMP type of the packet.
          Must be a number in range from -1 to 255.

        See also: `ICMP Types and Codes <http://www.nthelp.com/icmp.html>`_.

        For *icmp* protocol only.

        icmp_code
          ICMP code of the packet.
          Must be a number in range from -1 to 255.

          See also: `ICMP Types and Codes <http://www.nthelp.com/icmp.html>`_.

          For *icmp* protocol only.

    MAX_CONCURRENT_PROVISION
      Dictionary with model name as key and concurrent resources provisioning limit as value.


Installation from RPM repository
--------------------------------

To make sure dependencies are available, first install RDO repository.

.. code-block:: bash

    yum -y install http://opennodecloud.com/centos/7/rdo-release.rpm
    yum -y install waldur-openstack
