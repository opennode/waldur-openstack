"""
A copy of Django 1.10 password validators.
More details here:
https://github.com/django/django/blob/stable/1.10.x/django/contrib/auth/password_validation.py

XXX: remove it after migration to 1.10 or if a backport is used.
"""

from django.core.exceptions import ValidationError
from django.utils import lru_cache
from django.utils.translation import gettext as _, ungettext


@lru_cache.lru_cache(maxsize=None)
def get_default_password_validators():
    return [MinimumLengthValidator(), NumericPasswordValidator()]


def validate_password(password, user=None, password_validators=None):
    """
    Validate whether the password meets all validator requirements.
    If the password is valid, return ``None``.
    If the password is invalid, raise ValidationError with all error messages.
    """
    errors = []
    if password_validators is None:
        password_validators = get_default_password_validators()
    for validator in password_validators:
        try:
            validator.validate(password, user)
        except ValidationError as error:
            errors.append(error)
    if errors:
        raise ValidationError(errors)


class MinimumLengthValidator(object):
    """
    Validate whether the password is of a minimum length.
    """
    def __init__(self, min_length=8):
        self.min_length = min_length

    def validate(self, password, user=None):
        if len(password) < self.min_length:
            raise ValidationError(
                ungettext(
                    "This password is too short. It must contain at least %(min_length)d character.",
                    "This password is too short. It must contain at least %(min_length)d characters.",
                    self.min_length
                ),
                code='password_too_short',
                params={'min_length': self.min_length},
            )

    def get_help_text(self):
        return ungettext(
            "Your password must contain at least %(min_length)d character.",
            "Your password must contain at least %(min_length)d characters.",
            self.min_length
        ) % {'min_length': self.min_length}


class NumericPasswordValidator(object):
    """
    Validate whether the password is alphanumeric.
    """
    def validate(self, password, user=None):
        if password.isdigit():
            raise ValidationError(
                _("This password is entirely numeric."),
                code='password_entirely_numeric',
            )

    def get_help_text(self):
        return _("Your password can't be entirely numeric.")
