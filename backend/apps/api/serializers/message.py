"""
Message serializers.
"""
from typing import Optional


class MessageSerializer:
    """Serializer for message."""
    
    def __init__(self, instance=None, many: bool = False):
        self.instance = instance
        self.many = many
    
    @property
    def data(self) -> dict | list:
        if self.many:
            return [self._serialize_instance(item) for item in self.instance]
        return self._serialize_instance(self.instance)
    
    def _serialize_instance(self, instance) -> dict:
        if instance is None:
            return {}
        return {
            'message_id': str(instance.message_id),
            'session_id': str(instance.session_id) if instance.session_id else None,
            'role': instance.role,
            'content': instance.content,
            'message_type': instance.message_type,
            'parent_message_id': instance.parent_message_id,
            'group_id': instance.group_id,
            'token_count': instance.token_count,
            'metadata': instance.metadata,
            'gmt_create': instance.gmt_create.isoformat() if instance.gmt_create else None,
        }


class MessageListSerializer:
    """Serializer for message list response."""
    
    def __init__(self, messages: list, total: int, page: int, page_size: int):
        self.messages = messages
        self.total = total
        self.page = page
        self.page_size = page_size
    
    @property
    def data(self) -> dict:
        serializer = MessageSerializer(self.messages, many=True)
        return {
            'messages': serializer.data,
            'total': self.total,
            'page': self.page,
            'page_size': self.page_size,
        }
