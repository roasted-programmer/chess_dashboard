# Chess.com Game Data Pipeline

Downloads Chess.com games for a configured player, parses selected game information, stores PGN and CSV files locally, and supports incremental updates without reprocessing completed historical months.

## Setup

1. Copy or create a `.env` file in the project root with your Chess.com username:

```env
PLAYER=your_username
```

2. Install dependencies:

```bash
uv sync
```

## Usage

Run the pipeline:

```bash
uv run python main.py
```

The application creates data under:

```text
data/pgns/       # one PGN file per game
data/csv/        # games.csv (all games appended incrementally)
data/metadata/   # master.json plus one JSON file per month
```

## Behavior

- **`data/metadata/master.json`** tracks the last UTC run time and the last processed year-month.
- On each run, only archives from the last executed month (inclusive) through the current UTC month are requested.
- When the current month equals the last executed month, only that month is refreshed.
- When the current month is later, every month from the last executed through the current month is processed to catch gaps.
- At startup the pipeline reads only **master.json** and the last executed month metadata file to determine what to process.
- **Game UUIDs** are recorded in monthly metadata only after the PGN file is stored and the game row is appended to `games.csv`.
- **Metadata files** are saved atomically to support safe resumption after interruption.

## Tests

```bash
uv run pytest
```

## Project Structure

```text
main.py                 # application entrypoint
src/config.py           # environment and path configuration
src/pipeline.py         # workflow coordination
src/chess_com/          # API client and parsing
src/local_storage/      # PGN, CSV, and metadata persistence
tests/                  # focused unit tests
```
