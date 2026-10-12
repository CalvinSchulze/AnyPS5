# Immediate Shader Boost

> Dieses Dokument führt **nur die Spitze der laufenden Operation**. Erledigtes und
> überholte Annahmen werden ersetzt, nicht angehängt. Es ist kein Verlauf.

## Aktueller Stand

Messgrundlage: `APS5_PROFILE_DRAW`-Sitzung, 38.441 Frames, ~94 min, **~6,8 fps**
(68 Presents / 10 s, 148 ms pro Frame). Hardware: RTX 5080 (Host-Subgroup 32).

Die GPU ist der Engpass, nicht CPU und nicht IO: `batch 8996 ms first to last command`
pro 10-s-Fenster → **~90 % Wall-Clock-Belegung**. Datei-IO spielt keine Rolle.

GPU-Zeit ist extrem schief verteilt (6201 ms pro 10 s):

| Programm | pro 10 s | Anteil | pro Frame |
|---|---|---|---|
| `0x800038be00` | 4411 ms | **71 %** | 65 ms |
| `0x80003e8700` | 1265 ms | 20 % | 19 ms |
| 10 weitere zusammen | 474 ms | 8 % | — |

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
Duplikate trivial. Es erklärt also nichts von den 65 ms, wohl aber einen Teil der
`recompile 49,9 s` aus der Sitzung. Nicht mit fps-Erwartung anfassen.

### Zweiter Shader `0x80003e8700` (20 % GPU-Last, 19 ms)

428 Code-Words, 14 Blöcke, 8 Schleifen → **26.939 SPIR-V-Words** (63x), 876 Blöcke,
`8x8x1` Threads, wave64, LDS 0. laneCount-Faktor 1,35x.

## Codegröße erklärt die Kosten nicht

Alle 12 Programme aus der `[gputime]`-Liste liegen als Dump vor und wurden
nachgerechnet (`ms/Frame` = `ms pro 10 s` / 68 Presents):

| Programm | ms/Frame | Code-Words | SPIR-V | Faktor |
|---|---|---|---|---|
| `0x800038be00` | **64,87** | 1288 | 131.454 | 102x |
| `0x80003e8700` | 18,60 | 428 | 26.939 | 63x |
| `0x8000269d00` | **2,38** | 4976 | **711.493** | 143x |
| `0x80003bfe00` | 1,09 | 808 | 84.838 | 105x |
| `0x80003e6400` | 1,07 | 440 | 74.287 | 169x |
| `0x80003ed000` | 0,85 | 380 | 26.630 | 70x |
| `0x80003f3600` | 0,56 | 336 | 23.396 | 70x |
| `0x7ff6b46cf600` | 0,37 | 60 | 1.275 | 21x |
| `0x8000405300` | 0,24 | 248 | 21.850 | 88x |
| `0x80003cd800` | **0,21** | 656 | **186.103** | 284x |
| `0x8000423300` | 0,12 | 132 | 11.443 | 87x |
| `0x8000414300` | 0,09 | 180 | 11.977 | 67x |

`0x8000269d00` hat **5,4x mehr SPIR-V** als der Flaschenhals und kostet **27x weniger**.
`0x80003cd800` hat 1,4x mehr Code und kostet 309x weniger. Die Expansion von 102x,
die 15x Block-Zersplitterung und die 34 % Masken-Ops sind also **kein hinreichender
Grund** für die 65 ms — sonst müssten diese beiden Programme die Liste anführen.

**Vorbehalt:** die Invocation-Zahlen der anderen Programme sind ungemessen. Die Tabelle
widerlegt „Kosten ∝ Codegröße", sie beweist noch nicht, woran es stattdessen liegt.

## Offen — das entscheidet die Richtung

1. **Invocations pro Programm.** Ohne sie ist nicht zu trennen, ob `0x800038be00` teuer
   pro Invocation ist oder einfach als einziges über den vollen 4K-Grid läuft. Das ist
   die billigste und am stärksten unterscheidende Messung.
2. **Schleifen-Trip-Counts.** 8 Schleifen, Hauptschleife 21 Blöcke. Datenabhängig und
   statisch nicht bestimmbar.
3. **ALU- oder Memory-bound, Occupancy, Registerdruck.** Das Projekt hat kein
   `VK_KHR_performance_query`, dafür braucht es Nsight.

### Messplan

**A — Invocations für alle Programme, ein Lauf, in-project.**

```
APS5_PROFILE_GPU=1 APS5_PROFILE_DRAW=1 APS5_TRACE_DISPATCH_GEOMETRY=1 .\app.exe
```

Die Sonde meldet einmal pro Programm `groups=` und `indirect=`; mit den Threads pro
Gruppe aus dem Replay ergibt das die Invocations. Daraus `ms pro Mio. Invocations` je
Programm. Liegt `0x800038be00` dabei im Feld, ist es schlicht der einzige Voll-4K-Pass
und die Frage heißt Auflösung/HLE. Ist es ein Ausreißer pro Invocation, sitzt das
Problem im Shader (Trip-Counts, Speicher).

**B — Wave64-Kosten real messen, ein A/B.**

```
APS5_PROFILE_GPU=1 APS5_SINGLE_LANE=800038be00 .\app.exe
```

`HostSubgroupSize` (`Recompiler.cpp:84`) akzeptiert eine Adress-Teilzeichenkette, der
Schalter trifft also nur dieses Programm und setzt `laneCount` auf 1. Der
`[gputime]`-Wert gegen den Basislauf gibt die 1,90x Codegröße in Millisekunden.
Semantik ändert sich (Cross-Lane läuft über Workgroup- statt Subgroup-Scope), das Bild
also auf Korrektheit prüfen.

**C — nur falls A und B es nicht klären:** Nsight Graphics GPU Trace / Nsight Compute
für SM- gegen Memory-Throughput, Occupancy und Stall-Gründe; `sm__inst_executed` pro
Dispatch geteilt durch die Invocations aus A ergibt die effektiven Trip-Counts.

**Methodik für A und B:** `[gputime]` aggregiert über 10-s-Fenster, die Läufe müssen
also dieselbe Szene zeigen — gleicher Spielstand, Kamera geparkt, mehrere aufeinander
folgende Fenster vergleichen. Der Shader-Disk-Cache muss in beiden Läufen gleich warm
sein, sonst verfälschen Recompiles das Bild.

`[gputime] by program` braucht **`APS5_PROFILE_GPU`** (`Recorder.cpp:1800`);
`APS5_PROFILE_DRAW` allein liefert nur die Batch-Stempel.

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
