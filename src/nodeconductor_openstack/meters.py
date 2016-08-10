from . import models

# XXX: Meters should be grouped by OpenStack version.
INSTANCE_METERS = [
    # Meters added in the Icehouse release or earlier
    {
        'name': 'instance',
        'type': 'Gauge',
        'unit': 'instance',
        'description': 'Existence of instance',
    },
    {
        'name': 'memory',
        'type': 'Gauge',
        'unit': 'MB',
        'description': 'Volume of RAM allocated to the instance',
    },
    {
        'name': 'memory.usage',
        'type': 'Gauge',
        'unit': 'MB',
        'description': 'Volume of RAM used by the instance from the amount of its allocated memory',
    },
    {
        'name': 'cpu',
        'type': 'Cumulative',
        'unit': 'ns',
        'description': 'CPU time used',
    },
    {
        'name': 'cpu_util',
        'type': 'Gauge',
        'unit': '%',
        'description': 'Average CPU utilization',
    },
    {
        'name': 'vcpus',
        'type': 'Gauge',
        'unit': 'vcpu',
        'description': 'Number of virtual CPUs allocated to the instance',
    },
    {
        'name': 'disk.read.requests',
        'type': 'Cumulative',
        'unit': 'request',
        'description': 'Number of read requests',
    },
    {
        'name': 'disk.read.requests.rate',
        'type': 'Cumulative',
        'unit': 'request/s',
        'description': 'Average rate of read requests',
    },
    {
        'name': 'disk.write.requests',
        'type': 'Cumulative',
        'unit': 'request',
        'description': 'Number of write requests',
    },
    {
        'name': 'disk.write.requests.rate',
        'type': 'Gauge',
        'unit': 'request/s',
        'description': 'Average rate of write requests',
    },
    {
        'name': 'disk.read.bytes',
        'type': 'Cumulative',
        'unit': 'B',
        'description': 'Volume of reads',
    },
    {
        'name': 'disk.read.bytes.rate',
        'type': 'Gauge',
        'unit': 'B/s',
        'description': 'Average rate of reads',
    },
    {
        'name': 'disk.write.bytes',
        'type': 'Cumulative',
        'unit': 'B',
        'description': 'Volume of writes',
    },
    {
        'name': 'disk.write.bytes.rate',
        'type': 'Gauge',
        'unit': 'B/s',
        'description': 'Average rate of writes',
    },
    {
        'name': 'disk.root.size',
        'type': 'Gauge',
        'unit': 'GB',
        'description': 'Size of root disk',
    },
    {
        'name': 'disk.ephemeral.size',
        'type': 'Gauge',
        'unit': 'GB',
        'description': 'Size of ephemeral disk',
    },
    # Meters added in the Kilo release
    {
        'name': 'memory.resident',
        'type': 'Gauge',
        'unit': 'MB',
        'description': 'Volume of RAM used by the instance on the physical machine',
    },
    {
        'name': 'disk.latency',
        'type': 'Gauge',
        'unit': 'ms',
        'description': 'Average disk latency',
    },
    {
        'name': 'disk.iops',
        'type': 'Gauge',
        'unit': 'count/s',
        'description': 'Average disk iops',
    },
    {
        'name': 'disk.capacity',
        'type': 'Gauge',
        'unit': 'B',
        'description': 'The amount of disk that the instance can see',
    },
    {
        'name': 'disk.allocation',
        'type': 'Gauge',
        'unit': 'B',
        'description': 'The amount of disk occupied by the instance on the host machine',
    },
    {
        'name': 'disk.usage',
        'type': 'Gauge',
        'unit': 'B',
        'description': 'The physical size in bytes of the image container on the host',
    },
    # Meters added in the Liberty release
    {
        'name': 'cpu.delta',
        'type': 'Delta',
        'unit': 'ns',
        'description': 'CPU time used since previous datapoint',
    },
    # Meters added in the Newton release
    {
        'name': 'cpu_l3_cache',
        'type': 'Gauge',
        'unit': 'B',
        'description': 'L3 cache used by the instance',
    },
]

VOLUME_METERS = [
    # Meters added in the Icehouse release or earlier
    {
        'name': 'volume',
        'type': 'Gauge',
        'unit': 'volume',
        'description': 'Existence of the volume'
    },
    {
        'name': 'volume.size',
        'type': 'Gauge',
        'unit': 'GB',
        'description': 'Size of the volume'
    },
    # Meters added in the Kilo release
    {
        'name': 'volume.create.start',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume creation start'
    },
    {
        'name': 'volume.create.end',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume creation end'
    },
    {
        'name': 'volume.delete.start',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume deletion start'
    },
    {
        'name': 'volume.delete.end',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume deletion end'
    },
    {
        'name': 'volume.update.start',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume name or description update start'
    },
    {
        'name': 'volume.update.end',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume name or description update end'
    },
    {
        'name': 'volume.resize.start',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume size update start'
    },
    {
        'name': 'volume.resize.end',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume size update end'
    },
    {
        'name': 'volume.attach.start',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume attachment to an instance start'
    },
    {
        'name': 'volume.attach.end',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume attachment to an instance end'
    },
    {
        'name': 'volume.detach.start',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume detachment from an instance start'
    },
    {
        'name': 'volume.detach.end',
        'type': 'Delta',
        'unit': 'volume',
        'description': 'The volume detachment from an instance end'
    }
]

SNAPSHOT_METERS = [
    # Meters added in the Juno release
    {
        'name': 'snapshot',
        'type': 'Gauge',
        'unit': 'snapshot',
        'description': 'Existence of the snapshot'
    },
    {
        'name': 'snapshot.size',
        'type': 'Gauge',
        'unit': 'GB',
        'description': 'Size of the snapshot'
    },
    # Meters added in the Kilo release
    {
        'name': 'snapshot.create.start',
        'type': 'Delta',
        'unit': 'snapshot',
        'description': 'The snapshot creation start'
    },
    {
        'name': 'snapshot.create.end',
        'type': 'Delta',
        'unit': 'snapshot',
        'description': 'The snapshot creation end'
    },
    {
        'name': 'snapshot.delete.start',
        'type': 'Delta',
        'unit': 'snapshot',
        'description': 'The snapshot deletion start'
    },
    {
        'name': 'snapshot.delete.end',
        'type': 'Delta',
        'unit': 'snapshot',
        'description': 'The snapshot deletion end'
    },
]


def get_meters(model_name):
    return {
        models.Instance.__name__: INSTANCE_METERS,
        models.Volume.__name__: VOLUME_METERS,
        models.Snapshot.__name__: SNAPSHOT_METERS
    }[model_name]
