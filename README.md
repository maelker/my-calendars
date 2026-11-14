# My calendars

`events.csv` is the single source of truth. On every push to `main` (and daily at 05:00 UTC),
GitHub Actions builds `concerts.ics`, `sports.ics`, `esports.ics` and `all.ics` and publishes them on GitHub Pages.

Subscribe to: `https://<username>.github.io/<repo>/concerts.ics` (same for the others).

## Add an event
1. Open a pull request that adds a row to `events.csv` (status `approved`).
2. The "Validate pull request" check must pass.
3. Merge = published. Close the PR (or set `rejected`) = not published.

## Columns
`uid, status, category, emoji, title, start, end, timezone, location, url, notes`
- `category`: Concert, Sport or Esport
- `start` / `end`: local time `YYYY-MM-DD HH:MM`, or date-only `YYYY-MM-DD` for all-day / multi-day events (festivals)
- `end` empty = 2 hours (or a single day if date-only)
- `timezone`: IANA name, default `Europe/Paris`
- `uid`: unique and permanent; reuse it to update an event, never for a different one

## Local check
`python scripts/build_ics.py --check`
