# ccauth

OpenStack Chameleon device-flow authentication helper with refresh token caching.

Uses Keycloak OIDC device flow to obtain credentials and caches the refresh token locally.
Provides both a CLI (`ccauth`) and a keystoneauth1 plugin (`v3chameleonoidc`).

## Installation

```bash
pip install -e .
```

## Usage

### Authenticate

```bash
ccauth login --auth-url https://chi.uc.chameleoncloud.org:5000/v3 --project-id <id>
```

On first run you will be prompted to visit a URL to complete device flow.
Subsequent runs reuse the cached refresh token silently.

Without `--auth-url`, `ccauth login` tries to fetch site config from the OpenStack metadata
service (only available on Chameleon instances).

### Write output files

```bash
# Generate clouds.yaml
ccauth clouds-yaml --auth-url ... --output ~/.config/openstack/clouds.yaml

# Generate openrc
ccauth openrc --auth-url ... --output ~/openrc

# Overwrite existing entries
ccauth clouds-yaml --auth-url ... --output ~/.config/openstack/clouds.yaml --force
```

### Clear cached tokens

```bash
ccauth logout
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `CC_LOGIN_STATE` | `~/.cache/ccauth` | Directory for cached refresh token |

### Debug logging

```bash
ccauth --debug login --auth-url ...
```

## clouds.yaml plugin

The `v3chameleonoidc` auth type is registered as a keystoneauth1 plugin.
Any openstack tool (openstack CLI, openstacksdk) picks it up automatically
once `ccauth` is installed.

```yaml
clouds:
  chameleon:
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

`ccauth login` pre-warms the token cache. Subsequent `openstack` invocations reuse
the cached token without prompting.

## Development

```bash
pip install -e '.[dev]'
pytest
```
