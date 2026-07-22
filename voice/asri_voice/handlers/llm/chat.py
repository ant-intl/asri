class Chat:
    """
    Handles the chat using to avoid OOM issues.
    """

    def __init__(self, size):
        self.size = size
        self.init_chat_message = None
        # maxlen is necessary pair, since a each new step we add an prompt and assitant answer
        self.buffer = []

    def append(self, item):
        if not isinstance(item, dict):
            import logging
            logging.getLogger(__name__).warning(
                "Chat.append: rejecting non-dict item (type=%s)", type(item).__name__
            )
            return
        self.buffer.append(item)
        self._evict_if_needed()

    def _evict_if_needed(self):
        """Evict messages in groups to keep tool-call pairs intact.

        The OpenAI Chat API requires that every role="tool" message must be
        preceded by an assistant message with matching tool_calls.  Naively
        popping the first two messages can leave orphaned tool results, which
        causes an API error.  Instead, we evict complete conversational
        groups: a user message, followed by an optional assistant message
        (with its tool_calls + tool result messages), until we've removed at
        least one full user-assistant pair.
        """
        max_len = 2 * (self.size + 1)
        while len(self.buffer) > max_len:
            removed = 0
            while removed < 2 and self.buffer:
                self.buffer.pop(0)
                removed += 1
                # If the removed message was an assistant with tool_calls,
                # also remove the following tool result messages.
                # If the removed message was a tool result but the previous
                # assistant (already removed) had tool_calls, keep going.
                while self.buffer and self.buffer[0].get("role") == "tool":
                    self.buffer.pop(0)
                    removed += 1

    def init_chat(self, init_chat_message):
        self.init_chat_message = init_chat_message

    def to_list(self):
        msgs = [self.init_chat_message] + self.buffer if self.init_chat_message else self.buffer
        # Defensive: filter out non-dict entries (e.g. control messages) that
        # must not be sent to the LLM API.
        return [m for m in msgs if isinstance(m, dict)]

    def reset(self):
        self.buffer = []
        self.init_chat_message = None

    def strip_images(self):
        """Remove all image content parts from every message in the buffer.

        Called after appending the assistant response so images don't persist
        across turns.  Handles both Realtime-style ``input_image`` and
        Chat Completions-style ``image_url`` types.
        """
        _IMAGE_TYPES = {"input_image", "image_url"}
        for msg in self.buffer:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            text_parts = [
                p for p in content
                if (p.get("type") if isinstance(p, dict) else getattr(p, "type", None)) not in _IMAGE_TYPES
            ]
            msg["content"] = text_parts

