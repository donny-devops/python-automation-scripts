"""
Granola Engineer — meeting-context bridge
─────────────────────────────────────────
Turn exported Granola meeting notes into structured action items and,
optionally, To-Dojo tasks so work stays anchored to what a team actually
decided.

This tool reads a *local* Granola export (JSON) — it performs no network
I/O and needs no secrets. Untrusted JSON is coerced defensively, and any
files written go through the same atomic tmp+os.replace pattern used by
To-Dojo.

Supported export shapes (all fields optional and defensively coerced):
  • A list of meeting objects
  • {"meetings": [ ... ]}
  • A single meeting object

Each meeting may carry explicit ``action_items`` (strings or objects). When
absent, action items are extracted heuristically from the ``notes``/``summary``
markdown (checkbox lines, "TODO:", "Action:", etc.).

Usage:
  python granola_engineer.py list export.json
  python granola_engineer.py export export.json --out action_items.json
  python granola_engineer.py to-dojo export.json --data-file dojo.json
  python granola_engineer.py to-dojo export.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

# To-Dojo priority vocabulary this tool maps onto.
VALID_PRIORITIES = ("critical", "high", "normal", "low")
DEFAULT_PRIORITY = "normal"

# Keyword → priority hints used when a meeting note does not state one.
_PRIORITY_KEYWORDS = {
    "critical": ("critical", "blocker", "p0", "urgent", "asap", "immediately"),
    "high": ("high priority", "important", "high-priority", "p1", "soon"),
    "low": ("low priority", "nice to have", "nice-to-have", "someday", "p3", "backlog"),
}

# Free-text markers that introduce an action item on a single line.
_ACTION_LINE_RE = re.compile(
    r"""^\s*
        (?:[-*+]\s*)?            # optional bullet
        (?:\[\s*[ xX]?\s*\]\s*)? # optional checkbox
        (?:
            (?:TODO|ACTION|ACTION\ ITEM|AI|FOLLOW[\ -]?UP|NEXT\ STEP)
            \s*[:\-]\s*
        )
        (?P<text>.+?)\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Checkbox-only lines (e.g. "- [ ] do the thing") also count as action items.
_CHECKBOX_LINE_RE = re.compile(r"^\s*[-*+]?\s*\[\s*[ xX]?\s*\]\s*(?P<text>.+?)\s*$")

# "@name" or "(owner: name)" style assignee hints inside an action line.
_ASSIGNEE_RE = re.compile(r"(?:@|\bowner:\s*|\bassignee:\s*)([A-Za-z][\w.\-]*)", re.IGNORECASE)

# ISO-ish due dates mentioned inline (YYYY-MM-DD).
_DUE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


@dataclass
class ActionItem:
    text: str
    meeting_id: str = ""
    meeting_title: str = ""
    assignee: str | None = None
    due_date: str | None = None
    priority: str = DEFAULT_PRIORITY


@dataclass
class Meeting:
    id: str = ""
    title: str = ""
    date: str = ""
    summary: str = ""
    action_items: list[ActionItem] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)


class GranolaParseError(ValueError):
    """Raised when a Granola export cannot be parsed into meetings."""


def _as_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def infer_priority(text: str, explicit: object = None) -> str:
    """Return a To-Dojo priority for *text*, honoring an *explicit* hint first."""
    hint = _as_str(explicit).lower()
    if hint in VALID_PRIORITIES:
        return hint
    haystack = text.lower()
    for priority in ("critical", "high", "low"):
        if any(keyword in haystack for keyword in _PRIORITY_KEYWORDS[priority]):
            return priority
    return DEFAULT_PRIORITY


def _clean_action_text(text: str) -> str:
    """Strip inline assignee/due markers so the task title reads cleanly."""
    cleaned = _ASSIGNEE_RE.sub("", text)
    cleaned = re.sub(r"\((?:owner|assignee|due)[^)]*\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = _DUE_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip(" -–—:·|")
    cleaned = re.sub(r"\s+(?:by|on|before|due|until)\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" -–—:·|")


def _strip_leading_markers(text: str) -> str:
    match = _ACTION_LINE_RE.match(text) or _CHECKBOX_LINE_RE.match(text)
    return match.group("text") if match else text


def _action_from_text(raw: str, meeting: Meeting) -> ActionItem | None:
    text = _strip_leading_markers(_as_str(raw))
    if not text:
        return None
    assignee_match = _ASSIGNEE_RE.search(text)
    due_match = _DUE_RE.search(text)
    title = _clean_action_text(text)
    if not title:
        return None
    return ActionItem(
        text=title,
        meeting_id=meeting.id,
        meeting_title=meeting.title,
        assignee=assignee_match.group(1) if assignee_match else None,
        due_date=due_match.group(1) if due_match else None,
        priority=infer_priority(text),
    )


def _action_from_obj(raw: dict, meeting: Meeting) -> ActionItem | None:
    text = _as_str(raw.get("text") or raw.get("title") or raw.get("task") or raw.get("name"))
    if not text:
        return None
    assignee = _as_str(raw.get("assignee") or raw.get("owner")) or None
    due = _as_str(raw.get("due_date") or raw.get("due")) or None
    if not assignee:
        match = _ASSIGNEE_RE.search(text)
        assignee = match.group(1) if match else None
    if not due:
        match = _DUE_RE.search(text)
        due = match.group(1) if match else None
    return ActionItem(
        text=_clean_action_text(text) or text.strip(),
        meeting_id=meeting.id,
        meeting_title=meeting.title,
        assignee=assignee,
        due_date=due,
        priority=infer_priority(text, raw.get("priority")),
    )


def extract_from_notes(notes: str, meeting: Meeting) -> list[ActionItem]:
    """Heuristically pull action items out of free-text meeting notes."""
    items: list[ActionItem] = []
    seen: set[str] = set()
    for line in notes.splitlines():
        match = _ACTION_LINE_RE.match(line) or _CHECKBOX_LINE_RE.match(line)
        if not match:
            continue
        item = _action_from_text(match.group("text"), meeting)
        if item and item.text.lower() not in seen:
            seen.add(item.text.lower())
            items.append(item)
    return items


def _coerce_meeting(raw: dict) -> Meeting:
    if not isinstance(raw, dict):
        raise GranolaParseError("Each meeting must be a JSON object")
    meeting = Meeting(
        id=_as_str(raw.get("id") or raw.get("meeting_id")),
        title=_as_str(raw.get("title") or raw.get("name"), default="Untitled meeting"),
        date=_as_str(raw.get("date") or raw.get("created_at") or raw.get("start_time")),
        summary=_as_str(raw.get("summary") or raw.get("overview")),
    )

    decisions = raw.get("decisions")
    if isinstance(decisions, list):
        meeting.decisions = [d for d in (_as_str(item) for item in decisions) if d]

    raw_actions = raw.get("action_items")
    if isinstance(raw_actions, list):
        for entry in raw_actions:
            item = (
                _action_from_obj(entry, meeting)
                if isinstance(entry, dict)
                else _action_from_text(_as_str(entry), meeting)
            )
            if item:
                meeting.action_items.append(item)

    if not meeting.action_items:
        notes = _as_str(raw.get("notes") or raw.get("body") or raw.get("transcript"))
        text_blob = "\n".join(part for part in (notes, meeting.summary) if part)
        meeting.action_items = extract_from_notes(text_blob, meeting)

    return meeting


def parse_export(raw: object) -> list[Meeting]:
    """Coerce an arbitrary Granola export payload into a list of meetings."""
    if isinstance(raw, dict):
        if isinstance(raw.get("meetings"), list):
            entries = raw["meetings"]
        else:
            entries = [raw]
    elif isinstance(raw, list):
        entries = raw
    else:
        raise GranolaParseError("Export must be a JSON object or array")

    meetings: list[Meeting] = []
    for entry in entries:
        if isinstance(entry, dict):
            meetings.append(_coerce_meeting(entry))
    return meetings


def load_export(path: Path) -> list[Meeting]:
    if not path.is_file():
        raise GranolaParseError(f"Export file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GranolaParseError(f"Invalid JSON in {path}: {exc}") from exc
    return parse_export(raw)


def collect_action_items(meetings: list[Meeting]) -> list[ActionItem]:
    items: list[ActionItem] = []
    for meeting in meetings:
        items.extend(meeting.action_items)
    return items


def _atomic_write_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def write_action_items(items: list[ActionItem], path: Path) -> None:
    _atomic_write_json([asdict(item) for item in items], path)


# ── To-Dojo bridge ──────────────────────────────────────────────────────────


def _import_to_dojo():
    """Import the sibling To-Dojo module, adding its directory to sys.path.

    The monorepo keeps each tool in its own hyphenated directory, so the
    module is not importable by default when this script runs standalone.
    """
    import sys

    sibling = Path(__file__).resolve().parent.parent / "to-dojo"
    if sibling.is_dir() and str(sibling) not in sys.path:
        sys.path.insert(0, str(sibling))
    try:
        import to_dojo

        return to_dojo
    except ModuleNotFoundError as exc:  # pragma: no cover - defensive
        raise GranolaParseError(
            "The 'to-dojo' tool is required for the to-dojo bridge but could not be imported."
        ) from exc


def send_to_dojo(
    items: list[ActionItem],
    data_file: Path | None = None,
    *,
    default_priority: str | None = None,
) -> list[str]:
    """Create To-Dojo tasks from *items*, skipping titles that already exist.

    Returns the list of task titles that were newly created. Reuses To-Dojo's
    own atomic ``save_state`` and validated ``add_task_record`` so state stays
    consistent with the standalone tool.
    """
    to_dojo = _import_to_dojo()  # imported lazily so `list`/`export` don't require it

    path = data_file or to_dojo.default_data_file()
    state = to_dojo.load_state(path)
    existing = {str(task.get("title", "")).strip().lower() for task in state.tasks}

    created: list[str] = []
    for item in items:
        title = item.text.strip()
        if not title or title.lower() in existing:
            continue
        priority = default_priority or item.priority
        if priority not in VALID_PRIORITIES:
            priority = DEFAULT_PRIORITY
        tags = ["granola"]
        if item.meeting_title:
            tags.append(item.meeting_title)
        try:
            to_dojo.add_task_record(
                state,
                title,
                priority=priority,
                due_date=item.due_date,
                notes=f"From meeting: {item.meeting_title}".strip(),
                tags=tags,
            )
        except ValueError as exc:
            console.print(f"[yellow]Skipped {title!r}: {exc}[/]")
            continue
        existing.add(title.lower())
        created.append(title)

    if created:
        to_dojo.save_state(state, path)
    return created


# ── Display ──────────────────────────────────────────────────────────────────


def print_meetings(meetings: list[Meeting]) -> None:
    if not meetings:
        console.print("[dim]No meetings found in export.[/]")
        return
    for meeting in meetings:
        header = meeting.title or "Untitled meeting"
        if meeting.date:
            header += f"  [dim]({meeting.date})[/]"
        console.print(f"\n[bold cyan]{header}[/]")
        if meeting.decisions:
            for decision in meeting.decisions:
                console.print(f"  [green]decision[/] {decision}")
        if not meeting.action_items:
            console.print("  [dim]No action items detected.[/]")
            continue
        table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False)
        table.add_column("Priority", justify="left", width=10)
        table.add_column("Action item", style="white", min_width=30)
        table.add_column("Owner", width=12)
        table.add_column("Due", width=12)
        for item in meeting.action_items:
            table.add_row(
                item.priority,
                item.text,
                item.assignee or "—",
                item.due_date or "—",
            )
        console.print(table)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Granola Engineer — turn meeting notes into action items and To-Dojo tasks",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List meetings and detected action items")
    list_p.add_argument("export", help="Path to a Granola export JSON file")

    export_p = sub.add_parser("export", help="Write normalized action items to JSON")
    export_p.add_argument("export", help="Path to a Granola export JSON file")
    export_p.add_argument("--out", default="action_items.json", help="Output JSON path")

    dojo_p = sub.add_parser("to-dojo", help="Create To-Dojo tasks from action items")
    dojo_p.add_argument("export", help="Path to a Granola export JSON file")
    dojo_p.add_argument("--data-file", default=None, help="To-Dojo state file path")
    dojo_p.add_argument(
        "--priority",
        choices=VALID_PRIORITIES,
        default=None,
        help="Force a priority for every created task (default: inferred)",
    )
    dojo_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing state",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    export_path = Path(args.export)
    try:
        meetings = load_export(export_path)
    except GranolaParseError as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    if args.command == "list":
        print_meetings(meetings)
        total = sum(len(m.action_items) for m in meetings)
        console.print(f"\n[dim]{len(meetings)} meeting(s), {total} action item(s).[/]")
        return 0

    items = collect_action_items(meetings)

    if args.command == "export":
        out_path = Path(args.out)
        write_action_items(items, out_path)
        console.print(f"[green]Wrote {len(items)} action item(s) to {out_path}[/]")
        return 0

    if args.command == "to-dojo":
        if args.dry_run:
            print_meetings(meetings)
            console.print(f"\n[dim]Dry run: {len(items)} action item(s) would be considered.[/]")
            return 0
        data_file = Path(args.data_file) if args.data_file else None
        created = send_to_dojo(items, data_file, default_priority=args.priority)
        console.print(f"[green]Created {len(created)} To-Dojo task(s) from {len(items)} item(s).[/]")
        for title in created:
            console.print(f"  [cyan]+[/] {title}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
