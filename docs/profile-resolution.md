# Editorial profile resolution

`resolve_profile.py` loads the committed editorial YAML profiles using PyYAML's
safe loader. Resolution supplies editorial preferences to ChatGPT; it does not
make selects or approve an edit. Existing profile values are unchanged.

```bash
.venv/bin/python scripts/resolve_profile.py winery \
  --job-id synthetic-demo \
  --output artifacts/synthetic-demo/resolved-profile.json
```

The CLI creates a new snapshot and refuses to overwrite an existing file. It
publishes complete JSON through a temporary file and an exclusive hard link in
the output directory. Inside this repository, output must be under
`work/<job_id>/` or `artifacts/<job_id>/`; external output storage is allowed.
Use `--profiles-dir` to supply another explicit directory and `--selects` to
validate a supplied selects document against the resolved identity. There are no
network profile lookups or editorial-stage execution in this command.

## Contracts and merge behavior

The auxiliary `profile.schema.json` describes the existing YAML structure; YAML
profiles retain their original `profile`, integer `version`, and `parent` fields.
The auxiliary `resolved-profile.schema.json` describes generated snapshots with
`schema_version: "2.0.0"` and `job_id`. Neither adds fields to existing stage
contracts. Both use Draft 2020-12 through the existing offline registry.

Mappings merge recursively. Child scalars and complete lists replace inherited
values. Profile identity, version, and parent are metadata rather than inherited
settings. For example, winery inherits base source-integrity rules and travel
priorities, while its topic and story lists replace travel's lists. The resulting
snapshot records the child identity/version, merged settings, and root-first
parent chain with each declared version and SHA-256 of exact YAML file bytes.
Comments and formatting changes therefore change the binding even if resolved
settings remain identical. Resolution includes no timestamps or inferred versions.

Unknown top-level and nested fields fail. Priority scores must be finite numbers
between zero and one; durations must be positive and duration intervals ordered.
Duplicate mapping keys, aliases, merge keys, unsafe YAML tags, filename/identity
mismatches, missing parents, cycles, symlink profiles, and parent path traversal
are rejected. Chain length is bounded to 128 profiles and files to 1 MiB. New
editorial setting names require an explicit auxiliary contract update, rather
than silent acceptance or omission.

## API and freshness

`resolve_profile(profile, job_id, profiles_dir)` returns a validated snapshot.
`check_selects_binding(selects, snapshot, profiles_dir)` validates both contracts,
checks job/profile/version equality, resolves the current chain again, and rejects
a stale or altered snapshot. The existing selects profile/version alone does not
prove a parent was unchanged: retain the snapshot as a stage dependency in job
records and compare it on reuse. Saved hashes do not confer export authority.

These checks establish local file bindings, not media validity, editorial quality,
human approval, or upload permission. Concurrent edits during resolution can
produce a snapshot of bytes observed at different moments; later reuse compares
against fresh resolution, and callers must retain the observed snapshot as their
run dependency.
