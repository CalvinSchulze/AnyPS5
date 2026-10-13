# Messplan: flippt der Titel ein Bild, und ist es leer?

## Regel für diesen Auftrag: **nicht interpretieren**

Zahlen mit ihrer Quelle, nichts weiter. Kein Urteil, keine Ursache, keine Hypothese, kein
„damit ist bewiesen / widerlegt / ausgeschlossen", **kein Fazit-Abschnitt**. Wörtlich
zitieren mit Zeilennummer, zählen, tabellieren. Eine Beobachtung, die nicht zur Frage passt,
**unkommentiert nennen**. Fehlt ein Schalter oder scheitert ein Lauf: sagen, nicht ersetzen.

## Was die letzte Runde ergeben hat

**`[sysevent]`: 0 Aufrufe.** Der Titel pollt `sceSystemServiceReceiveEvent` nie — die
System-Event-Pumpe ist kein Gate. Erledigt.

**Der Film endet nicht, er bleibt stehen.** Diesmal:

```
4056:   1 decode calls,   0 pictures out, 0 flushes, 0 deletes, last 0x0
4447: 152 decode calls, 150 pictures out, 0 flushes, 0 deletes, last 1920x1080
4564: 304 decode calls, 302 pictures out, 0 flushes, 0 deletes
4609: 457 decode calls, 455 pictures out, 0 flushes, 0 deletes, last 1920x1080
```

Danach 3467 Zeilen ohne Dekodierung. Im Lauf davor waren es **152** Bilder, jetzt **455** —
die Zahl ist also **nicht** fest, und `flushes` wie `deletes` bleiben **0**. Der Titel baut
den Decoder nie ab. Die frühere Lesart „ein 5-Sekunden-Clip läuft zu Ende" ist damit
widerlegt: die Wiedergabe **stockt** an wechselnder Stelle.

**Woran das die Frage hängt:** eine Film-Pipeline, die ohne Abbau stehenbleibt, hängt
typischerweise an der **Ausgabeseite** — die dekodierten Bilder werden nicht abgeholt, die
Warteschlange füllt sich, der Titel schickt nichts mehr hinein. Und genau dort haben wir
eine Lücke: die präsentierten Frames sind schwarz, und `APS5_DUMP_TARGETS` schreibt 0
Dateien.

## Was neu im Build ist

`APS5_TRACE_FLIP=1` meldet alle fünf Sekunden eine `[flip]`-Zeile mit:

- wie viele Flips auf **echte** Puffer gingen, wie viele auf die Sonderindizes **BLACK**
  (−2) und **BLANK** (−1) — die sind per Definition schwarz,
- und wie viele von 16384 gelesenen Bytes eines echten Puffers **nicht null** waren
  (jedes 128. Byte der ersten 2 MiB, rein lesend).

Damit lassen sich zwei Dinge trennen, die der Frame-Dump zusammenwirft: ob der Titel
überhaupt ein Bild zum Flippen gibt, und ob dieses Bild leer ist.

## Bauen und Deployen: ja, nötig — **ein** Modul

```
ninja -C "I:\Emulation\PS5 Emu\Software\AnyPS5\build" core/libs/libs/libSceVideoOut.prx
```

Toolchain-`bin` in den `PATH`:

```
C:\Users\CptWhuti\AppData\Local\Temp\claude\I--Emulation-PS5-Emu-Software-AnyPS5\685ea80c-0bfb-4ab4-b237-3f3880416715\scratchpad\mingw64\bin
```

**Deployen**, dreifach:

```
build\core\libs\libs\libSceVideoOut.prx  ->  Z:\GhostOfYotei\libSceVideoOut.prx
                                             Z:\GhostOfYotei\libs\libSceVideoOut.prx
                                             Z:\GhostOfYotei\libs\libs\libSceVideoOut.prx
```

**Marker, dass es greift:**

> Mindestens eine `[flip]`-Zeile im Log. Fehlt sie: **abbrechen und melden**.

## Lauf 1 — Flips und Bildinhalt

```
APS5_TRACE_FLIP=1 APS5_TRACE_VIDEODEC=1 .pp.exe
```

**Vier Minuten.**

**Zu berichten:**

1. **Alle** `[flip]`-Zeilen wörtlich mit Zeilennummer, in Reihenfolge.
2. **Alle** `[videodec2] ... decode calls ...`-Zeilen wörtlich mit Zeilennummer.
3. Die Zeilennummer der letzten Zeile jeder Art und wie viele Logzeilen danach folgen.
4. Laufen die `[flip]`-Zahlen weiter, nachdem die `[videodec2]`-Zeilen aufgehört haben?
   Nur die Zahlen.

## Was nicht zu tun ist

- **Nicht** interpretieren.
- **Nicht** erneut Hang-Dumps, Sampler, `WATCH_ADDR`, `DUMP_GUEST`, Frame-Dumps,
  `DUMP_TARGETS`, `TRACE_FILEIO` oder `TRACE_SYSTEMEVENT` fahren — alle sind durch.
- **Nicht** an fps arbeiten.
- **Keinen** Code ändern.

## Ergebnisform

Die zitierten Zeilen, Logs nach `_analytics/menu_blocker/`.
