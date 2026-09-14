# Granola Engineer

Turn exported [Granola](https://www.granola.ai/) meeting notes into structured
action items — and optionally into [To-Dojo](../to-dojo/README.md) tasks — so
work stays anchored to what your team actually decided.

This tool reads a **local** Granola export (JSON). It performs no network I/O
and needs no secrets. Untrusted JSON is coerced defensively, and files are
written atomically (`tmp` + `os.replace`), matching the rest of the repo.

## Usage

```bash
# Inspect meetings and detected action items
python granola-engineer/granola_engineer.py list export.json

# Write normalized action items to JSON
python granola-engineer/granola_engineer.py export export.json --out action_items.json

# Create To-Dojo tasks from the action items (dedupes by title on re-run)
python granola-engineer/granola_engineer.py to-dojo export.json --data-file dojo.json

# Preview without writing any state
python granola-engineer/granola_engineer.py to-dojo export.json --dry-run
```

An editable install also exposes a `granola-engineer` console command.

## Supported export shapes

All fields are optional and defensively coerced:

- A list of meeting objects
- `{"meetings": [ ... ]}`
- A single meeting object

Each meeting may carry explicit `action_items` (strings or objects with
`text`/`title`, `owner`/`assignee`, `due`/`due_date`, `priority`). When no
explicit action items are present, they are extracted heuristically from the
`notes`/`summary` markdown:

- Checkbox lines — `- [ ] do the thing`, `* [x] done thing`
- Marker lines — `TODO:`, `Action:`, `Follow-up:`, `Next step:`

Inline `@owner` mentions and `YYYY-MM-DD` due dates are lifted into structured
fields, and priority is inferred from keywords (`urgent`/`asap` → `critical`,
`important` → `high`, `nice to have` → `low`).

## Priority mapping

Inferred priorities map onto To-Dojo's vocabulary: `critical`, `high`,
`normal`, `low`. Pass `--priority` to force a single priority for every created
task. Tasks created from meetings are tagged `granola` plus the meeting title.
