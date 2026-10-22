# Production release and development

`main` is the production branch. `dev` runs the same CI checks but never deploys.
The release workflow uses GitHub-hosted runners, not any runner belonging to another
project on the server. Actions are pinned to full commit SHAs and have job-specific
permissions. The `production` GitHub environment permits deployments from `main` only.

## Pipeline

1. Python 3.12 and Node.js 24 run `make check`, including isolated SQLite/PostgreSQL tests.
2. On `main`, Docker verifies the test target and publishes the runtime image to GHCR.
3. The production job sends its immutable image digest through a host-key-pinned SSH
   connection. Its temporary `GITHUB_TOKEN` authenticates the private registry pull.
4. The fixed SSH command validates the image repository and commit, obtains a project
   lock, pulls the image, and saves a PostgreSQL backup before changing the bot container.
5. Only the bot container is recreated. A failed health check restores the previous
   image. PostgreSQL and certificate volumes stay in place. Application rollback does
   not downgrade database migrations; use the private backup for a separately reviewed
   database recovery when a future release introduces an incompatible migration.
6. Public HTTPS is checked with normal certificate validation.

Runtime credentials remain in the server's private `.local/.env`, not in GitHub or
the image. Only the deployment SSH key and pinned host keys are GitHub environment
secrets. The deployment login has no general Docker access and its key cannot open
an interactive shell, forward ports, or execute arbitrary remote commands.

## Server layout

Everything for this application lives under `/opt/wiut-social-registrar`:

- `compose.yaml`, `compose.production.yaml`, `compose.release.yaml`, and `deploy/`:
  reviewed infrastructure files owned by root. Image-only deployments do not replace them.
- `.local/.env`: private runtime configuration, mode `600`, readable by the non-root
  application UID. It contains the production bot token, PostgreSQL password, verification
  secret, and renewable Outlook cache.
- `shared/current.json`: the successful image digest and source commit, without credentials.
- `shared/backups/`: the 14 latest private PostgreSQL dumps, created daily and before deploys.
- Project-prefixed Docker volumes: PostgreSQL and Caddy certificate state.

The Compose project name is always `wiut-social-registrar-production`. No `down -v`,
global Docker cleanup, other project directory, or shared reverse-proxy restart is used.
Infrastructure updates require explicitly reinstalling the reviewed infrastructure
files. The pipeline updates only the runtime image.

## Trusted HTTPS on a public IP

The release overlay serves the Mini App on `https://PUBLIC_IP`. Caddy obtains
and automatically renews a Let's Encrypt `shortlived` IP certificate. Its data volumes
must be preserved across releases. No private CA or client-side certificate bypass is used.

The existing Traefik Docker provider must expose `websecure` on port 443 and a
network selected by `REGISTRAR_EDGE_NETWORK`. Labels on **this project's Caddy
container only** pass TLS connections for the IP to Caddy without terminating TLS.
IP clients omit SNI; the route also accepts literal IP SNI and the reverse pointer
required by RFC 8738 for TLS-ALPN-01. Set `REGISTRAR_ACME_SNI` to
`ipaddress.ip_address(PUBLIC_IP).reverse_pointer`. Requests with another domain's
SNI remain with their existing routers. No other project's files, containers,
certificates, domain routes, or global proxy settings are changed.

The proxy must permit TLS-ALPN passthrough. Traefik permits it automatically when
none of its certificate resolvers uses `tlsChallenge`, as on this deployment host.
Its existing HTTP-01 resolver is left untouched. If a different host uses
TLS-ALPN itself, arrange explicit challenge routing before deploying this overlay.

Both certificate validation and application access use public port 443.
Use `REGISTRAR_ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory` to test
routing first, then the default production directory to obtain a trusted certificate.

## GitHub environment

Create the `production` environment restricted to the `main` branch, with:

| Name | Kind | Value |
| --- | --- | --- |
| `DEPLOY_HOST` | Variable | Server IP |
| `DEPLOY_USER` | Variable | Dedicated deployment account |
| `PRODUCTION_URL` | Variable | Public HTTPS origin, including port |
| `DEPLOY_SSH_KEY` | Secret | Dedicated Ed25519 private key |
| `DEPLOY_KNOWN_HOSTS` | Secret | Verified SSH host-key records |

Install `deploy/release.py` as `/usr/local/libexec/wiut-social-registrar-deploy`,
owned by root and mode `755`. The dedicated account's authorized-key entry uses
`restrict,command="sudo -n /usr/local/libexec/wiut-social-registrar-deploy"`; its
sudoers entry permits only that command. Create `shared/ready` only after PostgreSQL,
TLS, the private environment, and the initial data import have been prepared.

Install the project-prefixed backup service/timer and enable the timer after the
first successful deployment. Check the first backup before relying on unattended runs.

## One-time data move

Stop the old bot before exporting to avoid running two pollers with one token. Preserve
the production bot token and `BOT_VERIFICATION_SECRET`, so pending code hashes and
registered users remain associated with the same account.

```bash
python -m scripts.transfer_database export --env-file .env --file .local/production-snapshot.json
```

Transfer this private snapshot over SSH. Import it with the new runtime image using
the server's production configuration, mounting the snapshot read-only at a private
container path:

```bash
python -m scripts.transfer_database import --env-file /config/.env --file /migration/snapshot.json
```

The importer migrates the empty destination, restores all application tables in one
transaction, and resets PostgreSQL sequences. It refuses a non-empty destination.
Keep the original SQLite database and a private backup until recovery has been checked.
Neither command prints record contents or credentials.

## Local development

The project-root `.env` is the local development configuration. Use a different bot
token, verification secret, and SQLite file from production. Production credentials
and data snapshots stay ignored under `.local/` or on the server. Git branches do not
select credentials; the chosen private environment does.

```bash
python main.py --env-file .env
```

Never run this command alongside the existing local user service for the same token.
Use `systemctl --user restart wiut-social-registrar.service` when that service owns polling.

Official guidance: [GitHub container publishing](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images),
[GitHub secure Actions use](https://docs.github.com/en/actions/reference/security/secure-use),
[deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[Compose in production](https://docs.docker.com/compose/how-tos/production/),
[Let's Encrypt IP certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability),
and [ACME IP validation (RFC 8738)](https://www.rfc-editor.org/rfc/rfc8738.html).
