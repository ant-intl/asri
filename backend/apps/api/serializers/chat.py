"""
Chat serializers.
"""
from typing import Any


class ChatRequestSerializer:
    """Serializer for chat request."""
    
    def __init__(self, data: dict):
        self.data = data
        self._validated_data = None
        self._errors = {}
    
    def is_valid(self) -> bool:
        """Validate the request data."""
        self._errors = {}
        
        if not self.data.get('message'):
            self._errors['message'] = 'This field is required.'
        
        self._validated_data = {
            'session_id': self.data.get('session_id'),
            'message': self.data.get('message', ''),
            'user_id': self.data.get('user_id', 'anonymous'),
            'metadata': self.data.get('metadata', {}),
        }
        
        return len(self._errors) == 0
    
    @property
    def validated_data(self) -> dict:
        return self._validated_data or {}
    
    @property
    def errors(self) -> dict:
        return self._errors


class ChatResponseSerializer:
    """Serializer for chat response."""
    
    def __init__(self, instance: dict):
        self.instance = instance
    
    @property
    def data(self) -> dict:
        return {
            'session_id': self.instance.get('session_id'),
            'message_id': self.instance.get('message_id'),
            'content': self.instance.get('content'),
            'trace': self.instance.get('trace', []),
            'usage': self.instance.get('usage', {}),
        }


class BatchChatRequestSerializer:
    """Serializer for batch chat request."""
    
    def __init__(self, data: dict):
        self.data = data
        self._validated_data = None
        self._errors = {}
    
    def is_valid(self) -> bool:
        """Validate the request data."""
        self._errors = {}
        
        messages = self.data.get('messages', [])
        if not messages:
            self._errors['messages'] = 'This field is required.'
        
        self._validated_data = {
            'session_id': self.data.get('session_id'),
            'messages': messages,
            'user_id': self.data.get('user_id', 'anonymous'),
            'group_id': self.data.get('group_id'),
        }
        
        return len(self._errors) == 0
    
    @property
    def validated_data(self) -> dict:
        return self._validated_data or {}
    
    @property
    def errors(self) -> dict:
        return self._errors
