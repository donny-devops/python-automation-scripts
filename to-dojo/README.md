# To-Dojo

Gamified task manager with belt ranks, streaks, and achievements.

## Install

```bash
pip install -e ".[dojo]"
# or
pip install -r to-dojo/requirements.txt
```

## Usage

```bash
python to-dojo/to_dojo.py
python to-dojo/to_dojo.py add "Ship tests" --priority high
python to-dojo/to_dojo.py list
python to-dojo/to_dojo.py complete 1
python to-dojo/to_dojo.py edit 1 --title "Ship tests and docs"
python to-dojo/to_dojo.py history
python to-dojo/to_dojo.py stats
```

State path, in order: `--data-file`, `DOJO_DATA_FILE`, `./dojo_data.json` if that file already exists, otherwise `~/.to-dojo/dojo_data.json`. Writes are atomic; corrupt JSON is quarantined beside the original file.

Streaks increase only when you complete a task.
