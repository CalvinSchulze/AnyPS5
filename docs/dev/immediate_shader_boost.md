# Immediate Shader Boost

> Dieses Dokument führt **nur die Spitze der laufenden Operation**. Erledigtes und
> überholte Annahmen werden ersetzt, nicht angehängt. Es ist kein Verlauf.

## Aktueller Stand

Messgrundlage: Sitzung mit `APS5_PROFILE_GPU=1 APS5_PROFILE_DRAW=1
APS5_TRACE_DISPATCH_GEOMETRY=1`, **~6,5 fps** (65 Presents / 10 s, 154 ms pro Frame).
Hardware: RTX 5080, Host-Subgroup 32.

Die GPU ist der Engpass, nicht CPU und nicht IO: `batch 8869 ms first to last command`
pro 10-s-Fenster → **~89 % Wall-Clock-Belegung**. Datei-IO spielt keine Rolle.

GPU-Zeit ist extrem schief verteilt (6059 ms pro 10 s):

| Programm | pro 10 s | Anteil | pro Frame |
|---|---|---|---|
| `0x800038be00` | 4314 ms | **71 %** | 66 ms |
| `0x80003e8700` | 1240 ms | 20 % | 19 ms |
| 10 weitere zusammen | 505 ms | 8 % | — |

## Aktives Ziel: `0x800038be00`

### Gast-Shader — klein

- **818 RDNA-Instruktionen** in 1288 Code-Words, **102 Blöcke**, **8 Schleifen**
  (Back-Edges 29→9, 51→46, 58→53, 65→60, 79→75, 85→81, 91→87, 97→93;
  Hauptschleife `[9..29]`, 21 Blöcke, 164 Instruktionen).
- Grid `240x135x1` Gruppen x `16x16x1` Threads = **8.294.400 Guest-Threads** (4K-Pass).
- `wave64`, LDS 640 dwords (2560 B), 2 User-Data-Words, 10 Memory-Regionen.
- 6 Buffer format-spezialisiert (4→11, 5→60, 6→18, 8→18, 10→5, 11→60), 1 Image-Mode
  aus 21 aufgelöst.

### Erzeugter SPIR-V — 102x so groß

| | gemessen |
|---|---|
| Words | **131.449** |
| Instruktionen | 30.244 |
| Basisblöcke | **2.623** (Entry-Funktion 2.388 = 96 % des Codes) |
| Deklarationen / Funktionscode | 16.320 (12,4 %) / 115.129 (87,6 %) |
| Blockgröße | Median **7 Words**, Mittel 41,9, Max 5.857 |
| `OpLoopMerge` / `OpSelectionMerge` | 10 / **667** |

**102 Quell-Blöcke → 2.623 emittierte Blöcke.** Der Median-Block hat 7 Words, also
ein bis zwei Instruktionen: die Kontrollfluss-Struktur ist in Mikroblöcke zersplittert.

### Wave64 ist real, aber nicht die Hauptursache

A/B über `APS5_SINGLE_LANE=all`, das `laneCount` von 2 auf 1 schaltet:

| | laneCount=2 (NVIDIA) | laneCount=1 | Faktor |
|---|---|---|---|
| Words | 131.449 | 69.258 | **1,90x** |
| Basisblöcke | 2.623 | 1.569 | 1,67x |
| `OpSelectionMerge` | 667 | 421 | 1,58x |
| `OpLoopMerge` | 10 | 10 | 1,00x |

Mechanismus: `SpirvEmitter.cpp:256` setzt `laneCount = 2`, wenn ein wave64-Programm auf
einem 32-Lane-Host-Subgroup läuft; `SpirvFlowEmitter.cpp:745` emittiert daraufhin jede
Instruktion zweimal, eine pro Wave-Hälfte (wave-uniforme Werte nur einmal, über
`WaveUniformValues`). `HostSubgroupSize` (`Recompiler.cpp:84`) liefert dafür
`target.subgroupSize` = 32.

**Entscheidend:** schon bei `laneCount=1` bleiben 69.258 Words aus 818 Instruktionen —
**85 SPIR-V-Words pro Guest-Instruktion** und **15,4x Block-Zersplitterung** (102 → 1.569).
Die Basis-Übersetzung ist der dominierende Faktor, Wave64 legt 1,90x darauf.

### Ein Drittel des Codes ist Lane-Maskierung

| Opcode | Instruktionen | Words | Anteil Words |
|---|---|---|---|
| `OpBitwiseAnd` | 3.347 | 16.735 | 12,7 % |
| `OpSelect` | 2.104 | 12.624 | 9,6 % |
| `OpLogicalAnd` | 1.307 | 6.535 | 5,0 % |
| Vergleiche (`INotEqual`, `IEqual`, `ULessThan`) | 2.033 | 10.165 | 7,7 % |
| Shifts (`ShiftLeft/RightLogical`) | 1.403 | 7.015 | 5,3 % |

**10.194 von 30.244 Instruktionen (34 %)** sind Bit-Extraktion, Prädikation und
Masken-Verknüpfung. Dazu passen die vielen `condition=execz`-Terminatoren im Quell-CFG:
RDNA prädiziert jede Vektor-Instruktion über EXEC, und das wird explizit nachgebaut.

### Separater Defekt: keine Konstanten-Deduplikation

| | Instruktionen | distinkt | redundant | Words |
|---|---|---|---|---|
| `OpConstant` | 2.389 | 174 | 2.215 | 8.860 |
| `OpConstantTrue` | 1.002 | 1 | 1.001 | 3.003 |
| `OpConstantFalse` | 695 | 1 | 694 | 2.082 |

**13.945 Words = 10,6 % des Moduls** sind reine Duplikate; `OpConstant` Typ `%1` Wert `0`
allein 1.023-mal. Bei `0x80003e8700` sind es 14,4 %. Der Emitter hat keinen
Konstanten-Cache.

Das ist ein **Compile-Zeit-Kostenpunkt, kein GPU-Zeit-Kostenpunkt** — der Treiber faltet
Duplikate trivial. Es erklärt also nichts von den 66 ms, wohl aber einen Teil der
`recompile 49,9 s` aus der Sitzung. Nicht mit fps-Erwartung anfassen.

### Zweiter Shader `0x80003e8700` (20 % GPU-Last, 19 ms)

428 Code-Words, 230 Instruktionen, 14 Blöcke und **keine einzige Back-Edge** →
**26.939 SPIR-V-Words** (63x), 876 emittierte Blöcke, `8x8x1` Threads, wave64, LDS 0.
laneCount-Faktor 1,35x. Pro Invocation mit 9,200 ms/Mio. der teuerste der großen Pässe —
schleifenfrei.

## Codegröße erklärt die Kosten nicht

Alle Programme der `[gputime]`-Liste wurden gegen ihre Dumps nachgerechnet. Die
Expansion ist überall ähnlich groß (21x bis 284x) und läuft den Kosten **nicht** mitlaufend:

- `0x8000269d00` trägt **711.493** SPIR-V-Words — 5,4x so viel wie der Flaschenhals —
  und kostet 2,38 ms gegen 66,37 ms.
- `0x80003cd800` trägt **186.103** Words, mehr als der Flaschenhals, und kostet 0,20 ms.
- `0x80003f3600` trägt 23.396 Words bei **identischer Invocation-Zahl** und kostet 0,55 ms.

Die 102x Expansion, die 15x Block-Zersplitterung und die 34 % Masken-Ops sind damit
**kein hinreichender Grund** für die 66 ms — sonst müssten die beiden größten Module die
Liste anführen. Codegröße ist als Haupterklärung ausgeschlossen.

## Phase A durch: es sind die Guest-Buffer, nicht die Pixel

`APS5_TRACE_DISPATCH_GEOMETRY=1` lieferte die Grids aller 86 Programme, die Threads pro
Gruppe kommen aus dem Replay. `ms/Frame` = `ms pro 10 s` / 65 Presents.

| Programm | ms/Frame | Grid | Threads | Invocations | **ms/Mio. Inv** | Buffers | Regionen | Images |
|---|---|---|---|---|---|---|---|---|
| `0x8000269d00` | 2,38 | 1x64x36 | 4x4x4 | 147.456 | 16,172 | 24 | 46 | 29 |
| `0x80003e8700` | 19,08 | 240x135x1 | 8x8x1 | 2.073.600 | 9,200 | 3 | 10 | 2 |
| `0x80003bfe00` | 1,14 | 60x34x1 | 8x8x1 | 130.560 | 8,720 | — | — | — |
| `0x800038be00` | **66,37** | 240x135x1 | 16x16x1 | **8.294.400** | **8,002** | **12** | **10** | 1 |
| `0x80003ed000` | 0,86 | 64x32x1 | 8x8x1 | 131.072 | 6,573 | — | — | — |
| `0x7ff6b46cf600` | 0,37 | 2040x1x1 | 64x1x1 | 130.560 | 2,828 | — | — | — |
| `0x80003cd800` | 0,20 | 64x36x1 | 4x4x4 | 147.456 | 1,356 | 3 | 6 | 2 |
| `0x80003e6400` | 1,05 | 240x135x1 | 8x8x1 | 2.073.600 | 0,505 | 1 | 4 | 3 |
| `0x80003f3600` | 0,55 | 480x270x1 | 8x8x1 | **8.294.400** | **0,067** | 1 | 3 | 3 |
| `0x8000405300` | 0,25 | 480x270x1 | 8x8x1 | **8.294.400** | **0,030** | 0 | 3 | 5 |
| `0x8000423300` | 0,11 | 480x270x1 | 8x8x1 | **8.294.400** | **0,013** | 0 | 3 | 2 |

(`0x800035d400`: 64 Invocations bei 1x1x1-Grid, 1442 ms/Mio. — Launch-Overhead, kein
Signal.)

**Der kontrollierte Vergleich:** vier Programme fahren exakt dieselben 8.294.400
Invocations, dieselbe wave64, dieselbe Hardware. Drei davon kosten 0,013–0,067 ms pro
Mio. Invocations, `0x800038be00` kostet **8,002** — ein Faktor **120x bis 600x**.

Damit ist es **kein Auflösungsproblem**: andere Voll-4K-Pässe sind praktisch gratis.
Es ist ein Pro-Invocation-Ausreißer.

**Und es sind nicht die Schleifen.** `0x80003e8700` hat **null Back-Edges** (13 Blöcke,
230 Instruktionen) und kostet pro Invocation mit 9,200 sogar *mehr* als der Flaschenhals.
Trip-Counts können die gemeinsame Ursache nicht sein.

**Was übrig bleibt und monoton mitläuft, ist die Zahl der Guest-Buffer:**
0 Buffer → 0,013 / 0,030 · 1 Buffer → 0,067 / 0,505 · 3 Buffer → 1,356 / 9,200 ·
12 Buffer → 8,002 · 24 Buffer → 16,172. Images korrelieren nicht (die billigsten Pässe
haben die meisten).

### Die V#-Deskriptoren von `0x800038be00`

Aus `--mem`, dekodiert (dword1 Bits 29:16 = Stride, dword2 = num_records):

| Buffer | Stride | num_records | Größe | Format | geschrieben |
|---|---|---|---|---|---|
| 4 | **2 B** | **8.294.400** | 16,6 MB | 11 | ja |
| 10 | **1 B** | 8.165.312 | 8,2 MB | 5 | ja |
| 7, 9 | 4 B | 1.036.800 | je 4,1 MB | — | ja |
| 5, 11 | 4 B | 32.400 | je 130 KB | 60 | ja |
| 6, 8 | 2 B | 32.400 | je 65 KB | 18 | ja |
| 0 | 80 B | 1.024 | 82 KB | — | nein |
| 1 | 256 B | 1.024 | 262 KB | — | nein |

Buffer 4 hat **genau einen Record pro Invocation** bei 2 Byte Stride; Buffer 10 ebenso
bei 1 Byte. Sechs der zwölf werden geschrieben.

**Bandbreite ist es nicht:** ~34 MB adressierbar pro Dispatch in 66 ms sind
**~0,5 GB/s effektiv**, auf einer GPU mit ~960 GB/s. Das Speichersystem ist nahezu
unbeschäftigt — die Kosten stecken im Overhead *pro Zugriff*, nicht im Volumen.

Dazu passen die gemessenen 34 % Bit-Manipulation im emittierten Code: Sub-Dword-Zugriffe
(Stride 1 und 2 Byte) auf format-spezialisierte Buffer werden mit Shift/Mask/Select
nachgebaut.

## Offen — eine Frage, kein Suchfeld

Die verbleibende Unbekannte ist, ob der Pro-Zugriff-Overhead aus **Instruktionszahl**
oder aus **Latenz/Occupancy** kommt. Das entscheidet zwischen zwei völlig verschiedenen
Fixes und lässt sich in-project nicht trennen — das Projekt hat kein
`VK_KHR_performance_query`.

**B — Nsight Compute oder Nsight Graphics GPU Trace auf den Dispatch von
`0x800038be00`.** Konkrete Frage: SM-Throughput gegen Memory-Throughput, Occupancy,
und die Stall-Gründe an den Buffer-Load-Stellen. `sm__inst_executed` geteilt durch
8.294.400 gibt zusätzlich die real ausgeführten Instruktionen pro Invocation.

**C — flankierend, in-project:** `APS5_SINGLE_LANE=800038be00` preist die gemessenen
1,90x Codegröße in Millisekunden um (`HostSubgroupSize`, `Recompiler.cpp:84`, matcht die
Adresse als Teilzeichenkette). Semantik ändert sich dabei (Cross-Lane über Workgroup-
statt Subgroup-Scope), Bild also auf Korrektheit prüfen. Nach dem Befund oben ist davon
wenig zu erwarten — Codegröße erklärt die Kosten nicht —, aber es ist ein Lauf.

**Methodik:** `[gputime]` aggregiert über 10-s-Fenster, Läufe müssen dieselbe Szene
zeigen (gleicher Spielstand, Kamera geparkt, mehrere Fenster vergleichen), und der
Shader-Disk-Cache muss gleich warm sein. `[gputime] by program` braucht
**`APS5_PROFILE_GPU`** (`Recorder.cpp:1800`); `APS5_PROFILE_DRAW` allein liefert nur die
Batch-Stempel.

## Nachgelagert (nicht starten, bevor das aktive Ziel steht)

**Resource-Cache-Anomalie.** Drei Zahlen passen nicht zusammen:

- Kapazität **1024** (`APS5_RESOURCE_CACHE_ENTRIES`, `ShaderResources.cpp:2422`),
  belegt aber nur **163** Einträge — der Cache läuft nicht über.
- Nur **10** Invalidierungen.
- Trotzdem **631.372 Misses mit unverändertem Key** von 960.898 Misses gesamt
  (gegen 2.075.345 Hits).

Verdacht: Einträge werden nicht eingefügt oder direkt wieder entfernt. Unverifiziert —
nicht cachebare Objekte sind eine legitime Erklärung. Treibt die ~960.000 vollen
Resource-Builds und damit den Großteil von `B images` (581 s) und
`[guestmem] collect` (466 s / 13,8 M Calls).

Zweiter Miss-Grund: **222.871 Misses aus V#-Wort 0** — Basisadresse von
Ring-Allocations churnt den Content-Key, obwohl die Ressource äquivalent ist.
Fix-Richtung: auf Offset-im-Ring statt Absolutadresse keyed.

**`B images` aus dem GPU-Mutex holen** — 581 s serialisiert unter dem globalen
Mutex. Erst relevant, wenn die GPU entlastet ist.

## Werkzeuge

```
APS5_DUMP_SHADERS=1 APS5_PROFILE_DRAW=1 APS5_TRACE_DISPATCH_GEOMETRY=800038be00 .\app.exe
agc_shader_replay [--asm] [--cfg] [--spv] shader_800038be00.req
APS5_SINGLE_LANE=all agc_shader_replay ...     # laneCount=1 zum Vergleich
```

`agc_shader_replay` braucht `libc.prx` im `PATH`. `--cfg` gibt pro Block
`words=` aus — das ist `estimatedSpirvWords`, eine **Heuristik** des Structurizers,
keine Messung des Ergebnisses; für echte Größen den `--spv`-Dump auswerten.

## Referenz: Kostenverteilung CPU-Seite

Thread-Summen über 3.037.000 Dispatches, nicht Wall-Clock. `stage A`/`stage B` in den
`[resources]`-Zeilen sind **Summen** der Unterphasen (`precollect` in A, `images` in B) —
nicht addieren.

| Posten | Zeit |
|---|---|
| `resources: B images` (unter GPU-Mutex) | 581 s |
| `[guestmem] collect` | 466 s |
| `resources A (unlocked)` | 208 s |
| `proof` | 109 s |
| `[guestmem] compare` | 78 s |
| `record` (davon `marks` 35 s) | 59 s |

`[storage]`: ~55 GB Uploads + Write-backs pro 10 s (≈5,5 GB/s PCIe-Churn).
