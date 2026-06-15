"""
Skill serializers.
"""


class SkillSerializer:
    """Serializer for skill."""

    def __init__(self, instance=None, data=None, many: bool = False):
        self.instance = instance
        self._data = data
        self.many = many
        self._validated_data = None
        self._errors = {}

    def is_valid(self) -> bool:
        """Validate the request data."""
        self._errors = {}

        if self._data is None:
            return True

        self._validated_data = {
            'name': self._data.get('name'),
            'description': self._data.get('description', ''),
            'content': self._data.get('content'),
            'is_active': self._data.get('is_active', True),
            'metadata': self._data.get('metadata', {}),
        }

        # Required fields validation
        if not self._validated_data.get('name'):
            self._errors['name'] = 'This field is required.'
        if not self._validated_data.get('content'):
            self._errors['content'] = 'This field is required.'

        return len(self._errors) == 0

    @property
    def validated_data(self) -> dict:
        return self._validated_data or {}

    @property
    def errors(self) -> dict:
        return self._errors

    @property
    def data(self) -> dict | list:
        if self.many:
            return [self._serialize_instance(item) for item in self.instance]
        return self._serialize_instance(self.instance)

    def _serialize_instance(self, instance) -> dict:
        if instance is None:
            return {}
        return {
            'skill_id': str(instance.skill_id),
            'name': instance.name,
            'description': instance.description,
            'content': instance.content,
            'is_active': instance.is_active,
            'metadata': instance.metadata,
            'gmt_create': instance.gmt_create.isoformat() if instance.gmt_create else None,
            'gmt_modified': instance.gmt_modified.isoformat() if instance.gmt_modified else None,
        }


class SkillCreateSerializer:
    """Serializer for creating skill."""

    def __init__(self, data: dict):
        self.data = data
        self._validated_data = None
        self._errors = {}

    def is_valid(self) -> bool:
        """Validate the request data."""
        self._errors = {}

        self._validated_data = {
            'name': self.data.get('name'),
            'description': self.data.get('description', ''),
            'content': self.data.get('content'),
            'is_active': self.data.get('is_active', True),
            'metadata': self.data.get('metadata', {}),
        }

        # Required fields validation
        if not self._validated_data.get('name'):
            self._errors['name'] = 'This field is required.'
        if not self._validated_data.get('content'):
            self._errors['content'] = 'This field is required.'

        return len(self._errors) == 0

    @property
    def validated_data(self) -> dict:
        return self._validated_data or {}

    @property
    def errors(self) -> dict:
        return self._errors


class SkillUpdateSerializer:
    """Serializer for updating skill."""

    def __init__(self, data: dict):
        self.data = data
        self._validated_data = None
        self._errors = {}

    def is_valid(self) -> bool:
        """Validate the request data."""
        self._errors = {}

        self._validated_data = {
            'name': self.data.get('name'),
            'description': self.data.get('description', ''),
            'content': self.data.get('content'),
            'is_active': self.data.get('is_active'),
            'metadata': self.data.get('metadata'),
        }

        return len(self._errors) == 0

    @property
    def validated_data(self) -> dict:
        return self._validated_data or {}

    @property
    def errors(self) -> dict:
        return self._errors
