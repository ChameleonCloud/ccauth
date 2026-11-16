# Releasing ccauth

ccauth is published to PyPI as [`chameleon-ccauth`](https://pypi.org/p/chameleon-ccauth). Publishing a GitHub release runs [`.github/workflows/publish.yaml`](../.github/workflows/publish.yaml), which tests, builds, and uploads the package.

The version comes from the release's git tag ([setuptools-scm](https://setuptools-scm.readthedocs.io/)).

## Cutting a release

1. **Check `main`.** It should have everything you want in the release, and CI should be passing.

2. **Pick the version.** Use [semantic versioning](https://semver.org/) and check the [release history on PyPI](https://pypi.org/project/chameleon-ccauth/#history). PyPI never accepts the same version twice, even if it's deleted, so a version can only be used once.

3. **Publish a GitHub release** with a new tag named `v<version>`, for example `v0.4.0`.

   In the web UI: **Releases → Draft a new release**, type the new tag and choose *Create new tag on publish*, set the target to `main`, click *Generate release notes*, then **Publish release**.

   Or with the [GitHub CLI](https://cli.github.com/):

   ```bash
   gh release create v0.4.0 --target main --generate-notes
   ```

4. **Watch the run** in the [Actions tab](https://github.com/ChameleonCloud/ccauth/actions/workflows/publish.yaml). It runs three jobs in order:
   - `test`: the same lint and tests as CI
   - `build`: builds the sdist and wheel
   - `publish`: uploads them to PyPI

5. **Check the result:**

   ```bash
   pip install --upgrade chameleon-ccauth==0.4.0
   ccauth --version
   ```

### Rules to know

- **The tag must start with `v`.** The `pypi` environment only allows tags matching `v*`. A release tagged `0.4.0` builds, but its publish job is refused and nothing is uploaded.
- **Pushing a tag alone doesn't publish.** The workflow only runs when a GitHub release is published.

## Troubleshooting

When a run fails before anything reaches PyPI, the fix usually means redoing the release, because re-running the workflow reuses the same tag and commit. To delete a release and its tag:

```bash
gh release delete v0.4.0 --cleanup-tag
```

Deleting a release in the web UI leaves its tag behind. Delete the tag separately (`git push --delete origin v0.4.0`), or the tag name can't be reused.

## One-time setup

This is already configured. It's recorded here in case it needs to be checked or recreated.

- **GitHub environment:** under repo **Settings → Environments**, an environment named `pypi` with a deployment tag rule `v*`.
- **PyPI trusted publisher:** on the `chameleon-ccauth` project on PyPI, under **Manage → Publishing**, a GitHub publisher with:
  - Owner: `ChameleonCloud`
  - Repository: `ccauth`
  - Workflow: `publish.yaml`
  - Environment: `pypi`

  The upload authenticates through this, so the repo stores no PyPI token or secret. If the workflow file or environment is renamed, update the publisher to match.
