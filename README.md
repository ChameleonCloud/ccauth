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
