# Messplan: was der Titel nach dem Intro-Film noch tut

## Regel für diesen Auftrag: **nicht interpretieren**

Zahlen mit ihrer Quelle, nichts weiter. Kein Urteil, keine Ursache, keine Hypothese, kein
„damit ist bewiesen / widerlegt / ausgeschlossen", **kein Fazit-Abschnitt**. Wörtlich
zitieren mit Zeilennummer, zählen, tabellieren. Eine Beobachtung, die nicht zur Frage passt,
**unkommentiert nennen**. Fehlt ein Schalter oder scheitert ein Lauf: sagen, nicht ersetzen.

## Was die letzte Runde ergeben hat

Der korrigierte Lesezähler zeigt: **der Titel liest** (AIO lief am alten Zähler vorbei).

```
4054: 101 read calls, 6.0 MiB      4065: 1 decode calls, 0 pictures out, last 0x0
4437: 361 read calls, 6.8 MiB      4447: 42 decode calls, 40 pictures out, last 1920x1080
4518: 594 read calls, 7.5 MiB      4524: 80 decode calls, 78 pictures out
4539: 829 read calls, 8.2 MiB      4556: 116 decode calls, 114 pictures out
4619: 1064 read calls, 8.9 MiB     4625: 152 decode calls, 150 pictures out, last 1920x1080
```

**Der Decoder arbeitet** — 150 von 152 Aufrufen geben ein Bild bei 1920x1080 zurück. Und
**beide Reihen enden gleichzeitig** (Zeile 4619 und 4625); danach kommen ~3075 Logzeilen
ohne einen einzigen Lese- oder Dekodiervorgang, während die GPU weiterläuft
(`[gpu] 3000 → 3700 dispatches`).

Aus dem Code dazu ausgeschlossen: **AIO hängt nicht** (`Aio.cpp` führt jede Anfrage
synchron aus und setzt `AioCompleted`), und **Flip/Vblank-Events werden geliefert**
(`triggerEvents` pro Vblank). Weiterhin offen: `APS5_DUMP_TARGETS` erzeugt **0** Dateien,
auch im richtigen Verzeichnis.

**Die Frage dieser Runde:** 150 Bilder sind bei 30 fps ein 5-Sekunden-Clip. Baut der Titel
den Film danach ordentlich ab, und was pollt er, während er wartet?

## Bauen und Deployen: ja, nötig — **zwei** Module

```
ninja -C "I:\Emulation\PS5 Emu\Software\AnyPS5\build" core/libs/libs/libSceVideodec2.prx core/libs/libs/libSceSystemService.prx
```

Toolchain-`bin` in den `PATH`:

```
C:\Users\CptWhuti\AppData\Local\Temp\claude\I--Emulation-PS5-Emu-Software-AnyPS5\685ea80c-0bfb-4ab4-b237-3f3880416715\scratchpad\mingw64\bin
```

**Deployen**, beide Dateien je dreifach:

```
build\core\libs\libs\libSceVideodec2.prx     ->  Z:\GhostOfYotei\libSceVideodec2.prx
                                                 Z:\GhostOfYotei\libs\libSceVideodec2.prx
                                                 Z:\GhostOfYotei\libs\libs\libSceVideodec2.prx
build\core\libs\libs\libSceSystemService.prx ->  Z:\GhostOfYotei\libSceSystemService.prx
                                                 Z:\GhostOfYotei\libs\libSceSystemService.prx
                                                 Z:\GhostOfYotei\libs\libs\libSceSystemService.prx
```

**Marker, dass es greift:**

> Mindestens eine Zeile `[videodec2] ... flushes, ... deletes, last ...` **und** mindestens
> eine Zeile `[sysevent] ... receive calls`. Fehlt eines von beiden: **abbrechen und melden**,
> mit Angabe welches.

## Lauf 1 — Film-Abbau und Event-Pumpe

```
APS5_TRACE_VIDEODEC=1 APS5_TRACE_SYSTEMEVENT=1 .pp.exe
```

**Vier Minuten.** Beide Zeilenarten kommen höchstens alle fünf Sekunden.

Die `[videodec2]`-Fortschrittszeile trägt jetzt zusätzlich `flushes` und `deletes` (Aufrufe
von `sceVideodec2Flush` und `sceVideodec2DeleteDecoder`). `[sysevent]` zählt die Aufrufe von
`sceSystemServiceReceiveEvent`, das im Code **unbedingt `NO_EVENT`** zurückgibt.

**Zu berichten:**

1. **Alle** `[videodec2] ... decode calls ...`-Zeilen wörtlich mit Zeilennummer.
2. **Alle** `[sysevent]`-Zeilen wörtlich mit Zeilennummer.
3. Für jede der beiden Arten: die Zeilennummer der **letzten** Zeile und wie viele Logzeilen
   danach noch folgen.
4. Laufen die `[sysevent]`-Zahlen nach dem Ende der `[videodec2]`-Zeilen **weiter**? Nur die
   Zahlen, keine Deutung.

## Lauf 2 — nur falls Lauf 1 ohne `[sysevent]`-Zeilen bleibt

Dann pollt der Titel die Event-Pumpe nicht, und die Frage verschiebt sich. In diesem Fall
**keinen** weiteren Lauf starten, sondern melden — der nächste Schritt ist dann eine
Codeänderung, keine Messung.

## Was nicht zu tun ist

- **Nicht** interpretieren.
- **Nicht** erneut Hang-Dumps, Sampler, `WATCH_ADDR`, `DUMP_GUEST`, Frame-Dumps oder
  `TRACE_FILEIO` fahren — alle sind durch.
- **Nicht** an fps arbeiten.
- **Keinen** Code ändern.

## Ergebnisform

Die zitierten Zeilen, Logs nach `_analytics/menu_blocker/`.
