# Messplan: liest der Titel überhaupt etwas?

## Regel für diesen Auftrag: **nicht interpretieren**

Zahlen mit ihrer Quelle, nichts weiter. Kein Urteil, keine Ursache, keine Hypothese, kein
„damit ist bewiesen / widerlegt / ausgeschlossen", **kein Fazit-Abschnitt**. Zitiere wörtlich
mit Zeilennummer, zähle, tabelliere. Eine Beobachtung, die nicht zur Frage passt, **nenne
sie unkommentiert**. Fehlt ein Schalter oder scheitert ein Lauf: sagen, nicht ersetzen.
Ein Satz „fertig, hier sind die Zahlen" am Ende reicht.

Die letzte Runde war genau so, und sie war dadurch brauchbar.

## Bauen und Deployen: ja, nötig

Neu ist diesmal ein Schalter in **`libkernel.prx`** (`File/src/Open.cpp`,
`File/src/Stdio.cpp`, `File/include/File.hpp`).

```
ninja -C "I:\Emulation\PS5 Emu\Software\AnyPS5\build" core/libs/libs/libkernel.prx
```

Toolchain-`bin` dieses Rechners in den `PATH` (Ninja und g++ liegen im Scratchpad einer
früheren Sitzung, `cmake` ist **nicht** im `PATH`):

```
C:\Users\CptWhuti\AppData\Local\Temp\claude\I--Emulation-PS5-Emu-Software-AnyPS5\685ea80c-0bfb-4ab4-b237-3f3880416715\scratchpad\mingw64\bin
```

**Deployen** wie in der letzten Runde, diesmal für `libkernel.prx`:

```
build\core\libs\libs\libkernel.prx  ->  Z:\GhostOfYotei\libkernel.prx
                                        Z:\GhostOfYotei\libs\libkernel.prx
                                        Z:\GhostOfYotei\libs\libs\libkernel.prx
```

**Marker, dass es greift** — ohne ihn ist der Lauf wertlos:

> Im Log muss die Zeile **`[fileio] tracing enabled`** stehen. Fehlt sie, hat Build oder
> Deploy nicht gegriffen: **abbrechen und melden**.

## Stand: die Fence-Spur ist zu Ende

Die Dumps haben sie erledigt. Bei Stride 32 laufen die Slots 0, 1, 2, 4, 8, 9 mit der
Bildrate mit (0 → ~1331 in 194 s), Slot 3 und 5 bewegen sich **nie**, 6/7/10 blieben früh
bei 7 stehen, 11–15 haben sich genau einmal bewegt (Werte 12–16). Lauf 2 mit Stride 8
bestätigt es: dort laufen die Slots 0, 4, 8, 16 — also Byte 0, 32, 64, 128, genau die
aktiven aus Lauf 1.

**Warum das die Spur beendet:** der Hauptthread durchläuft seine fünf Spin-Schleifen weiter
und liefert Frames mit ~7/s. Wäre eine seiner Schleifen auf einen stehenden Slot gerichtet,
käme er dort nie wieder heraus und der Frame-Zähler stünde still. Die stehenden Slots
gehören also zu Warteschlangen, auf die niemand wartet. **Keine Vollzugsmeldung fehlt.**

## Die Korrektur, aus der dieser Lauf folgt

Ich hatte geschrieben, es werde „nichts gestreamt", weil im ganzen Lauf nur **7**
`sceKernelOpen`-Aufrufe stehen (`t26344.dat`, `playgo.pgm`, `save_icon.png`, `noloc.larc`
4x). **Das war unbelegt.** Ein Spiel öffnet seine Archive einmal und liest dann darin —
`noloc.larc` *ist* ein Archiv. Und **Lesezugriffe werden bisher gar nicht protokolliert**:
geloggt sind nur `sceKernelOpen` und `RunThread`.

Ob der Titel lädt, ist damit **offen**, und es ist die Frage, auf die alles hinausläuft.

## Lauf 1 — der Lesezähler

```
APS5_TRACE_FILEIO=1 .pp.exe
```

**Vier Minuten** laufen lassen, damit die Intro-Phase durch ist und der Ladekreisel mehrere
Minuten mitläuft.

`[fileio]`-Zeilen kommen höchstens alle fünf Sekunden und nur, wenn gelesen wurde.

**Zu berichten:**

1. Die Zeile `[fileio] tracing enabled` mit Zeilennummer.
2. **Alle** `[fileio]`-Zeilen wörtlich, in Reihenfolge, mit Zeilennummer.
3. Falls nach der ersten Minute **keine** weitere `[fileio]`-Zeile mehr kommt: genau das
   schreiben, mit der Zeilennummer der letzten.
4. Zusätzlich wie gehabt: alle `sceKernelOpen`-Pfade in Reihenfolge.

## Lauf 2 — Bild und Render-Targets (aus der letzten Runde offen)

```
APS5_DUMP_FRAMES=30 APS5_DUMP_FRAMES_EVERY=10 APS5_DUMP_SCALE=4 APS5_DUMP_TARGETS=12 APS5_TRACE_VIDEODEC=1 .pp.exe
```

Drei Minuten. Die Frage: rendert der Titel im hängenden Zustand nichts, oder entsteht ein
Bild, das auf dem Weg zum Bildschirm verloren geht? Die präsentierten Frames waren schwarz,
die **Render-Targets** hat niemand angesehen.

**Zu berichten:**

1. Pro `frame_*.bmp`: **Max-Wert je Kanal** (R, G, B), eine Zeile pro Datei, in
   Dateireihenfolge.
2. Dasselbe für die Target-Dumps: Datei, Breite x Höhe, `VkFormat`, Max je Kanal.
3. **Alle** `[videodec2]`-Zeilen wörtlich; falls keine erscheint, genau das schreiben.

**Falle vorweg:** die `[videodec2] Decode`-Zeile ist im Code auf die **ersten drei**
Dekodierungen begrenzt (`decoder.decoded < 3`). Drei Zeilen heißen **nicht** drei Frames.

## Was nicht zu tun ist

- **Nicht** interpretieren.
- **Nicht** erneut Hang-Dumps, Sampler, `WATCH_ADDR` oder `DUMP_GUEST` fahren — alle vier
  sind durch.
- **Nicht** an fps arbeiten.
- **Keinen** Code ändern.

## Ergebnisform

Die zitierten Zeilen und die zwei Tabellen aus Lauf 2, Logs nach `_analytics/menu_blocker/`.
