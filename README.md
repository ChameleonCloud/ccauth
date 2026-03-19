# ccauth

OIDC device flow auth plugin for OpenStack on Chameleon.

Caches refresh tokens locally so you authenticate once interactively,
then all subsequent `openstack` commands work silently.

## Installation

```bash
pip install .
```

## Quick start

```bash
# Authenticate (discovers sites automatically from the Chameleon API)
ccauth login

# Or specify a site directly
ccauth login --auth-url https://chi.uc.chameleoncloud.org:5000/v3
```

On first run you'll be prompted to visit a URL. Subsequent runs reuse the
cached refresh token silently.

## Generate config files

```bash
# clouds.yaml (auto-discovers all Chameleon sites)
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml

# clouds.yaml for a specific site
ccauth clouds-yaml --auth-url https://chi.uc.chameleoncloud.org:5000/v3 \
  --cloud-name chi_uc --output ~/.config/openstack/clouds.yaml

# openrc (single site)
ccauth openrc --auth-url https://chi.uc.chameleoncloud.org:5000/v3 \
  --output ~/openrc

# Overwrite existing entries
ccauth clouds-yaml --output ~/.config/openstack/clouds.yaml --force
```

## Clear cached tokens

```bash
ccauth logout
```

## Site discovery

When `--auth-url` is not provided, ccauth automatically discovers sites:

1. **Chameleon reference API** — queries `https://api.chameleoncloud.org/sites`
2. **OpenStack vendordata** — falls back to the metadata service (only on Chameleon instances)

You can override these URLs with `--sites-api-url` and `--metadata-url`.

## clouds.yaml plugin

The `v3chameleonoidc` auth type is registered as a keystoneauth1 plugin.
Once `ccauth` is installed, any openstack tool picks it up automatically:

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

Run `ccauth login` to prime the cache, then use `openstack` normally:

```bash
openstack --os-cloud uc server list
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CC_LOGIN_STATE` | `~/.cache/ccauth` | Directory for cached refresh token |

## Debug logging

```bash
ccauth --debug login
```

## Development

```bash
pip install -e '.[dev]'
pytest
```
