# Contributing to sangfor-scp

Thanks for helping improve the Sangfor Cloud Platform (SCP) Open-API client.
Bug reports, documentation fixes and new endpoint coverage are all welcome.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs and requesting features

- Search [existing issues](https://github.com/erelbi/sangfor-scp/issues) first.
- Use the **Bug report** or **Feature request** template.
- Include your SCP version (`client.system.version()["build_version"]`),
  the library version (`sangfor_scp.__version__`) and the exact error
  (HTTP status, `errcode` such as `0x120220010001`, message).
- **Never paste credentials, hostnames, IP addresses, UUIDs or VM names from a
  real environment.** Replace them with placeholders (`10.x.x.x`, `POOL-A`,
  `vm-uuid`).
- Security problems: do not open a public issue — see [SECURITY.md](SECURITY.md).

## Development setup

```bash
git clone https://github.com/erelbi/sangfor-scp.git
cd sangfor-scp
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,token-auth]"
pytest
```

The unit tests in `tests/` mock the HTTP layer and need no SCP access.

### Testing against a real SCP

Put credentials in a `.env` file in the project root (it is git-ignored):

```
SCP_HOST=https://10.x.x.x
SCP_ACCESS_KEY=...
SCP_SECRET_KEY=...
```

Then run read-only checks first, e.g. `python examples/vm_create_test.py discover`
or `scp-health`. Anything that creates, changes or deletes resources should be
tried on a disposable test VM — never on production workloads.

Specs and notes that contain real environment values belong in
`examples/specs/local/` (git-ignored).

## Adding or changing an endpoint

1. Find the endpoint in the SCP Open-API reference and note its API version
   (`/janus/20180725/…`, `20190725`, `20210725`, `20240725`). Versions of the
   same endpoint often return different fields.
2. Add the method to the matching class in `sangfor_scp/resources/`.
   - Paginated lists: subclass `PaginatedResource` and implement `_list_page()`.
   - Async operations: return the `task_id` so callers can use `client.tasks.wait()`.
   - Only send query parameters the endpoint documents; SCP rejects unknown ones
     with `400 Extra argument (x) is not accepted`.
3. Write down real-environment behaviour that differs from the documentation in
   the module docstring (see `resources/metrics.py` for an example).
4. Add a mocked test in `tests/` and a short example to `README.md`.

## Style

- Python 3.8+ compatible; type hints on public methods.
- Public method docstrings describe arguments, return value and the endpoint.
- Keep runtime dependencies to `requests` and `urllib3`.
- Code and docs must not contain data from a real environment (pool names, IPs,
  host names, UUIDs, template or VM names).

## Commits and pull requests

- One logical change per pull request; keep unrelated refactors separate.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(servers): …`, `fix(metrics): …`, `docs: …`.
- Make sure `pytest` passes and fill in the pull request template.
- Breaking changes must be called out in the PR description and README.

## Releases

Releases are automated by `.github/workflows/release.yml`:

```bash
packaging/bump-version.sh 0.5.0 "Short summary of the release"
git commit -am "release: v0.5.0"
git tag -a v0.5.0 -m "v0.5.0"
git push origin main v0.5.0
```

`bump-version.sh` updates the version in `pyproject.toml`,
`sangfor_scp/__init__.py`, the RPM spec and `debian/changelog`. Pushing the tag
runs the tests, builds the sdist/wheel, the RPM (Fedora) and the DEB (Debian),
installs them in clean Fedora, Debian and Ubuntu containers, and attaches
everything plus `SHA256SUMS` to a GitHub Release. When the repository variable
`PUBLISH_PYPI` is `true`, the same run publishes to
[PyPI](https://pypi.org/project/sangfor-scp/) via trusted publishing.

Packages can be built locally the same way: `packaging/build.sh` and
`packaging/build.sh test`.
