# Codex Provider Gateway

[English](README.md) | Deutsch

Dieses Repository vereint zwei verwandte, aber getrennte Werkzeuge:

- `opencode-go-proxy` ist ein lokaler Single-User-Adapter für die Responses API
  von Codex. Er routet native Codex-Modelle, OpenCode-Go-Modelle und
  OpenCode-Zen-Modelle. Dieser Teil ist ein Fork des Codex Provider Gateway
  unter https://github.com/kartikkabadi/opencode-go-proxy.
- `tools/codex-picker/` erzeugt nach Preis und Benchmark gefilterte
  Codex-Kataloge für direkte OpenRouter-Routen, direkte OpenCode-Go/Zen-Routen
  und den kombinierten lokalen Go/Zen-Proxy. Das Werkzeug konstruiert nicht die
  vollständige Pareto-Front, sondern wählt einen definierten, auswählbaren
  Punkt darauf aus.

Für die erzeugten Kataloge gibt es zwei Nutzungswege:

- Der OpenRouter-Provider wird von Codex direkt über den ausgewählten
  OpenRouter-Katalog verwendet.
- OpenCode Go und Zen können über den lokalen Proxy verwendet werden, der das
  Wire-Protokoll je Modellfamilie anhand des erzeugten Go/Zen-Katalogs
  übersetzt.

```text
Codex
├── model_provider=openrouter ────────────────> OpenRouter API
│
└── model_provider=opencode-proxy
    └── /v1/responses ──> opencode-go-proxy
                          ├── native Codex models
                          ├── OpenCode Go  ──> chat / responses / messages
                          └── OpenCode Zen ──> chat / responses / messages / Gemini
```

Die Toolchain erzeugt die folgenden Kataloge. Die Anzahl der Einträge ist ein
Beispiel aus der Prüfung vom 31. Oktober 2026. Für Proxy-Routen ist die
Live-Antwort von `/v1/models` maßgeblich; Picker- und Direkt-Provider-Dateien
sind erzeugte Snapshots.

| Datei                 | Zweck                                   | Inhalt im Audit                       |
| --------------------- | --------------------------------------- | ------------------------------------: |
| `picker-catalog.json` | Direkter OpenRouter-Provider            | 8 Modelle                             |
| `go-catalog.json`     | Direkter OpenCode-Go-Provider           | 3 Modelle                             |
| `zen-catalog.json`    | Direkter OpenCode-Zen-Provider          | 5 Modelle                             |
| `proxy-catalog.json`  | Kombinierter Go/Zen-Proxy               | 8 Modelle                             |
| `merged-models.json`  | Proxy-Runtime, nicht vom Picker erzeugt | Native Modelle plus 110 Go/Zen-Routen |

Der Picker schreibt `picker-catalog.json`, `go-catalog.json`,
`zen-catalog.json` und `proxy-catalog.json`. Der Proxy schreibt seine
Runtime-Dateien einschließlich `merged-models.json` in sein State-Verzeichnis.

## Funktionsweise

Codex sendet Anfragen an die Responses API über `POST /v1/responses`. Der Proxy
akzeptiert sowohl `/responses` als auch `/v1/responses` und wählt anschließend
eines von drei Zielen:

- Native Codex-Modelle werden unverändert an das konfigurierte ChatGPT-Backend
  weitergeleitet.
- OpenCode-Go-Modelle verwenden eine zertifizierte Protokollfamilie und
  explizite Slugs im Format `opencode-go/<model-id>`.
- OpenCode-Zen-Modelle verwenden Slugs im Format `zen/<model-id>` und werden
  dynamisch erkannt.

Das dokumentierte Go-Set enthält derzeit 33 Modelle: 5 Responses-, 19
Chat-Completions- und 9 Anthropic-Messages-Modelle. Der Picker kann daraus
anhand von Preis- und Intelligence-Index-Grenzen eine Auswahl treffen und so
einen anderen Punkt auf der Pareto-Front wählen.

Vier weitere Legacy-IDs mit einer verifizierten Protokollfamilie werden
ebenfalls akzeptiert. Der eingecheckte Seed ermöglicht den Start ohne
Netzwerkverbindung. Eine Runtime-Aktualisierung akzeptiert ausschließlich
dokumentierte oder protokollzertifizierte IDs; unbekannte IDs werden vor einer
Anfrage an den Upstream abgelehnt.

Zen erkennt seine Modellliste über OpenCode und verwendet, sofern verfügbar,
Metadaten von models.dev. Die Familienzuordnung lautet:

- Claude- und Qwen-Modelle auf Anthropic Messages
- Gemini-Modelle auf die Gemini API
- GPT- und Grok-Modelle auf Responses
- alle anderen Zen-Modelle auf Chat Completions

Die Routing-Reihenfolge ist explizit:

1. `opencode-go/<id>` wählt immer Go.
2. `zen/<id>` wählt immer Zen.
3. Ein erfasster nativer Slug wählt den nativen Codex-Endpunkt.
4. Ein reiner Zen-Slug, der nur in Zen existiert, wählt Zen.
5. Ein reiner Slug, der sowohl in Go als auch in Zen existiert, bleibt auf Go;
   `zen/<id>` wählt die Zen-Route.

Der Proxy unterstützt Streaming- und Nicht-Streaming-Anfragen, Echtzeit-SSE,
Tool-Schemata, Codex `apply_patch`, Reasoning-Replay, zstd-komprimierte
Request-Bodies, Bildübersetzung und Bildbeschreibung sowie die Koexistenz mit
nativen Modellen. Unbekannte oder fehlerhafte Modelle werden abgelehnt, statt
still ersetzt zu werden.

## Installation

Voraussetzungen: Python 3.11 oder neuer, `uv` und eine Codex-Installation, die
custom providers und `model_catalog_json` unterstützt.

### Proxy

Installieren Sie den Proxy dauerhaft und starten Sie anschließend den
Loopback-Adapter:

```powershell
$env:OPENCODE_GO_API_KEY = "your-key"

uv tool install --python 3.12 git+https://github.com/pskraemer11/codex-provider-gateway

opencode-go-proxy config enable
opencode-go-proxy --bind 127.0.0.1 --port 8787
```

Für die Entwicklung aus diesem Checkout verwenden Sie
`uv tool install --editable . --python 3.12`. Diese Installation bleibt mit
dem Checkout verknüpft; verwenden Sie die oben gezeigte nicht-editierbare
Installation, wenn der Befehl das Verschieben oder Entfernen des Checkouts
überleben soll. `uvx --from ...` ist ein einmaliger Runner und stellt keinen
dauerhaften Befehl `opencode-go-proxy` bereit.

Starten Sie Codex nach dem Aktivieren des Providers vollständig neu und wählen
Sie anschließend ein explizites Modell:

```bash
codex -m opencode-go/gpt-6-luna
codex -m zen/gpt-6-luna
```

`config enable` schreibt einen durch Marker abgegrenzten Block in die
`config.toml` von Codex. Der Block setzt `openai_base_url` und
`model_catalog_json` und verwaltet die Provider-Tabellen `opencode-go` und
`zen`. Unbeteiligte Einstellungen und die native ChatGPT-Autorisierung bleiben
erhalten. Nur den verwalteten Block entfernen Sie mit:

```bash
opencode-go-proxy config disable
```

Unter Windows befinden sich der optionale Autostart und der Health-Watchdog in
`tools/codex-picker/`. Der Installer kopiert den Watchdog in das lokale
App-Data-Verzeichnis des Benutzers; der Watchdog bevorzugt den installierten
Befehl `opencode-go-proxy`. `uv run` bleibt nur ein Entwicklungs-Fallback, wenn
der Befehl nicht installiert ist. Prüfen Sie die Task-Scheduler-Registrierung
vor dem Aktivieren:

```powershell
pwsh -File tools/codex-picker/install-proxy-autostart.ps1 -WhatIf -ReplaceExisting
```

### Katalogpicker

Der Picker läuft aus einem Repository-Checkout; eine dauerhafte Installation
des Proxys installiert den Picker nicht.

- Erforderlich: `ARTIFICIAL_ANALYSIS_API_KEY`
- Optional: `OPENROUTER_API_KEY` (die öffentliche Modellliste funktioniert auch
  ohne diesen Schlüssel)
- Für die aktuelle AA-only-Richtlinie nicht erforderlich:
  `OPENROUTER_MANAGEMENT_KEY`

Der Picker verwendet `CODEX_HOME/.tmp/bundled-catalog.json`, sofern vorhanden.
Andernfalls bezieht er eine vollständige Modellvorlage über
`codex debug models`; ein expliziter Parameter `--template PATH` überschreibt
beide Quellen. Die Proxy-URL ist standardmäßig
`http://127.0.0.1:8787/v1/models`, folgt `OPENCODE_GO_PROXY_PORT` und kann mit
`--proxy-url` überschrieben werden.

Validieren Sie Quellen und Auswahl gegen einen laufenden Proxy, ohne Dateien zu
schreiben:

```powershell
python tools/codex-picker/build_provider_catalogs.py --check
```

Erzeugen Sie alle Kataloge und den Audit:

```powershell
python tools/codex-picker/build_provider_catalogs.py
```

Schreibvorgänge in das aktive Codex-Home erfordern einen erreichbaren Proxy,
sofern `--allow-cached-proxy` den zwischengespeicherten Proxy-Katalog nicht
ausdrücklich akzeptiert. Dasselbe Flag ist erforderlich, wenn `--check` ohne
laufenden Proxy ausgeführt werden soll. Vorhandene Kataloge werden vor dem
Ersetzen gesichert; nach dem Schreiben wird der Codex-Loader geprüft.

Verwenden Sie `--provider openrouter|go|zen|proxy`, um einen einzelnen Katalog
zu erzeugen, und `--max-input-price` oder `--min-intelligence-score`, um einen
anderen Pareto-Punkt zu wählen. Der Standardgrenzwert für den Eingabepreis ist
`$0.25/M` (strikt darunter). Erhöhen Sie ihn, wenn Sie mehr Modelle wünschen.
Der kalibrierte Schwellenwert für den Artificial Analysis Intelligence Index
liegt standardmäßig strikt über `50/100`; die Kalibrierungspopulation enthält
immer alle nutzbaren Werte, bevor die Providerpreise angewendet werden. Der
Rohindex wird zuerst auf `0..100` skaliert und normalisiert.

Der Windows-Switcher schaltet den Root-Provider von Codex zwischen
`openrouter` und der lokalen Konfiguration `opencode-proxy` um:

```powershell
pwsh -File tools/codex-picker/switch-provider.ps1 -Check
pwsh -File tools/codex-picker/switch-provider.ps1 -Target proxy
pwsh -File tools/codex-picker/switch-provider.ps1 -Target openrouter
```

Der Switcher erwartet, dass die entsprechenden Provider-Tabellen existieren.
Der verwaltete Pfad `config enable` und der Windows-Switcher sind getrennte
Einrichtungswege: Ersterer verwaltet `opencode-go`/`zen`, Letzterer wählt einen
Provider `opencode-proxy` und `proxy-catalog.json`. Der Switcher lehnt ein Ziel
ab, dessen Provider-Tabelle fehlt, und ersetzt `config.toml` atomar.

Minimale, vom Benutzer verwaltete Provider-Tabellen für den Switcher:

```toml
[model_providers.openrouter]
name = "openrouter"
base_url = "https://openrouter.ai/api/v1"
wire_api = "responses"
env_key = "OPENROUTER_API_KEY"

[model_providers.opencode-proxy]
name = "OpenCode Go + Zen (local proxy)"
base_url = "http://127.0.0.1:8787/v1"
wire_api = "responses"
env_key = "OPENCODE_GO_API_KEY"
```

Der Picker erzeugt oder verändert diese Provider-Tabellen nicht, weil er
`config.toml` nicht anfasst.

## Schnittstellen

| Client-Anfrage              | Verhalten                                                               |
| --------------------------- | ----------------------------------------------------------------------- |
| `POST /v1/responses`        | Responses-Anfragen für alle gerouteten Modelle; je Familie übersetzt    |
| `POST /v1/chat/completions` | Unveränderte Chat-Completions-Weiterleitung für Go- und Zen-Chatmodelle |
| `POST /v1/messages`         | Nur OpenCode-Go-Messages-Modelle; Zen verwendet `/v1/responses`         |
| `GET /v1/models`            | Aktuelle kombinierte Liste aus nativen, Go- und Zen-Modellen            |
| `GET /health`               | Liveness und Status des Listeners                                       |
| `GET /state`                | Status, Port, Quota, Nutzung und aktuelles Modell                       |
| `GET /quota`                | Zuletzt erfasster Provider-Quota-Snapshot                               |
| `GET /cache`                | Treffer- und Fehlstatistik des Prefix-Caches                            |
| `GET /version`              | Proxy-Version und Update-Status                                         |

Die kompakten Aliase `/responses/compact` und `/v1/responses/compact` sind
ebenfalls verfügbar. Ein Modell, das an einen inkompatiblen
Direktformat-Endpunkt gesendet wird, wird abgelehnt, statt still in ein anderes
Antwortformat übersetzt zu werden.

## Bedienung

Die wichtigsten Betriebsbefehle sind:

```bash
opencode-go-proxy doctor --json
opencode-go-proxy smoke-test
opencode-go-proxy refresh-runtime
opencode-go-proxy status --json
opencode-go-proxy support-bundle --output proxy-support.json
```

`doctor --fix` repariert nur sichere lokale Verzeichnisse und Renderings; der
Befehl schreibt `config.toml` nicht neu. `smoke-test` sendet einen
Marker-Prompt durch den lokalen Proxy und kann mit `--model` ein Modell
auswählen. `support-bundle` entfernt geheimnisähnliche Werte, bevor
Diagnosedaten geschrieben werden.

Der Proxy verwendet genau einen HTTP-Port. Wichtige Standardeinstellungen:

| Option            | Umgebungsvariable                                                                      | Standard                        |
| ----------------- | -------------------------------------------------------------------------------------- | ------------------------------- |
| `--bind`          | `OPENCODE_GO_PROXY_BIND`                                                               | `127.0.0.1`                     |
| `--port`          | `OPENCODE_GO_PROXY_PORT`                                                               | `8787`                          |
| `--chat-base-url` | `OPENCODE_GO_BASE_URL`, dann `OPENCODE_ZEN_BASE_URL`, dann `CHAT_COMPLETIONS_BASE_URL` | `https://opencode.ai/zen/go/v1` |
| `--api-key-env`   | `OPENCODE_GO_PROXY_API_KEY_ENV`                                                        | `OPENCODE_GO_API_KEY`           |
| `--timeout-sec`   | `OPENCODE_GO_PROXY_TIMEOUT_SEC`                                                        | `180`                           |
| `--max-body-mb`   | `OPENCODE_GO_PROXY_MAX_BODY_MB`                                                        | `20`                            |

Lassen Sie den Listener auf Loopback. Ein Nicht-Loopback-Bind schlägt
standardmäßig fehl, sofern nicht `OPENCODE_GO_PROXY_ALLOW_REMOTE=1` und ein
separater Caller-Token konfiguriert sind. Der Caller-Token wird niemals an
einen Upstream-Provider weitergeleitet. Hinweise zu Zugangsdaten und Netzwerk
finden Sie in [SECURITY.md](SECURITY.md).

## Katalogdateien

### Proxy

Der Proxy speichert seinen Runtime-State unter `OPENCODE_GO_PROXY_STATE_DIR`,
standardmäßig `~/.codex/opencode-go-proxy/`. Die wichtigen Dateien sind:

- `opencode-go-models.json`: kompakter Go-Katalog für einen schnellen Start
- `opencode-go-catalog.json`: Go-Katalog in vollständiger Form
- `native-models.json`: erfasste native Codex-Modelle
- `zen-models.json`: erfasste Zen-Modellliste
- `zen-catalog.json`: persistierte Zen-Modellfamilien
- `merged-models.json`: native, Go- und Zen-Einträge für `/v1/models`
- `user-models.json`, `model-picker.json`, `announced-models.json`: lokale
  Overlays für Hinzufügen, Ausblenden und Anzeige sowie Ankündigungsstatus

Die eingecheckte Datei `contrib/opencode-go-models.json` ist der Offline-Seed.
Eine Runtime-Aktualisierung schreibt niemals nach `contrib/`. Beim Start
rendert der Proxy den State-Katalog sofort und aktualisiert ihn im Hintergrund
mit TTL-Begrenzung. Das vollständige Katalog-Rendering folgt der
versionsspezifischen `ModelsResponse`-Form von Codex; die Felder `fetched_at`,
`etag` und `client_version` sind Proxy-Metadaten und keine Anforderung von
`ModelsCache`.

### Katalogpicker

Der Picker schreibt die vier einleitend beschriebenen Kataloge sowie
`provider-catalog-audit.json` in das aktive Codex-Home. Er verwendet:

- OpenRouter-Preise aus `/api/v1/models`
- OpenCode-Go- und Zen-Preise aus deren Dokumentationstabellen
- Intelligence-Werte von Artificial Analysis aus der Live-AA-API
- einen datierten lokalen AA-Snapshot ausschließlich als begrenzten Fallback
- Go/Zen-Routennamen und -Familien aus dem laufenden Proxy und dessen
  State-Katalog

Die normale Auswahl erfordert einen Eingabepreis `< $0.25/M` und einen
kalibrierten AA-Intelligence-Score `> 50/100`. Der Score wird per Min-Max über
alle nutzbaren Werte der ausgewählten AA-Population kalibriert, bevor
Providerpreise angewendet werden. Dadurch bleibt die Skala am gesamten
Modellfeld verankert, statt `0/100` anhand der aktuell preisgeeigneten
Teilmenge neu zu definieren. Wenn die Live-Intelligence-Population nicht
verfügbar oder vollständig null ist, wird dieselbe Regel auf den begrenzten
lokalen Snapshot angewendet. Fehlende oder mehrdeutige Benchmark-Identitäten
bleiben `unverified`; sie werden nicht in null umgewandelt. Fünf ausdrücklich
angeforderte Free-Routen werden nur aufgenommen, wenn die Providerquelle einen
Eingabepreis von `$0` bestätigt. Die OpenRouter-Indizes Coding und Agentic
werden nicht als Ersatz für den AA-Intelligence-Score verwendet.

Der Audit zeichnet Quell-URLs, Abrufzeitpunkte, Hashes,
Kalibrierungspopulation, Auswahlgrund, exakte Identitätsübereinstimmung und
Rohindexwerte auf. Die vollständige Richtlinie und die CSV-Felder finden Sie in
[`tools/codex-picker/README.md`](tools/codex-picker/README.md) und
[`tools/codex-picker/METHODOLOGY.md`](tools/codex-picker/METHODOLOGY.md).

## Sicherheit

Dieses Projekt ist ein unabhängiger Single-User-Adapter. Es ist nicht mit
OpenAI oder OpenCode verbunden und stellt keine gemeinsam genutzten Konten,
geteilten Zugangsdaten, weiterverkaufte Abonnements oder Mechanismen zur
Umgehung von Providerlimits bereit. Verwenden Sie eigene Konten und beachten
Sie die aktuellen Bedingungen der Provider.

OpenCode-Zugangsdaten werden aus der konfigurierten Umgebungsvariable oder unter
macOS aus dem Keychain bezogen. Zugangsdatenwerte werden nicht in Traces,
Metern, Katalogen oder Support-Bundles geschrieben. Die native
Codex-Autorisierung wird ausschließlich an den konfigurierten nativen
HTTPS-Endpunkt weitergeleitet; sie wird niemals in einen OpenCode-Schlüssel
umgewandelt. Bild-URLs sind auf `data:image/` und `https://` beschränkt.

## Fehlerbehebung

| Symptom                                      | Prüfung                                                                                             |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `localhost:8787` verweigert Verbindungen     | Starten Sie den Proxy und prüfen Sie `GET /health`.                                                 |
| Port 8787 wird bereits verwendet             | Stoppen Sie die andere Proxy-Instanz; nur ein Listener wird unterstützt.                            |
| API-Schlüssel nicht gefunden                 | Setzen Sie `OPENCODE_GO_API_KEY` oder konfigurieren Sie den macOS-Keychain-Eintrag.                 |
| Unbekanntes Modell                           | Aktualisieren Sie den Katalog mit `opencode-go-proxy refresh-runtime` oder prüfen Sie `/v1/models`. |
| Warnung zu Modellmetadaten                   | Richten Sie `model_catalog_json` auf einen vollständigen Katalog wie `merged-models.json`.          |
| Desktop-Switcher meldet unbekannten Provider | Stellen Sie sicher, dass die Provider-Tabelle `opencode-proxy` oder `openrouter` existiert.         |

Die Ausgabe von `codex debug models` prüft den CLI-Katalog, nicht den
Desktop-Renderer. Das Verhalten des Desktop-Pickers sollte bei Änderungen am
Katalogschema mit der installierten Codex-Version geprüft werden.

## Entwicklung

Aus dem Repository-Stammverzeichnis:

```bash
uv sync
uv run python -m pytest tests -v
uvx ruff check
uv build
```

Das optionale lokale Git-Gate wird pro Clone mit
`git config core.hooksPath .githooks` aktiviert. Bei Codeänderungen führt es
beim Commit die vollständige Testsuite aus, beim Push immer. Der CI-Workflow
führt Tests, Ruff und den Wheel-Build auf `main`, `master`, Pull Requests und
Release-Tags aus. Ein Windows-Job parst die PowerShell-Skripte und führt
Fixture-Tests mit temporären Konfigurationen aus. Die CI dieses Repositories
ist in `.github/workflows/ci.yml` definiert.

## Lizenz

MIT. Siehe [LICENSE](LICENSE).

## Links

[![CI](https://github.com/pskraemer11/codex-provider-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/pskraemer11/codex-provider-gateway/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Dependencies: zstandard](https://img.shields.io/badge/dependencies-zstandard-blue.svg)](#)

- [Upstream-Repository](https://github.com/kartikkabadi/opencode-go-proxy)
- [Picker-Dokumentation](tools/codex-picker/README.md)
- [Picker-Methodik](tools/codex-picker/METHODOLOGY.md)
- [Sicherheitsrichtlinie](SECURITY.md)
- [Mitwirken](CONTRIBUTING.md)
- [Veröffentlichung](PUBLISHING.md)

Verwenden Sie Ihre eigenen Zugangsdaten für
[OpenCode Go](https://opencode.ai/docs/go) und
[OpenCode Zen](https://opencode.ai/zen) in
[Codex](https://github.com/openai/codex) über diesen lokalen Adapter.
