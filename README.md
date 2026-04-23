# ccauth

OpenStack Chameleon device-flow authentication helper with application-credential caching.

Two interfaces are provided:

- **`ccauth`** — authenticate once, generate `clouds.yaml`/`openrc` files that use the `v3chameleonoidc` keystoneauth1 plugin. Refresh tokens are cached locally so all subsequent OpenStack commands work silently. **`ccauth` must be installed on every machine that uses the generated files (and in the correct virtual environment for OpenStack clients being used, if applicable).**
- **`cc-login`** — authenticate once, create a short-lived OpenStack **application credential**, and write portable `openrc`/`clouds.yaml` files that work with any OpenStack client without `ccauth` installed for the OpenStack commands in use.

## Installation

```bash
pip install ccauth
```

---

## ccauth — OIDC plugin interface

### Quick start

```bash
# Authenticate
ccauth login

# Generate clouds.yaml for the current project and all discovered sites
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml

# Use a specific cloud (which can be found by name in clouds.yaml)
export OS_CLOUD=chameleon
openstack server list
```

On first run you'll be prompted to visit a URL. Subsequent runs reuse the cached refresh token silently.

### Subcommands

#### `ccauth login`

Runs the OIDC device flow and caches a refresh token. Discovers the current site from the OpenStack metadata service when on a Chameleon instance.

```bash
ccauth login
ccauth login --auth-url https://chi.uc.chameleoncloud.org:5000/v3
ccauth --debug login
```

#### `ccauth logout`

Clears the cached refresh token.

```bash
ccauth logout
```

#### `ccauth clouds-yaml`

Writes a `clouds.yaml` entry for every discovered site. Run `ccauth login` first.

```bash
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --force
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --all-projects
```

`--all-projects` generates one entry per (site, project) pair, named `<site>_<project>`.

#### `ccauth openrc`

Writes an openrc file for a single site (use `clouds-yaml` for multi-site).

```bash
ccauth openrc --output ~/openrc
ccauth openrc --auth-url https://chi.uc.chameleoncloud.org:5000/v3 --output ~/openrc
ccauth openrc --output ~/openrc --force
```

#### `ccauth discover-projects`

Interactively lists all projects you have access to across all sites and writes a `clouds.yaml` for the ones you choose in the format site_project (hyphens are converted to underscores).

```bash
ccauth discover-projects
ccauth discover-projects --output ~/my-clouds.yaml
```

### Generated clouds.yaml format

```yaml
clouds:
  chameleon:
    auth_type: v3chameleonoidc
    auth:
      auth_url: https://chi.uc.chameleoncloud.org:5000/v3
      identity_provider: chameleon
      protocol: openid
      client_id: chi-cli-device-token
      discovery_endpoint: https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration
      project_id: <your-project-id>
    region_name: CHI@UC
```

### Site discovery

When `--auth-url` is not provided, all available sites come from the Chameleon
reference API (`https://api.chameleoncloud.org/sites`). If running on a Chameleon
instance, the OpenStack metadata service at `169.254.169.254` may add the current
site to the list if it isn't already there (e.g. KVM or edge nodes).

The **current site** (used for `login` and `openrc`) is chosen in order:
1. `--region-name` if provided — matched against the site list
2. Vendordata — the site reported by the metadata service
3. First site in the list

Override the discovery endpoints with `--sites-api-url` and `--metadata-url`.

### Options

| Flag | Default | Description |
|---|---|---|
| `--auth-url URL` | auto-discovered | Keystone auth URL (skips discovery) |
| `--region-name NAME` | auto-discovered | OpenStack region |
| `--project-id ID` | auto-discovered | OpenStack project ID |
| `--client-id ID` | `chi-cli-device-token` | OIDC client ID |
| `--discovery-endpoint URL` | Chameleon Keycloak | OIDC discovery URL |
| `--cloud-name NAME` | `chameleon` | Cloud name in clouds.yaml |
| `--sites-api-url URL` | Chameleon reference API | Reference API URL |
| `--metadata-url URL` | `169.254.169.254/...` | Vendordata metadata URL |
| `--debug` | false | Enable debug logging |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `CC_LOGIN_STATE` | `~/.cache/ccauth` | Directory for cached refresh token |

---

## cc-login — application credential management

### Quick start

```bash
# Authenticate and generate an openrc file
cc-login --output-openrc ~/openrc

# Authenticate and generate a clouds.yaml entry
cc-login --output-clouds-yaml ~/.config/openstack/clouds.yaml

# Force a new device flow + new credential (bypass cache)
cc-login --output-openrc ~/openrc --force-refresh

# Overwrite an existing file
cc-login --output-openrc ~/openrc --force-openrc
cc-login --output-clouds-yaml ~/clouds.yaml --force-clouds-yaml

# Specify a site explicitly (skips auto-discovery)
cc-login --auth-url https://chi.uc.chameleoncloud.org:5000/v3 --output-openrc ~/openrc
```

On first run (or with `--force-refresh`), `cc-login` starts an OIDC device flow. A short-lived application credential is created and cached at `~/.cache/ccauth/chameleon-app-cred.json`. Subsequent runs within the TTL reuse the cached credential.

### Generated openrc format

```bash
export OS_AUTH_TYPE="v3applicationcredential"
export OS_AUTH_URL="https://chi.uc.chameleoncloud.org:5000/v3"
export OS_REGION_NAME="CHI@UC"
export OS_APPLICATION_CREDENTIAL_ID="<id>"
export OS_APPLICATION_CREDENTIAL_SECRET="<secret>"
```

### Generated clouds.yaml format

```yaml
clouds:
  chameleon:
    auth_type: v3applicationcredential
    auth:
      auth_url: https://chi.uc.chameleoncloud.org:5000/v3
      application_credential_id: <id>
      application_credential_secret: <secret>
    region_name: CHI@UC
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--output-openrc FILE` | — | Write openrc file |
| `--output-clouds-yaml FILE` | — | Write clouds.yaml entry |
| `--force-refresh` | false | Bypass cache, re-authenticate |
| `--force-openrc` | false | Overwrite existing openrc |
| `--force-clouds-yaml` | false | Overwrite existing clouds.yaml entry |
| `--auth-url URL` | auto-discovered | Keystone auth URL |
| `--region-name NAME` | auto-discovered | OpenStack region |
| `--project-id ID` | auto-discovered | OpenStack project |
| `--cloud-name NAME` | `chameleon` | Cloud name in clouds.yaml |
| `--app-cred-name PREFIX` | `chi-device-flow-auth` | App credential name prefix |
| `--app-cred-expires-hours N` | `24` | Credential lifetime in hours |
| `--app-cred-cache-path PATH` | `~/.cache/ccauth/chameleon-app-cred.json` | Cache file path |
| `--ttl-seconds N` | `86400` | Local cache TTL |
| `--debug` | false | Enable debug logging |

---

## Library usage

```python
# Core OIDC auth — build a keystoneauth1 session
from ccauth import AuthConfig, build_session

config = AuthConfig(auth_url="https://chi.uc.chameleoncloud.org:5000/v3")
session = build_session(config)  # prompts device flow on first call

# App credential caching (cc-login workflow)
from ccauth import AppCredConfig, ensure_app_cred
from ccauth.appcred import write_openrc, write_clouds_yaml

config = AppCredConfig(auth_url="https://chi.uc.chameleoncloud.org:5000/v3")
app_cred = ensure_app_cred(config)
write_openrc(app_cred, "~/openrc", auth_url=config.auth_url)

# Site discovery
from ccauth import from_reference_api, from_vendordata

sites = from_reference_api()   # all Chameleon sites
sites = from_vendordata()      # current site (on a Chameleon instance)
```

---

## Development

```bash
pip install -e '.[dev]'
pytest
pylint ccauth/
```
