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
"""

import os
import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich import box
from dotenv import load_dotenv

load_dotenv()

console = Console()
DATA_FILE = Path("dojo_data.json")

# ── Ranks ─────────────────────────────────────────────────────────────────────

RANKS = [
    ("White Belt",  "⬜",    0),
    ("Yellow Belt", "🟨",  100),
    ("Orange Belt", "🟧",  250),
    ("Green Belt",  "🟩",  500),
    ("Blue Belt",   "🟦",  900),
    ("Purple Belt", "🟪", 1400),
    ("Brown Belt",  "🟫", 2100),
    ("Red Belt",    "🟥", 3000),
    ("Black Belt",  "⬛", 4200),
    ("Grand Master","🏆", 6000),
]

PRIORITY_CONFIG = {
    "critical": {"dp": 40, "label": "CRITICAL", "color": "bold red",    "symbol": "🔴"},
    "high":     {"dp": 20, "label": "HIGH",     "color": "bold yellow", "symbol": "🟡"},
    "normal":   {"dp": 10, "label": "NORMAL",   "color": "bold green",  "symbol": "🟢"},
    "low":      {"dp":  5, "label": "LOW",      "color": "bold blue",   "symbol": "🔵"},
}

ACHIEVEMENTS = {
    "first_blood":  {"name": "First Blood",    "icon": "🩸", "desc": "Complete your first task",           "condition": lambda s: s["total_completed"] >= 1},
    "on_fire":      {"name": "On Fire",         "icon": "🔥", "desc": "Complete 5 tasks in one session",   "condition": lambda s: s["session_completed"] >= 5},
    "iron_will":    {"name": "Iron Will",       "icon": "⚙️", "desc": "Maintain a 7-day streak",           "condition": lambda s: s["streak"] >= 7},
    "dragon":       {"name": "Dragon",          "icon": "🐉", "desc": "Reach Black Belt",                  "condition": lambda s: s["total_dp"] >= 4200},
    "centurion":    {"name": "Centurion",       "icon": "💯", "desc": "Complete 100 tasks",                "condition": lambda s: s["total_completed"] >= 100},
    "perfectionist":{"name": "Perfectionist",  "icon": "✨", "desc": "Complete 10 critical tasks",        "condition": lambda s: s["critical_completed"] >= 10},
    "no_days_off":  {"name": "No Days Off",    "icon": "📅", "desc": "Maintain a 30-day streak",          "condition": lambda s: s["streak"] >= 30},
    "sensei":       {"name": "Sensei",          "icon": "🎓", "desc": "Reach Grand Master rank",           "condition": lambda s: s["total_dp"] >= 6000},
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
    id:          int
    title:       str
    priority:    str         = "normal"
    due_date:    str | None  = None
    created_at:  str         = field(default_factory=lambda: datetime.now().isoformat())
    completed_at:str | None  = None
    dp_earned:   int         = 0
    notes:       str         = ""
    tags:        list[str]   = field(default_factory=list)


@dataclass
class DojoState:
    tasks:               list[dict]      = field(default_factory=list)
    total_dp:            int             = 0
    total_completed:     int             = 0
    critical_completed:  int             = 0
    streak:              int             = 0
    last_active_date:    str | None      = None
    achievements:        list[str]       = field(default_factory=list)
    history:             list[dict]      = field(default_factory=list)
    session_completed:   int             = 0
    next_id:             int             = 1


# ── Persistence ───────────────────────────────────────────────────────────────

def load_state() -> DojoState:
    if DATA_FILE.exists():
        raw = json.loads(DATA_FILE.read_text())
        return DojoState(**raw)
    return DojoState()


def save_state(state: DojoState):
    DATA_FILE.write_text(json.dumps(asdict(state), indent=2))


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
    nxt     = get_next_rank(dp)
    if not nxt:
        return "[bold gold1]GRAND MASTER — MAX RANK[/]"
    earned  = dp - current[2]
    needed  = nxt[2] - current[2]
    pct     = min(earned / needed, 1.0)
    filled  = int(pct * 20)
    bar     = "█" * filled + "░" * (20 - filled)
    return f"[cyan]{bar}[/] {int(pct*100)}%  ({dp}/{nxt[2]} DP → {nxt[1]} {nxt[0]})"


# ── Streak ────────────────────────────────────────────────────────────────────

def update_streak(state: DojoState) -> int:
    today = str(date.today())
    if state.last_active_date == today:
        return state.streak
    yesterday = str(date.today() - timedelta(days=1))
    if state.last_active_date == yesterday:
        state.streak += 1
    elif state.last_active_date != today:
        state.streak = 1
    state.last_active_date = today
    return state.streak


def streak_multiplier(streak: int) -> float:
    if streak >= 30: return 3.0
    if streak >= 14: return 2.0
    if streak >=  7: return 1.5
    if streak >=  3: return 1.25
    return 1.0


# ── Achievements ──────────────────────────────────────────────────────────────

def check_achievements(state: DojoState) -> list[str]:
    new_badges = []
    stats = {
        "total_completed":    state.total_completed,
        "critical_completed": state.critical_completed,
        "streak":             state.streak,
        "total_dp":           state.total_dp,
        "session_completed":  state.session_completed,
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
            messages=[{
                "role": "user",
                "content": (
                    f"You are a wise kung-fu sensei. Give one short motivational line "
                    f"(max 20 words) to a student who just completed this task: '{task_title}'. "
                    f"Use a martial arts metaphor."
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception:
        return random.choice(KI_PHRASES)


# ── Display ───────────────────────────────────────────────────────────────────

def print_header(state: DojoState):
    rank = get_rank(state.total_dp)
    streak_mult = streak_multiplier(state.streak)
    console.print()
    console.print(Panel(
        f"[bold white]{rank[1]}  {rank[0].upper()}[/]  ·  "
        f"[bold gold1]{state.total_dp} DP[/]  ·  "
        f"[bold cyan]🔥 {state.streak}-day streak[/]  ·  "
        f"[bold magenta]×{streak_mult:.2f} multiplier[/]\n"
        f"{rank_progress_bar(state.total_dp)}",
        title="[bold red]⛩  TO-DOJO  ⛩[/]",
        border_style="red",
        expand=False,
    ))


def print_tasks(state: DojoState):
    pending = [Task(**t) for t in state.tasks if not t.get("completed_at")]
    if not pending:
        console.print("[dim]  No pending tasks — the dojo awaits your first scroll.[/]")
        return

    table = Table(title="📜 Pending Tasks", box=box.ROUNDED, show_lines=True, border_style="red")
    table.add_column("#",        style="dim", width=4)
    table.add_column("Task",     style="bold white", min_width=28)
    table.add_column("Priority", justify="center", width=12)
    table.add_column("DP",       justify="center", width=6)
    table.add_column("Due",      justify="center", width=12)
    table.add_column("Tags",     width=18)

    for t in sorted(pending, key=lambda x: ["critical","high","normal","low"].index(x.priority)):
        cfg     = PRIORITY_CONFIG[t.priority]
        due_str = t.due_date or "—"
        due_col = "red" if (t.due_date and t.due_date < str(date.today())) else "white"
        base_dp = cfg["dp"]
        mult    = streak_multiplier(state.streak)
        est_dp  = int(base_dp * mult)
        tags    = ", ".join(t.tags) if t.tags else "—"
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
    table.add_row("Rank",             f"{rank[1]} {rank[0]}")
    table.add_row("Total DP",         str(state.total_dp))
    table.add_row("Tasks Completed",  str(state.total_completed))
    table.add_row("Critical Done",    str(state.critical_completed))
    table.add_row("Current Streak",   f"🔥 {state.streak} days")
    table.add_row("Multiplier",       f"×{streak_multiplier(state.streak):.2f}")
    table.add_row("Pending Tasks",    str(sum(1 for t in state.tasks if not t.get("completed_at"))))
    table.add_row("Achievements",     str(len(state.achievements)))
    console.print(table)

    if state.achievements:
        badges = "  ".join(
            f"{ACHIEVEMENTS[k]['icon']} {ACHIEVEMENTS[k]['name']}"
            for k in state.achievements if k in ACHIEVEMENTS
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


# ── Actions ───────────────────────────────────────────────────────────────────

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
    notes   = Prompt.ask("Notes [dim](optional)[/]", default="")
    tags_raw= Prompt.ask("Tags [dim](comma-separated, optional)[/]", default="")
    tags    = [t.strip() for t in tags_raw.split(",") if t.strip()]

    task = Task(
        id=state.next_id,
        title=title.strip(),
        priority=priority,
        due_date=due_raw.strip() or None,
        notes=notes.strip(),
        tags=tags,
    )
    state.tasks.append(asdict(task))
    state.next_id += 1

    cfg = PRIORITY_CONFIG[priority]
    console.print(f"\n[bold green]✓ Scroll added:[/] {cfg['symbol']} [bold]{task.title}[/]  "
                  f"[{cfg['color']}]({cfg['label']})[/]  ID #{task.id}")
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

    for t in state.tasks:
        if t["id"] == tid and not t.get("completed_at"):
            task = Task(**t)

            # Calculate DP
            streak  = update_streak(state)
            mult    = streak_multiplier(streak)
            base_dp = PRIORITY_CONFIG[task.priority]["dp"]
            earned  = int(base_dp * mult)

            t["completed_at"] = datetime.now().isoformat()
            t["dp_earned"]    = earned

            state.total_dp          += earned
            state.total_completed   += 1
            state.session_completed += 1
            if task.priority == "critical":
                state.critical_completed += 1

            state.history.append({
                "task_id":     task.id,
                "title":       task.title,
                "priority":    task.priority,
                "dp_earned":   earned,
                "completed_at":t["completed_at"],
            })

            # Rank-up check
            old_rank = get_rank(state.total_dp - earned)
            new_rank = get_rank(state.total_dp)
            promoted = old_rank[0] != new_rank[0]

            # Print completion
            console.print()
            console.print(Panel(
                f"[bold green]TASK COMPLETE[/]  {PRIORITY_CONFIG[task.priority]['symbol']}\n\n"
                f"[bold white]{task.title}[/]\n\n"
                f"[bold gold1]+{earned} DP[/]  [dim](×{mult:.2f} streak bonus)[/]  →  "
                f"[bold cyan]{state.total_dp} DP total[/]",
                border_style="green",
                expand=False,
            ))

            if promoted:
                console.print(Panel(
                    f"[bold yellow]RANK UP!  {new_rank[1]}  {new_rank[0].upper()}[/]\n"
                    f"[dim]You have proven your worth, warrior.[/]",
                    border_style="yellow",
                    expand=False,
                ))

            # Check achievements
            new_badges = check_achievements(state)
            for key in new_badges:
                ach = ACHIEVEMENTS[key]
                console.print(Panel(
                    f"[bold magenta]ACHIEVEMENT UNLOCKED[/]  {ach['icon']}  [bold]{ach['name']}[/]\n"
                    f"[dim]{ach['desc']}[/]",
                    border_style="magenta",
                    expand=False,
                ))

            # Sensei wisdom
            hint = sensei_hint(task.title)
            console.print(f"\n[italic dim cyan]🧘 Sensei says: \"{hint}\"[/]\n")

            save_state(state)
            return

    console.print("[red]Task not found or already completed.[/]")


def delete_task(state: DojoState):
    print_tasks(state)
    tid_str = Prompt.ask("\n[bold red]Enter task ID to delete")
    try:
        tid = int(tid_str)
    except ValueError:
        console.print("[red]Invalid ID.[/]")
        return
    before = len(state.tasks)
    state.tasks = [t for t in state.tasks if not (t["id"] == tid and not t.get("completed_at"))]
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

def main():
    state = load_state()
    update_streak(state)

    console.clear()
    console.print(Panel(
        "[bold red]⛩  WELCOME TO THE TO-DOJO  ⛩[/]\n"
        "[dim]Where productivity meets the way of the warrior.[/]",
        border_style="red",
        expand=False,
    ))

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
            console.print("\n[bold red]⛩  The dojo awaits your return, warrior.  ⛩[/]\n")
            break
        else:
            console.print("[dim]Unknown command.[/]")


if __name__ == "__main__":
    main()
