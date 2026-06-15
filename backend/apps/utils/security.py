"""Security utilities for sensitive data handling."""

# Masked status value constants
MASKED_VALUES = ('configured', 'not_configured')


def is_masked_value(value: str | None) -> bool:
    """Check if value is a masked status string.

    Args:
        value: Value to check

    Returns:
        True if value is a masked status string
    """
    return value in MASKED_VALUES


def mask_api_key(value: str | None) -> str:
    """Mask API key to show only configuration status.

    Args:
        value: The api_key_encrypted field value from database

    Returns:
        "configured" if value exists and is not empty,
        "not_configured" otherwise
    """
    if value and value.strip():
        return "configured"
    return "not_configured"
