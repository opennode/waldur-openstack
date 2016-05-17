Installation
------------

* `Install NodeConductor <http://nodeconductor.readthedocs.org/en/latest/guide/intro.html#installation-from-source>`_

* Clone NodeConductor OpenStack repository

  .. code-block:: bash

    git clone https://github.com/opennode/nodeconductor-openstack.git

* Install NodeConductor OpenStack into NodeConductor virtual environment

  .. code-block:: bash

    cd /path/to/nodeconductor-openstack/
    python setup.py install


Installation from RPM repository
--------------------------------

To make sure dependencies are available, first install RDO repository.

.. code-block:: bash
    yum -y install http://opennodecloud.com/centos/7/rdo-release.rpm
    yum -y install nodeconductor-openstack
