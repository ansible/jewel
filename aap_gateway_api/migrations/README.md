# Migration Dependency Patterns

## Migration Graph Structure

The `aap_gateway_api` migration graph is not strictly linear. Starting at
migration 0017, the graph forks into two branches that converge at 0023:

```
0017 → 0018 → 0019 → 0020 → 0021 ─┐
  └──→ 0022 ─────────────────────────┴──→ 0023 (convergence, single leaf)
```

This is intentional. Django's migration system is a directed acyclic graph
(DAG), not a linear sequence. File numbers are cosmetic — execution order is
determined by the `dependencies` attribute in each migration class.

## Why the Fork Exists

Migration 0022 (`UserSessionMembership`) creates a new table that only
references `User` and `Session` — neither of which is modified by migrations
0018–0021. Its declared dependency on 0017 reflects this true schema
dependency, not the conventional "chain off the latest migration" pattern
that `makemigrations` produces by default.

This restructuring enables clean backporting of 0022 to stable branches
where migrations 0018–0021 do not exist (e.g., stable-2.6 stops at 0017).

## Convergence Migration (0023)

Migration `0023_merge_0021_0022` is an empty migration (`operations = []`)
that depends on both 0021 and 0022. Its purpose is to rejoin the two
branches into a single leaf node, which Django requires before
`makemigrations` will create new migrations.

The data cleanup previously performed by 0023 (removing console ServiceType
and RED_HAT_CONSOLE_URL preference) is handled by the `post_migrate` signal
handler `remove_console_service_type()` in `preloaded_data.py`.

## Rules for Future Backportable Migrations

When writing a migration that may need backporting to a stable branch:

1. Set `dependencies` to the earliest migration that the operations genuinely
   depend on — not just the latest migration on the branch.

2. Cherry-pick the migration file unmodified to the target stable branch.
   The dependency must be satisfied on that branch.

3. Forward-propagation: a migration backported to an older stable branch
   must also be present on all intermediate stable branches before those
   branches release. This prevents orphan `django_migrations` records on
   upgrade.

4. Add an empty convergence migration on devel (and downstream-only
   convergence migrations on stable branches if needed) to rejoin the
   graph into a single leaf.

5. All future migrations on devel depend on the convergence migration,
   maintaining a single leaf.

## What NOT to Do

- Do not use `migrate --prune` during upgrades. Without forward-propagation,
  `--prune` can delete `django_migrations` records for migrations whose
  files are missing on the target branch. On a subsequent upgrade to a
  release that includes those migrations, Django will attempt to re-apply
  them (e.g., `CREATE TABLE` on an existing table), causing a crash.

- Do not renumber migrations on stable branches. The same migration file
  (same name, same content) should exist on every branch where it's needed.

- Do not create branch-specific migration files with different names for
  the same schema change. This creates divergent `django_migrations` records
  that cannot be reconciled on upgrade.

## References

- AAP-82458: Migration re-parent and converge plan
- AAP-80663: Full analysis of migrations 0017–0023 with dependency mapping
- AAP-80375: Investigation of out-of-sync migration in stable-2.6
