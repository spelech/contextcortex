# Private CA certificates

Put PEM-encoded CA certificates (`*.crt`) in this folder when your network uses a private certificate authority, for example:

- An HTTPS LLM gateway with an internal certificate.
- A self-hosted GitLab server with an internal certificate.
- A TLS-inspecting proxy in front of PyPI and npm.

Git does not track the `*.crt` files in this folder (see `.gitignore`).

The certificates are used in two ways:

1. **Build time.** `docker compose build` adds the certificates to the trust store of the image. `npm ci` and `pip install` then trust them too.
2. **Run time.** `docker-compose.yml` mounts this folder at `/certs`. At start, `docker-entrypoint.sh` adds each `*.crt` file to the system trust store. This also works with the pre-built image. To use a different folder, set `EXTRA_CA_CERTS_DIR`.

Python (`httpx`, `openai`, `requests`) and Git then use `/etc/ssl/certs/ca-certificates.crt`, which contains the public CAs and your private CAs.
