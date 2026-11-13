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

Setup depends on where you run `ccauth`:

- **On a Chameleon instance** (a bare-metal node or KVM VM you launched on Chameleon), `ccauth` reads the site and project from the instance's metadata service. One command is enough.
- **Anywhere else** (your laptop, a CI runner, a VM on another cloud), there is no Chameleon metadata service, so you have to tell `ccauth` which project to use.

#### On a Chameleon instance

```bash
# Write a clouds.yaml entry for this instance's site and project.
# On first run you'll be prompted to visit a URL to authenticate.
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml

export OS_CLOUD=openstack   # the default entry name; change it with --cloud-name
openstack server list
```

#### On your own machine

```bash
# 1. List your projects. On first run you'll be prompted to visit a URL to authenticate.
ccauth discover-projects

# 2. Run the command it prints for the project you want. It looks like this:
ccauth clouds-yaml --all-sites --project-id <project-id> --output ~/.config/openstack/clouds.yaml

# 3. Choose a site by its ID: uc (CHI@UC), tacc (CHI@TACC), kvm (KVM@TACC), edge (CHI@Edge), ...
export OS_CLOUD=uc
openstack server list
```

This writes one `clouds.yaml` entry per Chameleon site, named by site ID.

If you run the Chameleon-instance command on your own machine, it fails with:

```
Could not determine current site. Pass --auth-url or use --all-sites to discover from the reference API.
```

That just means you're not on a Chameleon instance. Use the steps under [On your own machine](#on-your-own-machine) instead.

Subsequent runs reuse the cached refresh token silently. `ccauth login` is available as a convenience to pre-authenticate or verify credentials, but it is not a required first step — `clouds-yaml` and `discover-projects` will trigger the device flow automatically if no cached token is present.

### Subcommands

#### `ccauth login`

Optional. Runs the OIDC device flow and caches a refresh token. Useful for pre-authenticating or verifying credentials before running other commands. Works on any machine.

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

Writes a `clouds.yaml` file. By default the site and project come from the Chameleon metadata service, which only exists on a Chameleon instance. To run it anywhere else, use one of the "Any machine" combinations:

| Flags | Entries written | Works on |
|---|---|---|
| *(none)* | Current site, current project | Chameleon instance only |
| `--all-projects` | Current site, every project | Chameleon instance only |
| `--all-sites` | Every site, current project | Chameleon instance only |
| `--all-sites --project-id ID` | Every site, that project | Any machine |
| `--all-sites --all-projects` | Every site, every project | Any machine |
| `--auth-url URL --project-id ID` | That site, that project | Any machine |
| `--auth-url URL --all-projects` | That site, every project | Any machine |

```bash
# On a Chameleon instance: current site + current project
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml

# Anywhere: all sites + one project (get the ID from `ccauth discover-projects`)
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --all-sites --project-id <project-id>

# Anywhere: all sites + all projects
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --all-sites --all-projects

# Overwrite existing entries
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --all-sites --project-id <project-id> --force
```

Single-site entries are named `openstack` (change with `--cloud-name`). `--all-sites` names entries by site ID (`uc`, `tacc`, ...). `--all-projects` generates one entry per (site, project) pair, named `<site>_<project>`. `--no-vendordata` skips the metadata service lookup; requires `--auth-url` or `--all-sites`.

#### `ccauth openrc`

Writes an openrc file for a single site (use `clouds-yaml` for multi-site). On a Chameleon instance it uses the instance's site and project. Anywhere else, pass `--auth-url`, `--region-name`, and `--project-id` (the project's ID at that site).

```bash
# On a Chameleon instance
ccauth openrc --output ~/openrc
ccauth openrc --output ~/openrc --force

# Anywhere
ccauth openrc --auth-url https://chi.uc.chameleoncloud.org:5000/v3 --region-name CHI@UC \
  --project-id <project-id> --output ~/openrc
```

#### `ccauth discover-projects`

Lists all projects you have access to across all sites and prints ready-to-run `ccauth clouds-yaml` commands for each one. Works on any machine, and is the easiest way to get started when you're not on a Chameleon instance. Triggers the device flow automatically if no cached token is present.

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
  openstack:
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

Without `--auth-url`, the **current site** and project come from the OpenStack metadata service at `169.254.169.254` (vendordata). This is only available on a Chameleon instance. Anywhere else, `clouds-yaml` and `openrc` fail with `Could not determine current site` unless you pass `--auth-url` or `--all-sites`.

`--all-sites` fetches all available sites from the Chameleon reference API (`https://api.chameleoncloud.org/sites`) and merges in the current site from vendordata when available (e.g. to pick up the correct cloud name for KVM or edge nodes).

Use `--no-vendordata` to skip the metadata service entirely; requires `--auth-url` or `--all-sites`.

Override the discovery endpoints with `--sites-api-url` and `--metadata-url`.

### Options

| Flag | Default | Description |
|---|---|---|
| `--auth-url URL` | from metadata service (Chameleon instances only) | Keystone auth URL (skips discovery) |
| `--region-name NAME` | from metadata service (Chameleon instances only) | OpenStack region |
| `--project-id ID` | from metadata service (Chameleon instances only) | OpenStack project ID |
| `--client-id ID` | `chi-cli-device-token` | OIDC client ID |
| `--discovery-endpoint URL` | Chameleon Keycloak | OIDC discovery URL |
| `--cloud-name NAME` | `openstack` | Cloud name in clouds.yaml (single-site mode only) |
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
