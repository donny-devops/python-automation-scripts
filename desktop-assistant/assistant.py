"""
AI-Powered Interactive Desktop Assistant & Automated Notifications
─────────────────────────────────────────────────────────────────
Features:
  • Multi-turn conversation with Claude (claude-sonnet-4-6)
  • Voice input (microphone) + text input fallback
  • Text-to-speech responses via pyttsx3
  • Desktop notifications via plyer
  • Scheduled automated notifications (reminders, daily briefing)
  • System stats monitoring (CPU, memory, disk)
  • Clipboard reading / summarisation with secret redaction

Usage:
  python assistant.py            # interactive mode
  python assistant.py --text     # text-only (no mic)
  python assistant.py --notify   # run notification scheduler only
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from datetime import datetime

from dotenv import load_dotenv

from reminders import clip_text, parse_reminder_response, redact_secrets, strip_wake_word

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────

ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Aria")
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").lower() == "true"
WAKE_WORD = os.getenv("WAKE_WORD", "aria").lower()
MODEL = os.getenv("ASSISTANT_MODEL", "claude-sonnet-4-6")
HISTORY_LIMIT = max(4, int(os.getenv("ASSISTANT_HISTORY_LIMIT", "20")))
CLIPBOARD_LIMIT = max(200, int(os.getenv("ASSISTANT_CLIPBOARD_LIMIT", "2000")))

SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, a helpful, concise desktop assistant.
You have access to the user's system stats and clipboard when they share them.
Keep responses short and actionable — this is a desktop assistant, not a chatbot.
When the user asks you to set a reminder, extract the time and message and reply with:
REMINDER|<ISO datetime>|<message>
When the user asks to read their clipboard, they will provide the content — summarise it.
When the user asks for a system report, they will provide stats — give a concise health summary.
Never request or repeat secrets, API keys, or passwords."""


def get_api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is required. Copy desktop-assistant/.env.example to .env and set the key."
        )
    return key


# ── TTS Engine ────────────────────────────────────────────────────────────────


def build_tts():
    if not VOICE_ENABLED:
        return None
    try:
        import pyttsx3

        engine = pyttsx3.init()
        voices = engine.getProperty("voices") or []
        for v in voices:
            name = getattr(v, "name", "") or ""
            if any(token in name.lower() for token in ("female", "zira", "hazel")):
                engine.setProperty("voice", v.id)
                break
        engine.setProperty("rate", 175)
        engine.setProperty("volume", 0.9)
        return engine
    except Exception as exc:
        print(f"[TTS unavailable] {exc}")
        return None


def speak(engine, text: str) -> None:
    if not engine or not VOICE_ENABLED or not text:
        return
    clean = text.replace("**", "").replace("*", "").replace("`", "")
    try:
        engine.say(clean)
        engine.runAndWait()
    except Exception as exc:
        print(f"[TTS error] {exc}")


# ── Voice Input ───────────────────────────────────────────────────────────────


def listen_for_voice(timeout: int = 5) -> str | None:
    try:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        with sr.Microphone() as source:
            print(f"[{ASSISTANT_NAME}] Listening…", end=" ", flush=True)
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=15)
        text = recognizer.recognize_google(audio)
        print(f"You said: {text}")
        return text
    except Exception as exc:
        print(f"(voice error: {exc})")
        return None


# ── System Info ───────────────────────────────────────────────────────────────


def get_system_stats() -> str:
    import psutil

    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot
    return (
        f"CPU: {cpu}% | "
        f"RAM: {mem.percent}% used ({mem.used // 1024**2} MB / {mem.total // 1024**2} MB) | "
        f"Disk: {disk.percent}% used ({disk.used // 1024**3} GB / {disk.total // 1024**3} GB) | "
        f"Uptime: {str(uptime).split('.')[0]}"
    )


# ── Desktop Notifications ─────────────────────────────────────────────────────


def send_notification(title: str, message: str, timeout: int = 8) -> None:
    try:
        from plyer import notification

        notification.notify(
            title=title,
            message=message[:255],
            app_name=ASSISTANT_NAME,
            timeout=timeout,
        )
    except Exception as exc:
        print(f"[Notification error] {exc}")


def schedule_reminder(dt: datetime, message: str, engine) -> None:
    delay = (dt - datetime.now()).total_seconds()
    if delay <= 0:
        send_notification(f"{ASSISTANT_NAME} Reminder", message)
        return

    def fire():
        time.sleep(delay)
        send_notification(f"{ASSISTANT_NAME} Reminder", message)
        print(f"\n[Reminder] {message}")
        speak(engine, f"Reminder: {message}")

    threading.Thread(target=fire, daemon=True, name="reminder").start()
    print(f"[Reminder set for {dt.strftime('%H:%M')}] {message}")


# ── Scheduled Notifications ───────────────────────────────────────────────────


def daily_briefing(client, engine) -> None:
    hour = datetime.now().hour
    greeting = (
        "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    )
    weather_note = ""
    city = os.getenv("CITY", "").strip()
    weather_key = os.getenv("WEATHER_API_KEY", "").strip()
    if city and weather_key:
        try:
            from weather import fetch_weather_summary

            weather_note = f" Current weather: {fetch_weather_summary(city, weather_key)}."
        except Exception as exc:
            print(f"[Weather skipped] {exc}")
    prompt = (
        f"{greeting}! Please give me a very short daily briefing (3 bullets max). "
        f"Today is {datetime.now().strftime('%A, %B %d')}.{weather_note} "
        "Do not invent news headlines; keep it motivational and practical."
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


def system_health_check(engine) -> None:
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory().percent
    except Exception as exc:
        print(f"[Health check skipped] {exc}")
        return
    issues = []
    if cpu > 85:
        issues.append(f"CPU at {cpu}%")
    if mem > 85:
        issues.append(f"RAM at {mem}%")
    if issues:
        msg = "High resource usage: " + ", ".join(issues)
        send_notification(f"{ASSISTANT_NAME} Alert", msg)
        speak(engine, msg)
        print(f"[Health Alert] {msg}")


def hourly_reminder(engine) -> None:
    now = datetime.now().strftime("%I:%M %p")
    send_notification(ASSISTANT_NAME, f"It's {now}. Stay focused!")


def setup_scheduler(client, engine) -> None:
    import schedule

    schedule.every().day.at("08:00").do(daily_briefing, client, engine)
    schedule.every(30).minutes.do(system_health_check, engine)
    schedule.every().hour.do(hourly_reminder, engine)

    def run():
        while True:
            schedule.run_pending()
            time.sleep(30)

    threading.Thread(target=run, daemon=True, name="scheduler").start()
    print(
        "[Scheduler] Daily briefing @08:00 | Health check every 30m | Hourly pings active"
    )


def _build_client():
    import anthropic

    return anthropic.Anthropic(api_key=get_api_key())


# ── Conversation ──────────────────────────────────────────────────────────────


class Assistant:
    def __init__(self, text_only: bool = False):
        self.client = _build_client()
        self.engine = build_tts()
        self.history: list[dict] = []
        self.text_only = text_only

    def _trim_history(self) -> None:
        if len(self.history) > HISTORY_LIMIT:
            self.history = self.history[-HISTORY_LIMIT:]

    def chat(self, user_input: str) -> str:
        lowered = user_input.lower()
        if any(kw in lowered for kw in ("system", "cpu", "memory", "ram", "disk", "health")):
            try:
                user_input += f"\n\n[System stats: {get_system_stats()}]"
            except Exception as exc:
                user_input += f"\n\n[System stats unavailable: {exc}]"

        if "clipboard" in lowered:
            try:
                import pyperclip

                clip = pyperclip.paste() or ""
                if clip:
                    safe_clip = clip_text(redact_secrets(clip), CLIPBOARD_LIMIT)
                    user_input += f"\n\n[Clipboard content:\n{safe_clip}]"
            except Exception:
                pass

        self.history.append({"role": "user", "content": user_input})
        self._trim_history()

        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=self.history,
            )
            reply = response.content[0].text
        except Exception as exc:
            return f"I could not reach the model: {exc}"

        self.history.append({"role": "assistant", "content": reply})
        self._trim_history()

        reminder = parse_reminder_response(reply)
        if reminder:
            dt, msg = reminder
            schedule_reminder(dt, msg, self.engine)
            reply = f"Reminder set for {dt.strftime('%H:%M')} — {msg}"

        return reply

    def get_input(self) -> str | None:
        if self.text_only:
            return input("You: ").strip()
        voice = listen_for_voice()
        if voice:
            cleaned = strip_wake_word(voice, WAKE_WORD)
            if WAKE_WORD and cleaned is None:
                print(f"(say '{WAKE_WORD}' to continue)")
                return None
            return cleaned or voice
        return input("You (text): ").strip()

    def run(self) -> None:
        setup_scheduler(self.client, self.engine)
        print(f"\n{'─' * 50}")
        print(f"  {ASSISTANT_NAME} — AI Desktop Assistant")
        print(f"  Model: {MODEL}")
        print(f"  Voice: {'on' if VOICE_ENABLED and self.engine else 'off'}")
        print("  Type 'quit' to exit | 'clear' to reset history | 'stats' for system stats")
        print(f"{'─' * 50}\n")

        speak(
            self.engine,
            f"Hello! I'm {ASSISTANT_NAME}, your desktop assistant. How can I help you today?",
        )

        while True:
            try:
                user_input = self.get_input()
                if not user_input:
                    continue
                lowered = user_input.lower()
                if lowered in ("quit", "exit", "bye"):
                    speak(self.engine, "Goodbye!")
                    break
                if lowered == "clear":
                    self.history = []
                    print("[History cleared]")
                    continue
                if lowered in ("stats", "_stats"):
                    try:
                        print(get_system_stats())
                    except Exception as exc:
                        print(f"[stats unavailable] {exc}")
                    continue

                reply = self.chat(user_input)
                print(f"\n{ASSISTANT_NAME}: {reply}\n")
                speak(self.engine, reply)

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as exc:
                print(f"[Error] {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{ASSISTANT_NAME} Desktop Assistant")
    parser.add_argument(
        "--text", action="store_true", help="Text-only mode (no microphone)"
    )
    parser.add_argument(
        "--notify", action="store_true", help="Run notification scheduler only"
    )
    args = parser.parse_args(argv)

    if args.notify:
        client = _build_client()
        engine = build_tts()
        setup_scheduler(client, engine)
        print(
            f"[{ASSISTANT_NAME}] Notification scheduler running. Press Ctrl+C to stop."
        )
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
        return 0

    assistant = Assistant(text_only=args.text or not VOICE_ENABLED)
    assistant.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
