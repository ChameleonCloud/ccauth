# ccauth

OpenStack Chameleon device-flow authentication helper.

**`ccauth`** caches and refreshes credentials automatically, and allows you to authenticate from the CLI by opening a link in your browser. It works with all OpenStack CLI or API commands that understand a `clouds.yaml` file. Because this implements a keystoneauth1 plugin, `ccauth` must be installed in the same Python environment as the OpenStack clients using it.

> **Note:** The application credential flow (`cc-login`) is not recommended, and support for it will be dropped soon. Use the `ccauth` commands below instead.

## Installation

```bash
pip install <pypi name>
```

This installs the `ccauth` command and the `v3chameleonoidc` keystoneauth1 plugin.

---

## ccauth — OIDC plugin interface

### Quick start

```bash
# Generate clouds.yaml for the current site and project.
# On first run you'll be prompted to visit a URL to authenticate.
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml

# Use a specific cloud (which can be found by name in clouds.yaml)
export OS_CLOUD=chameleon
openstack server list
```

Subsequent runs reuse the cached refresh token silently. `ccauth login` is available as a convenience to pre-authenticate or verify credentials, but it is not a required first step — `clouds-yaml` and `discover-projects` will trigger the device flow automatically if no cached token is present.

### Subcommands

#### `ccauth login`

Optional. Runs the OIDC device flow and caches a refresh token. Useful for pre-authenticating or verifying credentials before running other commands. Discovers the current site from the OpenStack metadata service when on a Chameleon instance.

```bash
ccauth login
ccauth login --auth-url https://chi.uc.chameleoncloud.org:5000/v3
ccauth --debug login
```

#### `ccauth logout`

Clears all cached refresh tokens (for every identity provider).

```bash
ccauth logout
```

#### `ccauth clouds-yaml`

Writes a `clouds.yaml` file. By default, generates a single entry for the current site and project (discovered from the OpenStack metadata service). Use `--all-sites` to cover all Chameleon sites.

```bash
# Current site + current project (default)
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml

# All sites + current project, one entry per site
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --all-sites

# Current site + all projects, one entry per project
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --all-projects

# All sites + all projects
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --all-sites --all-projects

# Overwrite existing entries
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --force
```

`--all-projects` generates one entry per (site, project) pair, named `<site>_<project>`. `--no-vendordata` skips the metadata service lookup; requires `--auth-url` or `--all-sites`.

#### `ccauth openrc`

Writes an openrc file for a single site (use `clouds-yaml` for multi-site).

```bash
ccauth openrc --output ~/openrc
ccauth openrc --auth-url https://chi.uc.chameleoncloud.org:5000/v3 --output ~/openrc
ccauth openrc --output ~/openrc --force
```

#### `ccauth discover-projects`

Lists all projects you have access to across all sites and prints ready-to-run `ccauth clouds-yaml` commands for each one. Triggers the device flow automatically if no cached token is present.

```bash
ccauth discover-projects
ccauth discover-projects --output ~/my-clouds.yaml   # use a custom path in the printed commands
```

Example output:

```
Found 2 project(s). To add a project to clouds.yaml, run:

  # Project 1
  ccauth clouds-yaml --all-sites --project-id abc123 --output ~/.config/openstack/clouds.yaml

  # Project 2
  ccauth clouds-yaml --all-sites --project-id def456 --output ~/.config/openstack/clouds.yaml
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

Without `--auth-url`, the **current site** comes from the OpenStack metadata service at `169.254.169.254` (vendordata). This works automatically when running on a Chameleon instance.

`--all-sites` fetches all available sites from the Chameleon reference API (`https://api.chameleoncloud.org/sites`) and merges in the current site from vendordata when available (e.g. to pick up the correct cloud name for KVM or edge nodes).

Use `--no-vendordata` to skip the metadata service entirely; requires `--auth-url` or `--all-sites`.

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
| `--no-vendordata` | false | Skip metadata service lookup (requires `--auth-url` or `--all-sites`) |
| `--debug` | false | Enable debug logging |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `CC_LOGIN_STATE` | `~/.cache/ccauth` | Directory for cached refresh tokens (one `refresh_token-<hash>.json` per identity provider + client ID) |

---

## Library usage

```python
# Core OIDC auth — build a keystoneauth1 session
from ccauth import AuthConfig, build_session

config = AuthConfig(auth_url="https://chi.uc.chameleoncloud.org:5000/v3")
session = build_session(config)  # prompts device flow on first call

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
