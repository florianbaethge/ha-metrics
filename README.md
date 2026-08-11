# ha-metrics

Sammelt täglich Kennzahlen zu meinen Home-Assistant-Erweiterungen und legt sie
als JSON-Historie ab. Grundlage für den täglichen Report.

Beobachtete Repos: `simple_irrigation`, `bedtime_stories`, `advanced_cover`,
`deluxe_room_card`.

## Einrichtung

**1. Dieses Repo anlegen** — öffentlich, unter deinem Account, Name `ha-metrics`.
Öffentlich ist nötig, damit der Report die Daten ohne Zugangsdaten lesen kann.
Was hier landet: Sterne, Forks, Issues, PRs, Download-Zahlen und Traffic zu
deinen ohnehin öffentlichen Repos. Keine Zugangsdaten, keine privaten Inhalte.

**2. Token erzeugen.** GitHub → Settings → Developer Settings →
Personal access tokens → **Fine-grained tokens** → Generate new token.

- *Repository access*: Only select repositories → die vier Extension-Repos **und** `ha-metrics`
- *Permissions* → Repository permissions:
  - **Administration: Read-only** ← das ist der Schlüssel für Views/Clones
  - **Contents: Read and write** (damit die Action nach `data/` committen darf)
  - **Metadata: Read-only** (wird automatisch mitgesetzt)
- Laufzeit: so lang wie du magst. Bei Ablauf hört der Traffic-Teil auf, der Rest läuft weiter.

**3. Token hinterlegen.** In `ha-metrics` → Settings → Secrets and variables →
Actions → New repository secret → Name exakt `METRICS_TOKEN`.

**4. Erststart.** Actions → „Kennzahlen sammeln" → Run workflow.
Danach läuft es täglich um 05:10 UTC von allein.

## Warum ein Token nötig ist

Die Traffic-Endpunkte der GitHub-API (Views, Clones, Referrer) verlangen
laut GitHub-Doku die Berechtigung **Administration (read)**. Der in Actions
eingebaute `GITHUB_TOKEN` kennt diese Berechtigung nicht — sie lässt sich im
Workflow gar nicht anfordern. Deshalb das separate Fine-grained-Token.

Ohne Token läuft `collect.py` trotzdem durch: Sterne, Forks, Issues, PRs,
Releases und Downloads werden gesammelt, nur die Traffic-Felder bleiben `null`
und landen als Hinweis in `errors`.

## Was rauskommt

```
data/index.json              Übersicht aller Repos + Deltas zum Vortag
data/<repo>.json             Vollbild von heute + Tageshistorie
```

`data/<repo>.json` hat zwei Teile:

- `current` — der heutige Stand mit allen Details: offene Issues und PRs mit
  Titel, Autor und Alter, alle Releases mit Download-Zahlen pro Asset, neue
  Sterne und Forks der letzten 7 Tage, Traffic-Tageswerte, Referrer, Top-Pfade.
- `history` — ein schlanker Eintrag pro Tag. Daraus entstehen die Deltas und
  später Verlaufskurven.

## Zur 14-Tage-Grenze

GitHub hält Traffic-Daten nur 14 Tage vor. Genau deshalb schreibt dieses Repo
sie täglich weg — nach ein paar Wochen hast du eine Historie, die es bei GitHub
selbst nicht mehr gibt.

## Ein Repo dazunehmen

In `collect.py` die Liste `REPOS` ergänzen und das Repo im Token unter
*Repository access* mit auswählen.
