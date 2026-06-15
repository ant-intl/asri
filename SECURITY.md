# Security Policy

## Supported Versions

The following versions of ASRI are currently supported with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take the security of ASRI seriously. If you believe you have found a security vulnerability, please report it to us as described below.

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via GitHub Security Advisory at https://github.com/your-org/asri/security/advisories/new. You should receive a response within 48 hours. If for some reason you do not, please follow up via the same channel to ensure we received your original message.

**Please include the following information:**

- Type of issue (e.g., buffer overflow, SQL injection, cross-site scripting, etc.)
- Full paths of source file(s) related to the manifestation of the issue
- The location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

## Security Best Practices

### API Key Management

- API keys are encrypted at rest using the `cryptography` library
- Never log API keys or sensitive credentials
- Use environment variables for configuration
- Rotate keys regularly

### Input Validation

- All user input is validated and sanitized
- Use Django's built-in form validation
- Implement proper content-type checking
- Protect against XSS by escaping output

### Authentication

- WebSocket endpoints require Bearer Token authentication
- Tokens are hashed using SHA256 before storage
- Multi-tenant isolation ensures data separation
- Use strong, randomly generated secrets

### Database Security

- Use Django ORM exclusively (no raw SQL)
- This prevents SQL injection attacks
- Database credentials should never be committed
- Use separate database users with minimal privileges

### External API Calls

- All external API calls have timeout limits (≤30 seconds)
- Implement rate limiting to prevent abuse
- Use connection pooling for efficiency
- Handle errors gracefully without exposing internals

### Logging

- Use `logging.getLogger(__name__)` for all logging
- Never log sensitive information (API keys, passwords, tokens)
- Log security events (failed auth attempts, validation errors)
- Implement proper log rotation

## Security Architecture

### Multi-Tenant Isolation

ASRI implements complete tenant-level isolation:

- Each tenant has independent configuration
- Skills and tools are tenant-scoped
- Session and message data is isolated
- Bearer Token authentication identifies tenant context

### Token-Based Authentication

- Bearer Token required for all API endpoints (except local dev mode)
- Tokens validated via middleware on every request
- Tenant context propagated via `contextvars`
- No cross-tenant data access possible

### WebSocket Security

- WebSocket connections require authentication
- Session ownership validated on connection
- Messages scoped to authenticated tenant
- Rate limiting applied to prevent abuse

## Deployment Security Checklist

- [ ] Set `DEBUG = False` in production
- [ ] Use strong `DJANGO_SECRET_KEY` (minimum 50 characters)
- [ ] Configure `ALLOWED_HOSTS` properly
- [ ] Enable HTTPS for all endpoints
- [ ] Set up proper CORS headers
- [ ] Use Redis with authentication for channel layers
- [ ] Configure database with SSL/TLS
- [ ] Implement proper firewall rules
- [ ] Set up monitoring and alerting

## Acknowledgments

We appreciate responsible disclosure. Security researchers who help improve our security will be acknowledged here (with permission).

## Contact

For security-related questions, please open a GitHub Security Advisory at https://github.com/your-org/asri/security/advisories/new
