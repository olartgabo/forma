# Hosted deployment

The hackathon demo runs on one EC2 instance in AWS `us-east-1` (D033). The API
stores projects in SQLite and photos on local disk, so the stack needs a single
host with a persistent volume rather than a stateless container service.

## Layout

| Piece             | Resource                                                                          |
| ----------------- | --------------------------------------------------------------------------------- |
| Host              | EC2 `t4g.small`, Ubuntu 24.04 arm64, 20 GB encrypted gp3 root volume, 2 GB swap   |
| Network           | Security group `forma-web`: inbound TCP 80/443 only; no SSH key or port 22        |
| Address           | Elastic IP; hostname `<ip-with-dashes>.sslip.io` with a Let's Encrypt certificate |
| Administration    | SSM Session Manager and Run Command through instance role `forma-host`            |
| Secrets           | SSM Parameter Store, read only by `forma-host`                                    |
| Data              | Docker volume `forma_forma-data` mounted at `/data` in the API container          |
| Tags on resources | `project=forma`                                                                   |

`deploy/compose.yaml` runs three containers: Caddy terminates HTTPS and proxies
to Next.js, which rewrites `/api/*` to FastAPI over the internal network. Only
Caddy publishes ports. The API runs one Uvicorn worker because the SQLite store
and media directory are local to that container.

## Parameters

| Name                    | Type                   | Contents                                                               |
| ----------------------- | ---------------------- | ---------------------------------------------------------------------- |
| `/forma/host`           | String                 | Public hostname Caddy serves                                           |
| `/forma/api-tokens`     | SecureString           | JSON map of owner to bearer token (`olartgabo`, `resnidev`, `judge`)   |
| `/forma/model-api-key`  | SecureString           | Optional Muse provider key; absent means Muse actions disabled         |
| `/forma/design-context` | String (Advanced tier) | Optional design-context manifest JSON; absent blocks design generation |

`host-up.sh` writes the design-context manifest to `deploy/config/design-context.json`
on the host and mounts it read-only at `/config` in the API container. The
manifest must contain only measured process and profile values (D015) and match
each project's current inventory revision; see the
[demo runbook](demo-runbook.md). Advanced-tier parameters hold up to 8 KB. For a
larger manifest, place the file on the host through Session Manager and set
`FORMA_DESIGN_CONTEXT_PATH` by hand.

Read your connection token without printing the others:

```sh
aws ssm get-parameter --name /forma/api-tokens --with-decryption \
  --query Parameter.Value --output text --profile ithaca | jq -r .olartgabo
```

Changing a parameter takes effect after the next `host-up.sh` run.

## First boot

`deploy/ec2-user-data.sh` installs Docker from Docker's apt repository and the
AWS CLI, clones this repository at the exact commit substituted for
`__FORMA_REF__`, and runs `deploy/host-up.sh`. That script rebuilds
`deploy/.env` (mode 600) from Parameter Store, then runs
`docker compose up -d --build`. Bootstrap output is in
`/var/log/cloud-init-output.log`.

## Updating

Every push to `main` deploys itself. When the `Offline checks` workflow passes
for that commit, `.github/workflows/deploy.yml` assumes IAM role
`forma-github-deploy` through GitHub OIDC, runs the steps below on the instance
through SSM Run Command, and then requests `/api/health` over HTTPS. Its job
runs in the GitHub environment `production`, which only `main` may deploy to,
and the role trusts only that environment of this repository. The role may send
`AWS-RunShellScript` to the FORMA instance and read command results, nothing
else. A failed check, build or health request fails the job. Compose builds
every image before it replaces any container, so a failed build leaves the
previous version serving.

`Offline checks` also builds `deploy/api.Dockerfile`, starts the image and
requests its `/api/health`, so an image that builds but cannot start fails the
pull request instead of the host.

The `web-image` job builds `deploy/web.Dockerfile` with its own source copies.
This catches imports of shared packages omitted from the image, including the
assembly viewer's display projection, before deployment.

The workflow skips a commit the host has already moved past, so a late run for
an older commit does not roll the host back. To redeploy a commit, rerun its
`Deploy` job in GitHub Actions.

By hand, through SSM Run Command (`AWS-RunShellScript`) or a Session Manager
shell:

```sh
git -C /opt/forma fetch origin
git -C /opt/forma checkout --detach <commit>
bash /opt/forma/deploy/host-up.sh
```

Rebuilding replaces containers but keeps the `forma_forma-data` and
`forma_caddy-data` volumes.

## Local run

With Docker running, copy `deploy/.env.example` to `deploy/.env`, set tokens, and
run `docker compose --env-file deploy/.env -f deploy/compose.yaml up --build`.
With `FORMA_HOST=localhost`, Caddy serves `https://localhost` with its internal
certificate authority.

An isolated stack can opt in to intake research with
`FORMA_INTAKE_RESEARCH=1` in its environment. Compose passes the flag and
`MODEL_API_KEY` to FastAPI. The default flag is off. The application reads
these settings directly. The separate
[paid verification policy](../tools/devloop/guarded/POLICY.md#actual-app-runtime-and-live-tests)
governs acceptance tests that call the provider.

## Limits

- One host and one volume. Data Lifecycle Manager policy
  `policy-085f42670d282bb74` (role `forma-dlm`) snapshots volumes tagged
  `project=forma` daily at 06:00 UTC and keeps seven. Restoring means creating
  a volume from a snapshot and attaching it; that path has not been rehearsed.
  The root volume has `DeleteOnTermination=false`, so terminating the instance
  keeps the data volume until it is deleted explicitly.
- Tokens are static bearer credentials per owner. There is no registration,
  rotation or per-session expiry.
- Deleting a project removes its local rows and files. Provider-side retention
  of photos sent to Muse is governed by the provider and is not verified here.
- Cost while running is roughly $0.58 per day (instance, volume and public IPv4).

## Verification, November 2, 2026

Instance `i-04b51e85b3234c59b` at commit `dcfccd4`, hostname
`52-0-105-215.sslip.io`. A script on the host read the `judge` and `resnidev`
tokens from Parameter Store and called the public HTTPS URL; it printed status
codes only.

| Check                                                     | Result                            |
| --------------------------------------------------------- | --------------------------------- |
| `GET /api/health` over HTTPS with a publicly trusted cert | 200                               |
| `GET /api/projects` without a token                       | 401                               |
| Create project / upload 64x64 PNG                         | 201 / 201                         |
| Upload non-image bytes as `image/png`                     | 422                               |
| Read project or media list with another owner's token     | 404 / 404                         |
| Media list without a token                                | 401                               |
| After recreating API and web containers: project, photo   | 200, 1 photo, `private, no-store` |
| After rebooting the instance: project, photo              | 200, 1 photo, `private, no-store` |
| Delete project, then read it                              | 200, then 404                     |
| `deploy/.env` on the host                                 | mode 600, owned by root           |

Muse was deployed without `/forma/model-api-key`, so provider actions are
disabled. Not yet checked: the browser workflow from a fresh session on a phone,
a live Muse request through the 140-second proxy path, and a full
build/repair/test flow on the hosted app.

### Browser walkthrough from a fresh session

A Playwright browser at 390x844 used a temporary `verify` owner token, which was
removed from `/forma/api-tokens` afterwards; the API then returned 401 for it.
Sign-in, project creation, a synthetic 800x600 JPEG upload with preview, one
material record (width only, other dimensions left unknown) linked to the photo,
and saving materials all worked. After a full page reload and re-entering the
credential, the goal, photo, recorded width and inventory revision were
restored. The browser console showed no errors or warnings. The Muse banner
reported that Muse is not configured, and the input checklist listed the missing
joint profiles and design context. The test project was deleted.
