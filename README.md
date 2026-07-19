# Ossy's API Hub

Ossy's API Hub is a local-first reporting workspace for GraphQL and REST APIs. It accepts an endpoint, bearer token, custom headers and request data; follows cursor, page, offset or continuation-token pagination; combines the pages; previews the raw JSON and flattened table; and exports Excel, CSV or JSON.

## What is included

- Modern React + TypeScript interface
- Local FastAPI proxy and report engine
- GraphQL queries and REST GET/POST requests
- Cursor, page-number, offset and token pagination
- One page, selected page counts, or **All** pages
- Maximum-page and delay safeguards
- Raw GraphQL response viewer
- Flattened spreadsheet preview
- Excel workbook with Data, Run Summary, Query and Errors sheets
- CSV and JSON downloads
- Queries and groups persisted by the local backend
- Group-scoped bearer tokens persisted in the browser only and never stored with queries
- Search saved APIs by name or partial endpoint URL
- Copy queries and active result views with one click
- Access tokens returned by REST authentication endpoints are captured automatically and passed to subsequent requests
- One-click import of the RSMCP Swagger catalogue into reusable saved request templates
- Source-backed REST and GraphQL documentation with a safe local cache and refresh controls
- Optional AI environment placeholders; AI is disabled and not required

## Project structure

```text
graphql-hub/
├─ backend/                 FastAPI pagination and export service
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ models.py
│  │  └─ services/
│  ├─ tests/
│  └─ requirements.txt
├─ frontend/                React + Vite application
│  ├─ src/
│  ├─ package.json
│  └─ .env.example
├─ start.bat
├─ start.sh
└─ docker-compose.yml
```

## Quick start on Windows

Prerequisites for this development build:

- Python 3.11 or newer
- Node.js 20 or newer

Double-click `start.bat`, or run:

```powershell
.\start.bat
```

The script installs missing dependencies, builds the frontend, and opens the application at `http://localhost:8000`.

To stop a server running in the background:

```powershell
.\stop.bat
```

Use `.\stop.bat -WhatIf` to show the process that would be stopped without stopping it.

## Quick start on macOS or Linux

```bash
chmod +x start.sh
./start.sh
```

Then open `http://localhost:8000`.

To stop a background server:

```bash
chmod +x stop.sh
./stop.sh
```

Use `./stop.sh --dry-run` to inspect the matching process without stopping it.

## Manual development mode

Backend:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Docker

```bash
docker compose up --build
```

Open `http://localhost:8000`.

## Configuring pagination

For REST requests, query parameters and POST bodies are entered as JSON objects. Pagination variables can be added to either the query string or POST body. Leave the items path blank when the REST response is a root-level JSON array.

### Cursor

Example mapping:

```text
Items path:       data.transactions.edges
Record path:      node
Cursor variable:  after
Size variable:    first
Has-next path:    data.transactions.pageInfo.hasNextPage
Next-cursor path: data.transactions.pageInfo.endCursor
```

### Page number

Example mapping:

```text
Items path:        data.transactions.items
Page variable:     page
Size variable:     pageSize
Total-pages path:  data.transactions.totalPages  (optional)
```

### Offset

Example mapping:

```text
Items path:       data.transactions.items
Offset variable: offset
Limit variable:  limit
```

### Continuation token

Example mapping:

```text
Items path:       data.transactions.items
Token variable:  nextToken
Next-token path: data.transactions.nextToken
```

Use dotted JSON paths. List indices are also supported, such as `data.reports.0.items`.

## Viewing API documentation

Select a saved query and choose **Documentation** in the top toolbar. You can also right-click any saved query in the sidebar and choose **View documentation**.

The drawer shows source descriptions, parameters, request schemas and safe examples, REST responses, GraphQL arguments and result fields, and pagination settings. **Refresh from source** uses the selected group's in-session bearer token when protected Swagger or GraphQL introspection requires authentication. Credentials, client secrets and access tokens are redacted from cached documentation.

## Security notes

- Bearer tokens are never included in generated reports.
- Tokens are not saved to browser local storage.
- The service should be kept on the local machine or a trusted private network.
- A hosted multi-user version must add authentication, endpoint allow-listing, encrypted secret storage, rate limiting and SSRF protection.
- Disabling SSL verification should only be used for trusted development endpoints.

## AI fallback

The deterministic Python engine handles requests, pagination, flattening and exports. The environment file contains placeholders for future optional AI assistance:

```text
AI_ENABLED=false
AI_PROVIDER=gemini
GEMINI_API_KEY=
OPENROUTER_API_KEY=
OPENAI_API_KEY=
```

No query, response or credential is sent to an AI provider in this first build.

## Tests and validation

```bash
cd backend
pytest -q

cd ../frontend
npm run build
```
