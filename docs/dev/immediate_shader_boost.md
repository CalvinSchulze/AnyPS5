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

**Ursache belegt.** Der Eingriffs-Test ist durch: `APS5_NO_HOST_IMPORT=1` senkt die
GPU-Zeit des Flaschenhalses um **2,4x** und die des zweiten Shaders um **6,4x**, während
die bildbasierten Pässe sich nicht bewegen. PCIe-In-place-Zugriff ist damit als Ursache
belegt — aber nur für **~60 %** der Kosten, und der Eingriff selbst ist unbrauchbar
(1,2 fps). Zahlen und Vorbehalte unter
[Eingriffs-Test](#eingriffs-test-ursache-belegt-fix-noch-nicht).

**Der Fix steht und ist gemessen.** Der Riegel war weder die Device-Adresse noch das
Write-Bit, sondern `addDescriptorRegion`: für einen adressbasierten Build ist die ganze
Arena *eine* Basis-Region, jedes V#-Element liegt `Inside`, also entstand gar keine Region,
die das Staging hätte sehen können. Der **Carve-out** löst das und bringt den Flaschenhals
von 66,8 auf **27,6 ms** pro Dispatch und die Szene von 6,4 auf **8,3 fps**, bei 2,34 ms
Kopien pro Present und ruhiger CPU-Seite — siehe
[Carve-out](#der-carve-out-trägt-gemessen-24x-und-30--fps).

**Hier weitermachen.** Elf Läufe sind durch (A–D in `_analytics/carve_out_tests/`, 1–5 in
`_analytics/frame_cost_tests/`, 2 in `_analytics/pingpong_tests/`). Der Frame steht bei
100 ms: 27,6 ms Flaschenhals, 19,8 ms zweiter Shader, 18,4 ms `draw`, 24 ms
Storage-Image-Traffic.

1. **Die Front ist der Storage-Image-Pingpong, und sie ist jetzt belegt und lokalisiert.**
   `cpuWrote` ist für alle drei Haupt-Targets zu **100 % 0**, zwei davon werden zweimal pro
   Present hoch- und zurückgeschrieben, ohne dass CPU, Dirty-Flag oder DCC-Keys beteiligt
   sind. Der Ausweg existiert (`Texture.cpp:1424`), ist aber durch `originalValid = false`
   an `:1739` und `:2806` abgeschaltet. Obergrenze: **+48 % fps**. Nächster Schritt ist
   **bauen**, nicht messen — Richtung unter
   [Pingpong](#die-größte-front-der-storage-image-pingpong--belegt-und-lokalisiert).
2. **Die Codemenge ist als Hebel erledigt**, in beide Richtungen: `SPIRV_OPT=full` bringt
   1,4 %, `SINGLE_LANE` auf ein Programm kostet **+94 %** (symmetrisch für beide Shader).
   Zwei Lanes sind das Optimum, nicht Ballast. Siehe
   [Wave64](#wave64-emulation-hypothese-gefallen-2-lanes-sind-das-optimum).
3. **`0x80003e8700`** liegt nicht an Buffern; 16 Image-Fetches pro Invocation bei 92 %
   Occupancy sind der Kandidat:
   [zweiter Shader](#0x80003e8700-nicht-die-buffer-und-auch-nicht-pcie-bilder).
4. Der **Carve-out** ist fertig: 16 MiB gemessen, 4 MiB kostet 17 ms.

**Nicht erneut prüfen** — jedes mit Messung ausgeschlossen:

| Hypothese | Womit widerlegt |
|---|---|
| Auflösung / 4K-Grid | Drei Programme mit denselben 8.294.400 Invocations kosten 0,013–0,067 ms/Mio. |
| SPIR-V-**Modulgröße** als Prädiktor | `0x8000269d00` hat 5,4x mehr Code und kostet 27x weniger. **Achtung:** das schließt nur die Modulgröße aus, nicht die *ausgeführten* Instruktionen — die sind ungemessen und jetzt Hauptverdächtiger |
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

### Eingriffs-Test: Ursache belegt, Fix noch nicht

`APS5_NO_HOST_IMPORT=1` lässt `hostImportAlignment` auf 0 (`VulkanDevice.cpp:956`), damit
ist `importable == false` (`GuestBufferMemory.cpp:1748`) und die Import-Stufe fällt weg.
Die Kette in `:1812-1849` hat **drei** Stufen, nicht zwei:

```
1. importable            -> Host-Import, in place über PCIe        (mit dem Schalter aus)
2. sonst mirrorsEnabled  -> acquireMirror() -> device-local Mirror  (fängt die Ranges auf)
3. nur wenn der Mirror ablehnt -> addCopiedRange() -> gegen APS5_ADDRESS_COPY_MAX_MIB
```

Deshalb kam **kein Abort** und es brauchte keinen zweiten Lauf: Stufe 2 bedient alles,
`copies` bleibt leer. Ein Lease-Mirror ist device-local — genau die gewünschte
Intervention, nur über Stufe 2.

**Kontrolle, dass der Eingriff griff:** `host import of` kommt 0x vor, und

| | Basislinie | `NO_HOST_IMPORT=1` |
|---|---|---|
| `image mirrors` | 1 range, 1,5 MiB, 0 writable | **856 ranges, 4278 MiB, 855 writable** |

**Ergebnis pro Dispatch** (`ms pro 10 s` / Dispatch-Zahl, Basislinie 65 Presents gegen
12 im Eingriff):

| Programm | Basislinie | Eingriff | Faktor | Art |
|---|---|---|---|---|
| `0x800038be00` | 66,4 ms | **27,6 ms** | **2,4x schneller** | BDA, 12 Buffer |
| `0x80003e8700` | 19,1 ms | **3,0 ms** | **6,4x schneller** | BDA, 3 Buffer |
| `0x8000269d00` | 2,38 ms | 2,0 ms | 1,2x | kein BDA |
| `0x80003e6400` | 1,05 ms | 1,0 ms | — | BDA, 1 Buffer |
| `0x80003ed000` | 0,86 ms | 0,92 ms | — | bildbasiert |
| `0x80003f3600` | 0,55 ms | 0,67 ms | — | bildbasiert |
| `0x7ff6b46cf600` | 0,37 ms | 0,33 ms | — | — |
| `0x8000405300` | 0,25 ms | 0,23 ms | — | 0 Buffer, 5 Images |

Die Signatur ist exakt die vorhergesagte: **nur** die beiden in place gebundenen
Vielfach-Buffer-Shader fallen, die bildbasierten Pässe rühren sich nicht. Das ist
Kausalität, nicht Korrelation.

**Warum es kein Fix ist:** die Kosten wandern auf die CPU. 12 Presents statt 65
(1,2 fps), `idle gaps 773,2 ms` pro Present bei `GPU busy 50,7 ms` — die GPU steht. Die
`[address]`-Zeile nennt den Grund: `mirror prepare 44055 us per build`, also **44 ms pro
Build**, bei 154 adressbasierten Builds pro 10 s, plus 327.619 Refreshes, 6,25 Mio.
verglichene und 5,05 Mio. kopierte Blöcke. Die ganze 4,3-GB-Arena zu spiegeln und pro
Build nachzuziehen ist teurer als der PCIe-Zugriff.

**Vorbehalt zur Messung:** der Eingriffslauf läuft bei 1,2 fps mit 94 % GPU-Leerlauf.
Taktzustände, Cache-Residenz und fehlende Parallelarbeit unterscheiden sich damit von
der Basislinie; die Richtung und die Selektivität der Signatur sind überzeugend, die
genauen Faktoren 2,4x und 6,4x sind weich.

### Der Carve-out trägt: gemessen, 2,4x und +30 % fps

Gebraucht wurde device-lokale Ablage **nur für die Ranges, die der heiße Shader wirklich
anfasst**. Zwei Verdächtige fielen beim Lesen weg, bevor der echte Riegel auftauchte:
die **Device-Adresse** nicht (`addressRange` veröffentlicht `region.buffer->DeviceAddress()`
längst, und `gpuCopyUsage(addressable)` hängt `SHADER_DEVICE_ADDRESS_BIT` an), das
**Write-Bit** auch nicht (die Aufteilung in `AddressRanges()` vergibt es an den
`writes`-Intervallen mit der gestagten Adresse). Der Riegel war `addDescriptorRegion`:

```cpp
case BaseOverlap::Inside:
    return;              // die Basis-Region bedient die Range
```

Für einen adressbasierten Build ist die ganze 3416-MiB-Arena **eine** Basis-Region. Jedes
V#-Element liegt `Inside`, also entstand **gar keine Region**, die das Staging hätte sehen
können — das erklärt die acht kleinen Regionen aus dem R5-Trace restlos.

**Gebaut:** ein gefegtes geschriebenes Element wird aus der Basis-Region herausgeschnitten
(`carvedOut`), `stagingEligible` lässt genau diese Carve-outs bei adressierbaren Builds
durch, `AddressRanges()` **subtrahiert** die Spanne aus den Basis-Ranges (der Lookup ist
eine Binärsuche und braucht aufsteigende, überlappungsfreie Einträge — `requireTableOrder`
prüft das jetzt), und die Sweep-Erkennung trägt die Thread-Zahl von `Dispatch.cpp` über
`PrepareDispatch` bis `addGuestBuffer`, wo `threads * stride * 2 >= bytes` entscheidet.

**Messung** (A/B aus einem Binary, Logs unter `_analytics/carve_out_tests/`):

| | A: kein Staging | B: 16 MiB | C: 4 MiB | D: `ALL_BUFFERS_WRITTEN` |
|---|---|---|---|---|
| `0x800038be00` pro Dispatch | 66,8 ms | **27,6 ms** (2,42x) | 44,4 ms | 28,0 ms |
| `0x80003e8700` pro Dispatch | 19,9 ms | 19,8 ms | 18,4 ms | 19,1 ms |
| Presents / 10 s | 64 (~6,4 fps) | **83 (~8,3 fps)** | 72 (~7,2 fps) | — |
| GPU busy / idle gaps | 140,2 / 17,1 ms | 102,7 / 17,3 ms | 116,2 / 23,1 ms | — |
| gestagte Regionen | 192 (nur ≤ 640 KiB) | 1.743 (16,2 / 8,0 / 2x 4,1 MB) | 1.368 (ohne 16,2 / 8,0) | alle |
| Staging-Kopien pro Present | ~0,09 ms | **~2,34 ms** | ~1,25 ms | — |
| `mirror prepare` pro Build | 0 us | **0 us** | 0 us | 0 us |
| `[bda-table]` hits / misses | 631 / 189 | 664 / 415 | 575 / 360 | — |

**Das Fenster ist die Stellschraube, nicht ein Fehler.** Bei 4 MiB fallen Buffer 4
(16,2 MB) und Buffer 10 (8,0 MB) heraus und laufen wieder über PCIe: 44,4 statt 27,6 ms,
7,2 statt 8,3 fps. Die beiden tragen also allein ~17 ms. 16 MiB deckt sie, und die
Kopierkosten steigen dafür nur von 1,25 auf 2,34 ms pro Present.

Der Flaschenhals landet damit **genau auf dem Niveau des `NO_HOST_IMPORT`-Laufs** (27,6 ms)
— aber ohne dessen Preis: 2,34 ms Kopien pro Present statt 44 ms Mirror-Vorbereitung pro
Build, CPU-Seite ruhig, keine Faults, keine Tabellen-Überlappung, kein verlorener
Copy-back. Die Gegenrechnung, an der der Eingriffs-Test gestorben ist, geht diesmal auf.

### Lauf C hat einen latenten Fehler gefunden, nicht eine Fenstergrenze

`APS5_SWEPT_SHADOW_MAX_KIB=4096` brach reproduzierbar nach 14 s ab:

```
compute shader 0x800038be00: AGC graphics: guest buffer view exceeds its GPU owner
```

Mit `APS5_NO_ADDRESSABLE_STAGING=1` lief dasselbe Fenster stabil. **Das heißt nicht, dass
16 MiB nötig sind** — es heißt, dass ein *teilweiser* Carve-out einen Fehler in
`owner()` freilegt, der bei 16 MiB nur nicht getroffen wurde:

Bei 4096 KiB bleiben die 16,2-MB- und die 8,0-MB-Range in der Arena, während die beiden
4050-KiB-Ranges und einige kleine herausgeschnitten werden. `owner()` gab „die Region mit
dem größten `begin` unterhalb der Adresse" zurück und überließ die Endprüfung dem Aufrufer.
Die Elemente eines Dispatches liegen aber **Stoß an Stoß**: der Carve-out
`0x500a743200+0x1fa40` endet auf `0x500a762c40` — genau der Basis des nicht gecarvten
8-MB-Buffers. Für dessen Adresse lieferte `owner()` also den Carve-out statt der Arena,
und die Bounds-Prüfung in `Descriptor()` schlug fehl.

**Behoben:** eine Region, die die Adresse **enthält**, gewinnt jetzt gegen eine, die nur
darunter beginnt; enthalten beide (ein Carve-out in seiner Basis-Region), gewinnt wie
bisher das größere `begin`. Das betrifft auch die vier Write-Back-Pfade, die über
`owner(begin)` gehen. Regressionstest in `tests/BdaResources.cpp`: ein gefegtes Element,
ein nicht gefegtes direkt dahinter, und die Prüfung, dass die Tabelle disjunkt bleibt.

**Nachgeholt:** mit dem Fix läuft Lauf C sauber durch und beantwortet die Fensterfrage
(44,4 ms bei 4 MiB gegen 27,6 bei 16 MiB). Der Abbruch war der Fehler, nicht die Grenze.

### `0x80003e8700`: nicht die Buffer, und auch nicht PCIe-Bilder

Der zweite Shader (20 % GPU-Last) fällt unter `NO_HOST_IMPORT` um 6,4x auf 3,0 ms, rührt
sich unter dem Carve-out aber nicht (19,9 → 19,8 ms), und auch `ALL_BUFFERS_WRITTEN=1`
bewegt ihn nicht (19,1 ms). Seine Buffer-Elemente sind also nicht die Kosten.

Aus dem Dump (`agc_shader_replay --spv`, dann Opcode-Zählung) kommt der Unterschied:

| | `0x800038be00` | `0x80003e8700` |
|---|---|---|
| `OpImageFetch` | **2** | **16** |
| `OpLoad` / `OpAccessChain` | 714 / 522 | 288 / 263 |
| `OpConvertUToPtr` | 16 | 20 |
| BDA-Schreibfunktionen im Modul | **keine** | `get_bda_write_pointer`, `note_bda_write`, `write_bda_bytes`, `get_bda_atomic_pointer` |

**16 Image-Fetches pro Invocation** bei 2,07 Mio. Invocations sind ~33 Mio. Fetches — das
ist der Kandidat. **Aber nicht als PCIe-Zugriff:** Storage-Images werden in device-lokale
`VkImage`s hochgeladen, und das Log zeigt genau das, 347 MiB pro Present in der Klasse
`storage-upload`. Ein Fetch trifft Device-Speicher. Die 19,8 ms sind damit entweder die
Fetch-Arbeit selbst (Tiling, Formatumrechnung, emulierte Filterung) oder die BDA-Schreibseite,
die nur dieser Shader hat.

**Warum er unter `NO_HOST_IMPORT` trotzdem fiel**, ist damit offen und die nächste Frage:
dort wurden *alle* Ranges device-lokal gespiegelt, auch die, die kein Deskriptor-Element
und kein Bild sind. Zu prüfen mit einem Lauf, der die `[staging]`-Ranges dieses Shaders
auflistet und mit seinen V#-Basen vergleicht.

## Zweite Kostenquelle: die ausgeführte Befehlsmenge

**PCIe ist raus, zweifach.** 27,6 ms mit vier Elementen device-lokal (Lauf B), 28,0 ms mit
**allen** (Lauf D). Und die Schreibseite ist es nicht: das Modul definiert gar keine
BDA-Schreibfunktion, also kein `note_bda_write`, keine Device-Scope-Atomics pro Store.

**Registerdruck ist es auch nicht** (`APS5_PIPELINE_STATS=1`):

| | Register | Binary Size | Stack | Shared |
|---|---|---|---|---|
| `0x800038be00` | 80 | **210.688 B** | **0** | 2560 B |
| `0x80003e8700` | 46 | 74.240 B | 0 | 0 |
| `0x80003f3600` (billig, gleiches Grid) | 71 | **28.672 B** | 0 | — |

`Stack Size = 0` heißt **kein Spilling**. Der Flaschenhals trägt aber **7,3x so viel
Maschinencode** wie der gleich große, 50x billigere 4K-Pass.

Zwei Dinge dabei genau nehmen: 80 Register sind **nicht** „hohe Occupancy" — bei 65.536
Registern pro SM sind das 25 von 48 Warps, also **~52 %**, gegen ~92 % beim zweiten
Shader. Es ist kein Katastrophenwert, aber die Hälfte. Und die gemeldete
`Local Memory Size = 68719476736` ist genau 2^36 und damit ein Müllwert des Treibers, der
nicht zitiert werden sollte.

**Schlechte Optimierung ist es nicht** (`APS5_SPIRV_OPT=full`, volle SPIRV-Tools-Pipeline
samt exhaustivem Inlining): 27,21 statt 27,59 ms, also **1,4 %**. Der zweite Shader 2,6 %.
Da liegt nichts brach. (Der Lauf meldet `recompile 14,1 s` gegen 49,8 s der Basislinie —
das ist niedriger *trotz* teurerer Optimierung, also war der Shader-Disk-Cache warm. Die
Compile-Zeit von `=full` ist damit **nicht** gemessen, nur die Laufzeit.)

**Was bleibt: die Menge der ausgeführten Befehle.** 27,6 ms auf 8,29 Mio. Invocations sind
~89.000 Befehls-Slots pro Invocation (84 SMs x 128 Lanes, 2,5 GHz, volle Auslastung
unterstellt). Bei 210.688 Byte Maschinencode — grob 20.000 Instruktionen — heißt das, dass
jede Invocation das Modul mehrfach durchläuft: **Trip-Counts**, multipliziert mit der
Übersetzungsexpansion (85 SPIR-V-Words pro Guest-Instruktion, 34 % Masken-Ops, 1,90x
wave64-auf-32).

**Nächste Messung, und sie ist klein:** `APS5_SINGLE_LANE` nimmt eine **Programmadresse**,
nicht nur `all`. Der `=all`-Lauf ist an fremden Shadern gescheitert (siehe unten), aber
`APS5_SINGLE_LANE=800038be00` trifft nur den Flaschenhals und beantwortet, was die
Wave64-Emulation von den 27,6 ms kostet.

**Noch nicht gemessen, aber weiter Kandidat:** der Lookup pro Zugriff
(`get_bda_pointer`, nicht inlinebare Binärsuche). Keiner der fünf Läufe hat ihn berührt —
dass der Flaschenhals in Lauf 5 unverändert bleibt, zeigt nur, dass seine Kosten vom
Storage-Pfad unabhängig sind, nichts über den Lookup. Und seine Speichertraffic läuft
über das Deskriptor-Array (714 `OpLoad`, 522 `OpAccessChain`), nicht über Zeiger.

### Nebenbefund: `APS5_SINGLE_LANE=all` bricht den Recompiler

Der Lauf erreicht die Render-Schleife nicht (0 Presents). Drei Fehler beim Vorbereiten
früher Shader:

```
0x80001f1100: GetImageResource dword 0 is not a valid runtime value
0x8000139c00: GetImageResource dword 0 is not a valid runtime value
0x80000bb700: value IR instruction definition does not dominate its use
```

Der dritte ist eine gebrochene SSA-Invariante, also ein echter Defekt auf dem
`laneCount=1`-Pfad — notierenswert, aber kein Blocker: die Adressform des Schalters
umgeht ihn.

## Die größte Front: der Storage-Image-Pingpong — belegt und lokalisiert

`APS5_GPU_NO_WRITEBACK=1` als Obergrenze gemessen, und sie ist groß:

| | Referenz | `GPU_NO_WRITEBACK` |
|---|---|---|
| Presents / 10 s | 82 (~8,2 fps) | **121 (~12,1 fps)**, +48 % |
| GPU busy | 104,3 ms | **77,3 ms** |
| `draw` pro Present | 18,97 ms | **7,25 ms** |
| `storage-upload` | 10,31 ms (349 MiB) | **5,89 ms** (216 MiB) |
| `storage-writeback` | 14,68 ms (375 MiB) | **8,15 ms** (210 MiB) |
| `0x800038be00` | 27,55 ms | 26,73 ms |

Der Write-back kostet nicht nur sich selbst: er halbiert die **Uploads** und drittelt die
**Draws**. Zusammen ~27 ms pro Frame. Die heißen Dispatches rühren sich nicht.

### Die Messung: `cpuWrote` ist zu 100 % 0

`APS5_CAPTURE_TRACE=1` liefert die Zeile, die die Entscheidung trägt. 5.716
`refresh`-Ereignisse über 152 Presents, **37,6 pro Present**, dazu 36,8 Uploads und 43,2
Write-backs pro Present. Global: `cpuWrote` in **95,7 %** der Fälle 0, `dirty` in 80,9 %,
`keysChanged` in 86,5 %.

Für die drei Haupt-Targets, die sich in 151 von 152 Presents wiederholen:

| Ziel | Auflösung | refresh/Present | up/back pro Present | `cpuWrote=0` | `dirty=0` | `keysChanged=0` |
|---|---|---|---|---|---|---|
| `0x5000860000` | 3840x2160 (~32 MiB) | 2,90 | 0,99 / 0,04 | **100 %** | 68,5 % | 67,3 % |
| `0x50727e0000` | 1920x1080 (~8 MiB) | 1,99 | 2,00 / 1,99 | **100 %** | **100 %** | **100 %** |
| `0x5060d30000` | 1920x1080 (~8 MiB) | 1,99 | 2,00 / 1,99 | **100 %** | **100 %** | **100 %** |

Zwei Targets werden **zweimal pro Present** hochgeladen und zweimal zurückgeschrieben,
obwohl weder die CPU sie anfasst, noch sie schmutzig sind, noch die DCC-Keys sich ändern.
`generation` steigt jeden Present.

### Die Ursache, auf drei Zeilen

Es gibt einen Ausweg, und er ist abgeschaltet. `Texture.cpp:1424`:

```cpp
if (!unchanged && !keysChanged && !pendingChanged && originalValid && equalsOriginal()) {
    unchanged = true;   // Gastspeicher gleicht noch `original` -> kein Upload
```

`original` hält laut Kommentar „the guest bytes the image was last uploaded from **or
written back as**". Genau dieser Vergleich würde den Pingpong abfangen — er verlangt aber
`originalValid`, und das wird an zwei Stellen gelöscht:

- `:1739` — im Host-Import-Pfad: `if (GuestMemory::Watched(...)) originalValid = false;`
  Für ein Target unter Write-Watch gibt es also **nie** einen Baseline-Vergleich.
- `:2806` — nach dem Write-back selbst, mit dem Kommentar *„the stamps make their next
  Refresh re-upload, `original` no longer vouching for the bytes"*.

Damit entscheidet allein die Block-Stempelung aus der Write-Watch, und die stempelt auch
**unsere eigenen** Write-backs. Der Treiber kann seine Schreibzugriffe nicht von denen des
Spiels unterscheiden, also lädt er zurück, was er selbst geschrieben hat. Der Trace zeigt
genau das: `originalValid 0` im dominierenden Fall.

### Fix-Richtung

Der Weg führt **nicht** über `equalsOriginal()` — dafür müssten die zurückgeschriebenen
Bytes auf der CPU liegen, und genau diesen Readback will man sich sparen. Richtig ist die
stärkere Aussage: **eine Unit, deren Stempel nur vom eigenen Write-back kommen, ist nicht
geändert** — das Image *ist* die Quelle dieser Bytes. Gebraucht wird also eine
Pro-Block-Notiz „von uns zurückgeschrieben bei Generation G", gegen die
`UnchangedSince` / `ChangedBlocks` prüfen kann. Bausteine sind da: `NoteShadowSeed` im
Write-back-Pfad, `GuestMemory::StoredOver`, `cpuBlocks` getrennt von `stampedBlocks`.

Die Schwierigkeit ist die Reihenfolge: die Stempel des Write-backs landen **asynchron**
auf der GPU, die Notiz muss also die Generation *nach* dem Landen tragen — dafür ist die
Pending-Results-Maschinerie (`layerPending`, `pendingChanged`) der Ankerpunkt.

**Kein Fix:** `APS5_GPU_NO_WRITEBACK=1` bricht die Korrektheit per Definition. 12,1 fps
sind eine Obergrenze, keine Zielmarke.

## Wave64-Emulation: Hypothese gefallen, 2 Lanes sind das Optimum

`APS5_SINGLE_LANE=<hex>` trifft nur ein Programm (die `=all`-Form war an fremden Shadern
gescheitert). Mit der Adressform bleiben die drei Recompiler-Fehler aus, und der Code
halbiert sich wie erwartet (162.427 → 85.261 Words).

| Lauf | `0x800038be00` | `0x80003e8700` |
|---|---|---|
| Referenz | 27,55 ms | 19,89 ms |
| `SINGLE_LANE=800038be00` | **53,47 ms** (+94 %) | 19,70 ms |
| `SINGLE_LANE=80003e8700` | 27,09 ms | **39,58 ms** (+99 %) |

**Symmetrisch, exakt 2x, und nur beim adressierten Programm.** Halber Code, doppelte
Laufzeit. Die 2-Lane-Entrollung ist also **kein Ballast, sondern die bessere Wahl**: bei
`laneCount=1` braucht eine Gast-Wave64 zwei Warps statt einen, und wave-interne Operationen
werden aus billigen Intra-Warp-Subgroup-Ops zu teuren Workgroup-Barrieren.

**Damit ist die Codemenge als Hebel in beide Richtungen erledigt:** mehr Optimierung bringt
1,4 %, halber Code kostet 94 %. Was von den 27,6 ms bleibt, ist die Arbeit des
Gast-Algorithmus selbst plus der Pro-Zugriff-Overhead — und der Flaschenhals ist damit
möglicherweise näher an seinem Boden als der Rest des Frames.

## Upstream-Abgleich (Stand 13.10.)

`I:\Emulation\PS5 Emu\Software\AnyPS5Source` hält Upstream-`main`
(`boykopovar/AnyPS5`). **Keine gemeinsame Historie** mit unserem Repo — die
Upstream-Arbeit kam als ein Squash-Commit herein, also kein `merge-base`, kein
Cherry-Pick. Vergleich nur über Blob-Hashes pro Datei (`git hash-object` gegen
`git rev-list main -- <datei>`). Basis am 13.10.: `GuestBufferMemory.cpp` entspricht
`c11a9cb59` (10.10.), der SPIR-V-Backend-Stand ist älter (`b2a481330`, 08.10.).

Drei Upstream-Commits berühren unsere Front:

| Commit | Was | Für uns |
|---|---|---|
| `2688b7646` perf(agc): stage read and written buffer elements a dispatch sweeps | Weitet das Written-Shadow-Fenster für **gefegte** Elemente auf 16 MiB: gelesen *und* geschrieben (`bufferRead`), direkter Dispatch, Threads x Stride decken ≥ die Hälfte des Elements. Gemessen 4,8 ms → 0,06 ms + 0,9 ms Kopien. | Bestätigt Mechanismus und Methode unabhängig von uns, **hilft unseren beiden heißen Shadern aber nicht**: `stagingEligible` behält `addressable` im Early-Return. Die Sweep-Heuristik ist genau das Fenster-Kriterium, das wir brauchen — übernehmen. |
| `d220f48e9` perf(shader): load from buffers without Coherent when the load has no GLC or DLC | Ein einziger GLC/DLC-Zugriff dekorierte das **ganze** Buffer-Array `Coherent`; auf NVIDIA fallen damit alle Loads aus dem L1. Gemessen **2,7x** langsamer. Fix: zweites Array `buffers_coherent`. | **Nicht in unserem Baum** (`coherentBufferAlias`, `storageBufferCoherentVariable` fehlen). Trifft den Deskriptor-Array-Pfad, nicht BDA — also nicht unseren Flaschenhals, aber ein heißer Kandidat für `0x8000269d00`, das pro Invocation teuerste Programm **ohne** BDA (16,172 ms/Mio.). RTX 5080 ist NVIDIA. |
| `2fb7a77ac` feat(shader): note which guest buffer elements a shader loads from | `DescriptorBinding::bufferRead` neben `bufferWritten`/`bufferAtomic`, Shader-Cache-Format 24. | Voraussetzung für die Sweep-Heuristik; fehlt uns ebenfalls. |

Was upstream **nicht** angefasst hat: der `addressable`-Riegel in `stagingEligible` und
die Binärsuche in `get_bda_pointer`. Beide Fronten sind unbesetzt.

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

`agc_shader_replay` braucht **beide** Verzeichnisse im `PATH`, sonst startet es mit
`0xC0000135` nicht: `build/core/libs/libs/unpatched` (für `libc.prx` und `libkernel.prx`)
**und** das MinGW-`bin` der Toolchain (für `libstdc++-6.dll`, `libwinpthread-1.dll`).
`--spv` schreibt `shader_<adresse>.req.spv` neben die Eingabe. `--cfg` gibt pro Block `words=` aus — das ist
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
`host_import_trace/`, `mem/`, `no_host_import_tests/`, `carve_out_tests/`
(Läufe A/B/C/D des Carve-outs).

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
