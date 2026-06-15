/**
 * Safely parse a JSON string without throwing exceptions
 * @param text - The JSON string to parse
 * @param fallback - Default value when parsing fails
 * @returns Parsed object or default value
 */
export function safeJsonParse<T = unknown>(text: string, fallback?: T): T | undefined {
  try {
    return JSON.parse(text) as T;
  } catch {
    return fallback;
  }
}

/**
 * Safely parse a JSON string, throwing a user-friendly error when parsing fails
 * @param text - The JSON string to parse
 * @param fieldName - Field name (used in error message)
 * @returns Parsed object
 */
export function parseJsonOrThrow(text: string, fieldName: string = 'JSON'): Record<string, unknown> {
  try {
    const result = JSON.parse(text);
    if (typeof result !== 'object' || result === null || Array.isArray(result)) {
      throw new Error(`${fieldName} must be a JSON object`);
    }
    return result;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith(fieldName)) {
      throw error;
    }
    throw new Error(`${fieldName} format is invalid, please check JSON syntax`);
  }
}
