# OpenCode Go und Zen in Codex

Stand: 26.10.2026. Umsetzung abgeschlossen, gehaertet und gemessen; offen bleibt nur der
Picker-Feinschliff für die OpenRouter-Seite (siehe unten). Die frühere
Plugin-Einschränkung der Desktop-App ist mit `requires_openai_auth = true` gelöst.

## Worum es geht

Codex soll zusätzlich zu OpenAI und OpenRouter die Modelle aus dem
OpenCode-Abo (Go bzw. Go Plus) nutzen können. Der Anlass ist nicht die
Modellauswahl — die ist über OpenRouter breit vorhanden —, sondern der
Festpreis: Go kostet 10 USD/Monat (Go Plus 40 USD) und deckelt die Nutzung je
Modell über ein Monatsbudget. Dazu kommt, dass Codex' Sandbox ohne
Einzelrückfragen arbeitet, OpenCode mit `permission: ask` dagegen ständig
unterbricht.

Zen (Pay-as-you-go) wird **nicht** verfolgt: Die interessanten Zen-Modelle sind
über OpenRouter erreichbar, die Free-Tier-Modelle sind für Harnesses gesperrt
(siehe unten), und ein zweiter Abrechnungsweg bringt keinen Vorteil.

## Die technische Grenze: Codex spricht nur Responses

`wire_api` akzeptiert in Codex nur noch `responses`. Der Wert `chat` wurde zum
1. Februar 2026 entfernt und führt heute zu einem harten Konfigurationsfehler;
die Konfigurationsreferenz listet als einzigen Wert `responses`.

Damit ist die Ausgangsfrage beantwortet: Über den offiziellen Console-Weg
bekommt man **nicht alle** Provider, sondern nur die Modelle, die Responses
sprechen. Laut Harness-Doku sind das für Codex: GPT, Grok und Muse Spark, auf
Go zusätzlich DeepSeek V4. Claude, Gemini, GLM, Kimi, Qwen und MiniMax bleiben
dort außen vor, obwohl sie im Workspace aktiviert sind.

## Messungen (25.10.2026, ohne gültigen Key)

| Prüfung                                  | Ergebnis                                                    |
| ---------------------------------------- | ----------------------------------------------------------- |
| `GET opencode.ai/zen/v1/models`          | 200, 85 Modelle                                             |
| `GET opencode.ai/zen/go/v1/models`       | 200, 38 Modelle                                             |
| `POST /inference/go/openai/v1/responses` | 400 `MissingSessionID` → Route existiert                    |
| `POST /zen/go/v1/chat/completions`       | 400 `MissingSessionID`                                      |
| `POST /zen/v1/chat/completions`          | 400 `Model is unavailable` → keine Session-Pflicht          |
| `POST opencode.ai/console/mcp`           | 401 `unauthorized`, OAuth erwartet → MCP-Endpunkt existiert |
| Codex CLI lokal                          | 0.164.0                                                     |

Die Fehlerform ist ein brauchbarer Nachweis: Ein unbekanntes Modell antwortet
mit `400 Model is unavailable`, ein bekanntes Modell läuft in die
Authentifizierungsprüfung (`401`). Die Familienprüfung (welche API ein Modell
spricht) ist von außen also **nicht** prüfbar — dafür gilt die Doku.

## Was in der Console hängt (25.10.2026)

| Connection                                | aktiv / gesamt | Familie                      |
| ----------------------------------------- | -------------- | ---------------------------- |
| Anthropic                                 | 2 / 17         | Anthropic Messages           |
| LM Studio                                 | 5 / 5          | OpenAI-kompatibel, lokal     |
| OpenAI                                    | 6 / 33         | Responses                    |
| OpenCode (eingebaut, Zen- und Go-Katalog) | 18 / 85        | gemischt                     |
| OpenRouter                                | 44 / 390       | überwiegend Chat Completions |

Wichtig: Die Console routet pro Modell genau die Familie, die das Modell
spricht. OpenRouter- und Anthropic-Modelle im Workspace sind für Codex deshalb
nicht erreichbar, obwohl sie aktiviert sind. Das Go-Abo ist gebucht, aber die
Go-exklusiven Modelle (`deepseek-v4-pro`, `grok-4.7`, `glm-5.3`,
`kimi-k2.7-code`, `qwen3.8-max`, `gemini-4-argon`) stehen im Workspace noch auf
„nicht aktiviert“; `kimi-k3.1-pro` fehlt in der Console-Liste, obwohl es im
Go-Katalog (`/zen/go/v1/models`) enthalten ist. Die Console-Liste läuft dem
Go-Katalog also nachlaufend hinterher.

Beleg: `docs/OpenCode_Console - verbundene Anbieter 20261025.png` (Providers-Seite
des Workspace).

## Die fünf Wege und warum vier ausfallen

|                           | A Console direkt   | B Zen direkt | C go-proxy          | D LiteLLM                | E getrennt lassen |
| ------------------------- | ------------------ | ------------ | ------------------- | ------------------------ | ----------------- |
| Go-Modelle                | ~8 (nur Responses) | 0            | alle 38             | alle (via Chat-Bridge)   | –                 |
| Claude/Gemini/GLM/Kimi    | X                  | X            | ✓                   | ✓                       | nur in OpenCode   |
| Zusatzprozess             | X                  | X            | ✓                   | ✓                       | X                 |
| Drittsoftware im Key-Pfad | X                  | X            | klein, 1 Maintainer | groß, 109 Abhängigkeiten | X                 |
| Session pro Konversation  | Codex-eigene       | –            | ja, pro Thread      | nein, statisch           | –                 |
| Aufwand                   | 5 Min              | 5 Min        | 30–60 Min           | 1–2 h                    | 0                 |

- **A entfällt.** Der Nutzen wäre auf GPT, Grok, Muse Spark und DeepSeek V4
  beschränkt. Grok ist ausgeschlossen, GPT und Muse Spark sind über OpenRouter
  billiger oder gleichwertig erreichbar, DeepSeek V4.1 Flash gibt es dort
  ebenfalls. Bleibt ein zusätzlicher Hop ohne Gegenwert.
- **B entfällt.** Weniger Modelle als A, kein Go-Zugang.
- **E entfällt.** Zwei Apps, kein einheitlicher Workflow — genau das Problem,
  das gelöst werden soll.
- **D bleibt Reserve.** LiteLLM ist die richtige Wahl, wenn später OpenRouter,
  LM Studio und OpenCode hinter *einem* Gateway zusammengefasst werden sollen.
  Für „Go in Codex“ ist es Überbau.
- **C bleibt die Wahl.** Ein Befehl statt YAML-Baum, Modellfamilien muss man
  nicht kennen, und der Proxy erzeugt pro Thread eine Session.

## Warum die Session-ID über den Preis entscheidet

Go verlangt `x-opencode-session` für Routing-Affinität und Prompt-Cache. Die
offizielle Doku führt Codex als validierten Client und sagt ausdrücklich: „Go
recognizes its native session header. Some versions and proxy setups still omit
it; preserve the session header when forwarding requests.“

Daraus folgt für die Werkzeuge:

| Weg              | Session-Verhalten                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------|
| A (direkt)       | Codex sendet seinen nativen Header, Go erkennt ihn                                        |
| C (go-proxy)     | erzeugt pro Thread eine `ses_`-ID                                                         |
| D (LiteLLM)      | `extra_headers` ist statisch; `forward_client_headers_to_llm_api` reicht nur `x-*`-Header |
|                  |    durch, Codex' `session_id` ist ein einfacher Header und fällt heraus                   |
| D + eigener Hook | möglich, aber dann ist es wieder Eigenbau                                                 |

Der Cache ist kein Detail, sondern der größte Einzelposten. DeepSeek V4.1 Flash
kostet off-peak 0,15 USD/1M Input und 0,003 USD/1M Cache-Read — Faktor 50 pro
Token. Bei einem typischen Codex-Turn mit 150k Kontext und 90 % unverändertem
Prefix ergibt das über 50 Turns rund 0,13 USD mit Cache gegen 1,13 USD ohne,
also Faktor 8,5 auf den Turn-Preis. Ein statischer Header ist deshalb kein
Schönheitsfehler, sondern ein Kostenrisiko — und ein Proxy, der pro Thread eine
ID vergibt, ist billiger als jede Nachbesserung.

## Preise der Kandidaten (Go, off-peak, Stand 25.10.2026)

Tokenpreise in USD je 1M, Monatslimit = Go-Plan (nicht Go Plus).

| Modell                     | Input  | Output | Cache-Read | Monatslimit |
| -------------------------- | ------ | ------ | ---------- | ----------- |
| DeepSeek V4.1 Flash        |  0,15  |  0,60  |  0,003     |  80 USD     |
| DeepSeek V4 Pro            |  0,66  |  1,98  |  0,022     |  15 USD     |
| GLM-5.3-Flash              |  0,15  |  0,50  |  0,03      |  60 USD     |
| GLM-5.3                    |  1,40  |  4,40  |  0,26      |  15 USD     |
| Qwen3.8 Flash              |  0,15  |  0,47  |  0,016     |  30 USD     |
| Qwen3.8 Max                | [2,00] |  6,00  |  0,25      |  15 USD     |
| MiniMax M3                 |  0,30  |  1,20  |  0,06      |  60 USD     |
| MiniMax M3.1 Flash         |  0,15  |  0,60  |  0,015     |  20 USD     |
| Kimi K2.7 Code             |  0,95  |  4,00  |  0,19      |  60 USD     |
| MiMo-V2.6-Flash            |  0,14  |  0,28  |  0,0028    |  60 USD     |
| MiMo-V2.6-Pro              |  0,435 |  0,87  |  0,0036    |  15 USD     |
| LongCat-2.0                |  0,30  |  1,20  |  0,006     |  60 USD     |
| GPT 6 Luna                 |  0,10  |  0,50  |  0,01      |  15 USD     |
| GPT 5.6 Luna               |  0,20  |  1,20  |  0,02      |  15 USD     |
| Claude Haiku 5.5           |  0,10  |  0,50  |  0,01      |  15 USD     |
| Grok 4.7                   | [2,00] |  6,00  |  0,50      |  15 USD     |
| Kimi K3                    | [3,00] | 15,00  |  0,30      |  15 USD     |
| Gemini 4 Argon             | [4,00] | 20,00  |  0,20      |  30 USD     |
| Muse Spark 1.3 Contributor |  0,10  |  0,20  |  0,002     |  60 USD     |

Tageszeit: DeepSeek Peak ist 01:00–04:00 und 06:00–10:00 UTC, Mo–Fr; alles
andere ist off-peak (Peak kostet das Doppelte).

## Vorschlag für die kuratierte Liste

Acht Einträge, nach Provider-Prefix sortierbar (`Go · <Modell>`), Reihenfolge
über `priority`. Ausgeschlossen sind Grok (politisch nicht gewollt), Gemini
(Preis-Leistung), Muse Spark Contributor (Trainingsfreigabe auf Anfragedaten),
Qwen3.8 Max und GLM-5.3 (teuer bei kleinem Limit).

| Anzeigename              | Go-Modell             | Rolle                                               |
| ------------------------ | --------------------- | --------------------------------------------------- |
| Go · DeepSeek V4.1 Flash | `deepseek-v4.1-flash` | Arbeitstier, bestes Cache-Verhältnis, größtes Limit |
| Go · DeepSeek V4 Pro     | `deepseek-v4-pro`     | schwere Fälle, kleines Limit                        |
| Go · GLM-5.3-Flash       | `glm-5.3-flash`       | zweite Familie, günstig                             |
| Go · Qwen3.8 Flash       | `qwen3.8-flash`       | dritte Familie, mittleres Limit                     |
| Go · MiniMax M3          | `minimax-m3`          | Allrounder, 60 USD Limit                            |
| Go · Kimi K2.7 Code      | `kimi-k2.7-code`      | Code-Spezialist, nicht K3                           |
| Go · MiMo-V2.6-Flash     | `mimo-v2.6-flash`     | billigste Tokens, Backfill                          |
| Go · LongCat-2.0         | `longcat-2.0`         | Reserve, sehr billiger Cache                        |

Doppelte Modelle vermeiden: `gpt-6-luna`, `claude-haiku-5-5` und
`deepseek-v4.1-flash` liegen zusätzlich unter „OpenAI“, „Anthropic“ bzw.
OpenRouter. Sie kommen nur in die Go-Liste, wenn bewusst Go-Kontingent statt
OpenRouter-Guthaben verbraucht werden soll.

### Kimi K3: über OpenRouter, nicht über Go

Kimi K3 ist wieder im Rennen, aber auf der OpenRouter-Seite. Der Preisrutsch
hängt an K3.1 Pro und gilt bei OpenRouter: Dort kostet Kimi K3 am 25.10.2026
**0,239 USD/1M Input** und 10,80 USD/1M Output bei 1.048.576 Token Kontext
(Artificial Analysis: Intelligence 43,6, Coding 76,2). Go listet dasselbe
Modell unverändert mit 3,00 USD/1M Input, 15,00 USD/1M Output und einem
Monatslimit von nur 15 USD. Bei diesem Abstand wandert K3 in den
OpenRouter-Katalog des Pickers, nicht in die Go-Liste. K3.1 Pro (2,00/10,00 bei
OpenRouter) bleibt draußen.

## OpenRouter: Modellpflege per Filter

Der Picker-Katalog ist Pflegearbeit, sobald Modelle und Preise sich bewegen.
Statt die Liste von Hand nachzuziehen, soll ein Skill sie aus der
OpenRouter-API erzeugen. Der Filter ist messbar und braucht keine Webseite:

| Kriterium            | Quelle im API-Objekt                                | Schwelle                         |
| -------------------- | --------------------------------------------------- | -------------------------------- |
| Input-Preis je Token | `pricing.prompt` (USD je Token, ×1e6 = USD je 1M)   | < 0,0000005                      |
| Intelligenz          | `benchmarks.artificial_analysis.intelligence_index` | > 40                             |
| Kontext              | `context_length`                                    | nach Bedarf, z. B. ≥ 200k        |
| Werkzeuge            | `supported_parameters` enthält `tools`              | Pflicht für agentisches Arbeiten |

Datenquelle: `GET https://openrouter.ai/api/v1/models` (467 Modelle am
25.10.2026, ohne Key lesbar; Preise als Strings in USD je Token). Der
AA-Index steckt bereits im Objekt, eine zweite Quelle ist nicht nötig — die
Webseiten-Filter `min_intelligence_index=40` und `order=pricing-low-to-high`
sind nur die Oberfläche derselben Daten.

Der Skill soll außerdem: Dubletten gegen den Go-Katalog erkennen, Grok
ausschließen, die bestehenden `display_name`-Präfixe (`Go ·`, `Or ·`)
beibehalten, `priority` neu durchnummerieren und den Katalog vor dem Schreiben
validieren (jeder Eintrag braucht `slug`, `display_name`, `priority`,
`context_window`, `supported_reasoning_levels`, sonst bricht der Codex-Loader
ab).

## Umsetzung (Stand 26.10.2026, ausgeführt)

1. **Proxy** läuft commit-gepinnt:

   ```powershell
   uvx --from git+https://github.com/kartikkabadi/opencode-go-proxy@4a372975416a74957cbf388193b7d8bfff1fbbcd `
     opencode-go-proxy --bind 127.0.0.1 --port 8787
   ```

   Health 200, 111 Modelle
   (`opencode-go/…` für Go, `zen/…` für Pay-as-you-go). `config enable` wurde
   bewusst **nicht** verwendet; es hatte ohnehin abgelehnt
   (`refusing to replace user-owned model_catalog_json`).

   Eine Aktivierung der Go-Modelle im Console-UI ist **nicht** nötig: Der Proxy
   liest den Go-Katalog aus `GET /zen/go/v1/models` (38 Modelle, ohne Key
   lesbar). Die Schalter im Console-Workspace steuern die Modellliste der
   OpenCode-App, nicht die Gateway-Route.

2. **Provider-Block** in `~/.codex/config.toml`, hinter dem LM-Studio-Block;
   der OpenRouter-Block bleibt unverändert:

   ```toml
   [model_providers.opencode-go]
   name = "Go"
   base_url = "http://127.0.0.1:8787/v1"
   wire_api = "responses"
   requires_openai_auth = true
   ```

   `env_key` wurde am 26.10.2026 entfernt. Der lokale Proxy liest
   `OPENCODE_GO_API_KEY` aus seinem eigenen Environment; Codex sendet fuer die
   ChatGPT-authentifizierte Desktop-Sitzung den bestehenden Bearer, den der
   Proxy nicht an Go weiterreicht.

   **Nachtrag 03.11.2026:** Die Provider-Tabelle des Windows-Switchers
   (`[model_providers.opencode-proxy]`) folgt jetzt derselben Form
   (`requires_openai_auth = true`, kein `env_key`). `config enable` schreibt sie
   fuer `opencode-go` und `zen` ebenfalls so; `doctor` warnt bei `env_key`.
   Vorher wich der Switcher-Pfad vom hier dokumentierten Desktop-Setup ab, was
   Plugin-Schalter wieder auf HTTP 432 laufen liess.

3. **Overlay-Profil** `~/.codex/go.config.toml` (drei Zeilen: `model_provider`,
   `model`, `model_catalog_json` → `~/.codex/go-catalog.json`). Das Profil ist
   fuer die CLI gedacht und keine Desktop-Duplikation: Desktop-Providerwechsel
   laufen ueber `tools/codex-picker/switch-provider.ps1`, das die drei globalen
   Werte in `~/.codex/config.toml` austauscht.

4. **Katalog** über `tools/codex-picker/build_go_catalog.py` erzeugt: acht
   Einträge aus dem Proxy-Katalog, Anzeigenamen `Go · <Modell>`, `priority`
   0–7. Ersetzt bewusst den ganzen 26er-Katalog, weil `model_catalog_json` die
   Picker-Liste ersetzt statt ergänzt. `mimo-v2.6-flash` fehlt im Proxy-Katalog
   und ist durch `mimo-v2.5` ersetzt (gleicher Preis, ältere Generation);
   `build_go_catalog.py --check` bestätigt 8/8 geroutete Slugs.

5. **Smoke-Test** (beide Wege, 25.10.2026): direkt gegen den Proxy
   (`POST /v1/responses`, `deepseek-v4.1-flash`) → Antwort `OK`,
   `usage`: 37 Input-, 12 Output-Token, davon 10 Reasoning. Über Codex
   (`codex exec --profile go`) → Antwort `OK`, keine
   „Model metadata not found“-Warnung mehr. Der erste Lauf ohne Profil zeigte
   die Warnung — Beleg, dass der Katalog greift.

6. **Start** zuerst manuell per PowerShell (Entscheidung 25.10.2026), zusätzlich
   Task `opencode-go-proxy` bei der Anmeldung (30 s Verzögerung, unbegrenzte
   Laufzeit, `MultipleInstances IgnoreNew`).

## Messung der Cache-Quote (25.10.2026, echte Sitzung)

Eine Codex-Sitzung über `opencode-go/deepseek-v4.1-flash`, 85 Modellaufrufe,
protokolliert in `~/.codex/sessions/…jsonl` (`cached_input_tokens` je Turn):

| | |
| --- | --- |
| Input gesamt | 24.505.867 Token |
| davon aus dem Cache | 23.495.168 Token |
| **Cache-Quote** | **95,9 %** (letzte Turns 99,9 %) |

Das bestätigt die zentrale Annahme: Der Proxy vergibt eine Session-ID pro
Thread, Go bedient daraus den Prefix-Cache. Zum Vergleich in derselben Woche:
eine Sitzung ohne diesen Mechanismus (erster Aufruf, 98.917 Token) hatte 0 %.

Preislich (DeepSeek V4.1 Flash off-peak, 0,15 USD/1M Input, 0,003 USD/1M
Cache-Read):

- mit Cache: 23,50 M × 0,003 + 1,01 M × 0,15 = **0,22 USD**
- ohne Cache: 24,51 M × 0,15 = 3,68 USD

Also Faktor 16,5 — und 0,28 % des Go-Monatslimits von 80 USD für 85 Turns.


## Preisvergleich mit belastbaren Quellen (25.10.2026)

Die OpenRouter-API nennt für `deepseek/deepseek-v4.1-flash-1017` als
**Listenpreis des offiziellen Anbieters**:

| | Input / 1M | Output / 1M | Cache-Read / 1M |
| --- | --- | --- | --- |
| Go, off-peak | 0,15 USD | 0,60 USD | 0,003 USD |
| **OpenRouter (offizieller Anbieter)** | **0,15 USD** | **0,60 USD** | **0,003 USD** |
| Zen | 0,30 USD | 1,20 USD | 0,03 USD |

OpenRouter und Go liegen also **gleichauf**, inklusive derselben Peak-Aufschläge
(die API führt `pricing.overrides` mit 0,30/1,20 zwischen 01:00–04:00 und
06:00–10:00 UTC). Zen ist durchgehend doppelt so teuer wie Go off-peak.

Die günstigeren Anbieter in der Modellansicht (Open Inference 0,02 USD Input,
Morph/Relace 0,07, drei weitere 0,08) sind Drittanbieter-Routen hinter demselben
Gateway. Sie sind echt, aber nicht garantiert: OpenRouter kann dorthin oder zum
offiziellen Anbieter routen, und ob diese Routen Prompt-Caching anbieten, steht
nicht in den Preisdaten.

### Woher die Preisspanne kommt: zwölf Endpunkte, drei Quantisierungen

OpenRouter fragt die Modell-Endpunkte einzeln ab
(`GET /api/v1/models/deepseek/deepseek-v4.1-flash-1017/endpoints`). Für dieses
Modell sind es zwölf:

| Anbieter | Quantisierung | Input / 1M | Output / 1M | Cache-Read / 1M |
| --- | --- | --- | --- | --- |
| OpenInference | **fp4** | 0,02 USD | 1,00 USD | 0,015 USD |
| Relace | unbekannt | 0,07 USD | 0,50 USD | 0,008 USD |
| Morph | fp8 | 0,07 USD | 0,60 USD | 0,010 USD |
| DeepInfra | fp8 | 0,0784 USD | 0,2352 USD | **0,0024 USD** |
| InferenceNet | fp8 | 0,08 USD | 0,50 USD | 0,008 USD |
| Reka | unbekannt | 0,08 USD | 0,80 USD | 0,08 USD |
| Cloudflare | unbekannt | 0,10 USD | 0,60 USD | 0,003 USD |
| Sail Research | fp4 | 0,101 USD | 0,15 USD | 0,0067 USD |
| Wafer | mxfp4 | 0,13 USD | 0,50 USD | 0,008 USD |

Der billigste Input-Preis (0,02) gehört also zur **schwächsten Quantisierung
(fp4)**; die mittleren Preise sind fp8, die offizielle Route läuft in voller
Präzision. Preis und Qualität sind hier nicht unabhängig.

**Routing steuert man serverseitig.** OpenRouter verteilt standardmäßig
preisgewichtet (Gewicht 1/Preis²) über die gesunden Anbieter, nicht „immer der
billigste". Die drei Modi der Oberfläche entsprechen dem `provider`-Objekt im
Request: *Balanced* = Default-Load-Balancing, *Nitro* = `sort: "throughput"`,
*Floor* = `sort: "price"`. Weitere Felder: `only`/`ignore`, `order`,
`allow_fallbacks`, `quantizations`, `max_price`, `require_parameters`.

**Preset ist nicht Router.** Zwei verschiedene Dinge, die leicht verwechselt
werden:

- **Router** sind Modell-Slugs: `openrouter/auto` (Auto), `openrouter/pareto-code`
  (Pareto), `typesafe/jev-router` (Jev). Ihre Parameter gehen als `plugins` in
  den Request-Body, z. B. `{ "id": "auto-router", "cost_tier": "low",
  "allowed_models": [...] }`.
- **Presets** (`@preset/<slug>`) sind gespeicherte Konfigurationen mit
  Systemprompt, Modellauswahl und Ausschlüssen sowie Laufzeitparametern
  (`temperature`, `top_k`, `reasoning`, `cache_enabled`, `cache_ttl_seconds`).
  Sie werden wie ein Modell aufgerufen.

In Codex gibt es nur den Modell-Slug, also Router und Preset gleichermaßen —
Router-Parameter lassen sich dort nicht setzen. In OpenCode trägt
`providers.openrouter.models.<id>.body` beides: den Slug als Schlüssel und die
Router-Parameter im Body.

**Einfacher als Presets: Routing-Varianten im Slug.** `:floor` und `:nitro` sind
keine eigenen Katalogeinträge, sondern Suffixe, die auf **jedem** Modell-Slug
funktionieren („routing variants are accepted on any model ID at request time").
`:floor` sortiert nach Preis und lässt zusätzlich Flex-Tier-Endpunkte zu,
`:nitro` sortiert nach Durchsatz. Damit lässt sich Routing ohne Preset und ohne
`provider`-Block steuern — Codex schickt den Slug, OpenRouter wertet ihn aus.
Die Metadaten bleiben die des Basismodells.

**Aber `:floor` kauft bei diesem Modell die schwächste Route.** Es optimiert den
*gelisteten* Preis und landet damit auf dem fp4-Endpunkt zu 0,02 USD — dessen
Cache mit 0,015 USD aber teurer ist als der von DeepInfra fp8 (0,0024). Für
cache-lastige Agentenarbeit ist `:floor` deshalb nicht die günstigste, sondern
nur die billigst-gelistete Variante. Wer Qualität und Cachekosten zugleich
kontrollieren will, braucht ein Preset mit `quantizations: ["fp8"]` und
`sort: "price"` (oder `only: ["deepinfra"]`).

Für die gemessene Sitzung (95,9 % Cache) wäre DeepInfra fp8 mit 0,0024 USD
Cache-Read die günstigste Route: rund 0,16 USD gegen 0,27 USD auf der
offiziellen Route und 0,46 USD über den fp4-Anbieter — letzterer wird durch
seinen teuren Cache (0,015) trotz niedrigem Input-Preis unattraktiv.


### Was das für die gemessene Sitzung bedeutet

85 Turns, 24,51 M Input (95,9 % gecacht), 0,085 M Output:

| Route | Rechnung | Ergebnis |
| --- | --- | --- |
| Go off-peak | 23,50 × 0,003 + 1,01 × 0,15 + 0,085 × 0,60 | **0,27 USD** Kontingent |
| Go, tatsächlicher Beitrag | 0,27 USD von 80 USD Limit bei 10 USD Beitrag | **≈ 0,034 USD** |
| OpenRouter, offizieller Anbieter | wie Go, ohne Rabatt | 0,27 USD |
| OpenRouter, billigster Anbieter (0,02/1,00, ohne Cache) | 24,51 × 0,02 + 0,085 × 1,00 | 0,58 USD |
| Zen | 23,50 × 0,03 + 1,01 × 0,30 + 0,085 × 1,20 | 1,11 USD |

Und für eine cache-kalte, input-lastige Aufgabe (1 M Input, 10 k Output):

| Route | Ergebnis |
| --- | --- |
| OpenRouter, billigster Anbieter (0,02) | 0,03 USD |
| Go off-peak (0,15) | 0,16 USD Kontingent · ≈ 0,020 USD Beitrag |
| Zen (0,30) | 0,31 USD |

**Fazit:** Go ist für agentische Arbeit mit hoher Cache-Quote die günstigste
Route — nicht wegen des Input-Preises, sondern wegen des Cache-Reads
(0,003 gegen 0,03 bei Zen) und des Abo-Rabatts (10 USD für 80 USD Kontingent,
also ein Achtel). Bei cache-kalten Aufgaben gewinnt OpenRouter über
Drittanbieter-Routen nach Listenpreis, gegen den Abo-Beitrag bleibt Go aber
knapp vorn. Der Rabatt gilt anteilig: Wer das Kontingent nur zur Hälfte nutzt,
zahlt effektiv den doppelten Preis.

**Nebenbefund:** Der Artificial-Analysis-Index für dieses Modell liegt bei
**39,5** — knapp unter der 40er-Schwelle des geplanten Picker-Filters
(PLANUNG 19). Ein Filter mit genau 40 würde das meistgenutzte Go-Modell
ausschließen.


## Fallstricke

- **Kein `config enable`.** Es schreibt `openai_base_url` in den Wurzelbereich
  von `config.toml` (kein Umgebungswert, ein Konfigurationsschlüssel) und
  ersetzt `model_catalog_json`. Beides ist hier falsch: `openai_base_url`
  leitet die native ChatGPT-Route durch den Proxy, der Katalogtausch löscht die
  OpenRouter-Presets.
- **Picker-Semantik.** `model_catalog_json` ersetzt die eingebaute Modellliste,
  statt sie zu ergänzen. Deshalb zeigt Codex derzeit ausschließlich die 18
  OpenRouter-Einträge und keine nativen OpenAI-Modelle — das ist die Folge der
  gewählten Konfiguration, kein Fehler. Ein Katalogeintrag hat kein
  Provider-Feld; welcher Provider bedient, entscheidet `model_provider`. Mischen
  geht nur über Profile (`model_provider = "openai"` mit eigenem Katalog).
- **Provider und Katalog müssen zusammenpassen.** Ein OpenRouter-Slug bei
  `model_provider = "opencode-go"` schlägt fehl.
- **Privacy/Regionen.** DeepSeek V4 verlangt „Global“ unter Regions, Muse Spark
  Contributor zusätzlich die Freigabe für Trainings-Endpunkte.
- **Limits.** 5 h = 20 %, Woche = 50 %, Monat = 100 % des Modelllimits.
- **Namenskollisionen.** `gpt-6-luna`, `claude-haiku-5-5` und
  `deepseek-v4.1-flash` existieren unter mehreren Connections; welcher Anbieter
  bedient, entscheidet die Console, nicht der Client.
- **Kein Plugin, sondern MCP.** Codex hat kein OpenCode-Console-Plugin wie die
  Desktop-App. Was es gibt, ist ein MCP-Endpunkt für die Workspace-Verwaltung:
  `codex mcp add opencode-console --url https://opencode.ai/console/mcp`.
  Das liefert Modelle, Guthaben und Aktivität, aber keine Modellroute.
  **Installiert am 25.10.2026.**
- **API-Key für den Proxy.** Ein eigener Console-Key (`codex-gateway`) hält den
  Zugriff widerrufbar und vom OpenRouter-Zugang getrennt. Notwendig ist allein
  `Models: Request`; die übrigen Leserechte und `Providers: Write` braucht der
  Proxy nicht.
- **Codex Desktop kennt keine Profile.** Der Umschalter ist ein offener
  Feature-Request (`openai/codex#39527`); `profile = "…"` als Top-Level-Schlüssel
  wurde in 0.134 entfernt, `-p/--profile` wirkt nur in der CLI. Die App liest
  ausschließlich `config.toml`. Deshalb entscheiden `model_provider`, `model` und
  `model_catalog_json` im Wurzelbereich darüber, welche Modelle im Picker
  erscheinen — umschalten mit `tools/codex-picker/switch-provider.ps1`.
- **`codex` muss im PATH liegen, sonst schweigt der Proxy.** Fehlt die CLI,
  meldet er beim Start `catalog.refresh.skipped: codex CLI not found; set
  OPENCODE_GO_PROXY_CODEX_BIN to its path`. Der Server läuft trotzdem, aber der
  Katalog wird nicht aufgefrischt. Abhilfe: `OPENCODE_GO_PROXY_CODEX_BIN` auf
  die Binary setzen (Befund aus der ersten Einrichtung am 24.10.2026).
- **Codex nach Änderungen vollständig beenden** (auch Tray/App-Server); die
  Desktop-App liest `config.toml` nur beim Start.
- **Codex-Anmeldung kann ablaufen.** Am 25.10.2026 war der ChatGPT-Refresh-Token
  abgelaufen: `codex_login … refresh token has expired`, dazu 401
  `token_expired` von den MCP-Servern. Die Go-Route lief trotzdem. Abhilfe:
  `codex login`.

## Offene Punkte

**Erledigt am 25.10.2026**

1. Weg C, Session-ID durch den Proxy — gemessen: **95,9 % Cache-Quote** über 85
   Turns (Abschnitt oben).
2. Slug-Form `opencode-go/<id>`, geprüft von `build_go_catalog.py --check`
   (8/8).
3. **Picker-Feinschliff:** Kimi K3 über OpenRouter aufgenommen
   (`moonshotai/kimi-k3`, 0,239/10,80 USD je 1M, AA 43,6). Der Katalog hat jetzt
   19 Einträge, `build_picker_catalog.py` hat ihn gebaut, Loader-Verify ok.
   Native OpenAI-Modelle bleiben bewusst draußen: Ein Katalog kann nur einen
   Provider bedienen (`model_provider` ist global), ein OpenAI-Eintrag würde
   über den Go-Proxy laufen und scheitern.
4. Codex-Anmeldung erneuert (`codex login status` → „Logged in using ChatGPT").

**Offen**

5. Skill zur Modellpflege des Pickers (Filter Input < 0,5 USD/1M, AA-Index > 40)
   — Konzept in PLANUNG 19.
6. **Gelöst am 25.10.2026 — Plugin-Verwaltung in Codex Desktop:** Mit
   `model_provider = "opencode-go"` scheiterten Plugin-Schalter an Status 432,
   weil ein Provider mit `env_key` nicht als ChatGPT-authentifizierte Sitzung
   gilt und der App das `workspaceRouting` fehlt.
   `requires_openai_auth = true` im Provider-Block behebt das: Die App behält
   ihre Sitzung, die Go-Modelle erscheinen im Picker, und Plugins lassen sich
   wieder umschalten (vom Nutzer bestätigt). Am 26.10.2026 wurde der dann
   redundante `env_key` entfernt. Codex sendet die ChatGPT-Sitzung an den
   lokalen Proxy; der Proxy ignoriert den eingehenden Bearer und nutzt selbst
   `OPENCODE_GO_API_KEY`. Der Token bleibt auf dem Rechner; der Proxy
   protokolliert keine Header.
7. MiMo V2.6 / V2.6 Flash: **entschieden, so lassen.** Der Proxy kennt die
   Familie nicht („no certified protocol family"), der direkte Go-Aufruf
   antwortet 200 mit `billing_source: go`. Ein lokaler Fork wäre dauerhafte
   Abweichung für ein Modellpaar; `user-models.json` bleibt als Vorbereitung
   liegen, damit ein Upstream-Update sofort greift.

## Quellen

- `https://opencode.ai/docs/go` — Pläne, Modellliste, Preise, Limits, validierte
  Clients und die Session-Header-Aussage zu Codex
- `https://opencode.ai/docs/console/harnesses` — Harness-Tabelle (Codex nur
  Responses)
- `https://developers.openai.com/codex/config-reference` — `wire_api` nur
  `responses`, Katalogschlüssel
- `https://docs.litellm.ai/docs/proxy/forward_client_headers` — Allowlist für
  durchgereichte Header
- `https://github.com/kartikkabadi/opencode-go-proxy` — Proxy, Katalog, Doctor
- `GET https://openrouter.ai/api/v1/models` — Preise (`pricing.prompt`) und
  Artificial-Analysis-Indizes (`benchmarks.artificial_analysis`) je Modell
- eigene Messungen 25.10.2026 (siehe Tabellen oben)
