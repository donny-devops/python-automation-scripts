"""
To-Dojo — Gamified Kung-Fu Task Manager
────────────────────────────────────────
Progress through the martial arts ranks by completing tasks.
Your productivity earns you belt promotions, Dojo Points (DP),
streak multipliers, and AI-powered Sensei wisdom.

Ranks (in order):
  White Belt → Yellow Belt → Orange Belt → Green Belt →
  Blue Belt → Purple Belt → Brown Belt → Red Belt →
  Black Belt → Grand Master

Features:
  • Add tasks with priority (Critical / High / Normal / Low)
  • Complete tasks to earn Dojo Points based on priority + streak
  • Belt promotion system with thresholds
  • Daily streak multiplier (bonus DP for consecutive days)
  • Achievement badges (First Blood, On Fire, Iron Will, etc.)
  • AI Sensei motivational hints via Claude (optional)
  • Full task history & stats dashboard
  • Persistent JSON storage

Usage:
  python to_dojo.py
  python to_dojo.py add "Ship the patch" --priority high
  python to_dojo.py complete 1
  python to_dojo.py list
  python to_dojo.py stats
"""

import os
import json
import random
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict, fields

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from rich import box
from dotenv import load_dotenv

load_dotenv()

console = Console()
DATA_FILE = Path(os.getenv("DOJO_DATA_FILE", "dojo_data.json"))
PRIORITY_ORDER = ["critical", "high", "normal", "low"]

# ── Ranks ─────────────────────────────────────────────────────────────────────

RANKS = [
    ("White Belt", "⬜", 0),
    ("Yellow Belt", "🟨", 100),
    ("Orange Belt", "🟧", 250),
    ("Green Belt", "🟩", 500),
    ("Blue Belt", "🟦", 900),
    ("Purple Belt", "🟪", 1400),
    ("Brown Belt", "🟫", 2100),
    ("Red Belt", "🟥", 3000),
    ("Black Belt", "⬛", 4200),
    ("Grand Master", "🏆", 6000),
]

PRIORITY_CONFIG = {
    "critical": {"dp": 40, "label": "CRITICAL", "color": "bold red", "symbol": "🔴"},
    "high": {"dp": 20, "label": "HIGH", "color": "bold yellow", "symbol": "🟡"},
    "normal": {"dp": 10, "label": "NORMAL", "color": "bold green", "symbol": "🟢"},
    "low": {"dp": 5, "label": "LOW", "color": "bold blue", "symbol": "🔵"},
}

ACHIEVEMENTS = {
    "first_blood": {
        "name": "First Blood",
        "icon": "🩸",
        "desc": "Complete your first task",
        "condition": lambda s: s["total_completed"] >= 1,
    },
    "on_fire": {
        "name": "On Fire",
        "icon": "🔥",
        "desc": "Complete 5 tasks in one session",
        "condition": lambda s: s["session_completed"] >= 5,
    },
    "iron_will": {
        "name": "Iron Will",
        "icon": "⚙️",
        "desc": "Maintain a 7-day streak",
        "condition": lambda s: s["streak"] >= 7,
    },
    "dragon": {
        "name": "Dragon",
        "icon": "🐉",
        "desc": "Reach Black Belt",
        "condition": lambda s: s["total_dp"] >= 4200,
    },
    "centurion": {
        "name": "Centurion",
        "icon": "💯",
        "desc": "Complete 100 tasks",
        "condition": lambda s: s["total_completed"] >= 100,
    },
    "perfectionist": {
        "name": "Perfectionist",
        "icon": "✨",
        "desc": "Complete 10 critical tasks",
        "condition": lambda s: s["critical_completed"] >= 10,
    },
    "no_days_off": {
        "name": "No Days Off",
        "icon": "📅",
        "desc": "Maintain a 30-day streak",
        "condition": lambda s: s["streak"] >= 30,
    },
    "sensei": {
        "name": "Sensei",
        "icon": "🎓",
        "desc": "Reach Grand Master rank",
        "condition": lambda s: s["total_dp"] >= 6000,
    },
}

KI_PHRASES = [
    "The journey of a thousand tasks begins with a single step.",
    "A warrior who acts completes; a warrior who waits is forgotten.",
    "Discipline is choosing between what you want now and what you want most.",
    "The obstacle is the way. Complete it.",
    "Small victories compound into mastery.",
    "In the dojo of productivity, every task is a sparring partner.",
    "Strike swiftly. Rest briefly. Strike again.",
    "Your belt is earned by action, not intention.",
    "The strongest warrior is not the one who wins, but the one who doesn't quit.",
    "Each completed task is a brick in the fortress of your future.",
]


# ── Data Model ────────────────────────────────────────────────────────────────


@dataclass
class Task:
    id: int
    title: str
    priority: str = "normal"
    due_date: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str | None = None
    dp_earned: int = 0
    notes: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class DojoState:
    tasks: list[dict] = field(default_factory=list)
    total_dp: int = 0
    total_completed: int = 0
    critical_completed: int = 0
    streak: int = 0
    last_active_date: str | None = None
    achievements: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    session_completed: int = 0
    next_id: int = 1


# ── Persistence ───────────────────────────────────────────────────────────────

_STATE_FIELDS = {item.name for item in fields(DojoState)}


def _coerce_state(raw: dict) -> DojoState:
    filtered = {k: v for k, v in raw.items() if k in _STATE_FIELDS}
    state = DojoState(**filtered)
    if not isinstance(state.tasks, list):
        state.tasks = []
    if not isinstance(state.history, list):
        state.history = []
    if not isinstance(state.achievements, list):
        state.achievements = []
    cleaned_tasks = []
    task_fields = {item.name for item in fields(Task)}
    for task in state.tasks:
        if not isinstance(task, dict) or "id" not in task or "title" not in task:
            continue
        priority = str(task.get("priority", "normal")).lower()
        if priority not in PRIORITY_CONFIG:
            priority = "normal"
        task = {k: v for k, v in task.items() if k in task_fields}
        task["priority"] = priority
        task.setdefault("tags", [])
        if not isinstance(task["tags"], list):
            task["tags"] = []
        cleaned_tasks.append(task)
    state.tasks = cleaned_tasks
    state.total_dp = max(0, int(state.total_dp or 0))
    state.total_completed = max(0, int(state.total_completed or 0))
    state.critical_completed = max(0, int(state.critical_completed or 0))
    state.streak = max(0, int(state.streak or 0))
    state.session_completed = max(0, int(state.session_completed or 0))
    state.next_id = max(1, int(state.next_id or 1))
    return state


def load_state(path: Path | None = None) -> DojoState:
    data_path = path or DATA_FILE
    if not data_path.exists():
        return DojoState()
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("state root must be an object")
        return _coerce_state(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        backup = data_path.with_suffix(data_path.suffix + ".corrupt")
        try:
            backup.write_bytes(data_path.read_bytes())
            console.print(f"[yellow]Corrupt state moved to {backup} ({exc})[/]")
        except OSError:
            console.print(f"[yellow]Could not load {data_path}: {exc}[/]")
        return DojoState()


def save_state(state: DojoState, path: Path | None = None) -> None:
    data_path = path or DATA_FILE
    data_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(state), indent=2)
    tmp = data_path.with_name(data_path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, data_path)


# ── Rank Helpers ──────────────────────────────────────────────────────────────


def get_rank(dp: int) -> tuple[str, str, int]:
    current = RANKS[0]
    for rank in RANKS:
        if dp >= rank[2]:
            current = rank
    return current


def get_next_rank(dp: int) -> tuple[str, str, int] | None:
    for rank in RANKS:
        if dp < rank[2]:
            return rank
    return None


def rank_progress_bar(dp: int) -> str:
    current = get_rank(dp)
    nxt = get_next_rank(dp)
    if not nxt:
        return "[bold gold1]GRAND MASTER — MAX RANK[/]"
    earned = dp - current[2]
    needed = nxt[2] - current[2]
    pct = min(earned / needed, 1.0)
    filled = int(pct * 20)
    bar = "█" * filled + "░" * (20 - filled)
    return f"[cyan]{bar}[/] {int(pct * 100)}%  ({dp}/{nxt[2]} DP → {nxt[1]} {nxt[0]})"


# ── Streak ────────────────────────────────────────────────────────────────────


def record_activity(state: DojoState) -> int:
    """Update streak only when a task is completed."""
    today = str(date.today())
    if state.last_active_date == today:
        return state.streak
    yesterday = str(date.today() - timedelta(days=1))
    if state.last_active_date == yesterday:
        state.streak += 1
    else:
        state.streak = 1
    state.last_active_date = today
    return state.streak


def current_streak(state: DojoState) -> int:
    """Streak shown in the UI; drops to 0 if the last active day was missed."""
    today = str(date.today())
    yesterday = str(date.today() - timedelta(days=1))
    if state.last_active_date in {today, yesterday}:
        return state.streak
    return 0


def streak_multiplier(streak: int) -> float:
    if streak >= 30:
        return 3.0
    if streak >= 14:
        return 2.0
    if streak >= 7:
        return 1.5
    if streak >= 3:
        return 1.25
    return 1.0


# ── Achievements ──────────────────────────────────────────────────────────────


def check_achievements(state: DojoState) -> list[str]:
    new_badges = []
    stats = {
        "total_completed": state.total_completed,
        "critical_completed": state.critical_completed,
        "streak": state.streak,
        "total_dp": state.total_dp,
        "session_completed": state.session_completed,
    }
    for key, ach in ACHIEVEMENTS.items():
        if key not in state.achievements and ach["condition"](stats):
            state.achievements.append(key)
            new_badges.append(key)
    return new_badges


# ── AI Sensei ─────────────────────────────────────────────────────────────────


def sensei_hint(task_title: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return random.choice(KI_PHRASES)
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=80,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"You are a wise kung-fu sensei. Give one short motivational line "
                        f"(max 20 words) to a student who just completed this task: '{task_title}'. "
                        f"Use a martial arts metaphor."
                    ),
                }
            ],
        )
        return response.content[0].text.strip()
    except Exception:
        return random.choice(KI_PHRASES)


# ── Display ───────────────────────────────────────────────────────────────────


def print_header(state: DojoState):
    rank = get_rank(state.total_dp)
    streak = current_streak(state)
    streak_mult = streak_multiplier(streak)
    console.print()
    console.print(
        Panel(
            f"[bold white]{rank[1]}  {rank[0].upper()}[/]  ·  "
            f"[bold gold1]{state.total_dp} DP[/]  ·  "
            f"[bold cyan]🔥 {streak}-day streak[/]  ·  "
            f"[bold magenta]×{streak_mult:.2f} multiplier[/]\n"
            f"{rank_progress_bar(state.total_dp)}",
            title="[bold red]⛩  TO-DOJO  ⛩[/]",
            border_style="red",
            expand=False,
        )
    )


def print_tasks(state: DojoState):
    pending = [Task(**t) for t in state.tasks if not t.get("completed_at")]
    if not pending:
        console.print("[dim]  No pending tasks — the dojo awaits your first scroll.[/]")
        return

    table = Table(
        title="📜 Pending Tasks", box=box.ROUNDED, show_lines=True, border_style="red"
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Task", style="bold white", min_width=28)
    table.add_column("Priority", justify="center", width=12)
    table.add_column("DP", justify="center", width=6)
    table.add_column("Due", justify="center", width=12)
    table.add_column("Tags", width=18)

    for t in sorted(
        pending, key=lambda x: PRIORITY_ORDER.index(x.priority) if x.priority in PRIORITY_ORDER else 99
    ):
        cfg = PRIORITY_CONFIG.get(t.priority, PRIORITY_CONFIG["normal"])
        due_str = t.due_date or "—"
        due_col = "red" if (t.due_date and t.due_date < str(date.today())) else "white"
        base_dp = cfg["dp"]
        mult = streak_multiplier(current_streak(state))
        est_dp = int(base_dp * mult)
        tags = ", ".join(t.tags) if t.tags else "—"
        table.add_row(
            str(t.id),
            t.title,
            f"[{cfg['color']}]{cfg['symbol']} {cfg['label']}[/]",
            f"[bold green]+{est_dp}[/]",
            f"[{due_col}]{due_str}[/]",
            f"[dim]{tags}[/]",
        )
    console.print(table)


def print_stats(state: DojoState):
    table = Table(title="📊 Dojo Stats", box=box.SIMPLE_HEAVY, border_style="cyan")
    table.add_column("Stat", style="bold cyan")
    table.add_column("Value", style="white")

    rank = get_rank(state.total_dp)
    table.add_row("Rank", f"{rank[1]} {rank[0]}")
    table.add_row("Total DP", str(state.total_dp))
    table.add_row("Tasks Completed", str(state.total_completed))
    table.add_row("Critical Done", str(state.critical_completed))
    table.add_row("Current Streak", f"🔥 {current_streak(state)} days")
    table.add_row("Multiplier", f"×{streak_multiplier(current_streak(state)):.2f}")
    table.add_row(
        "Pending Tasks", str(sum(1 for t in state.tasks if not t.get("completed_at")))
    )
    table.add_row("Achievements", str(len(state.achievements)))
    console.print(table)

    if state.achievements:
        badges = "  ".join(
            f"{ACHIEVEMENTS[k]['icon']} {ACHIEVEMENTS[k]['name']}"
            for k in state.achievements
            if k in ACHIEVEMENTS
        )
        console.print(Panel(badges, title="🏅 Achievements", border_style="gold1"))


def print_menu():
    console.print()
    options = [
        ("[bold green]a[/]", "Add task"),
        ("[bold yellow]c[/]", "Complete task"),
        ("[bold cyan]l[/]", "List tasks"),
        ("[bold magenta]s[/]", "Stats"),
        ("[bold red]d[/]", "Delete task"),
        ("[bold white]h[/]", "History"),
        ("[bold blue]e[/]", "Edit task"),
        ("[bold dim]q[/]", "Quit"),
    ]
    parts = "  ".join(f"{k} {v}" for k, v in options)
    console.print(f"[dim]Actions:[/]  {parts}")


def add_task_record(
    state: DojoState,
    title: str,
    priority: str = "normal",
    due_date: str | None = None,
    notes: str = "",
    tags: list[str] | None = None,
) -> Task:
    priority = priority.lower()
    if priority not in PRIORITY_CONFIG:
        raise ValueError(f"Unknown priority {priority!r}")
    if due_date:
        try:
            datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Due date must be YYYY-MM-DD") from exc
    task = Task(
        id=state.next_id,
        title=title.strip(),
        priority=priority,
        due_date=due_date,
        notes=notes.strip(),
        tags=tags or [],
    )
    if not task.title:
        raise ValueError("Task title is required")
    state.tasks.append(asdict(task))
    state.next_id += 1
    return task


def complete_task_by_id(state: DojoState, tid: int) -> tuple[Task, int, bool, list[str]] | None:
    for t in state.tasks:
        if t["id"] == tid and not t.get("completed_at"):
            task = Task(**t)
            streak = record_activity(state)
            mult = streak_multiplier(streak)
            base_dp = PRIORITY_CONFIG.get(task.priority, PRIORITY_CONFIG["normal"])["dp"]
            earned = int(base_dp * mult)

            t["completed_at"] = datetime.now().isoformat()
            t["dp_earned"] = earned

            state.total_dp += earned
            state.total_completed += 1
            state.session_completed += 1
            if task.priority == "critical":
                state.critical_completed += 1

            state.history.append(
                {
                    "task_id": task.id,
                    "title": task.title,
                    "priority": task.priority,
                    "dp_earned": earned,
                    "completed_at": t["completed_at"],
                }
            )
            old_rank = get_rank(state.total_dp - earned)
            new_rank = get_rank(state.total_dp)
            promoted = old_rank[0] != new_rank[0]
            badges = check_achievements(state)
            return task, earned, promoted, badges
    return None


def add_task(state: DojoState):
    console.print("\n[bold red]— New Scroll —[/]")
    title = Prompt.ask("[bold white]Task title")
    if not title.strip():
        console.print("[dim]Cancelled.[/]")
        return

    priority = Prompt.ask(
        "Priority",
        choices=["critical", "high", "normal", "low"],
        default="normal",
    )
    due_raw = Prompt.ask("Due date [dim](YYYY-MM-DD or blank)[/]", default="")
    notes = Prompt.ask("Notes [dim](optional)[/]", default="")
    tags_raw = Prompt.ask("Tags [dim](comma-separated, optional)[/]", default="")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    try:
        task = add_task_record(
            state,
            title,
            priority=priority,
            due_date=due_raw.strip() or None,
            notes=notes,
            tags=tags,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return

    cfg = PRIORITY_CONFIG[task.priority]
    console.print(
        f"\n[bold green]✓ Scroll added:[/] {cfg['symbol']} [bold]{task.title}[/]  "
        f"[{cfg['color']}]({cfg['label']})[/]  ID #{task.id}"
    )
    save_state(state)


def complete_task(state: DojoState):
    pending = [t for t in state.tasks if not t.get("completed_at")]
    if not pending:
        console.print("[dim]No pending tasks.[/]")
        return

    print_tasks(state)
    tid_str = Prompt.ask("\n[bold yellow]Enter task ID to complete")
    try:
        tid = int(tid_str)
    except ValueError:
        console.print("[red]Invalid ID.[/]")
        return

    result = complete_task_by_id(state, tid)
    if not result:
        console.print("[red]Task not found or already completed.[/]")
        return

    task, earned, promoted, new_badges = result
    streak = current_streak(state)
    mult = streak_multiplier(streak)

    console.print()
    console.print(
        Panel(
            f"[bold green]TASK COMPLETE[/]  {PRIORITY_CONFIG[task.priority]['symbol']}\n\n"
            f"[bold white]{task.title}[/]\n\n"
            f"[bold gold1]+{earned} DP[/]  [dim](×{mult:.2f} streak bonus)[/]  →  "
            f"[bold cyan]{state.total_dp} DP total[/]",
            border_style="green",
            expand=False,
        )
    )

    if promoted:
        new_rank = get_rank(state.total_dp)
        console.print(
            Panel(
                f"[bold yellow]RANK UP!  {new_rank[1]}  {new_rank[0].upper()}[/]\n"
                f"[dim]You have proven your worth, warrior.[/]",
                border_style="yellow",
                expand=False,
            )
        )

    for key in new_badges:
        ach = ACHIEVEMENTS[key]
        console.print(
            Panel(
                f"[bold magenta]ACHIEVEMENT UNLOCKED[/]  {ach['icon']}  [bold]{ach['name']}[/]\n"
                f"[dim]{ach['desc']}[/]",
                border_style="magenta",
                expand=False,
            )
        )

    hint = sensei_hint(task.title)
    console.print(f'\n[italic dim cyan]🧘 Sensei says: "{hint}"[/]\n')
    save_state(state)


def delete_task(state: DojoState):
    print_tasks(state)
    tid_str = Prompt.ask("\n[bold red]Enter task ID to delete")
    try:
        tid = int(tid_str)
    except ValueError:
        console.print("[red]Invalid ID.[/]")
        return
    before = len(state.tasks)
    state.tasks = [
        t for t in state.tasks if not (t["id"] == tid and not t.get("completed_at"))
    ]
    if len(state.tasks) < before:
        console.print(f"[dim]Task #{tid} removed.[/]")
        save_state(state)
    else:
        console.print("[red]Task not found or already completed.[/]")


def edit_task(state: DojoState):
    print_tasks(state)
    tid_str = Prompt.ask("\n[bold cyan]Enter task ID to edit")
    try:
        tid = int(tid_str)
    except ValueError:
        console.print("[red]Invalid ID.[/]")
        return
    for t in state.tasks:
        if t["id"] == tid and not t.get("completed_at"):
            console.print(f"[dim]Current title:[/] {t['title']}")
            new_title = Prompt.ask("New title [dim](blank = keep)[/]", default="")
            if new_title.strip():
                t["title"] = new_title.strip()
            new_priority = Prompt.ask(
                "New priority [dim](blank = keep)[/]",
                choices=["critical", "high", "normal", "low", ""],
                default="",
            )
            if new_priority:
                t["priority"] = new_priority
            new_due = Prompt.ask("New due date [dim](blank = keep)[/]", default="")
            if new_due.strip():
                t["due_date"] = new_due.strip()
            save_state(state)
            console.print("[green]Task updated.[/]")
            return
    console.print("[red]Task not found.[/]")


def show_history(state: DojoState):
    if not state.history:
        console.print("[dim]No completed tasks yet.[/]")
        return
    table = Table(title="📜 Completed Scrolls", box=box.ROUNDED, border_style="dim")
    table.add_column("Title", style="white", min_width=28)
    table.add_column("Priority", justify="center")
    table.add_column("DP", justify="center", style="bold gold1")
    table.add_column("Completed", justify="center", style="dim")
    for h in reversed(state.history[-30:]):
        cfg = PRIORITY_CONFIG.get(h["priority"], PRIORITY_CONFIG["normal"])
        completed = h["completed_at"][:10] if h.get("completed_at") else "—"
        table.add_row(
            h["title"],
            f"[{cfg['color']}]{cfg['symbol']} {cfg['label']}[/]",
            f"+{h['dp_earned']}",
            completed,
        )
    console.print(table)


# ── Main Loop ─────────────────────────────────────────────────────────────────


def interactive_loop(state: DojoState) -> None:
    console.clear()
    console.print(
        Panel(
            "[bold red]⛩  WELCOME TO THE TO-DOJO  ⛩[/]\n"
            "[dim]Where productivity meets the way of the warrior.[/]",
            border_style="red",
            expand=False,
        )
    )

    while True:
        print_header(state)
        print_menu()

        choice = Prompt.ask("\n[bold red]Command").strip().lower()

        if choice == "a":
            add_task(state)
        elif choice == "c":
            complete_task(state)
        elif choice == "l":
            print_tasks(state)
        elif choice == "s":
            print_stats(state)
        elif choice == "d":
            delete_task(state)
        elif choice == "h":
            show_history(state)
        elif choice == "e":
            edit_task(state)
        elif choice in ("q", "quit", "exit"):
            save_state(state)
            console.print(
                "\n[bold red]⛩  The dojo awaits your return, warrior.  ⛩[/]\n"
            )
            break
        else:
            console.print("[dim]Unknown command.[/]")


def main(argv: list[str] | None = None) -> int:
    global DATA_FILE
    parser = argparse.ArgumentParser(description="To-Dojo — gamified task manager")
    parser.add_argument(
        "--data-file",
        default=os.getenv("DOJO_DATA_FILE", "dojo_data.json"),
        help="Path to JSON state file",
    )
    sub = parser.add_subparsers(dest="command")

    add_p = sub.add_parser("add", help="Add a task")
    add_p.add_argument("title")
    add_p.add_argument("--priority", choices=PRIORITY_ORDER, default="normal")
    add_p.add_argument("--due", dest="due_date", default="")
    add_p.add_argument("--notes", default="")
    add_p.add_argument("--tags", default="")

    complete_p = sub.add_parser("complete", help="Complete a task by ID")
    complete_p.add_argument("task_id", type=int)

    sub.add_parser("list", help="List pending tasks")
    sub.add_parser("stats", help="Show dojo stats")

    delete_p = sub.add_parser("delete", help="Delete a pending task by ID")
    delete_p.add_argument("task_id", type=int)

    args = parser.parse_args(argv)
    DATA_FILE = Path(args.data_file)
    state = load_state(DATA_FILE)

    if args.command is None:
        interactive_loop(state)
        return 0

    if args.command == "add":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        try:
            task = add_task_record(
                state,
                args.title,
                priority=args.priority,
                due_date=args.due_date.strip() or None,
                notes=args.notes,
                tags=tags,
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            return 1
        save_state(state, DATA_FILE)
        console.print(f"[green]Added[/] #{task.id} {task.title} ({task.priority})")
        return 0

    if args.command == "complete":
        result = complete_task_by_id(state, args.task_id)
        if not result:
            console.print("[red]Task not found or already completed.[/]")
            return 1
        task, earned, promoted, _badges = result
        save_state(state, DATA_FILE)
        extra = " — RANK UP!" if promoted else ""
        console.print(f"[green]Completed[/] #{task.id} {task.title} (+{earned} DP){extra}")
        return 0

    if args.command == "list":
        print_header(state)
        print_tasks(state)
        return 0

    if args.command == "stats":
        print_header(state)
        print_stats(state)
        return 0

    if args.command == "delete":
        before = len(state.tasks)
        state.tasks = [
            t
            for t in state.tasks
            if not (t["id"] == args.task_id and not t.get("completed_at"))
        ]
        if len(state.tasks) == before:
            console.print("[red]Task not found or already completed.[/]")
            return 1
        save_state(state, DATA_FILE)
        console.print(f"[dim]Task #{args.task_id} removed.[/]")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
