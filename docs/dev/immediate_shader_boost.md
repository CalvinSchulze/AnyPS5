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

## Hier morgen weitermachen

**Stand:** `0x800038be00` ist als **Pro-Invocation-Ausreißer** eingekreist — 8,002 ms pro
Mio. Invocations, wo drei Programme mit *identischer* Invocation-Zahl 0,013–0,067
brauchen. Der Mechanismus dahinter ist identifiziert, aber **nicht als Ursache belegt**:
die Gast-Arena ist ein 3416-MiB-Host-Import im System-RAM, und weil der Shader
`PhysicalStorageBufferAddresses` deklariert, bindet er diese Ranges in place — jeder
Zugriff geht über PCIe.

**Offen:** der Eingriffs-Test. `APS5_NO_HOST_IMPORT=1` erzwingt Kopien statt
In-place-Zugriff. Fällt der `[gputime]`-Posten von `0x800038be00` deutlich unter die
Basislinie von 4122–4314 ms pro 10 s, ist PCIe-in-place die Ursache; bleibt er flach,
ist er es nicht. Zwei Läufe, Details unter
[Nächster Schritt](#nächster-schritt--kausalität-durch-eingriff-kein-profiler).

**Nicht erneut prüfen** — jedes mit Messung ausgeschlossen:

| Hypothese | Womit widerlegt |
|---|---|
| Auflösung / 4K-Grid | Drei Programme mit denselben 8.294.400 Invocations kosten 0,013–0,067 ms/Mio. |
| SPIR-V-Codegröße (102x Expansion) | `0x8000269d00` hat 5,4x mehr Code und kostet 27x weniger |
| Schleifen / Trip-Counts | `0x80003e8700` ist schleifenfrei und pro Invocation teurer |
| Wave64 auf Subgroup-32 | Alle zwölf Programme sind wave64, auch die billigen; Codeeffekt nur 1,90x |
| Speicherbandbreite | ~34 MB pro Dispatch in 66 ms = ~0,5 GB/s von ~960 GB/s |
| Written-Shadow-Fenster | `MAX_KIB` 2048→20480 flach; Staging-Set identisch, Filter nie erreicht |
| Buffer-Zahl als Prädiktor | Zwei Programme mit je 3 Buffern liegen 6,8x auseinander |
| BDA als Prädiktor | Teuerstes Programm pro Invocation nutzt kein BDA |

**Konstanten-Duplikation** (10,6 % des Moduls) bleibt ein echter, aber **separater**
Defekt: Compile-Zeit, nicht GPU-Zeit. Nicht mit fps-Erwartung anfassen.

**Daten und Werkzeuge:** siehe [Werkzeuge](#werkzeuge) am Ende.

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

## Phase A: ein Pro-Invocation-Ausreißer

`APS5_TRACE_DISPATCH_GEOMETRY=1` lieferte die Grids aller 86 Programme, die Threads pro
Gruppe kommen aus dem Replay. `ms/Frame` = `ms pro 10 s` / 65 Presents.

| Programm | ms/Frame | Grid | Threads | Invocations | **ms/Mio. Inv** | Buffers | Reg. | Img | BDA |
|---|---|---|---|---|---|---|---|---|---|
| `0x8000269d00` | 2,38 | 1x64x36 | 4x4x4 | 147.456 | 16,172 | 24 | 46 | 29 | nein |
| `0x80003e8700` | 19,08 | 240x135x1 | 8x8x1 | 2.073.600 | 9,200 | 3 | 10 | 2 | ja |
| `0x80003bfe00` | 1,14 | 60x34x1 | 8x8x1 | 130.560 | 8,720 | — | — | — | ja |
| `0x800038be00` | **66,37** | 240x135x1 | 16x16x1 | **8.294.400** | **8,002** | **12** | **10** | 1 | ja |
| `0x80003ed000` | 0,86 | 64x32x1 | 8x8x1 | 131.072 | 6,573 | — | — | — | nein |
| `0x7ff6b46cf600` | 0,37 | 2040x1x1 | 64x1x1 | 130.560 | 2,828 | — | — | — | nein |
| `0x80003cd800` | 0,20 | 64x36x1 | 4x4x4 | 147.456 | 1,356 | 3 | 6 | 2 | ja |
| `0x80003e6400` | 1,05 | 240x135x1 | 8x8x1 | 2.073.600 | 0,505 | 1 | 4 | 3 | ja |
| `0x80003f3600` | 0,55 | 480x270x1 | 8x8x1 | **8.294.400** | **0,067** | 1 | 3 | 3 | nein |
| `0x8000405300` | 0,25 | 480x270x1 | 8x8x1 | **8.294.400** | **0,030** | 0 | 3 | 5 | nein |
| `0x8000423300` | 0,11 | 480x270x1 | 8x8x1 | **8.294.400** | **0,013** | 0 | 3 | 2 | nein |

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

**Kein statisches Attribut sagt die Kosten vorher.** Die Buffer-Zahl sah über eine
Teilmenge monoton aus, hält über alle elf Programme aber nicht: `0x80003cd800` und
`0x80003e8700` haben beide **3 Buffer** und liegen 7x auseinander (1,356 gegen 9,200).
Auch BDA trennt nicht — `0x8000269d00` ist pro Invocation das teuerste und nutzt
**kein** `PhysicalStorageBufferAddresses`, während die billigen `0x80003e6400` (0,505)
und `0x80003cd800` (1,356) es nutzen. Images korrelieren negativ, wenn überhaupt: die
billigsten Pässe haben die meisten.

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
## Widerlegt: das Written-Shadow-Fenster ist nicht der Gate

Begründet war der Verdacht durch `GuestBufferMemory.cpp:2138`:

> *"A written V# element bound in place makes the shader store into host memory over
> PCIe: the froxel culling kernel's ~248K scattered 4-byte stores took 2.8 ms per
> dispatch [...] on a GPU that is otherwise idle."*

Die Gegenmaßnahme (Written-Shadow-Staging) ist über `APS5_WRITTEN_SHADOW_MAX_KIB` auf
2048 KiB begrenzt, die geschriebenen Buffer des Flaschenhalses sind 16,6 / 8,2 / 4,1 /
4,1 MB. Gemessen auf RTX 5080, warmer Disk-Cache, identische Szene:

| Lauf | `MAX_KIB` | `0x800038be00` | gestagte Regionen |
|---|---|---|---|
| R0 | 2048 (Default) | 4299 ms | 392 / 180.704 KiB |
| R1 | 5120 | 4220 ms | 200 / 88.544 KiB |
| R2 | 9216 | 4275 ms | 397 / 182.944 KiB |
| R3 | 20480 | 4333 ms | 392 / 180.704 KiB |

**Flach.** Und R5 (`APS5_TRACE_STAGING=1`) entscheidet es: das Staging-Set ist bei
Default und bei 20480 KiB **identisch** — genau 8 Regionen, alle ≤ 640 KiB. Die großen
Buffer tauchen nie auf, der Größenfilter wird also gar nicht erreicht. Sie scheitern
früher in `stagingEligible` (`GuestBufferMemory.cpp:2295`), an einem von
`stagingAllowed`, `addressable`, `unstaged`, `sparse`, `mirror != nullptr` oder
`WritesOverlap`.

`addressable` wurde geprüft und reicht als Erklärung nicht: die Kosten pro Invocation
trennen sich nicht entlang `PhysicalStorageBufferAddresses` (siehe Tabelle oben).

### Nebenbefund aus R4: das Staging trägt die DCC-Keys

`APS5_NO_WRITTEN_SHADOW=1` bricht nach ~30 s reproduzierbar ab:

```
VideoOut: display buffer 0x5005160000 reads mixed DCC keys at 0x5007168000 over its
0x28000 key bytes [...] presenting DCC metadata that is not uniformly uncompressed or
fast-cleared is not implemented
```

Die genannte Range `0x5007168000+0x28000` ist eine der acht gestagten Regionen. Das
Written-Shadow-Staging hält also die DCC-Keys kohärent; ohne es wird ein Display-Buffer
mit gemischten Keys präsentiert und der Titel terminiert. Damit ist die Gegenprobe
nicht gelaufen — und ein Debug-Schalter, der in einen `SIGABRT` führt, ist für sich
notierenswert.
## Mechanismus bestätigt: die Arena ist ein Host-Import, BDA bindet in place

`APS5_TRACE_HOST_IMPORT=1` zeigt einen einzigen Import über die ganze Gast-Arena:

```
[gpu] host import of 0x5000000000+0xd5800000 ok (1 live, 3416.0 MiB live, 3416.0 MiB ever)
```

3416 MiB von `0x5000000000` bis `0x50d5800000`, also **System-RAM über PCIe**. Alle
V#-Basen von `0x800038be00` liegen darin (Buffer 4 bei +151 MiB, Buffer 10 bei +167 MiB).

`VulkanDevice.cpp:954` benennt den Zweck:

> *"Guest memory is host memory: importing it lets address-based shaders use it in place
> instead of copying every registered allocation per draw."*

Und damit ist auch geklärt, warum das Staging-Fenster wirkungslos war: `0x800038be00`
deklariert `PhysicalStorageBufferAddresses`, also ist in `stagingEligible` das
`addressable`-Flag gesetzt und das Staging wird **vor** dem Größenfilter abgewiesen —
adressierbare Builds lesen den Import in place, weil `AddressRanges` eine Device-Adresse
braucht. Die Buffer bleiben im Host-RAM, und 8,29 Mio. Invocations greifen dort zu.

### Was damit noch nicht gezeigt ist

Der Import der Arena ist **erwartbar** — so funktioniert Gast-Speicher hier
grundsätzlich. Dass der Mechanismus vorliegt, ist belegt; dass er die 66 ms *verursacht*,
noch nicht. Drei Datenpunkte aus der Tabelle oben widersprechen einer reinen
„in place über PCIe"-Erklärung:

- `0x80003e6400`: BDA, **1** Buffer, 2.073.600 Invocations → **0,505** ms/Mio.
- `0x80003e8700`: BDA, **3** Buffer, 2.073.600 Invocations → **9,200** ms/Mio.
- `0x80003cd800`: BDA, **3** Buffer → **1,356** ms/Mio., also 6,8x billiger als
  `0x80003e8700` bei gleichem Mechanismus und gleicher Buffer-Zahl.
- `0x8000269d00`: pro Invocation das teuerste (16,172) und nutzt **kein** BDA, bindet
  also gar nicht adressierbar in place.

Was zählt, ist offenbar die Zahl der **Zugriffe pro Invocation**, nicht die Zahl der
gebundenen Buffer — und die ist statisch nicht ablesbar. Der Mechanismus ist damit der
plausibelste Hauptverdächtige, aber als Kausalaussage fehlt der Eingriff.

### Nächster Schritt — Kausalität durch Eingriff, kein Profiler

`APS5_NO_HOST_IMPORT=1` schaltet `VK_EXT_external_memory_host` ab
(`VulkanDevice.cpp:956`). Adressierbare Builds müssen die Ranges dann **kopieren**
statt in place zu lesen, der Zugriff läuft also device-local. Fällt `0x800038be00`
dabei deutlich, ist PCIe-in-place die Ursache; bleibt es flach, ist es das nicht.

Vorsicht bei der Grenze: `APS5_ADDRESS_COPY_MAX_MIB` steht auf **64 MiB**, und ein
Überschreiten ruft `std::abort()` mit `FATAL: an address-based build copies <n> MiB of
<k> registered ranges, past 64 MiB` (`GuestBufferMemory.cpp:1445`, `:1857`).

1. **Erst mit Default laufen.** Der Abbruch ist selbst das Messergebnis: die Meldung
   listet die acht größten kopierten Ranges mit Größe und Grund und sagt damit, wie viel
   Gast-Speicher ein adressierbarer Build dieses Shaders überhaupt anfasst.
2. **Dann mit angehobener Grenze**, z. B. `APS5_ADDRESS_COPY_MAX_MIB=4096`, und
   `[gputime] by program` gegen die Basislinie (4122–4314 ms) vergleichen. Die
   Kopierkosten tauchen separat auf (`[address]`-Zeile, `guest memory upload`), die
   fps dürfen also sinken — entscheidend ist allein der Posten `0x800038be00`.

Nsight Compute bleibt die Rückfallebene, ist aber auf dem Messrechner nicht installiert
und wird durch diesen Eingriff auch nicht gebraucht: er testet die Hypothese direkt,
statt sie aus Countern zu erschließen.

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

Messlauf (`[gputime] by program` braucht `APS5_PROFILE_GPU`, nicht `APS5_PROFILE_DRAW`):

```
APS5_PROFILE_GPU=1 APS5_PROFILE_DRAW=1 APS5_DUMP_SHADERS=1 APS5_TRACE_DISPATCH_GEOMETRY=1 .pp.exe
```

Offline-Auswertung der Dumps:

```
agc_shader_replay [--asm] [--cfg] [--spv] [--mem] shader_<adresse>.req
APS5_SINGLE_LANE=all agc_shader_replay ...          # laneCount=1 zum Vergleich
python tools/spirv_stats.py  <modul>.spv             # Größe, Blöcke, Opcodes, Konstanten, BDA
python tools/cfg_summary.py  cfg.txt                 # Back-Edges und Schleifenkörper
```

`agc_shader_replay` braucht `libc.prx` im `PATH`
(`build/core/libs/libs/unpatched`). `--cfg` gibt pro Block `words=` aus — das ist
`estimatedSpirvWords`, eine **Heuristik** des Structurizers (`GraphBuilder.cpp:19`),
keine Messung des Ergebnisses; echte Größen nur über `--spv` und `spirv_stats.py`.

Nützliche Schalter, alle verifiziert: `APS5_TRACE_DISPATCH_GEOMETRY=<hex|1>`,
`APS5_SINGLE_LANE=<hex|all>`, `APS5_TRACE_STAGING=1`, `APS5_TRACE_HOST_IMPORT=1`,
`APS5_WRITTEN_SHADOW_MAX_KIB`, `APS5_NO_HOST_IMPORT=1`, `APS5_ADDRESS_COPY_MAX_MIB`
(Default 64, darüber `abort()`), `APS5_PROBE_DISPATCH=<hex>[:index]`.

**Achtung:** `APS5_NO_WRITTEN_SHADOW=1` führt nach ~30 s zum `SIGABRT` in VideoOut
(gemischte DCC-Keys) — nicht als Gegenprobe brauchbar.

`spirv_stats.py` meldet nebenbei das Addressing-Model: `PhysicalStorageBuffer64` beim
Flaschenhals gegen `Logical` bei den billigen Pässen — das ist dasselbe `addressable`,
das in `stagingEligible` das Staging blockiert.

Die Rohdaten liegen unter `_analytics/` (gitignored, nicht im Repo):
`game_debug.log`, `shaders/shader_*.req`, `written_shadow_tests/`,
`host_import_trace/`, `mem/`.

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
