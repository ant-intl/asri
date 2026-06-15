"""
Session serializers.
"""
from typing import Any, Optional


class SessionSerializer:
    """Serializer for session."""
    
    def __init__(self, instance=None, data: Optional[dict] = None, many: bool = False):
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
            'user_id': self._data.get('user_id', 'anonymous'),
            'title': self._data.get('title', ''),
            'agent_type': self._data.get('agent_type', 'react'),
            'metadata': self._data.get('metadata', {}),
        }
        
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
            'session_id': str(instance.session_id),
            'user_id': instance.user_id,
            'title': instance.title,
            'status': instance.status,
            'agent_type': instance.agent_type,
            'metadata': instance.metadata,
            'gmt_create': instance.gmt_create.isoformat() if instance.gmt_create else None,
            'gmt_modified': instance.gmt_modified.isoformat() if instance.gmt_modified else None,
        }


class SessionCreateSerializer:
    """Serializer for creating session."""
    
    def __init__(self, data: dict):
        self.data = data
        self._validated_data = None
        self._errors = {}
    
    def is_valid(self) -> bool:
        """Validate the request data."""
        self._errors = {}
        
        self._validated_data = {
            'user_id': self.data.get('user_id', 'anonymous'),
            'title': self.data.get('title', ''),
            'agent_type': self.data.get('agent_type', 'react'),
            'metadata': self.data.get('metadata', {}),
        }
        
        return len(self._errors) == 0
    
    @property
    def validated_data(self) -> dict:
        return self._validated_data or {}
    
    @property
    def errors(self) -> dict:
        return self._errors


class SessionUpdateSerializer:
    """Serializer for updating session."""
    
    def __init__(self, data: dict):
        self.data = data
        self._validated_data = None
        self._errors = {}
    
    def is_valid(self) -> bool:
        """Validate the request data."""
        self._errors = {}
        
        self._validated_data = {
            'title': self.data.get('title'),
            'status': self.data.get('status'),
            'metadata': self.data.get('metadata'),
        }
        
        return len(self._errors) == 0
    
    @property
    def validated_data(self) -> dict:
        return self._validated_data or {}
    
    @property
    def errors(self) -> dict:
        return self._errors
