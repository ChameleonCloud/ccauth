# ccauth

OIDC device flow auth plugin for OpenStack on Chameleon.

Two complementary interfaces are provided:

- **`cc-login`** — the classic interface. Authenticates via device flow and creates short-lived OpenStack **application credentials**, caches them, and writes portable `openrc`/`clouds.yaml` files that work with any OpenStack client without `ccauth` installed.
- **`ccauth`** — the newer subcommand interface. Caches a refresh token instead of application credentials. The generated config files reference the `v3chameleonoidc` keystoneauth1 plugin, so `ccauth` must be installed on every machine that uses them.

## Installation

```bash
pip install .
```

---

## cc-login — application credential management

`cc-login` authenticates once via OIDC device flow, then creates a short-lived
OpenStack application credential and caches it locally (default TTL 24 h).
Generated `openrc`/`clouds.yaml` files embed the credential directly and work
with any standard OpenStack client (`openstack`, `python-keystoneclient`, etc.)
without requiring `ccauth` to be installed.

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
cc-login --auth-url https://chi.uc.chameleoncloud.org:5000/v3 \
         --output-openrc ~/openrc

# View all options
cc-login --help
```

### How it works

1. On first run (or with `--force-refresh`), `cc-login` starts an OIDC device
   flow. You visit a URL and approve the login in your browser.
2. A short-lived OpenStack application credential is created and cached at
   `~/.cache/ccauth/chameleon-app-cred.json`.
3. On subsequent runs within the TTL, the cached credential is reused — no
   browser interaction needed.
4. The generated `openrc` sets `OS_AUTH_TYPE=v3applicationcredential` with the
   credential ID and secret embedded directly.

### Generated openrc format

```bash
export OS_AUTH_TYPE="v3applicationcredential"
export OS_AUTH_URL="https://chi.uc.chameleoncloud.org:5000/v3"
export OS_REGION_NAME="CHI@UC"
export OS_APPLICATION_CREDENTIAL_ID="<id>"
export OS_APPLICATION_CREDENTIAL_SECRET="<secret>"
```

Source it and use `openstack` as normal:

```bash
source ~/openrc
openstack server list
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

### cc-login options

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
| `--client-id ID` | `chi-cli-device-token` | OIDC client ID |
| `--discovery-endpoint URL` | Chameleon Keycloak | OIDC discovery URL |
| `--debug` | false | Enable debug logging |

---

## ccauth — OIDC plugin interface

`ccauth` uses a keystoneauth1 plugin (`v3chameleonoidc`) that handles token
refresh transparently. Instead of embedding credentials in config files, the
generated files reference the plugin by name. **`ccauth` must be installed on
any machine that uses these files.**

Caches a refresh token locally so you authenticate once interactively; all
subsequent `openstack` commands work silently.

```bash
# Authenticate (discovers all Chameleon sites automatically)
ccauth login

# Generate clouds.yaml for all discovered sites
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml

# Generate openrc for a specific site
ccauth openrc --auth-url https://chi.uc.chameleoncloud.org:5000/v3 \
              --output ~/openrc

# Overwrite existing entries
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --force

# Clear cached refresh token
ccauth logout

# View all options
ccauth --help
```

### Generated clouds.yaml format

```yaml
clouds:
  uc:
    auth_type: v3chameleonoidc
    auth:
      auth_url: https://chi.uc.chameleoncloud.org:5000/v3
      identity_provider: chameleon
      protocol: openid
      project_id: <your-project-id>
      client_id: chi-cli-device-token
      discovery_endpoint: https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration
    region_name: CHI@UC
```

Run `ccauth login` to prime the token cache, then use `openstack` normally:

```bash
openstack --os-cloud uc server list
```

### Site discovery

When `--auth-url` is not provided, `ccauth` discovers sites automatically:

1. **Chameleon reference API** — queries `https://api.chameleoncloud.org/sites`
2. **OpenStack vendordata** — falls back to the metadata service (only on Chameleon instances)

Override with `--sites-api-url` and `--metadata-url`.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CC_LOGIN_STATE` | `~/.cache/ccauth` | Directory for cached refresh token |

## Debug logging

```bash
ccauth --debug login
cc-login --debug --output-openrc ~/openrc
```

## Development

```bash
pip install -e '.[dev]'
pytest
```
