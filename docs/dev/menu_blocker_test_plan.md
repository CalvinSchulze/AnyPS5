# Messplan: liest er wirklich nichts, und kommen Bilder aus dem Decoder?

## Regel für diesen Auftrag: **nicht interpretieren**

Zahlen mit ihrer Quelle, nichts weiter. Kein Urteil, keine Ursache, keine Hypothese, kein
„damit ist bewiesen / widerlegt / ausgeschlossen", **kein Fazit-Abschnitt**. Wörtlich
zitieren mit Zeilennummer, zählen, tabellieren. Eine Beobachtung, die nicht zur Frage passt,
**unkommentiert nennen**. Fehlt ein Schalter oder scheitert ein Lauf: sagen, nicht ersetzen.

Die letzten zwei Runden waren genau so, und beide waren dadurch brauchbar.

## Warum diese Runde nötig ist: zwei Instrumente waren untauglich

**1. Mein Lesezähler war blind.** Er saß in `sceKernelPread`, aber `Aio.cpp` ruft
`NativePositioned_nid_no_patch` **direkt** — die Lesevorgänge des AIO-Workers liefen also
daran vorbei. „101 Leseaufrufe, 6,0 MiB, danach nichts" war damit **kein** Beweis, dass der
Titel nichts lädt. Der Zähler sitzt jetzt am Engpass, durch den `pread` **und** AIO laufen.

**2. `size=0x0` in den `[videodec2] Decode`-Zeilen bedeutet nichts.** Die Zeile liest
`decoder.width/height` **vor** dem Dekodieren, und sie ist auf die ersten drei Aufrufe
begrenzt — 0x0 ist also der Zustand vor dem ersten Bild, kein Fehler. Neu ist deshalb eine
Fortschrittszeile, die zählt, wie viele Dekodier-Aufrufe kamen und wie viele davon ein Bild
**zurückgegeben** haben.

Was aus der letzten Runde stehen bleibt: der Decoder wird für **H.264 1920x1088** erzeugt,
und der Titel schickt echte Access Units hinein (249250, 13157, 17651 Byte). Gefüttert wird
er also.

## Bauen und Deployen: ja, nötig — **zwei** Module

```
ninja -C "I:\Emulation\PS5 Emu\Software\AnyPS5\build" core/libs/libs/libkernel.prx core/libs/libs/libSceVideodec2.prx
```

Toolchain-`bin` in den `PATH` (Ninja und g++ im Scratchpad einer früheren Sitzung, `cmake`
ist **nicht** im `PATH`):

```
C:\Users\CptWhuti\AppData\Local\Temp\claude\I--Emulation-PS5-Emu-Software-AnyPS5\685ea80c-0bfb-4ab4-b237-3f3880416715\scratchpad\mingw64\bin
```

**Deployen** wie gehabt, jetzt **beide** Dateien, je dreifach:

```
build\core\libs\libs\libkernel.prx        ->  Z:\GhostOfYotei\libkernel.prx
                                              Z:\GhostOfYotei\libs\libkernel.prx
                                              Z:\GhostOfYotei\libs\libs\libkernel.prx
build\core\libs\libs\libSceVideodec2.prx  ->  Z:\GhostOfYotei\libSceVideodec2.prx
                                              Z:\GhostOfYotei\libs\libSceVideodec2.prx
                                              Z:\GhostOfYotei\libs\libs\libSceVideodec2.prx
```

**Marker, dass es greift:**

> `[fileio] tracing enabled` muss im Log stehen **und** mindestens eine Zeile der Form
> `[videodec2] N decode calls, M pictures out, last WxH`. Fehlt eines von beiden:
> **abbrechen und melden**, mit der Angabe, welches fehlt.

## Lauf 1 — Lesen und Dekodieren zusammen

```
APS5_TRACE_FILEIO=1 APS5_TRACE_VIDEODEC=1 .pp.exe
```

**Vier Minuten.** Beide Zeilenarten kommen höchstens alle fünf Sekunden.

**Zu berichten:**

1. **Alle** `[fileio]`-Zeilen wörtlich mit Zeilennummer, in Reihenfolge.
2. **Alle** `[videodec2] ... decode calls ...`-Zeilen wörtlich mit Zeilennummer, in
   Reihenfolge. (Die `Decode`-Zeilen mit `input=`/`au=` sind diesmal **nicht** gefragt.)
3. Die Zeilennummer der **letzten** Zeile jeder der beiden Arten, und wie viele Logzeilen
   danach noch kommen.
4. Alle `sceKernelOpen`-Pfade in Reihenfolge.

## Lauf 2 — die Render-Targets, zweiter Versuch

Im letzten Lauf entstanden **0** `target_*.raw`-Dateien, obwohl `APS5_DUMP_TARGETS=12`
gesetzt war. Die Dateien heißen `target_<adresse>_<n>.raw` und werden ins
**Arbeitsverzeichnis des Titels** geschrieben, dort, wo auch die `frame_*.bmp` landen.

```
APS5_DUMP_TARGETS=12 APS5_DUMP_FRAMES=4 APS5_DUMP_SCALE=4 .pp.exe
```

Zwei Minuten.

**Zu berichten:**

1. Eine **Verzeichnisauflistung** des Ordners, in dem die `frame_*.bmp` liegen — alle
   Dateinamen, die beim Lauf neu entstanden sind.
2. Falls `target_*`-Dateien dabei sind: pro Datei Breite x Höhe, `VkFormat` und Max je Kanal.
3. Falls keine dabei sind: genau das schreiben, zusammen mit der Auflistung aus Punkt 1.

## Was nicht zu tun ist

- **Nicht** interpretieren.
- **Nicht** erneut Hang-Dumps, Sampler, `WATCH_ADDR`, `DUMP_GUEST` oder einen reinen
  Frame-Dump fahren — alle fünf sind durch (30 Frames, alle schwarz).
- **Nicht** an fps arbeiten.
- **Keinen** Code ändern.

## Ergebnisform

Die zitierten Zeilen, die Verzeichnisauflistung, Logs nach `_analytics/menu_blocker/`.
