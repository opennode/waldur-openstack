from django.core.validators import MaxValueValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _
from iptools.ipv4 import validate_cidr

from waldur_core.core import models as core_models
from waldur_core.structure import models as structure_models


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
            raise ValidationError(_('Wrong value for "from_port": '
                                    'expected value in range [-1, 255], found %d') % self.from_port)
        if self.to_port is not None and not -1 <= self.to_port <= 255:
            raise ValidationError(_('Wrong value for "to_port": '
                                    'expected value in range [-1, 255], found %d') % self.to_port)

    def validate_port(self):
        if self.from_port is not None and self.to_port is not None:
            if self.from_port > self.to_port:
                raise ValidationError(_('"from_port" should be less or equal to "to_port"'))
        if self.from_port is not None and self.from_port < 1:
            raise ValidationError(_('Wrong value for "from_port": '
                                    'expected value in range [1, 65535], found %d') % self.from_port)
        if self.to_port is not None and self.to_port < 1:
            raise ValidationError(_('Wrong value for "to_port": '
                                    'expected value in range [1, 65535], found %d') % self.to_port)

    def validate_cidr(self):
        if not self.cidr:
            return

        if not validate_cidr(self.cidr):
            raise ValidationError(
                _('Wrong cidr value. Expected cidr format: <0-255>.<0-255>.<0-255>.<0-255>/<0-32>'))

    def clean(self):
        if self.to_port is None:
            raise ValidationError(_('"to_port" cannot be empty'))

        if self.from_port is None:
            raise ValidationError(_('"from_port" cannot be empty'))

        if self.protocol == 'icmp':
            self.validate_icmp()
        elif self.protocol in ('tcp', 'udp'):
            self.validate_port()
        else:
            raise ValidationError(_('Wrong value for "protocol": '
                                    'expected one of (tcp, udp, icmp), found %s') % self.protocol)
        self.validate_cidr()

    def __str__(self):
        return '%s (%s): %s (%s -> %s)' % \
               (self.security_group, self.protocol, self.cidr, self.from_port, self.to_port)


@python_2_unicode_compatible
class Port(core_models.BackendModelMixin, models.Model):
    # TODO: Use dedicated field: https://github.com/django-macaddress/django-macaddress
    mac_address = models.CharField(max_length=32, blank=True)
    ip4_address = models.GenericIPAddressField(null=True, blank=True, protocol='IPv4')
    ip6_address = models.GenericIPAddressField(null=True, blank=True, protocol='IPv6')
    backend_id = models.CharField(max_length=255, blank=True)

    class Meta(object):
        abstract = True

    def __str__(self):
        return self.ip4_address or self.ip6_address or 'Not initialized'

    @classmethod
    def get_backend_fields(cls):
        return super(Port, cls).get_backend_fields() + ('ip4_address', 'ip6_address', 'mac_address')


class BaseImage(structure_models.ServiceProperty):
    min_disk = models.PositiveIntegerField(default=0, help_text=_('Minimum disk size in MiB'))
    min_ram = models.PositiveIntegerField(default=0, help_text=_('Minimum memory size in MiB'))

    class Meta(structure_models.ServiceProperty.Meta):
        abstract = True

    @classmethod
    def get_backend_fields(cls):
        return super(BaseImage, cls).get_backend_fields() + ('min_disk', 'min_ram')
