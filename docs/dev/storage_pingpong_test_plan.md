# Messplan: wer die Storage-Images schmutzig macht

> **Gelaufen am 13.10., abgeschlossen.** Logs unter `_analytics/pingpong_tests/`,
> Ergebnisse im Hauptdokument. Lauf 1: Hypothese **bestätigt**, `cpuWrote` zu 100 % 0 für
> alle drei Haupt-Targets, Ursache auf `Texture.cpp:1424` / `:1739` / `:2806` festgenagelt.
> Lauf 2: Hypothese **gefallen** — `laneCount=1` verdoppelt die Laufzeit, symmetrisch für
> beide Shader; zwei Lanes sind das Optimum. Nächster Schritt ist eine Codeänderung, kein
> Messlauf.

Zwei Läufe, beide klein. Vorgeschichte in
[`immediate_shader_boost.md`](immediate_shader_boost.md); die Runde davor steht in
[`frame_cost_test_plan.md`](frame_cost_test_plan.md) und ist abgeschlossen.

Referenz ist **Lauf 1** aus `_analytics/frame_cost_tests/lauf_1_pipeline_stats.log`
(82 Presents / 10 s, `draw` 18,97 ms, `storage-upload` 10,31 ms, `storage-writeback`
14,68 ms pro Present). Basis wie immer:

```
APS5_PROFILE_GPU=1 APS5_PROFILE_DRAW=1 .pp.exe
```

Logs nach `_analytics/pingpong_tests/`.

## Lauf 1 — `APS5_CAPTURE_TRACE=1 APS5_TRACE_UPLOAD=1`

**Die Frage.** `APS5_GPU_NO_WRITEBACK=1` brachte +48 % fps und halbierte dabei auch die
*Uploads*, obwohl der Schalter nur den Write-back abschaltet. Der Verdacht: der Treiber
schreibt GPU-Ergebnisse in den Gastspeicher, die Write-Watch sieht die Blöcke als
geschrieben, und der nächste Refresh hält die eigenen Bytes für eine Gast-Änderung und
lädt sie zurück. Ein Pingpong.

Der `[upload]`-Trace allein beantwortet das **nicht**: er druckt „guest memory changed"
schlicht dann, wenn die DCC-Keys gleich waren (`Texture.cpp:1467`), nicht weil jemand eine
Gast-Änderung festgestellt hat. `APS5_CAPTURE_TRACE=1` schaltet die Zeile frei, die die
Entscheidung trägt (`Texture.cpp:1460`):

```
refresh image=<addr> bytes=<n> generation=<n> dirty=<0|1> keysChanged=<0|1> cpuWrote=<0|1>
```

**Zu notieren**, und zwar getrennt für die drei häufigsten Adressen aus der letzten Runde
(`0x5000860000+0x1fe0000` ~32 MiB 4K-Target, `0x50727e0000+0x870000`,
`0x5060d30000+0x870000`):

- Verteilung von `cpuWrote` über die `refresh`-Zeilen: **wie oft 1, wie oft 0?** Das ist
  die Kernzahl des Laufs.
- Dieselbe Verteilung für `dirty` und `keysChanged`, und ob `generation` sich pro Present
  ändert.
- Wiederholt sich **dieselbe** Adresse Present für Present, oder wandern die Adressen?
- Wie viele `refresh`-Zeilen pro Present insgesamt, gegen die 31 Uploads und 43
  Write-backs aus der Klassenzählung.

**Wie das Ergebnis zu lesen ist** — bitte genau diese Unterscheidung treffen:

- `cpuWrote=1` häufig → das **Spiel** schreibt diese Targets wirklich, und der Pingpong
  ist keiner. Dann ist die Hypothese tot und der Hebel liegt woanders.
- `cpuWrote=0` häufig, `dirty=0`, und trotzdem Upload → der Treiber hält seine **eigenen**
  Write-backs für Änderungen. Dann ist die Hypothese bestätigt und die Richtung ist, die
  zurückgeschriebenen Blöcke als eigene zu erkennen (die Maschinerie dafür existiert:
  `Recorder::NoteWrittenBack`, `GuestMemory::StoredOver`, `stampedBlocks`).

**Warnung zur Größe:** der Capture-Trace ist gesprächig. Wenn das Log unhandlich wird,
lieber **kürzer** laufen lassen und das sagen, als ein Fenster zu nehmen, in dem die Szene
noch nicht stabil ist. Zahlen als Verteilung angeben, nicht als Einzelzeilen-Zitat.

## Lauf 2 — `APS5_SINGLE_LANE=800038be00`

**Die Frage.** Wie viel der 27,6 ms des Flaschenhalses kostet die Wave64-Emulation auf
32-Lane-Subgroups? Sie verdoppelt den emittierten Code (131.449 → 69.258 Words bei
`laneCount=1`).

`APS5_SINGLE_LANE=all` ist letzte Runde am Recompiler gescheitert (fremde Shader, 0
Presents). Der Schalter nimmt aber eine **Programmadresse in Hex**, und dann trifft er nur
dieses Programm.

**Zu notieren:** ms pro Dispatch für `0x800038be00`, Presents pro 10 s, und ob die drei
Recompiler-Fehler der letzten Runde ausbleiben. Zum Vergleich mit derselben Adressform
optional `APS5_SINGLE_LANE=80003e8700`.

**Das ist eine Messung, kein Fix.** Die Emulation wird semantisch falsch; Bildfehler in den
betroffenen Pässen sind erwartet und **kein** Abbruchgrund. Nur ein Absturz oder 0 Presents
macht den Lauf unbrauchbar.

## Was nicht zu tun ist

- **Nicht** `APS5_GPU_NO_WRITEBACK` als Fix behandeln oder damit fps melden. Die 12,1 fps
  sind eine Obergrenze eines kaputten Zustands.
- **Nicht** aus `[upload]`-Gründen auf Ursachen schließen. Der String ist ein else-Zweig.
- **Nicht** erneut PCIe, Staging, Fenstergröße, Registerdruck oder `SPIRV_OPT` messen —
  alle vier sind erledigt.
- **Keinen** Code ändern.

## Ergebnisform

Pro Lauf: die Zahlen mit Logzeile, die oben genannten Verteilungen als Tabelle, zwei Sätze
Urteil, Rohlogs unter `_analytics/pingpong_tests/`. Wo eine These nicht trägt, das bitte
schreiben — in den letzten drei Runden ist jede Runde mindestens eine gefallen, auch meine.
