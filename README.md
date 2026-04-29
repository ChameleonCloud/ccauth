# ccauth

OpenStack Chameleon device-flow authentication helper with application-credential caching.

Uses Keycloak OIDC device flow to obtain credentials, creates short-lived
application credentials, and caches them locally. Provides both CLI and library APIs.

## Installation

```bash
pip install -e .
pip install -e '.[test]'
```

## CLI

After installation, use the `cc-login` command:

```bash
# Generate openrc file
cc-login --output-openrc ~/openrc

# Generate clouds.yaml
cc-login --output-clouds-yaml ~/clouds.yaml

# View all options
cc-login --help
```

## keystoneauth plugin

`ccauth` registers a `v3chameleonoidc` auth plugin with keystoneauth1.
Any OpenStack tool that uses keystoneauth (`openstack`, `python-chi`, etc.)
can use it directly.

The plugin runs the OIDC device flow on first use, then caches the refresh
token to `~/.cache/ccauth/refresh_token.json`. Subsequent authentications 
refresh silently. Override the cache directory with the `CC_LOGIN_STATE` 
env var.

Example `clouds.yaml`:

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

Then:

```bash
export OS_CLOUD=chameleon
openstack server list
```

## Linting

Install the linting dependencies:

```bash
pip install -e '.[lint]'
```

Run pylint on the package:

```bash
pylint ccauth/
```

## Testing

```bash
pytest
```
