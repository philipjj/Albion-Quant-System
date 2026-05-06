# AQS stack map

Albion Quant Trading System: **Python 3.10+**, **FastAPI** (`main.py`), **SQLAlchemy** + SQLite by default, **APScheduler** (`workers/scheduler.py`), **Discord** webhook + optional bot (`app/alerts/`).

## Layout

| Path | Role |
|------|------|
| `main.py` | FastAPI app, CLI (`--init`, `--collect`, `--scan`), uvicorn entry |
| `app/api/` | REST routers (`/market`, `/arbitrage`, `/crafting`, `/export`, `/user`) |
| `app/db/` | SQLAlchemy models + session |
| `app/ingestion/` | Market data collector |
| `app/arbitrage/`, `app/crafting/` | Scanners / engines |
| `app/alerts/` | Discord webhook alerter + command bot |
| `workers/scheduler.py` | Periodic jobs |
| `app/staticdata/` | Static game data pipeline |
| `data/` | SQLite DB, raw/parsed data (created at runtime) |

## Commands (local)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt -r requirements-dev.txt

# Lint / types / tests / wheel build
ruff check .
mypy
pytest

pip install build
python -m build

# Run API + scheduler + bot (needs .env)
python main.py

# One-shot CLI
python main.py --init
python main.py --collect
python main.py --scan
```

## CI

GitHub Actions: `.github/workflows/ci.yml` runs install, `ruff`, `mypy`, `pytest`, and `python -m build`.

## Test mode

Pytest sets `DISABLE_BACKGROUND_TASKS=true` and a temporary `DATABASE_URL` so the FastAPI lifespan does not start the scheduler, Discord bot, or background collection (see `tests/conftest.py`).
