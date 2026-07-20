# Database migration compatibility

Music Manager v0.2.0 reconciles two short-lived legacy migration chains:

- the deployed v0.1.3 `main` chain (`0001` through `0008`), including selected-result jobs, runtime `app_settings`, track file metadata, and defensive legacy compatibility;
- the unreleased v0.2 overhaul chain, which used its own `0006_provider_settings` and duplicate `0007_track_file_metadata` revisions before it was merged back to `main`.

The canonical chain is now linear: `0001` → `0008` from `main`, then `0009` for encrypted `provider_settings`. Revisions `0008` and `0009` are intentionally idempotent/guarded so databases created from either legacy chain can upgrade safely without duplicate-column or duplicate-table failures.
