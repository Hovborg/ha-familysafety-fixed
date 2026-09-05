# Offline CI

## Offline CI

GitHub Actions validates the tracked source inventory in `.github/source-check.json`.
Run `python -m pip install -r .github/requirements-ci.txt` followed by
`python .github/scripts/validate_source.py`. Python, JSON, YAML and shell files are
parsed without importing application code. Update the inventory when adding files.
Actions and dependencies are pinned. Passing syntax checks does not establish live
service behavior; CI must not use account credentials, private data or devices.

Config-flow URLs belong in `description_placeholders`, not translation strings.
Keep the same placeholders bound on initial display and error redisplay, and
preserve the Microsoft authorization URL parameters when maintaining translations.
