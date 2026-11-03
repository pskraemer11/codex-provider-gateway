# Planung: offene Proxy-Befunde

Stand: 2026-11-03  
Status: die Blocker aus der Erkundung sind umgesetzt; offen bleiben nur
Befunde, die eine Live-Beobachtung oder eine Nutzerentscheidung brauchen.

## Erledigt am 2026-11-03

- [x] **Widerspruch Provider-Tabelle vs. `requires_openai_auth`.** `config
      enable` und der Windows-Switcher schreiben für `opencode-go`, `zen` und
      `opencode-proxy` jetzt `requires_openai_auth = true` **ohne** `env_key`.
      Grund: Codex Desktop verweigert Plugin-Schalter mit HTTP 432, wenn der
      aktive Provider über `env_key` angebunden ist. Der Proxy ignoriert den
      eingehenden Bearer ohnehin. `doctor` und `switch-provider.ps1 -Check`
      melden die alte Form als Warnung.
- [x] **`doctor`-Providerdiagnose vervollständigen.** `check_config` wertet
      beide Setup-Pfade aus (Root-`openai_base_url` aus `config enable` und
      Root-`model_provider` samt `[model_providers.<name>]` aus dem Switcher),
      prüft, ob das gewählte `model` im `model_catalog_json` steht, und
      `check_provider_auth` warnt bei `env_key` bzw. fehlendem
      `requires_openai_auth`.
- [x] **Installierbares Betriebs-Skill aktualisieren.**
      `skills/opencode-go-proxy/SKILL.md` beschreibt Go-/Zen-Routing samt
      Präzedenz, die Ablehnung unbekannter Modelle (HTTP 400,
      `model_not_found`, kein stiller Fallback), den Bind-Guard als
      Startfehler, die `install-skills`-Quelle und die Provider-Auth-Form.
- [x] **Updater-Releasekanal entschieden.** Der Fork
      `pskraemer11/codex-provider-gateway` ist der Kanal; `updates.py` und
      `ops.py` nutzen ihn für Check, Release-URL und Installquelle. Weil der
      Fork Tags, aber (noch) keine GitHub-Releases hat, fällt der Check bei
      HTTP 404 auf `/tags?per_page=1` zurück.
- [x] **Native-Capture leer.** `native-models.json` war leer, weil
      `codex debug models` den *konfigurierten* Katalog rendert — mit
      `model_catalog_json` auf `proxy-catalog.json` also nur die drei
      Zen-Free-Routen. Die Capture nutzt jetzt
      `codex debug models --bundled` (12 native Modelle, davon 10 nach
      Go-Kollisionsfilter). Ohne `--bundled`-Unterstützung fällt sie auf den
      alten Aufruf zurück; `_native_only` filtert Proxy-Routen weiterhin.
- [x] **Gewähltes Modell nicht im Katalog.** `zen/gpt-6-luna` (AA-roh 27,8,
      kalibriert ≈ 45,1) fiel unter der alten Schwelle `> 50` aus dem
      Proxy-Katalog. `catalog_rules.MIN_CALIBRATED_SCORE` steht auf `45.0`;
      der Proxy-Katalog wird damit neu gebaut. Der Picker-Template-Fallback
      nutzt ebenfalls `--bundled`.
- [x] **Typechecker-Entscheidung.** Kein MyPy/PyRight: `pyproject.toml`
      konfiguriert Ruff und Pytest, es gibt keine Typkonfiguration und keinen
      Bedarf, der eine neue Abhängigkeit rechtfertigt. Wird das Projekt
      paketiert, ist die Entscheidung erneut zu prüfen.

## Katalog-Redaktion und Preis-Default 2026-11-03

- [x] **Beschreibungsfeld.** `description` schreibt `Auswahl: <reason>` statt
      `Auswahlgrund <reason>`.
- [x] **AA-Abkürzung.** Die sichtbaren Katalogtexte und die Konsole verwenden
      `AA` (Transportlabels `AA Data API` / `dated AA snapshot`,
      `benchmark_source=AA`, Fehlermeldungen `AA: …`). Maschinenwerte im Audit
      bleiben unverändert: `benchmark_source=artificial-analysis` und die
      Kalibrierungsquellen `artificial-analysis-data-api` /
      `artificial-analysis-local-snapshot` sind Provenienzschlüssel, keine
      Anzeigetexte.
- [x] **Preis-Default.** `catalog_rules.INPUT_PRICE_LIMIT` steht auf
      `Decimal("0.30")`; die AA-Schwelle bleibt `> 45/100` auf der normierten
      Skala. Der Live-Rebuild (Proxy kurz gestartet, danach gestoppt) wählte
      weiterhin 8 Proxy-Routen; die Zahl der geprüften günstigen Kandidaten
      stieg von 129 auf 149 (OpenRouter) bzw. 14 auf 15 (Zen), ohne neue
      Qualifikation.
- [x] **Hilfeformate.** `--help` nennt für `--max-input-price` „Dezimalzahl in
      USD ohne Währungssymbol oder Einheit, z. B. 0.30" und für
      `--min-intelligence-score` „Zahl von 0 bis 100 auf der Min-Max-Skala,
      z. B. 45"; beide Defaults werden aus den Konstanten interpoliert.
- [x] **Reasoning-Stufen und ein Eintrag pro Modell.** AA liefert je
      Reasoning-Stufe eine Zeile (`-low` … `-max`, `-reasoning`,
      `-non-reasoning`, `-minimal`). Der Picker gruppiert pro Basismodell und
      verwendet den höchsten Intelligence-Wert; die Kalibrierungspopulation
      enthält dadurch ein Wert pro Modell (live 47 statt 94). Jeder Katalog
      führt ein Modell nur einmal pro Provider-Route; die Reasoning-Intensität
      bleibt `supported_reasoning_levels`/`default_reasoning_level`.
      Effort-Varianten als separate Routen werden dedupliziert (bester Score,
      dann günstigerer Preis, dann kürzerer Slug) und im Audit unter
      `deduplicated_reasoning_variants` gemeldet. `opencode-go/` und `zen/`
      bleiben getrennte Abrechnungsrouten. Produkt-Suffixe wie `-pro` sind
      keine Reasoning-Stufe und bleiben eigene Familien.
- [x] **Rollierender AA-Snapshot mit Fallback.** Jeder erfolgreiche Live-Abruf
      wird atomar nach
      `tools/codex-picker/data/artificial-analysis-live-snapshot.json`
      geschrieben (git-ignoriert, beim nächsten Build überschrieben). Schlägt
      der Abruf aus irgendeinem Grund fehl — fehlender Key, Netzwerkfehler,
      abgelehnte Antwort — nutzt der Builder diesen Snapshot, danach den
      datierten Snapshot. `--check` liest ihn nur und schreibt nichts. Das Audit
      belegt den Schreibvorgang (`sources.artificial_analysis.snapshot`) und
      beide Snapshot-Dateien. Live geprüft: Build schrieb 748.054 Bytes,
      `sha256` stimmte mit dem effektiven Fallback überein; ein Lauf mit
      leerem Key wählte dieselben 8/3/5 Modelle aus dem Snapshot.

## Live-Verifikation 2026-11-03

- `proxy-catalog.json` neu gebaut: 8 Routen, darunter `zen/gpt-6-luna` und
  `opencode-go/gpt-6-luna` (47,0). `--check` bestätigt die Auswahl gegen den
  laufenden Proxy.
- `native-models.json`: 10 native Modelle (12 aus `--bundled`, zwei
  Go-Kollisionen gefiltert). `merged-models.json`: 120 Einträge (78 zen,
  32 go, 10 nativ); `/v1/models` liefert 120, inklusive `zen/gpt-6-luna` und
  dem nackten nativen `gpt-5.5`.
- `~/.codex/config.toml`: `[model_providers.opencode-proxy]` umgestellt
  (`requires_openai_auth = true`, `env_key` entfernt), Backup
  `config.toml.backup-20261103-150702-before-provider-auth`.
- `doctor --json`: `ok: true`, inklusive Modell-im-Katalog- und
  Provider-Auth-Prüfung. `switch-provider.ps1 -Check`: Katalog ok, Provider-Auth
  ok.
- `update --force`: „up to date" über den Fork-Tag `v0.4.10` (Tag-Fallback, weil
  der Fork keine GitHub-Releases hat).
- Keine echte Modellinferenz ausgeführt; der für den Katalogbau gestartete
  Proxy wurde danach wieder gestoppt.

## Offen

- [x] **Vollständige Validierung.** Fokussierte Suite 192 passed/1 skipped;
      volle Suite 1061 passed/6 skipped/16 Subtests; `uvx ruff==0.17.3 check .`
      sauber; die 12 geänderten Python-Dateien sind format-clean; die
      PowerShell-Fixture-Tests bestehen. Ein Lauf der vollen Suite hatte zuvor
      einen Fehler in
      `tests/test_catalog_local.py::test_models_endpoint_grows_after_refresh_without_restart`;
      der Test bestand allein, in seiner Datei und im Wiederholungslauf. Ursache
      ist die Windows-Dateizeit-Granularität hinter dem `st_mtime_ns`-Schlüssel
      von `protocol._CATALOG_CACHE`, nicht diese Änderung.
- [ ] **`ruff format --check` für den Rest des Repos.** 65 unveränderte Dateien
      sind nicht formatiert (z. B. `tests/test_streaming.py`). Das Gate des
      Unterprojekts prüft nur `ruff check`; eine Repo-weite Formatierung wäre
      eine eigene, unabhängige Änderung.
- [ ] **Zeitabhängige Betriebsbefunde neu prüfen.** Aussagen in
      `COMPACTIONS.md` zu aktiver Codex-Konfiguration, Proxy-Logs,
      Go-/Zen-Aufrufen und Quota vor Maßnahmen mit aktuellen, redigierten
      Daten verifizieren.
- [ ] **Desktop-Picker-Verhalten verifizieren.** Den Katalog in der
      installierten Codex-Desktop-Version prüfen; das bisherige UI-Verhalten
      ist nicht verifiziert.
- [ ] **Free-429-Diskrepanz mit aktuellen Belegen prüfen.** Der Proxy reicht
      einen vom Zen-Upstream gelieferten HTTP 429 weiter; lokale Tests können
      die abweichende Desktop-Erfahrung nicht erklären. Für eine Reproduktion
      exakte Free-Modell-ID und bereinigte Fehlermeldung vergleichen; keine
      echte Provideranfrage ohne gesonderte Freigabe starten.

## Annahmen und offene Fragen

- Eine CLI-Katalogprüfung ersetzt keinen UI-Test des aktuellen
  Desktop-Pickers.
- Historische Suite-Zahlen in `COMPACTIONS.md` unterscheiden sich: am
  31.10.2026 1.013 bestanden/6 übersprungen (ein Backup-Test bestand separat
  beim Wiederholungslauf); am 02.11.2026 1.043 bestanden/6 übersprungen/16
  Subtests. Keine Zahl ist eine erneute Validierung in dieser RCA.

## RCA: HTTP-Dispatch für Zen-Free-IDs

- **Erwartet:** Eine bekannte nackte Zen-only-ID wird über `/v1/responses` zum Zen-Upstream geroutet.
- **Bisherige Testlücke:** Routing-Unit-Tests prüfen die Klassifizierung; der HTTP-End-to-End-Test nutzte nur `zen/...`.
- **Regressionstest:** `tests/test_zen_upstream.py::TestAppDispatch` deckt explizite und nackte Zen-Free-IDs ab. Der Test war vor dem Fix rot (HTTP 400 wegen des fehlenden `zen/`-Präfixes); nach dem Fix bestanden die fokussierten Dispatch- und Picker-Tests.
- **Verifikation:** Gezielt **95 passed**; `uvx ruff==0.17.3 check` für die vier geänderten Python-Dateien bestand. Die vollständige Suite wurde nicht ausgeführt.

## Codex-TUI-Score-Anzeige

- Intelligence-Scores in Katalognamen, Beschreibungen und `--check`-Ausgabe werden mit einer Nachkommastelle dargestellt. Free-Ausnahmen zeigen den Score, wenn verfügbar, andernfalls `unverified`; die gespeicherte Audit-Präzision bleibt unverändert.
- Der aktive Katalog im Codex-Home wurde am 03.11.2026 neu erzeugt (8 Proxy-Routen, `zen/gpt-6-luna` enthalten).
