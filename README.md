# ccauth

OpenStack Chameleon device-flow authentication helper with application-credential caching.

Uses Keycloak OIDC device flow to obtain credentials and caches the refresh token locally.
Provides both a CLI (`cc-login`) and a keystoneauth1 plugin (`v3chameleonoidc`).

## Installation

```bash
pip install -e .
```

## Usage

### Pre-warm the token cache

```bash
cc-login --auth-url https://chi.uc.chameleoncloud.org:5000/v3 --project-name <name>
```

On first run you will be prompted to visit a URL to complete device flow.
Subsequent runs reuse the cached refresh token silently.

Without `--auth-url`, cc-login tries to fetch site config from the OpenStack metadata
service (only available on Chameleon instances).

### Write output files

```bash
# Generate clouds.yaml
cc-login --auth-url ... --output-clouds-yaml ~/.config/openstack/clouds.yaml

# Generate openrc
cc-login --auth-url ... --output-openrc ~/openrc

# Overwrite existing entries
cc-login --auth-url ... --output-clouds-yaml ~/.config/openstack/clouds.yaml --force
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `CC_LOGIN_STATE` | `~/.cache/ccauth` | Directory for cached refresh token |

```bash
CC_LOGIN_STATE=~/.cclogin cc-login --auth-url ...
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
      project_name: <your-project-name>
      project_domain_name: chameleon
      client_id: chi-cli-device-token
      discovery_endpoint: https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration
    region_name: CHI@UC
```

`cc-login` pre-warms the token cache. Subsequent `openstack` invocations reuse
the cached token without prompting.

## Development

```bash
pip install -e '.[dev]'
pytest
```
