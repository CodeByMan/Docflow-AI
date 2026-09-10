# DocFlow-AI Security Notes

## Secrets

- Never commit .env or a real DOCFLOW_API_KEY.
- Use separate random values for database credentials and the API key.
- Rotate any credential that was ever committed to Git history.

## Access model

Local mode is intended for loopback development and does not require an API
key. Hosted mode requires X-DocFlow-Key, explicit CORS origins, and explicit
trusted hosts. The hosted key is a trusted-operator gate, not a user identity
system.

The application currently has no user accounts, tenant isolation, or per-file
ownership. Do not expose the hosted prototype as a multi-tenant service without
adding those controls.

## File-processing protections

Uploads are bounded by extension, MIME type, signature, size, page, row, cell,
worksheet, extracted-text, and Office ZIP expansion limits. Downloads are
confined to the configured storage root.

## Data handling

Source documents and extracted text may contain sensitive business data. Use
synthetic or non-confidential documents for public demonstrations. Retention
cleanup and user-directed deletion are not yet implemented.

## Deployment

- Keep the API behind HTTPS and a trusted reverse proxy.
- Use the hosted PostgreSQL configuration for deployment.
- Keep the API and storage volumes private.
- Add authentication, tenant ownership, retention, and a durable worker queue
  before production use.

## Reporting

Do not include credentials or confidential documents in bug reports. Record the
request ID returned by the API and report security issues privately.
