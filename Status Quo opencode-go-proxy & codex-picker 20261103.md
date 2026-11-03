# Status Quo opencode-go-proxy & codex-picker, Stand 03. Novembeer 2026

## Kurzbefund

Das Repo enthält **zwei getrennte Werkzeuge**, die nur über Dateien und den lokalen HTTP-Port 8787 miteinander reden:

| Baustein            | Rolle                                                                                                               | Ort                      |
|---------------------|---------------------------------------------------------------------------------------------------------------------|--------------------------|
| `opencode-go-proxy` | laufender Adapter: Codex spricht Responses API, der Proxy übersetzt pro Modell in das Wire-Format des Zielproviders | `src/opencode_go_proxy/` |
| `codex-picker`      | Offline-Baukasten: erzeugt preis-/benchmark-gefilterte Kataloge, die Codex als `model_catalog_json` lädt            | `tools/codex-picker/`    |

Der Picker ist **nicht** Teil der Proxy-Installation. `pip install opencode-go-proxy` liefert nur den Proxy; der Picker existiert ausschließlich in diesem Checkout.

---

## 1. Was der Proxy tut

### Request-Pfad

```
Codex  ──POST /v1/responses──▶  app.py (ThreadingHTTPServer, 127.0.0.1:8787)
                                   │
                                   ├─ routing.py  → welche Route?
                                   │
                                   ├─ go_upstream.py    → opencode.ai/zen/go/...
                                   ├─ zen_upstream.py   → opencode.ai/zen/v1/...
                                   └─ passthrough.py    → native Codex-Modelle
```

`app.py` ist bewusst nur Dispatch (782 Zeilen): Endpunkte (`/v1/responses`, `/v1/models`, `/health`), Guards (Origin-/Token-Prüfung), Catalog-Refresh-Threads. Die Protokollarbeit liegt in `protocol.py`, `streaming.py` (1009 Zeilen SSE-Übersetzung) und den beiden Upstream-Modulen.

### Routing-Präzedenz (`routing.py`)

1. `opencode-go/<id>` → immer Go
2. `zen/<id>` → immer Zen
3. Bare Slug, der im Native-Snapshot (`native-models.json`) steht → native
4. Bare Slug, der nur in der Zen-Erfassung steht → Zen
5. Bare Slug mit Go/Zen-Kollision → **Go** gewinnt

Der Docstring begründet Punkt 4 explizit: der Picker gibt Zen-IDs bare weiter, und ein Go-Aufruf mit einer Zen-ID läuft in einen 401.

### Familien-Übersetzung

**Go** (`go_models.py`): 33 zertifizierte Modelle + 4 Legacy-IDs, aufgeteilt in drei Familien:

- 5 × `openai_responses`
- 19 × `openai_chat`
- 9 × `anthropic_messages`

Nicht zertifizierte Go-Modelle werden **nicht** dynamisch exponiert — der Modellkatalog kann sich unabhängig vom Wire-Vertrag ändern. Der Seed `contrib/opencode-go-models.json` enthält dieselben 33 Slugs.

**Zen** (`zen_catalog.py`): vier Surfaces, pro Modell aufgelöst:

| Familie | Endpunkt | Auth |
|---|---|---|
| `openai_chat` | `/zen/v1/chat/completions` | `Bearer` |
| `openai_responses` | `/zen/v1/responses` | `Bearer` |
| `anthropic_messages` | `/zen/v1/messages` | `x-api-key` |
| `google_gemini` | `/zen/v1/models/<id>` | `x-goog-api-key` |

Die Zen-Liste kommt von `GET /zen/v1/models` (ohne Auth), liegt als `zen-models.json` im State-Dir mit TTL-Gate und fällt bei Netzfehler auf den Cache zurück. Aktuell erfasst: **78 Modelle**.

Alle Zen-Turns metern mit `provider="zen"` und zählen damit nie gegen das Go-Kontingent — das ist der Grund, warum Go und Zen überhaupt parallel betrieben werden können.

### Katalog-Pipeline (`catalog.py`, 1162 Zeilen)

Drei Schichten:

1. **Seed/Merge** — State-Dir-Compact oder eingecheckter Seed, additiv gemerged mit authentifizierter Go-Discovery, TTL-gated und mit `If-None-Match`/ETag, damit ein frischer Katalog nie ins Netz geht.
2. **Overlay** — `user-models.json` (add/hide/edit), Availability-Announcements, Hidden-Flags.
3. **Render** — Projektion durch das kanonische Modell-Schema nach `merged-models.json`, ausschließlich unter dem State-Dir.

---

## 2. Anbindung an Codex — zwei getrennte Wege

Das ist der Punkt, an dem die Dokumentation und der Ist-Zustand auseinanderlaufen.

**Weg A — `config enable`** (`config_manager.py`) schreibt genau einen marker-kommentierten Block in `~/.codex/config.toml`:

```toml
openai_base_url = "http://127.0.0.1:8787/v1"
model_catalog_json = "~/.codex/opencode-go-proxy/merged-models.json"
[model_providers.opencode-go]  # base_url 127.0.0.1:8787, wire_api = responses
[model_providers.zen]          # base_url 127.0.0.1:8787, wire_api = responses
```

Hier bleibt der Root-`model_provider` unangetastet; die Auswahl läuft über Provider-Profile.

**Weg B — `switch-provider.ps1`** ändert nur drei Root-Schlüssel (`model_provider`, `model`, `model_catalog_json`), legt vorher ein Backup an und prüft den `/health`-Endpunkt; bei Ziel „proxy" startet es zuerst `watchdog-proxy.ps1`.

Beide Wege setzen voraus, dass Provider-Tabelle und Katalog zusammenpassen: `model_catalog_json` **ersetzt** die eingebaute Codex-Modellliste, es erweitert sie nicht.

---

## 3. Was der Picker tut

`build_provider_catalogs.py` (1534 Zeilen) zieht OpenRouter-Modelle, Artificial-Analysis-Werte (live oder lokaler Snapshot, max. 31 Tage alt) und den Go/Zen-Bestand, wendet die reinen Regeln aus `catalog_rules.py` an und schreibt **vier** Kataloge plus ein Audit-CSV (`provider-selection-review-*.csv`):

`picker-catalog.json` (OpenRouter) · `go-catalog.json` · `zen-catalog.json` · `proxy-catalog.json`

### Auswahlregeln

- `INPUT_PRICE_LIMIT = Decimal("0.25")` — **strikt** darunter, exakt 0,25 USD/M fällt raus.
- `MIN_CALIBRATED_SCORE = 50.0` auf einer Skala, die über die **vollständige** verwendbare AA-Intelligence-Population kalibriert wird, **bevor** der Preisfilter greift. Das war die bewusste Abkehr von Variante A („erst Preis, dann kalibrieren"), deren Skala bei jeder Änderung des billigen Kandidatensatzes wanderte.
- Fehlender Score heißt `unverified`, nicht null.
- Fünf gepinnte Gratis-Routen umgehen die Score-Schwelle — nur bei verifiziertem `$0`.

### Verbindung zum Proxy

Der Proxy-Teil des Pickers hängt an zwei Quellen: dem laufenden `/v1/models` des Proxys und dem State-`merged-models*.json`. `--check` **verlangt** deshalb einen erreichbaren Proxy. Das Ergebnis ist eine gefilterte Teilmenge, nicht der volle Proxy-Katalog.

---

## 4. Ist-Zustand auf dieser Maschine

| Befund | Wert |
|---|---|
| Proxy erreichbar? | **nein** — `http://127.0.0.1:8787/health` verweigert die Verbindung |
| Root-Auswahl | `model_provider = "opencode-proxy"`, `model = "zen/gpt-6-luna"` |
| `model_catalog_json` | `$HOME/.codex/proxy-catalog.json` |
| `proxy-catalog.json` | 3 Modelle: `zen/deepseek-v4.1-flash-free`, `zen/glm-5.3-flash-free`, `zen/mimo-v2.6-flash-free` |
| `go-catalog.json` | **0 Modelle** |
| `zen-catalog.json` | 3 (dieselben Free-Pins) |
| `picker-catalog.json` | 5 OpenRouter-Modelle |
| `merged-models.json` | 110 (32 × `opencode-go/` + 78 × `zen/`) |
| `native-models.json` | **0** |
| `zen-models.json` | 78 |

Drei Dinge fallen auf:

1. **Das gewählte Modell steht nicht im aktiven Katalog.** `zen/gpt-6-luna` fehlt in `proxy-catalog.json`, das nur die drei Free-Pins enthält. `gpt-6-luna` ist in `go_models.py` als Go-Modell mit `openai_responses` zertifiziert — mit `zen/`-Präfix erzwingt das Routing aber den Zen-Pfad, unabhängig davon.
2. **Der Provider-Eintrag `opencode-proxy` weicht vom dokumentierten Desktop-Setup ab.** Er nutzt `env_key = "OPENCODE_GO_API_KEY"` und **kein** `requires_openai_auth`. Die Doku vom 25.10. begründet `requires_openai_auth = true` ausdrücklich als Lösung der Plugin-Einschränkung der Desktop-App.
3. **`native-models.json` ist leer.** Das ist die in `COMPACTIONS.md` (02.11.) notierte Ursache für Fehlrouting bare Slugs — Regel 3 der Präzedenz kann nicht greifen, weil kein einziger nativer Slug erfasst ist.

Der leere `go-catalog.json` ist kein Fehler, sondern Folge der strikten Politik: wenn kein Go-Modell beide Schwellen gleichzeitig erfüllt, bleibt der Katalog leer, während der Proxy selbst weiter 110 Routen anbietet.

---

## 5. Arbeitsbaum

Nicht committet: `PLANUNG.md` (untracked) sowie Änderungen an `zen_upstream.py`, `CHANGELOG.md`, `COMPACTIONS.md`, beiden Doku-Dateien, den Picker-Skripten (`build_provider_catalogs.py`, `switch-provider.ps1`, `watchdog-proxy.ps1`, `install-proxy-autostart.ps1`), deren Tests und `tests/test_zen_upstream.py` / `test_codex_picker_selection.py`. Zusätzlich ist `docs/Codex vs. OpenCoden Vergleich bzgl Sicherheit.md` als gelöscht markiert. Ein Diff von 14 Dateien, +303/−207.

---

## 6. Offene Punkte (aus `PLANUNG.md`)

- `doctor` prüft nur `openai_base_url`, nicht den aktiven Root-`model_provider` — die derzeit tatsächlich wirksame Auswahl bleibt damit ungeprüft.
- Das Betriebs-Skill `skills/opencode-go-proxy/SKILL.md` beschreibt noch den reinen Go-Chat-Pfad; Go/Zen-Routing, abgelehnte unbekannte Modelle und der externe-Bind-Fehlerfall fehlen.
- Updater-Kanal unentschieden: Metadaten zeigen auf `pskraemer11/codex-provider-gateway`, `updates.py`/`ops.py` nutzen Upstream-Releases.

Wenn du willst, kann ich als nächsten Schritt einen der drei Punkte angehen — oder zuerst den Widerspruch zwischen `opencode-proxy`-Provider-Tabelle und dokumentiertem `requires_openai_auth`-Setup auflösen, denn der erklärt möglicherweise, warum die aktuelle Codex-Konfiguration nicht das tut, was die Doku beschreibt.
