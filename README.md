# conference-chase

Tracks submission deadlines of scientific conferences (formal methods, programming
languages, logic & theory, SE & security) and shows them on a GitHub Pages site.

- **Site** (`index.html`, `assets/`): plain HTML/CSS/JS with three views — deadline cards
  with countdowns, a 12-month timeline, and a sortable table. It reads `data/conferences.json`.
- **Data** (`data/conferences.json`, schema in `data/schema.json`): conferences → editions
  (one per year: website, call-for-papers page, location, dates, PC chairs) → rounds (abstract /
  submission deadline, rebuttal period, notification, final version, submission link,
  page limit, optional round-specific CFP).
- **Agent** (`agent/`): a weekly GitHub Actions workflow picks the stalest conferences, runs one
  LLM agent per conference (at most 5 in parallel) that searches the web and reads the official
  CFP, then merges the results into the JSON and commits them.

## Setup

1. **Pages**: Settings → Pages → *Deploy from a branch* → `master` / `(root)`.
2. **LLM provider** (any OpenAI-compatible Chat Completions API with tool calling):
   - secret `LLM_API_KEY` (Settings → Secrets and variables → Actions → *Secrets*)
   - variable `LLM_MODEL`, e.g. `gpt-4.1-mini` (→ *Variables*)
   - variable `LLM_BASE_URL`, e.g. `https://openrouter.ai/api/v1` (omit for OpenAI)
3. **Web search**: free and keyless — the agent queries DuckDuckGo's HTML endpoint (with
   retries when rate-limited) and fetches pages directly; no search API key is needed.
4. Actions → *Update conference data* → *Run workflow* (optionally with `ids: cav,popl`).
   It also runs every Monday at 03:00 UTC.

## Adding a conference

Add an entry to `data/conferences.json` with `id`, `acronym`, `name`, `category` (one of
`categories`), optional `homepage`, and `"editions": []`. The next run fills in the dates.
Dates can also be edited by hand; the merge never replaces a known value with null.

## Running locally

```sh
python3 -m http.server          # site at http://localhost:8000
pip install -r agent/requirements.txt
python agent/select_stale.py --explain
LLM_API_KEY=… LLM_MODEL=… [LLM_BASE_URL=…] python agent/gather.py cav   # → out/cav.json
python agent/merge.py           # merges out/*.json into data/conferences.json
python agent/validate.py
```
