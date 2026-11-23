# My calendars

`events.csv` is the single source of truth. On every push to `main` (and daily at 05:00 UTC),
GitHub Actions builds one `.ics` per category (see `categories.csv`) plus `all.ics`, and publishes them on GitHub Pages.

Subscribe to: `https://maelker.github.io/my-calendars/concerts.ics` (same for sports, esports, other, all).

## Add an event
1. Open a pull request that adds a row to `events.csv` (status `approved`).
2. The "Validate pull request" check must pass.
3. Merge = published. Close the PR (or set `rejected`) = not published.

## Columns
`uid, status, category, emoji, title, start, end, timezone, location, url, notes, recurrence, exceptions, geo`

| column | meaning |
|---|---|
| `uid` | unique and permanent; reuse it to update an event, never for a different one |
| `status` | `approved` = published, `pending` = to review, `rejected` = hidden |
| `category` | one of the names in `categories.csv` |
| `start` / `end` | local time `YYYY-MM-DD HH:MM`, or date-only `YYYY-MM-DD` for all-day / multi-day events. `end` empty = 2 hours (or one day) |
| `timezone` | IANA name, default `Europe/Paris` |
| `recurrence` | optional RRULE, e.g. `FREQ=WEEKLY;UNTIL=20271231` or `FREQ=MONTHLY;BYMONTHDAY=5;COUNT=12` |
| `exceptions` | optional dates to skip, `YYYY-MM-DD` separated by `;` |
| `geo` | optional GPS point `lat,lon` (e.g. `45.192154,5.707741`): Apple Calendar shows a map pin, Google Calendar a map link from `location` |

## Categories
Edit `categories.csv` (`category, slug, calendar_name`). Each row creates one calendar file `<slug>.ics`.
Add a line to add a category; nothing else to change.

## Recurring events
One row describes the whole series; `start`/`end` are the **first** occurrence.
Each occurrence is published with uid `<uid>-YYYYMMDD`, in the right local time across daylight-saving changes.
- Without `UNTIL` or `COUNT` the series is published 2 years ahead.
- **Cancel one date:** add it to `exceptions`.
- **Change one date:** add it to `exceptions`, then add a normal row with uid `<uid>-YYYYMMDD` and the new details.

## Local check
`pip install -r requirements.txt` (once; needed on Windows), then `python scripts/build_ics.py --check`

## Edit page (`/edit.html`)
After a build, `https://maelker.github.io/my-calendars/edit.html` lets you search, edit, add, duplicate and delete events
(title, dates, times, place, link, notes, recurrence, categories) from a phone or computer.
- **Place:** type an address or venue (OpenStreetMap search, no key needed) or paste a Google Maps / Apple Plans link. The address goes in `location`, the GPS point in `geo`. Short links (`maps.app.goo.gl`) cannot be read: paste the long link.
- **Saving:** ⚙️ → enter your repo and a *fine-grained* GitHub token limited to this repo (Contents: Read and write; Pull requests: Read and write for pull-request mode). The token stays in your browser only. Without a token you can still edit and download the CSV.
- **Two modes:** commit straight to `main` (published after about a minute) or open a pull request.
- The page and the CSV files are public, like the rest of the repo.

## Pages (publiées sur GitHub Pages)
| Page | Rôle |
|---|---|
| `/index.html` | liens d'abonnement (un flux `.ics` par catégorie + `all.ics`) |
| `/view.html` | **visualisation** : liste par jour ou vue mois, filtres par catégorie, recherche, détail + liens Google Maps / Plans |
| `/edit.html` | **modification** : ajouter, modifier, supprimer, dupliquer — un par un ou **plusieurs à la fois** |

### Modifier plusieurs événements à la fois (`edit.html`)
1. Coche les cases, ou « ☑ Tout sélectionner » (s'applique à la liste filtrée : filtre d'abord par catégorie / recherche / période).
2. Barre du bas : **✏️ Modifier** (catégorie, statut, emoji, fuseau, lieu, lien, notes, décalage en jours/minutes, durée), **⧉ Dupliquer**, **🗑 Supprimer**.
3. **＋ Plusieurs** : colle des lignes `date heure ; titre ; lieu ; fin ; lien` (ou un tableau avec en-tête `title,start,end,category,location…` copié depuis Excel/Sheets). Aperçu et erreurs ligne par ligne avant ajout.
4. **💾 Enregistrer** : un seul commit (ou une Pull Request) pour tous les changements.
