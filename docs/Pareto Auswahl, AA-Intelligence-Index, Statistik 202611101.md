# Pareto Auswahl, AA-Intelligence-Index, Statistik 

* vgl. "$HOME\Python-Projekte\automatisierter Benchmark-Abgleich\data\AA-intelligence-index-scores.xlsx"

Die aktuelle Live-Auswertung vom 1. November 2026, 18:17 UTC ergibt:

- AA-API-Zeilen: 719
- davon mit nicht-leerem Intelligence Index v5: 89
- vollständige Population: Minimum 1,8, Maximum 59,4
- aktuell preisberechtigte Population: 16 Modelle, Minimum 5,5, Maximum 36,2

Vergleich der beiden Varianten

|                           | A: Preis zuerst,  | B: vollständige AA-Population   |
|                           | dann kalibrieren  | kalibrieren, dann Preis filtern |
|---------------------------|-------------------|---------------------------------| 
| Kalibrierungspopulation   |16 preisberechtigte|   89 AA-Modelle mit   |
|                           |   Treffer         |   Intelligence-Wert   |
| Skala                     | 5,5 bis 36,2      |     1,8 bis 59,4      |
| OpenRouter normal         |         6         |            0          |
| OpenRouter Free-Pins      |         2         |            2          |
| OpenCode Go normal        |         3         |            0          |
| Zen normal                |         2         |            0          |
| Zen Free-Pins             |         3         |            3          |
| Gesamt                    |        16         |            5          |
| Neue normale Modelle      |         –         |            0          |
| Entfernte normale Modelle |         –         |           11          |

Die fünf Free-Pins bleiben in beiden Varianten unverändert, weil sie nicht vom Score abhängen.

Für die relevanten Bezahlmodelle ergibt Variante B:

| Modell                    |Inputpreis|AA Intell. | Score A | Score B |
|---------------------------|---------:|----------:|--------:|--------:|
| Claude Haiku 5.5          |  $0,10   |    36,2   |  100,0  |  59,7   |
| DeepSeek V4.1 Flash 1017  |  $0,035  |    32,5   |   87,9  |  53,3   |
| GLM-5.3                   |  $0,08   |    31,7   |   85,3  |  51,9   |
| MiniMax M3.1 Flash        |  $0,075  |    28,9   |   76,2  |  47,1   |
| GPT-6 Luna                |  $0,10   |    27,8   |   72,6  |  45,1   |
| GLM-5.3 Flash             |  $0,15   |    27,8   |   72,6  |  45,1   |
| MiMo V2.6 Flash           |  $0,14   |    26,7   |   69,1  |  43,2   |

Damit ist das Ergebnis eindeutig: Variante B verändert die Auswahl sehr stark, bringt MiMo aber ebenfalls nicht über 70. 
Bei der vollständigen Population erreicht selbst das beste preisberechtigte Bezahlmodell nur 59,72.

Deine Aussage zur Nicht-Kommutativität ist fast präzise: Die beiden Prädikate Preis < Grenze und Score > 70 sind für sich kommutativ. 
Nicht kommutativ ist die Definition der Score-Skala:

calibrieren(Modellwerte | nur preisberechtigte Modelle)
≠
calibrieren(Modellwerte | alle verfügbaren Modelle)

Die Min-Max-Transformation ist innerhalb einer festen Population monoton, verändert aber bei einer anderen Population sämtliche Scores und damit die Bedeutung der Grenze 70.

Methodisch würde ich deshalb nicht einfach die aktuelle 70er-Grenze auf Variante B übertragen. Sinnvoll wären:

1. Eine versionierte, feste Referenzpopulation für AA Intelligence v5 und eine daraus abgeleitete dokumentierte Grenze.
2. Ein absoluter Rohwert-Cutoff statt eines bei jedem Lauf neu definierten 70/100.
3. Wenn die bisherige Auswahlgröße erhalten bleiben soll, müsste die Grenze für Variante B auf ungefähr 45,14 oder niedriger gesenkt werden. 
Für MiMo müsste sie unter 43,23 liegen.

Variante A liefert die intuitivere „beste günstige Modelle bis 100“-Skala, ist aber wegen der kleinen und veränderlichen Population instabil. 
Variante B ist über den Preisbereich hinweg vergleichbarer und stabiler, macht die bisherige 70/100-Grenze jedoch bedeutungslos.
---

In Variante B lautet die vollständige Population:

Minimum: 1,8
Maximum: 59,4

Der Maximalwert 59,4 gehört zu Gemini 4 Carbon (High). Dieses Modell wird deshalb auf 100 skaliert. 
Es kostet aber $4,00/M Input und fällt nach der Kalibrierung durch den Preisfilter.

Claude Haiku mit Rohwert 36,2 liegt innerhalb derselben B-Skala darunter:

(36,2 - 1,8) / (59,4 - 1,8) × 100 = 59,72

Damit ergibt sich:

| Modell                 |Rohwert| Inputpreis |A: preisbereinigt|B: vollständig|
|                        |       |            |   kalibriert    |  kalibriert  |
|------------------------|------:|-----------:|----------------:|-------------:|
| Gemini 4 Carbon (High) |  59,4 |    $4,00   |nicht preisberechtigt|  100,0   |
| Claude Haiku 5.5       |  36,2 |    $0,10   |      100,00     |       59,7   |
| GPT-6 Luna             |  27,8 |    $0,10   |       72,6      |       45,1   |
| MiMo V2.6 Flash        |  26,7 |    $0,14   |       69,0      |       43,2   |

Die beiden Varianten verwenden also unterschiedliche 100-Prozent-Anker:

- A: Das beste preisberechtigte Modell erhält 100. Deshalb erreicht Claude Haiku dort 100.
- B: Das insgesamt beste AA-Modell erhält 100. Das ist Gemini 4 Carbon mit 59,4; Claude Haiku erreicht dort nur 59,72.

Wenn dein gewünschtes Kriterium lautet „Das beste Modell unterhalb der Preisgrenze soll 100 erhalten“, dann ist das genau Variante A. 
Variante B ist nur dann sinnvoll, wenn 70/100 eine modellübergreifende, preisunabhängige Qualitätsgrenze darstellen soll. 
Bei der aktuellen B-Population müsste diese Grenze deutlich niedriger liegen.

