# Codex vs. OpenCoden Vergleich bzgl. Sandbox vs Safety-Guard
* OpenCode / DeepSeek V4.1-Falsh, 26.10.2026

## Kurzfassung

Codex fragt nicht weniger, weil es besser klassifiziert — es fragt an einer **anderen Stelle**. 
OpenCode prüft *Befehle*, Codex setzt eine **Grenze im Betriebssystem** (Schreibrechte + Netz) und lässt innerhalb dieser Grenze alles laufen. 
Das ist der ganze Unterschied, und er lässt sich in OpenCode nicht durch bessere Regeln nachbauen.

Bestätigt: Codex ist Open Source (Apache-2.0, `openai/codex`, 131 k Sterne, heute noch gepusht). Bei dir läuft `codex-cli 0.164.0`.

## Was Codex anders macht

|                    | Codex                                                                            | OpenCode + permission-guard                |
|--------------------|----------------------------------------------------------------------------------|--------------------------------------------|
| Durchsetzung       | OS-Sandbox: Write-Restricted Token + synthetische SID + ACLs, Netz per Firewall  | Klassifizierer im Plugin, kein OS-Boundary |
| Entscheidungsfrage | „Verlässt die Aktion die Grenze?"                                                | „Ist dieser Befehl beweisbar harmlos?"     |
| Standard           | **allow** innerhalb Workspace, ask nur beim Grenzübertritt                       | **ask**, allow nur nach Beweis             |
| Prüfzeitpunkt      | nachher, wenn die Sandbox den Befehl abbrechen lässt (Eskalation)                | vorher, pro Befehl                         |
| Lernen             | „Allow" schreibt eine `prefix_rule` in `~/.codex/rules/default.rules`            | keine Erinnerung; jeder Aufruf neu         |
| Skriptzerlegung    | tree-sitter; pro Teilbefehl, restriktivster gewinnt                              | eigene Segmentierung, quote-blind          |

Zwei Punkte daraus sind für dich praktisch wichtig:

**1. Codex prüft Wirkung, nicht Wortlaut.** `rg`, `Get-PhysicalDisk`, `nvidia-smi`, `Get-AppxPackage`, `pwsh -File deploy.ps1` — alles läuft ohne Rückfrage, 
weil es die Grenze nicht verlässt. Deine häufigsten Rückfragen (`nvidia-smi.exe -L`, `Get-PhysicalDisk`, `pnputil /enum-drivers`) hätte Codex **nie** gefragt.

**2. Der Preis ist explizit.** 
In Codex `workspace-write` darf der Agent den Workspace **ohne Rückfrage zerstören** — `rm -rf` auf das Repo inklusive! 
Geschützt sind nur `.git`, `.codex`, `.agents`, `.aws` (rekursiv, read-only). Codex schützt die *Maschine*, nicht dein *Projekt*. 

OpenCode schützt beides, deshalb fragt es.

## Deine Codex-Config ist schon auf diesem Modell

```
approval_policy     = "on-request"
sandbox_mode        = "workspace-write"
network_access      = true          # Netz an
trust_level         = "trusted"     # 8 Projekte
[windows] sandbox   = "unelevated"
```

Das erklärt die Entspannung vollständig. Der Windows-Sandbox-Ansatz ist übrigens aus demselben Grund entstanden wie dein Guard: OpenAI schreibt selbst, 
Windows-Nutzer hätten vorher nur die Wahl gehabt zwischen „fast jeden Befehl bestätigen, auch Lesen" und „Full Access". 
Sie haben es **nicht** mit einem besseren Klassifizierer gelöst, sondern mit einem OS-Boundary (Doku: „Building a safe, effective sandbox to enable Codex on Windows", 13.05.2026). 
Der `unelevated`-Backend, den du fährst, ist die Variante ohne Admin-Setup: eingeschränktes Token + synthetische SID + ACLs, Netz nur „advisory" gedrosselt 
— bei dir ohnehin irrelevant, weil `network_access = true`.

## Warum das in OpenCode nicht direkt geht

Die Permission-Schicht in OpenCode ist **kommandoförmig** (`shell`, `edit`, `read`, `external_directory` mit Mustern). 
`shell` läuft mit den Rechten deines Benutzers — es gibt keine Grenze, die man prüfen könnte. 
Also bleibt nur Vorab-Klassifikation, und die kann prinzipbedingt nur freigeben, was sie beweisen kann. 
Deine 48,9 % allow sind das Maximum dieser Bauart, nicht ein Zwischenstand.

## Woher die 129 Rückfragen wirklich kamen

Ich habe das Fenster 16:10–21:49 gegen `evaluate()` + die statische Liste des Reviewers nachgerechnet (`staging/measure-guard-noise.mjs`, nicht deployt):

```
allow 233 (62,0 %) · ask 143 (38,0 %) · deny 0
Reviewer-Band (nicht einordenbar): 126
  verschleiernder Operator :  51
  Risikomuster RISKY[0]    :  62
  sonstige Risikomuster    :  13
```

Zwei unangenehme Befunde, beide gegen die bisherige Deutung:

- **44 der 51 Operator-Treffer sind `2>&1`** (bzw. `*>&1`, `2>$null`). `guard.js` behandelt das längst korrekt — nur `reviewer.js` kennt die Ausnahme nicht. 
  Das ist zusätzlich **mein** Fehler: ich habe `2>&1` reflexhaft an jeden Befehl gehängt.

- ** RISKY[0] (`^(\S*['"\\=$]|[-0-9])`) trifft überwiegend Nicht-Befehle. ** 
  ** Die Segmentierung ignoriert Anführungszeichen, deshalb entstehen Fragmente wie `XDNA' }`, `REV_00\4`, `IPU' }`; dazu absolute Windows-Pfade (`C:\Windows\System32\...` 
  — der Backslash steht in der Zeichenklasse) und `$var = ...`-Zuweisungen, die `guard.js` als `noop`/`read` einordnet, `reviewer.js` aber blockt. 
    Registriert: 12 Pfade, 15 Ziffer-/Bindestrich-Anfänge, 35 Zitat-/Zuweisungs-Fragmente.

Was die naheliegenden Änderungen leisten (nur Reviewer-Band, 126 Fälle):

| Variante                  | statisch blockiert | erreicht das Modell |
|---------------------------|--------------------|---------------------|
| heute                     |         114        |         12          |
| nur Redirection-Ausnahme  |         100        |         26          |
| nur Pfad-Ausnahme         |         105        |         21          |
| beides                    |          88        |       **38**        |

Und die Bremse danach: das Modell antwortete in deiner Statistik 19 von 29 Mal mit „Nein". Selbst mit perfekter statischer Liste bleibt also ein großer Teil bei `ask`. 
Der Reviewer ist heute nicht der Flaschenhals — die **Bauart** ist es.

## Optionen, geordnet nach Wirkung

**A — Boundary statt Klassifizierer (strukturell, das Codex-Modell).** 
OpenCode in einem Podman-Container mit bind-gemountetem Projekt, Netz aus, und `permissions.shell` breit auf `allow`. 
Damit ist die Rückfragefrequenz strukturell dieselbe wie bei Codex. 
Kosten: Projekt-Setup, WSL2-Pfad- und Ownership-Fragen, LibreOffice/llama.cpp-Zugriff aus dem Container, und der Guard wird innerhalb des Containers überflüssig. 
Das ist die einzige Variante, die dein Problem wirklich löst, und sie ist ein eigenes Projekt, kein Regel-Fix.

**B — Die zwei Fehlalarm-Familien entschärfen (billig, messbar).** 
In `reviewer.js`: `2>&1`/`*>&1`/`2>$null` aus dem Operator-Test nehmen (wie `guard.js` es schon macht), und `RISKY[0]` 
auf tatsächliche Befehlssegmente beschränken statt auf Zitat-Fragmente und Zuweisungen. 
Erwartung nach Messung: rund 25 zusätzliche Fälle erreichen das Modell, bei konservativem Anteil also ~10 Rückfragen weniger pro 5,5 h. 
Ehrlich: ein Tropfen, kein Durchbruch — aber risikoarm, weil `guard.js` die Schreibprüfung unabhängig macht.

**C — Meine Befehlsmode.** 
Kein `Write-Output "=== … ==="`, kein `2>&1`, keine dekorativen Zwischenüberschriften. 
Das allein hätte in diesem Fenster ~44 Rückfragen vermieden, ohne eine Zeile Code zu ändern. 
Das ist meine Bringschuld und ab sofort meine Vorgabe.

**D — Reviewer-Prompt nachschärfen.** 
Die Ja/Nein-Frage bestraft Lesen außerhalb des Projekts, obwohl der Prompt es erlaubt. 
`bench-quality.ps1` (18 Befehle) könnte eine zweite, positiv formulierte Frage gegen die jetzige messen. Eigener Punkt, kein Nebeneffekt.

## Empfehlung

Nicht B weiter drehen, bevor A entschieden ist — sonst optimiert man den Klassifizierer, obwohl die Grenze fehlt. Reihenfolge: **C sofort** (kostet nichts), 
**A als eigenes Vorhaben prüfen** (das ist der eigentliche Codex-Effekt), **B als Zwischenlösung** nur, wenn A verworfen wird. D lohnt erst nach B.

Soll ich das als PLANUNG-Punkt 23 mit Entscheidungslog festhalten und die Messung in `docs/` ablegen? Die Zahlen liegen reproduzierbar in `staging/measure-guard-noise.mjs`; 
ich würde sie beim Übernehmen nach `tools/permission-guard/` verschieben, damit sie nicht mit dem Temp-Ordner verschwindet.