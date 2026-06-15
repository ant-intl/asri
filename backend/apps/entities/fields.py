"""
Custom model fields.
"""
import json

from django.db import models


class FloatCharField(models.CharField):
    """A CharField that transparently converts between Python float
    and a string representation in the database.

    Data is stored as a VARCHAR column (so OceanBase / MySQL do not
    impose floating-point rounding) but behaves like a regular Python
    ``float`` on the application side.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 32)
        kwargs.setdefault('default', 0.0)
        kwargs.setdefault('blank', True)
        super().__init__(*args, **kwargs)

    # -- DB → Python ----------------------------------------------------------

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return 0.0
        if isinstance(value, float):
            return value
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    def to_python(self, value):
        if value is None or value == '':
            return 0.0
        if isinstance(value, float):
            return value
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    # -- Python → DB ----------------------------------------------------------

    def get_prep_value(self, value):
        if value is None:
            return '0'
        if isinstance(value, str):
            try:
                float(value)
                return value
            except ValueError:
                return '0'
        try:
            return repr(float(value))
        except (ValueError, TypeError):
            return '0'


class JsonTextField(models.TextField):
    """A TextField that transparently serializes/deserializes JSON.

    Data is stored as a plain TEXT column in the database (no native
    JSON type required) but behaves like :class:`~django.db.models.JSONField`
    on the Python side — values are automatically converted between
    Python objects (``dict`` / ``list``) and JSON strings.
    """

    def __init__(self, *args, **kwargs):
        # Accept default=dict or default=list like JSONField does.
        kwargs.setdefault('default', dict)
        kwargs.setdefault('blank', True)
        super().__init__(*args, **kwargs)

    # -- DB → Python ----------------------------------------------------------

    def from_db_value(self, value, expression, connection):
        if value is None:
            return self._empty_default()
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    def to_python(self, value):
        if isinstance(value, (dict, list)):
            return value
        if value is None:
            return self._empty_default()
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    # -- Python → DB ----------------------------------------------------------

    def get_prep_value(self, value):
        if value is None:
            return '{}'
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    # -- Helpers ---------------------------------------------------------------

    def _empty_default(self):
        """Return a fresh empty container matching the field default."""
        d = self.default
        if callable(d):
            return d()
        return d
