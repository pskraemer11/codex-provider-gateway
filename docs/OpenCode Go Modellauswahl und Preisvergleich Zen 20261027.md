# OpenCode Go Modellauswahl und Preisvergleich Zen, Stand 27.10.2026

Alles belegt. Zwei Antworten.

---

# 1. Watchdog: ja, das geht — drei Wege

**Messwerte zuerst**, weil sie die Entscheidung tragen:

| Größe                                     | Wert                                             |
| ----------------------------------------- | ------------------------------------------------ |
| Proxy-Prozesskette (`uvx` + 2× `python` ) | **7,8 MB** Working Set                           |
| Kaltstart bis `/health` 200               | ~1 s (uvx-Cache warm)                            |
| Kollision mit anderen Apps                | **keine** — siehe unten                          |
| Lücke heute                               | nach Codex-Start bis zu **60 s** ohne Go-Modelle |

**Warum „läuft immer" nichts kaputt macht** (geprüft, nicht vermutet):
- `opencode.jsonc` enthält **keinen** Verweis auf 8787; OpenWork (`.openwork`, `AppData\Roaming\openwork`, `OpenWork Chat`) und Bionic (`AppData\Roaming\Bionic`) ebenfalls **0 Treffer**.
- Kein Systemproxy: `ProxyEnable=0`, kein `AutoConfigURL`, kein `HTTP_PROXY`.
- Der Proxy ist ein **passiver Listener** auf `127.0.0.1:8787`. Er greift nur, wenn ein Client ihn adressiert — und das tut ausschließlich `config.toml` von Codex.

### Option A — Dauerbetrieb per Autostart (Empfehlung)

Der Grund für das sichtbare Fenster war **nicht** der Dauerbetrieb, sondern dass der Anmelde-Task `uvx.exe` direkt startete. Mit `hidden-run.vbs` ist das erledigt.

- Task `opencode-go-proxy` wieder aktivieren, Aktion auf `wscript.exe <hidden-run.vbs> <uvx…>` umstellen (wie bei den Watchdogs).
- Watchdog-Task `opencode-go-proxy watchdog` **deaktivieren**.
- Ergebnis: kein Minuten-Takt, keine Startlücke, kein Fenster, 7,8 MB.
- Preis: Der Proxy läuft auch, wenn Codex zu ist. Wenn dich das stört, bleibt ein langsamer Sicherheitsnetz-Check (10 min) für Crash-Recovery.

### Option B — Codex-Hooks (`SessionStart` / `SessionEnd`)

Codex 0.164.0 hat das: `codex features list` → `hooks stable true`, und die Doku beschreibt `SessionStart` (Matcher `startup|resume|clear|compact|fork`) und `SessionEnd`.

Startseitig ist das **besser** als ein Watchdog: `SessionStart` läuft vor dem ersten Modell-Request, der Hook kann synchron auf `/health` warten → der erste Request geht nie ins Leere.

```toml
[[hooks.SessionStart]]
matcher = "startup|resume"

[[hooks.SessionStart.hooks]]
type = "command"
command = 'pwsh -NoProfile -File "C:\...\tools\codex-picker\start-proxy.ps1"'
timeout = 20
```

**Aber der Stopp-Teil trägt nicht.** `SessionEnd` feuert **pro Session**, nicht pro App — und zwar auch beim Archivieren/Löschen einer Konversation oder nach 30 min Untätigkeit. Damit würde der Proxy sterben, während ein anderer Chat offen ist. Dazu kommt: Hooks müssen einmalig per `/hooks` getrustet werden (hash-basiert), und ob die Desktop-App den Trust-Dialog zeigt, müsste man erst verifizieren.

→ Als **Start**-Mechanismus gut, als **Stopp**-Mechanismus unbrauchbar.

### Option C — ein Daemon statt 1440 Task-Starts

Ein Prozess ab Anmeldung, der `Wait-Process`/15-s-Schleife fährt. Kein Task-Spam mehr, aber weiterhin Polling — und ein zusätzlicher Dauerprozess. Der Gewinn gegenüber heute ist kosmetisch.

### Korrektur zu deiner Vermutung

`[mcp_servers.sandbox-python-isolated]` steht in deiner `config.toml` auf **`enabled = false`** — es startet aktuell gar nichts. Das WSL-Fenster kam also nicht von dort. Der MCP-Weg wäre technisch möglich (Codex startet stdio-Server beim Sessionstart), aber er hat dasselbe Lebenszyklus-Problem wie Option B: kein verlässliches „kill beim Schließen".

**Meine Empfehlung: A.** Ereignisgetriebene Varianten sparen 7,8 MB und einen Listener — sie kosten aber die Crash-Recovery und bringen neue Fehlerquellen. Sag Bescheid, dann baue ich A um (Task-Aktion + Watchdog aus, inkl. Beleg im Log).

---

# 2. Go-Modelle vs. `go-catalog.json`

**Wichtig zur Einordnung:** Go und Zen sind zwei verschiedene Preislisten. Go ist das Abo ($10/Monat, Go Plus $40) mit **modell-eigenen Monatslimits**; Zen ist Pay-as-you-go. Die Preise sind teilweise identisch, bei DeepSeek weicht Go deutlich ab.

Stand heute: Go dokumentiert **30 Modelle**, der `/models`-Endpunkt liefert **38** (8 Altlasten ohne Doku-Preis). Preise je 1M Token, USD.

## Die 30 Go-Modelle 

„Picker" = steht in deiner `go-catalog.json`. „Route" = der gepinnte Proxy-Commit kennt die Protokoll-Familie (Quelle: `go_models.py` im uv-Cache).

| Modell                  | Input       | Output    | Cache-Read  | Limit/Monat | Picker | Route    |            |
| ----------------------- | ----------- | --------- | ----------- | ----------- | ------ | -------- | ---------- |
| Kimi K3.1 Pro           | 2,00        | 10,00     | 0,20        | $15         | –      | **nein** |            |
| Kimi K3                 | 3,00        | 15,00     | 0,30        | $15         | –      | ja       |            |
| Kimi K2.7 Code          | 0,95        | 4,00      | 0,19        | $60         | **✓**  | ja       |            |
| *GLM-5.3-Flash*         | *0,15*      | 0,50      | 0,03        | $60         | **✓**  | ja       |            |
| GLM-5.3                 | 1,40        | 4,40      | 0,26        | $15         | –      | ja       |            |
| GLM-5.2                 | 1,40        | 4,40      | 0,26        | $60         | –      | ja       |            |
| *DeepSeek V4.1 Flash*   | *0,15/0,30* | 0,60/1,20 | 0,003/0,006 | $80         | **✓**  | ja       |            |
| DeepSeek V4 Pro         | 0,66/1,32   | 1,98/3,96 | 0,022/0,044 | $15         | **✓**  | ja       |            |
| Qwen3.8 Max             | 2,00        | 6,00      | 0,25        | $15         | –      | ja       |            |
| *Qwen3.8 Flash*         | *0,15*      | 0,47      | 0,016       | $30         | **✓**  | ja       |            |
| Qwen3.7 Plus            | 0,40/1,20   | 1,60/4,80 | 0,04/0,12   | $60         | –      | ja       |            |
| MiniMax M3              | 0,30        | 1,20      | 0,06        | $60         | **✓**  | ja       |            |
| *MiniMax M3.1 Flash*    | *0,15*      | 0,60      | 0,015       | $20         | –      | **nein** |            |
| *MiMo-V2.6-Fl ash*      | *0,14*      | 0,28      | 0,0028      | $60         | –      | **nein** |            |
| MiMo-V2.6-Pro           | 0,435       | 0,87      | 0,003625    | $15         | –      | **nein** |            |
| *MiMo-V2.5*             | *0,14*      | 0,28      | 0,0028      | $60         | **✓**  | ja       |            |
| MiMo-V2.5-Pro           | 0,435       | 0,87      | 0,003625    | $15         | –      | ja       |            |
| LongCat-2.0             | 0,30        | 1,20      | 0,006       | $60         | **✓**  | ja       |            |
| *Hy3*                   | *0,14*      | 0,58      | 0,035       | $60         | –      | ja       |            |
| Hy4 preview             | 0,834       | 2,50      | 0,042       | $30         | –      | ja       |            |
| Step 5 Preview          | 1,00        | 2,70      | 0,10        | $15         | –      | **nein** |            |
| *GPT 6 Luna*            | *0,10/0,20  | 0,50/0,75 | 0,01/0,02   | $15         | –      | **nein** |            |
| GPT 5.6 Luna            | 0,20/0,40   | 1,20/1,80 | 0,02/0,04   | $15         | –      | ja       |            |
| *Claude Haiku 5.5*      | *0,10/0,50  | 0,50/2,50 | 0,01/0,05   | $15         | –      | **nein** |            |
| Gemini 4 Argon (50 %)   | 2,00        | 10,00     | 0,10        | $30         | –      | **nein** |            |
| Muse Spark 1.3 Contrib. | 0,10        | 0,20      | 0,002       | $60         | –      | ja       | kein ZDR ! |
| Muse Spark 1.2 Contrib. | 0,10        | 0,20      | 0,002       | $60         | –      | ja       | kein ZDR ! |


Zweite Zahl bei DeepSeek = Peak/Off-Peak, bei Grok/GPT/Claude/Qwen3.7 = langes Kontextfenster. **Peak ist 01–04 und 06–10 UTC, Mo–Fr** → bei dir (UTC+1) **02:00–05:00 und 07:00–11:00**. Dein Vormittag liegt also komplett im Peak: DeepSeek kostet dann das Doppelte.

## Die 8 ausgewählten Modelle: Go gegen Zen

| Modell            | Go In/Out/Cache         | Zen In/Out/Cache | Bemerkung                    |
| ----------------- | ----------------------- | ---------------- | ---------------------------- |
| DeepSeek V4.1     | 0,15/0,60/0,003         | 0,30/1,20/0,006  | Go off-peak = halber         |
| Flash             | (off-peak)              |                  | Zen-Preis                    |
| DeepSeek V4 Pro   | 0,66/1,98/0,022         | 1,74/3,48/0,145  | Go ~2,6× günstiger, Cache    |
|                   | (off-peak)              |                  | ~6,6×                        |
| GLM-5.3-Flash     | 0,15/0,50/0,03          | 0,15/0,50/0,03   | identisch                    |
| Qwen3.8 Flash     | 0,15/0,47/0,016         | 0,15/0,47/0,016  | identisch                    |
| MiniMax M3        | 0,30/1,20/0,06          | 0,30/1,20/0,06   | identisch                    |
| Kimi K2.7 Code    | 0,95/4,00/0,19          | 0,95/4,00/0,19   | identisch                    |
| MiMo-V2.5         | 0,14/0,28/0,0028        | –                | nicht bei Zen gelistet       |
| LongCat-2.0       | 0,30/1,20/0,006         | –                | nicht bei Zen gelistet       |

## Drei Befunde, die du kennen solltest

1. **11 der 30 Go-Modelle kann der Proxy nicht routen** — darunter Kimi K3.1 Pro, GPT 6 Luna, Claude Haiku 5.5, Gemini 4 Argon und beide MiMo-V2.6. Der Commit `4a3729…` hat eine feste Familie-Tabelle; `--check` prüft nur, ob ein Slug **gelistet** ist, nicht ob er **routet**. Deshalb steht im Picker auch `mimo-v2.5` statt `mimo-v2.6-flash`. Ein Update des Pins würde die Auswahl deutlich erweitern.
2. **Die Limits sind pro Modell, kein gemeinsamer Topf.** Go gibt dir z. B. $80 für DeepSeek V4.1 Flash **und** $60 für GLM-5.3-Flash **und** $60 für LongCat — jeweils mit 20 %/5 h, 50 %/Woche. Go Plus hat eigene, nicht linear skalierte Limits.
3. **Cache-Read ist der eigentliche Hebel.** Bei DeepSeek V4.1 Flash kostet gecachtes Lesen $0,003 gegen $0,15 Input — Faktor 50. Deine gemessene Cache-Quote von 95,9 % ist der Grund, warum die 8er-Auswahl trotz niedriger Limits weit trägt.

Im `/v1/models`-Endpunkt stehen zusätzlich 8 Modelle ohne Doku-Preis: `glm-5.1`, `grok-4.6`, `omen-alpha`, `kimi-k2.6`, `minimax-m2.5`, `minimax-m2.7`, `qwen3.6-plus`, `qwen3.7-max`.

---

Soll ich als Nächstes (a) den Watchdog auf Dauerbetrieb umbauen, (b) den Proxy-Pin aktualisieren, damit die 11 fehlenden Modelle routbar werden, oder beides?