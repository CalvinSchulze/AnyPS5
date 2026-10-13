# Messplan: wartet jemand auf ein Ereignis, das nie kommt?

## Regel für diesen Auftrag: **nicht interpretieren**

Zahlen mit ihrer Quelle, nichts weiter. Kein Urteil, keine Ursache, keine Hypothese, kein
„damit ist bewiesen / widerlegt / ausgeschlossen", **kein Fazit-Abschnitt**. Wörtlich
zitieren mit Zeilennummer, zählen, tabellieren. Beobachtungen, die nicht zur Frage passen,
**unkommentiert nennen**.

**Ausnahme wie zuvor erwünscht:** ein Satz, was auf dem **Bildschirm** zu sehen war. Falls
kein Spielfenster sichtbar ist, bitte genau das schreiben — im letzten Lauf stand dort „nur
Desktop", und dann ist die Beobachtung wertlos, nicht das Spiel.

## Warum dieser Lauf

Neun Runden haben alles Messbare ausgeschlossen: Deadlock, GPU-Fences, blockierte Threads,
Savedata, PlayGo, System-Event-Pumpe (0 Aufrufe), AIO, Flip-/Vblank-Events, Dekodierung
(455 Bilder), Anzeigepfad, fehlende Dateien, Sprache (wir melden ENGLISH_US, Englisch ist
installiert) und Geschwindigkeit (`TIME_SCALE` ändert nichts).

Der Intro-Film läuft **vollständig** durch (deterministisch ~455 Bilder, 9,0 MiB aus dem
522 MB großen `noloc.larc`), und danach verlangt der Titel nichts mehr.

Was dazu passt und noch offen ist: **drei Threads parken dauerhaft in
`sceKernelWaitEqueue`** — und **kein NP- oder Trophy-Modul von uns ruft je
`EqueueTriggerEvent`**. Ein Ereignis, auf das dort gewartet wird, käme also nie. Nur sieht
man das mit keinem bisherigen Instrument: `APS5_TRACE_WAITS` meldet erst, **wenn** ein
Warten endet, und ein ewig geparkter Thread erzeugt gar keine Zeile.

## Was neu im Build ist

`APS5_TRACE_EQUEUE=1` gibt **alle zehn Sekunden** eine Zeile pro lebender Event-Queue aus,
aus einem **eigenen Thread** — weil genau der Fall interessant ist, in dem nichts
zurückkehrt:

```
[equeue] "<name>" handle=N waiting=K waits=W timeouts=T events=E
```

`waiting` sind die Threads, die **jetzt** darin hängen, `events` die je zugestellten
Ereignisse. Eine Queue mit `waiting>=1` und `events=0` über Minuten ist das gesuchte Bild.

## Bauen und Deployen: ja, nötig — **ein** Modul

```
ninja -C "I:\Emulation\PS5 Emu\Software\AnyPS5\build" core/libs/libs/libkernel.prx
```

Toolchain-`bin` in den `PATH`:

```
C:\Users\CptWhuti\AppData\Local\Temp\claude\I--Emulation-PS5-Emu-Software-AnyPS5\685ea80c-0bfb-4ab4-b237-3f3880416715\scratchpad\mingw64\bin
```

**Deployen**, dreifach:

```
build\core\libs\libs\libkernel.prx  ->  Z:\GhostOfYotei\libkernel.prx
                                        Z:\GhostOfYotei\libs\libkernel.prx
                                        Z:\GhostOfYotei\libs\libs\libkernel.prx
```

**Marker:**

> Die Zeile `[equeue] tracing enabled` muss im Log stehen. Fehlt sie: **abbrechen und
> melden**.

## Lauf 1 — die Event-Queues über die Zeit

```
APS5_TRACE_EQUEUE=1 APS5_TRACE_VIDEODEC=1 .pp.exe
```

**Fünf Minuten.**

**Zu berichten:**

1. Die Zeile `[equeue] tracing enabled` mit Zeilennummer.
2. Den **ersten** vollständigen Block `[equeue]`-Zeilen (alle Zeilen eines Zehn-Sekunden-
   Berichts), wörtlich mit Zeilennummern.
3. Den **letzten** vollständigen Block, wörtlich mit Zeilennummern.
4. Eine Tabelle über alle Queues, die irgendwann `waiting>=1` hatten: Name, `waiting` im
   letzten Block, `waits`, `timeouts`, `events` im letzten Block.
5. Alle `[videodec2] ... decode calls ...`-Zeilen wörtlich (zur Einordnung, wann der Film
   endete).
6. Ein Satz zum Bildschirm.

## Was nicht zu tun ist

- **Nicht** interpretieren (außer der Bildschirm-Beobachtung).
- **Nicht** erneut Hang-Dumps, Sampler, `WATCH_ADDR`, `DUMP_GUEST`, Frame- oder
  Target-Dumps, `TRACE_SYSTEMEVENT`, `TRACE_FLIP`, `TRACE_FILEIO` oder `TIME_SCALE` fahren —
  alle sind durch.
- **Nicht** an fps arbeiten (dafür gibt es einen eigenen Auftrag, siehe unten).
- **Keinen** Code ändern.

## Parallel, unabhängig: der fps-Hebel

Falls Zeit bleibt, in einem **getrennten** Lauf (anderes Modul, andere Frage):

```
APS5_TRACE_ALIAS=1 APS5_PROFILE_GPU=1 APS5_PROFILE_DRAW=1 .pp.exe
```

Dafür `libSceAgcDriver.prx` bauen und dreifach deployen:

```
ninja -C "I:\Emulation\PS5 Emu\Software\AnyPS5\build" core/libs/libs/libSceAgcDriver.prx
```

`APS5_TRACE_ALIAS=1` nennt einmal pro Fläche und Grund, **welche von sechs Klauseln**
verhindert, dass der Image-Round-Trip (24 ms pro Present) auf dem Device abgekürzt wird.
Marker: mindestens eine `[alias]`-Zeile.

**Zu berichten:** alle `[alias]`-Zeilen wörtlich, und wie oft jeder Grund vorkommt.

## Ergebnisform

Die zitierten Zeilen und Tabellen, Logs nach `_analytics/menu_blocker/` bzw.
`_analytics/alias_tests/`.
