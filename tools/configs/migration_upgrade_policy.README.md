# Migration upgrade policy

`migration_upgrade_policy.json` configures which migration differences the
upgrade CI treats as failures. Keep exceptions narrow and use exact identifiers.

- `enforced_apps`: Django app labels whose available/applied migrations are
  compared across upgrade stages.
- `allowed_missing`: exact `app_label.migration_name` keys that may be absent
  from a later stage.
- `allowed_fingerprint_changes`: exact migration keys whose source fingerprint
  may change after an earlier stage has applied them.
- `immutable_vcs_stages`: stage names where installed VCS dependencies must be
  non-editable Git checkouts requested by a full commit SHA matching the
  resolved commit. An empty list records provenance without enforcing that
  pinning policy.

Per-run inventories and database snapshots are generated CI artifacts, not
policy inputs; do not commit them. Do not add credentials, deployed-system data,
or internal issue references to this file or its exceptions.
