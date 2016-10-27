from django.core.validators import MaxValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from iptools.ipv4 import validate_cidr


@python_2_unicode_compatible
class BaseSecurityGroupRule(models.Model):
    TCP = 'tcp'
    UDP = 'udp'
    ICMP = 'icmp'

    CHOICES = (
        (TCP, 'tcp'),
        (UDP, 'udp'),
        (ICMP, 'icmp'),
    )

    protocol = models.CharField(max_length=4, blank=True, choices=CHOICES)
    from_port = models.IntegerField(validators=[MaxValueValidator(65535)], null=True)
    to_port = models.IntegerField(validators=[MaxValueValidator(65535)], null=True)
    cidr = models.CharField(max_length=32, blank=True)

    backend_id = models.CharField(max_length=128, blank=True)

    class Meta(object):
        abstract = True

    def validate_icmp(self):
        if self.from_port is not None and not -1 <= self.from_port <= 255:
            raise ValidationError('Wrong value for "from_port": '
                                  'expected value in range [-1, 255], found %d' % self.from_port)
        if self.to_port is not None and not -1 <= self.to_port <= 255:
            raise ValidationError('Wrong value for "to_port": '
                                  'expected value in range [-1, 255], found %d' % self.to_port)

    def validate_port(self):
        if self.from_port is not None and self.to_port is not None:
            if self.from_port > self.to_port:
                raise ValidationError('"from_port" should be less or equal to "to_port"')
        if self.from_port is not None and self.from_port < 1:
            raise ValidationError('Wrong value for "from_port": '
                                  'expected value in range [1, 65535], found %d' % self.from_port)
        if self.to_port is not None and self.to_port < 1:
            raise ValidationError('Wrong value for "to_port": '
                                  'expected value in range [1, 65535], found %d' % self.to_port)

    def validate_cidr(self):
        if not self.cidr:
            return

        if not validate_cidr(self.cidr):
            raise ValidationError(
                'Wrong cidr value. Expected cidr format: <0-255>.<0-255>.<0-255>.<0-255>/<0-32>')

    def clean(self):
        if self.protocol == 'icmp':
            self.validate_icmp()
        elif self.protocol in ('tcp', 'udp'):
            self.validate_port()
        else:
            raise ValidationError('Wrong value for "protocol": '
                                  'expected one of (tcp, udp, icmp), found %s' % self.protocol)
        self.validate_cidr()

    def __str__(self):
        return '%s (%s): %s (%s -> %s)' % \
               (self.security_group, self.protocol, self.cidr, self.from_port, self.to_port)
