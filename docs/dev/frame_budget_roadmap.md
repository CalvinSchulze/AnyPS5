# Frame-Budget: was 60 fps verlangt

Dauerhaftes Referenzdokument, kein Verlauf und keine Operationsspitze — die steht in
[`immediate_shader_boost.md`](immediate_shader_boost.md). Hier steht, **wohin die 120 ms
gehen**, was davon holbar ist und was 60 fps rechnerisch verlangt. Alle Zahlen gemessen,
Grundlage ist Lauf B aus `_analytics/carve_out_tests/run_B_carveout.log` (83 Presents / 10 s,
RTX 5080, leere Szene hinter dem Ladekreisel).

## Vorbehalt zur Messgrundlage

Die Zahlen unten stammen aus der **3D-Phase** (leere Szene hinter dem Ladekreisel). Von
außen beobachtet laufen die **Intro-Animationen davor flüssig**, Richtung 60, mit
synchronem Ton — unsere Telemetrie zeigt aber über **58 Fenster** eines 600-s-Laufs
durchgehend nur 71–92 Presents pro 10 s. Entweder läuft das Intro also auch bei ~9 fps und
wirkt durch Video und synchronen Ton flüssiger als es ist, oder es erreicht den Schirm über
einen Pfad, den unser Zähler nicht sieht (`presents` wird am Blit hochgezählt,
`VulkanDevice.cpp:2516`).

**Für dieses Budget ist das ohne Folgen** — es beschreibt die 3D-Phase, und die ist das
Ziel. Aber wer „8,3 fps" zitiert, meint die 3D-Phase, nicht die Sitzung.

## Der Abstand

**120 ms pro Frame heute, 16,7 ms für 60 fps — Faktor 7,2.**

## Wohin die Zeit geht

| Posten | pro Present | Anteil |
|---|---|---|
| `0x800038be00` — Froxel-artig, 8,29 Mio. Invocations | **27,6 ms** | 23 % |
| `0x80003e8700` — 2,07 Mio. Invocations, 16 Image-Fetches je Invocation | **19,8 ms** | 17 % |
| `draw` — 25 Draws, **25 Render-Passes** | **18,4 ms** | 15 % |
| `storage-writeback` — 375 MiB | **13,9 ms** | 12 % |
| `storage-upload` — 347 MiB | **10,1 ms** | 8 % |
| zehn weitere Programme | 6,7 ms | 6 % |
| Staging (Carve-out) | 2,3 ms | 2 % |
| `fill`, `fill-clear`, `dcc-*`, `present-blit` | 1,2 ms | 1 % |

## Die Hardware ist nicht das Limit

`0x80003f3600` fährt **dieselben 8.294.400 Invocations** auf demselben 4K-Grid wie der
Flaschenhals und kostet **0,55 ms**. Ein Voll-4K-Pass ist auf dieser Karte also weit unter
einer Millisekunde. Der Flaschenhals kostet 27,6 ms — **50x** mehr für dieselbe Thread-Zahl.
Der Faktor liegt in der Übersetzung, nicht an der GPU.

## Stufe 1: Emulator-Abfall, ~38 ms

Arbeit, die **kein PS5-Spiel verursacht**. Beide Posten haben eine belegte Ursache **und**
eine Mechanik, die im Baum schon existiert und nur nicht greift.

**Image-Round-Trip — 24 ms, 721 MiB pro Present.** Dieselbe Rendertarget-Fläche ist getiledes
Image *und* linearer Gast-Buffer; `0x80003e8700` bindet sie als Buffer, je zweimal pro
Present lesend und schreibend. Daraus folgen 2 Write-backs und 2 Uploads pro Fläche, 93 %
aller Write-backs mit `reason=storage refresh`. Der Ausweg heißt `borrowUnits` und wird von
einer von sechs Klauseln verweigert — welche, sagt eine risikolose Trace-Ergänzung.
Obergrenze gemessen: **+48 % fps** (`APS5_GPU_NO_WRITEBACK=1`, kaputter Zustand, nur als
Schranke).

**Render-Pass pro Draw — 18,4 ms bei 25 Draws.** `render passes 2075 begun, 0 draws
continued one`: jeder Draw öffnet seinen eigenen Pass auf 4K-DCC-Targets, jeder Pass lädt
und speichert die Attachments. Die Fortsetzung existiert (`Draw.cpp:1614`), hängt aber an
`!gpuIndirect && !readsTarget` — und dieser Titel zeichnet GPU-seitig indirekt, wo die
Argument-Barriere außerhalb des Passes sitzen muss. Sie kann also **konstruktiv nie**
greifen, nicht zufällig null von 2075.

**Was Stufe 1 bringt** (Draws konservativ auf 4 ms angesetzt):

> 120 ms − 38 ms = **82 ms = 12,3 fps**

Das deckt sich mit der gemessenen Obergrenze von 12,1 fps aus dem `NO_WRITEBACK`-Lauf.

## Stufe 2: die Rechnung, die 60 fps verlangt

Nach Stufe 1 sind die **zwei heißen Shader 47,4 ms von 82 ms = 58 %**. Und hier ist die
Zahl, die die Prognose trägt:

> **Selbst wenn alles außer diesen zwei Shadern auf null fiele, wären 47,4 ms = 21 fps.**

**60 fps sind also ohne Angriff auf die Übersetzungssteuer unerreichbar.** Ab Stufe 1
braucht es einen Faktor **4,9** auf das gesamte restliche Budget — und der Großteil davon
muss aus diesen beiden Programmen kommen.

## Stufe 3: die Übersetzungssteuer, und was dort noch offen ist

Gemessen: ~89.000 Lane-Zyklen pro Invocation, wo echte Hardware einige Tausend bräuchte.
85 SPIR-V-Words pro Guest-Instruktion, 34 % des Codes Lane-Maskierung. **Von der Codemenge
her ist sie nicht reduzierbar** — volle Optimierung bringt 1,4 %, halber Code kostet +94 %.

Was damit **noch nicht** gemessen ist, in der Reihenfolge der Plausibilität. Jeder Punkt
mit der Messung, die ihn qualifizieren würde:

1. **Sub-Dword-Zugriffe.** Buffer 4 hat **2 Byte** Stride, Buffer 10 **1 Byte**, jeweils ein
   Record pro Invocation. Solche Zugriffe werden mit Shift/Mask/Select nachgebaut — dazu
   passen die gemessenen 34 % Bit-Manipulation. *Messung:* die Zugriffe im Entry-Code
   zählen und gegen `ms/Mio. Invocations` der elf Programme auftragen; danach prüfen, ob
   eine native Formatsicht sie ersetzen kann.
2. **Der Lookup pro Zugriff.** `get_bda_pointer` ist mit `DontInline` deklariert und macht
   eine **Binärsuche** über die Range-Tabelle, mit einem Load pro Iteration. *Messung:*
   dynamische Aufrufzahl pro Invocation, dann ein A/B mit inlinebarer Variante.
3. **16 Image-Fetches pro Invocation** im zweiten Shader, bei emulierter Formatumrechnung
   und Filterung. *Messung:* welcher Anteil seiner 19,8 ms auf die Fetches geht — ein
   Variantenlauf mit reduzierter Fetch-Zahl beantwortet es.
4. **Die Lane-Maskierung selbst** (34 %). Strukturell: RDNA prädiziert über EXEC, und das
   wird explizit nachgebaut. Die einzige bekannte Reduktion wäre echte wave64-Hardware, die
   es auf NVIDIA nicht gibt. Hier ist am wenigsten zu erwarten.

## Nicht erneut prüfen

| Ausgeschlossen | Womit |
|---|---|
| PCIe / Gast-Speicherzugriff | 27,6 ms mit vier Elementen device-lokal, 28,0 ms mit **allen** |
| Registerdruck / Spilling | 80 bzw. 46 Register, `Stack Size = 0` |
| Fehlende SPIR-V-Optimierung | `APS5_SPIRV_OPT=full` bringt 1,4 % |
| Codemenge / Wave64-Lane-Zahl | `SINGLE_LANE` auf ein Programm kostet **+94 %**, symmetrisch für beide Shader |
| Modulgröße als Prädiktor | `0x8000269d00` hat 5,4x mehr Code und kostet 27x weniger |
| Auflösung / 4K-Grid | drei Programme mit denselben 8,29 Mio. Invocations kosten 0,013–0,067 ms/Mio. |
| Buffer-Zahl, BDA-Präsenz, Speicherbandbreite | siehe Hauptdokument |
| Mirroring der ganzen Arena | 44 ms Vorbereitung pro Build, 1,2 fps |

## Der Vorbehalt

**fps machen das Menü nicht sichtbar.** Der Titel verlässt seine Initialisierungsstufe nicht
— 560 Sekunden ohne einen neuen Shader, kein Streaming, keine Arbeit für die Worker. Diese
Roadmap gilt für den Zustand *danach*: wenn geladen wird, ist sie der Plan, und dann in der
Reihenfolge Stufe 1, dann Stufe 3.
