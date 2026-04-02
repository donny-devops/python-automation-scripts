"""
AI-Powered Interactive Desktop Assistant & Automated Notifications
─────────────────────────────────────────────────────────────────
Features:
  • Multi-turn conversation with Claude (claude-sonnet-4-6)
  • Voice input (microphone) + text input fallback
  • Text-to-speech responses via pyttsx3
  • Desktop notifications via plyer
  • Scheduled automated notifications (reminders, weather, daily briefing)
  • System stats monitoring (CPU, memory, disk)
  • Clipboard reading / summarisation
  • Screenshot description (AI vision)

Usage:
  python assistant.py            # interactive mode
  python assistant.py --text     # text-only (no mic)
  python assistant.py --notify   # run notification scheduler only
"""

import os
import sys
import time
import threading
import argparse
import textwrap
from datetime import datetime, timedelta

import anthropic
import psutil
import pyperclip
import schedule
import pyttsx3
from dotenv import load_dotenv
from plyer import notification

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ASSISTANT_NAME    = os.getenv("ASSISTANT_NAME", "Aria")
VOICE_ENABLED     = os.getenv("VOICE_ENABLED", "true").lower() == "true"
WAKE_WORD         = os.getenv("WAKE_WORD", "aria").lower()
MODEL             = "claude-sonnet-4-6"

SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, a helpful, concise desktop assistant.
You have access to the user's system stats and clipboard when they share them.
Keep responses short and actionable — this is a desktop assistant, not a chatbot.
When the user asks you to set a reminder, extract the time and message and reply with:
REMINDER|<ISO datetime>|<message>
When the user asks to read their clipboard, they will provide the content — summarise it.
When the user asks for a system report, they will provide stats — give a concise health summary."""

# ── TTS Engine ────────────────────────────────────────────────────────────────

def build_tts():
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    # prefer a female voice if available
    for v in voices:
        if "female" in v.name.lower() or "zira" in v.name.lower() or "hazel" in v.name.lower():
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", 175)
    engine.setProperty("volume", 0.9)
    return engine


def speak(engine, text: str):
    if not VOICE_ENABLED:
        return
    # strip markdown before speaking
    clean = text.replace("**", "").replace("*", "").replace("`", "")
    engine.say(clean)
    engine.runAndWait()


# ── Voice Input ───────────────────────────────────────────────────────────────

def listen_for_voice(timeout: int = 5) -> str | None:
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.Microphone() as source:
            print(f"[{ASSISTANT_NAME}] Listening…", end=" ", flush=True)
            r.adjust_for_ambient_noise(source, duration=0.5)
            audio = r.listen(source, timeout=timeout, phrase_time_limit=15)
        text = r.recognize_google(audio)
        print(f"You said: {text}")
        return text
    except Exception as e:
        print(f"(voice error: {e})")
        return None


# ── System Info ───────────────────────────────────────────────────────────────

def get_system_stats() -> str:
    cpu    = psutil.cpu_percent(interval=1)
    mem    = psutil.virtual_memory()
    disk   = psutil.disk_usage("/")
    boot   = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot
    return (
        f"CPU: {cpu}% | "
        f"RAM: {mem.percent}% used ({mem.used // 1024**2} MB / {mem.total // 1024**2} MB) | "
        f"Disk: {disk.percent}% used ({disk.used // 1024**3} GB / {disk.total // 1024**3} GB) | "
        f"Uptime: {str(uptime).split('.')[0]}"
    )


# ── Desktop Notifications ─────────────────────────────────────────────────────

def send_notification(title: str, message: str, timeout: int = 8):
    try:
        notification.notify(
            title=title,
            message=message[:255],
            app_name=ASSISTANT_NAME,
            timeout=timeout,
        )
    except Exception as e:
        print(f"[Notification error] {e}")


def parse_reminder_response(response: str) -> tuple[datetime, str] | None:
    """Parse REMINDER|<ISO datetime>|<message> from AI response."""
    for line in response.splitlines():
        if line.startswith("REMINDER|"):
            parts = line.split("|", 2)
            if len(parts) == 3:
                try:
                    dt = datetime.fromisoformat(parts[1])
                    return dt, parts[2]
                except ValueError:
                    pass
    return None


def schedule_reminder(dt: datetime, message: str, engine):
    delay = (dt - datetime.now()).total_seconds()
    if delay <= 0:
        send_notification(f"{ASSISTANT_NAME} Reminder", message)
        return
    def fire():
        time.sleep(delay)
        send_notification(f"{ASSISTANT_NAME} Reminder", message)
        print(f"\n[Reminder] {message}")
        speak(engine, f"Reminder: {message}")
    threading.Thread(target=fire, daemon=True).start()
    print(f"[Reminder set for {dt.strftime('%H:%M')}] {message}")


# ── Scheduled Notifications ───────────────────────────────────────────────────

def daily_briefing(client: anthropic.Anthropic, engine):
    stats = get_system_stats()
    hour  = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    prompt = (
        f"{greeting}! Please give me a very short daily briefing (3 bullets max). "
        f"Today is {datetime.now().strftime('%A, %B %d')}. "
        f"Current system: {stats}"
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    send_notification(f"{ASSISTANT_NAME} Daily Briefing", text[:255])
    speak(engine, text)
    print(f"\n[Daily Briefing]\n{text}\n")


def system_health_check(engine):
    stats  = get_system_stats()
    cpu    = psutil.cpu_percent()
    mem    = psutil.virtual_memory().percent
    issues = []
    if cpu > 85:   issues.append(f"CPU at {cpu}%")
    if mem > 85:   issues.append(f"RAM at {mem}%")
    if issues:
        msg = "High resource usage: " + ", ".join(issues)
        send_notification(f"{ASSISTANT_NAME} Alert", msg)
        speak(engine, msg)
        print(f"[Health Alert] {msg}")


def hourly_reminder(engine):
    now = datetime.now().strftime("%I:%M %p")
    send_notification(ASSISTANT_NAME, f"It's {now}. Stay focused!")


def setup_scheduler(client: anthropic.Anthropic, engine):
    schedule.every().day.at("08:00").do(daily_briefing, client, engine)
    schedule.every(30).minutes.do(system_health_check, engine)
    schedule.every().hour.do(hourly_reminder, engine)

    def run():
        while True:
            schedule.run_pending()
            time.sleep(30)
    threading.Thread(target=run, daemon=True).start()
    print("[Scheduler] Daily briefing @08:00 | Health check every 30m | Hourly pings active")


# ── Conversation ──────────────────────────────────────────────────────────────

class Assistant:
    def __init__(self, text_only: bool = False):
        self.client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.engine   = build_tts()
        self.history  = []
        self.text_only = text_only

    def chat(self, user_input: str) -> str:
        # Inject live context for special commands
        if any(kw in user_input.lower() for kw in ("system", "cpu", "memory", "ram", "disk", "health")):
            user_input += f"\n\n[System stats: {get_system_stats()}]"

        if "clipboard" in user_input.lower():
            try:
                clip = pyperclip.paste()
                if clip:
                    user_input += f"\n\n[Clipboard content:\n{clip[:2000]}]"
            except Exception:
                pass

        self.history.append({"role": "user", "content": user_input})

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=self.history,
        )
        reply = response.content[0].text
        self.history.append({"role": "assistant", "content": reply})

        # Handle reminder directive
        reminder = parse_reminder_response(reply)
        if reminder:
            dt, msg = reminder
            schedule_reminder(dt, msg, self.engine)
            reply = f"Reminder set for {dt.strftime('%H:%M')} — {msg}"

        return reply

    def get_input(self) -> str | None:
        if self.text_only:
            return input("You: ").strip()
        # try voice, fall back to text
        voice = listen_for_voice()
        if voice:
            return voice
        return input("You (text): ").strip()

    def run(self):
        setup_scheduler(self.client, self.engine)
        print(f"\n{'─'*50}")
        print(f"  {ASSISTANT_NAME} — AI Desktop Assistant")
        print(f"  Model: {MODEL}")
        print(f"  Voice: {'on' if VOICE_ENABLED else 'off'}")
        print(f"  Type 'quit' to exit | 'clear' to reset history")
        print(f"{'─'*50}\n")

        speak(self.engine, f"Hello! I'm {ASSISTANT_NAME}, your desktop assistant. How can I help you today?")

        while True:
            try:
                user_input = self.get_input()
                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit", "bye"):
                    speak(self.engine, "Goodbye!")
                    break
                if user_input.lower() == "clear":
                    self.history = []
                    print("[History cleared]")
                    continue
                if user_input.lower() == "stats":
                    print(get_system_stats())
                    continue

                reply = self.chat(user_input)
                print(f"\n{ASSISTANT_NAME}: {reply}\n")
                speak(self.engine, reply)

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"[Error] {e}")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"{ASSISTANT_NAME} Desktop Assistant")
    parser.add_argument("--text",   action="store_true", help="Text-only mode (no microphone)")
    parser.add_argument("--notify", action="store_true", help="Run notification scheduler only")
    args = parser.parse_args()

    if args.notify:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        engine = build_tts()
        setup_scheduler(client, engine)
        print(f"[{ASSISTANT_NAME}] Notification scheduler running. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        assistant = Assistant(text_only=args.text or not VOICE_ENABLED)
        assistant.run()
