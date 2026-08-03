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
data/csv/        # one CSV file per game
data/metadata/   # one JSON file per month
```

## Behavior

- **Historical months** (before the current UTC month) are skipped once marked complete in metadata.
- **The current UTC month** is always refreshed so new games can be added incrementally.
- **Game UUIDs** are recorded in metadata only after both PGN and CSV files are written successfully.
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
