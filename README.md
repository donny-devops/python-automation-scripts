# Python Automation Scripts

A curated collection of **Python-based automation scripts** for DevOps, system administration, data workflows, and everyday productivity.

## Overview

This repository contains modular, production-ready scripts that automate repetitive tasks such as file management, log processing, API integrations, backups, and scheduled jobs.

Each script is:
- Focused on a single responsibility
- Configurable via environment variables or CLI arguments
- Documented with usage examples
- Designed to be easily extended or composed into larger workflows

## Features

- File and directory automation (cleanup, archival, organization)
- Log rotation and parsing helpers
- API integration utilities (REST, webhooks, simple polling)
- Backup and sync helpers (local and remote targets)
- CLI wrappers with argparse / Typer / Click
- Cross-platform friendly (Linux, macOS, Windows where possible)
- Ready for cron, systemd timers, or task schedulers

## Repository Structure

```bash
python-automation-scripts/
├── README.md
├── scripts/
│   ├── backup/
│   ├── file_ops/
│   ├── logs/
│   ├── network/
│   └── misc/
├── config/
│   └── examples/
├── tests/
└── requirements.txt
```

### Scripts

Organize scripts into logical groups under `scripts/`:

- `backup/` — database exports, directory backups, rotation
- `file_ops/` — cleanup, rename, move, compress, checksum
- `logs/` — log rotation, parsing, filtering, alerting hooks
- `network/` — HTTP checks, simple uptime pings, API utilities
- `misc/` — one-off helpers and utilities

## Getting Started

### Prerequisites

- Python 3.10+ recommended
- `pip`, `uv`, or `pipx` for dependency management

### Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/your-username/python-automation-scripts.git
cd python-automation-scripts
pip install -r requirements.txt
```

Optionally, install in editable mode for development:

```bash
pip install -e .
```

## Usage

Most scripts can be run directly from the `scripts/` directory or via a wrapper entrypoint.

### General pattern

```bash
python scripts/<category>/<script_name>.py --help
```

Example:

```bash
python scripts/file_ops/cleanup_temp_files.py --path /tmp --days 7
```

### Environment Variables

Many scripts can be configured via environment variables. Example `.env` snippet:

```env
BACKUP_SOURCE=/var/data
BACKUP_DEST=s3://my-bucket/backups
BACKUP_RETENTION_DAYS=14
LOG_LEVEL=INFO
```

Use tools like `direnv`, `dotenv`, or your scheduler’s environment configuration to load these.

## Scheduling

These automation scripts are designed to be used with common schedulers:

- cron (Linux/macOS)
- systemd timers
- Windows Task Scheduler
- Containerized jobs (Docker, Kubernetes CronJobs)

Example cron entry (run every night at 2:30):

```cron
30 2 * * * /usr/bin/python /opt/python-automation-scripts/scripts/backup/run_nightly_backup.py >> /var/log/backup.log 2>&1
```

## Configuration & Secrets

- Store non-sensitive defaults in `config/` or `.env.example`
- Use environment variables for secrets (tokens, passwords, keys)
- Prefer secret managers (AWS Secrets Manager, HashiCorp Vault, Azure Key Vault, etc.) in production

Example configuration pattern inside a script:

```python
import os

BACKUP_SOURCE = os.getenv("BACKUP_SOURCE", "/var/data")
BACKUP_DEST = os.getenv("BACKUP_DEST", "./backups")
RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "14"))
```

## Development

### Code Style

- Follow PEP 8 and type hints where practical
- Prefer `pathlib` over raw `os.path`
- Use structured logging for long-running jobs

### Recommended Tooling

```bash
pip install -r requirements-dev.txt

# Linting and formatting
ruff check .
ruff format .

# Type checking
mypy scripts

# Tests
pytest
```

## Testing

Each script should include:

- Unit tests for core logic
- Safe dry-run options where destructive actions are possible
- Clear logging for success and failure paths

Example dry-run flag pattern:

```python
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Show actions without executing them",
)
```

## Examples

Consider adding a dedicated `examples/` or `recipes/` section with:

- Sample automation workflows (e.g., log cleanup + backup + notification)
- Example config files per environment
- Example scheduler definitions (cron, systemd, Kubernetes CronJob YAML)

## Roadmap

- Add richer CLI UX with Typer or Click
- Provide Dockerfile for running scripts as containers
- Add observability hooks (metrics, tracing, structured logs)
- Add integration examples with GitHub Actions or other CI tools
- Publish selected scripts as pip-installable tools

## License

Choose a license that fits your intended use, such as MIT, Apache-2.0, or a private internal license.

## Notes

To make this repository portfolio-ready, consider adding:

- Detailed per-script documentation under `docs/`
- Architecture and flow diagrams
- Example screenshots of logs, dashboards, or CI runs
- Security considerations and safeguard patterns (dry runs, confirmations)
