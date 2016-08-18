from __future__ import absolute_import

# Global import of all tasks from submodules.
# Required for proper work of celery autodiscover
# and adding all tasks to the registry.

from .backup import *
from .backup_restoration import *
from .base import *
from .celerybeat import *
from .dr_backup import *
from .dr_backup_restoration import *
from .flavor import *
from .floating_ip import *
from .instance import *
from .volume import *
