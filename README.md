# Chess.com Game Data Pipeline

Downloads Chess.com games for a configured player, parses selected game information, stores PGN files and monthly metadata in Google Cloud Storage, inserts structured game rows into BigQuery, and supports incremental updates without reprocessing completed historical months.

## Setup

1. Create a `.env` file in the project root:

```env
PLAYER=your_username
GCP_PROJECT_ID=your-project-id
GCP_PROJECT_NUMBER=your-project-number
LOCATION=us-central1
GCS_BASE_BUCKET_NAME=chess-data
BQ_DATASET_NAME=chess
BQ_TABLE_NAME=games
```

The GCS bucket name is constructed as:

```text
{GCS_BASE_BUCKET_NAME}-{GCP_PROJECT_NUMBER}-{LOCATION}
```

2. Authenticate with Application Default Credentials:

```bash
gcloud auth application-default login
```

3. Install dependencies:

```bash
uv sync
```

## Usage

Run the pipeline:

```bash
uv run python main.py
```

## Storage Layout

### Google Cloud Storage

```text
pgns/{year}-{month}-{uuid}.pgn
metadata/{year}-{month}.json
metadata/master.json
temp/missing-link/{year}-{month}-{uuid}.pgn
```

### BigQuery

```text
{GCP_PROJECT_ID}.{BQ_DATASET_NAME}.{BQ_TABLE_NAME}
```

## Behavior

- **`metadata/master.json`** tracks the last UTC run time and the last processed year-month.
- On each run, only archives from the last executed month (inclusive) through the current UTC month are requested.
- When the current month equals the last executed month, only that month is refreshed.
- When the current month is later, every month from the last executed through the current month is processed to catch gaps.
- **Game UUIDs** are recorded in monthly metadata only after the PGN upload and BigQuery insertion both succeed.
- If a cloud write fails, the UUID is not marked processed and the month is not marked complete.

## Tests

```bash
uv run pytest
```

Tests mock Google Cloud clients and do not require real GCP access.

## Project Structure

```text
main.py                 # application entrypoint
src/config.py           # environment configuration
src/pipeline.py         # workflow coordination
src/chess_com/          # API client and parsing
src/gcp/                # GCS and BigQuery persistence
tests/                  # focused unit tests
```
