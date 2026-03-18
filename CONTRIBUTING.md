# Contributing

## Goals

1. **Native auth** — keystoneauth1 plugin (`v3chameleonoidc`) so any OpenStack tool works out of the box
2. **Discovery** — automatically find Chameleon sites and the user's projects, no manual config
3. **Templating** — generate correct `clouds.yaml` and `openrc` files from discovered data

Works **outside Chameleon** (laptop, CI) via the reference API and device flow.
Works **inside Chameleon** (on instances) via vendordata for the current site.

## How it works

1. **Device code flow** gets the initial OIDC token from Keycloak — no password stored
2. **Refresh token** is cached locally and rotated on use, so subsequent auth is silent
3. **Reference API** (`api.chameleoncloud.org/sites`) provides all Chameleon site URLs
4. **Vendordata** (OpenStack metadata service) provides the current site's URL when running on a Chameleon instance
5. **Refresh token → Keystone token** exchange happens per-site via the site's `auth_url`
6. **Federation project list** (`/OS-FEDERATION/projects`) returns the user's projects per site
7. Combining sites × projects, we can **generate a complete clouds.yaml** with no user input beyond the initial device flow

## Development

```bash
uv pip install -e .
pytest
```

## Where to make changes

- `plugin.py` — keystoneauth1 plugin. Standalone, no internal imports. Treat as upstreamable.
- `loader.py` — registers the plugin with keystoneauth1. Rarely needs changes.
- `config.py` — `SiteConfig` dataclass. Pure data, no I/O.
- `discover.py` — site and project discovery (reference API, vendordata). Chameleon-specific conventions live here.
- `writers.py` — generates `clouds.yaml` and `openrc` files from `SiteConfig`s.
- `cli.py` — subcommand dispatch, orchestrates everything above.
