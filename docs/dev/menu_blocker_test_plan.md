# Messplan: kommt der Titel weiter, wenn die Gast-Uhr langsamer läuft?

## Regel für diesen Auftrag: **nicht interpretieren**

Zahlen mit ihrer Quelle, nichts weiter. Kein Urteil, keine Ursache, keine Hypothese, kein
„damit ist bewiesen / widerlegt / ausgeschlossen", **kein Fazit-Abschnitt**. Wörtlich
zitieren mit Zeilennummer, zählen, tabellieren. Beobachtungen, die nicht zur Frage passen,
**unkommentiert nennen**.

**Eine Ausnahme, ausdrücklich erwünscht:** was auf dem **Bildschirm** zu sehen ist. Also
schlicht: Intro sichtbar? Ladekreisel? Menü? Etwas anderes? Ein Satz pro Lauf, als
Beobachtung, nicht als Deutung.

## Bauen und Deployen: **nein, nicht nötig**

Alle drei Schalter dieses Auftrags sind vorhanden und bereits deployed:
`APS5_TIME_SCALE` (von Anfang an im Baum), `APS5_TRACE_VIDEODEC` und `APS5_TRACE_FILEIO`
(aus den letzten Runden, in `libSceVideodec2.prx` und `libkernel.prx`).

**Marker, dass die Zähler laufen:**

> Je mindestens eine `[videodec2] ... decode calls ...`- und eine `[fileio]`-Zeile. Fehlt
> eine: **abbrechen und melden**, mit Angabe welche.

## Warum dieser Lauf

Der Titel läuft mit **~9 fps**, erwartet aber 30 oder 60. Die Filmwiedergabe **stockt** an
wechselnder Stelle (152 Bilder im einen Lauf, 455 im nächsten) und wird **nie abgebaut**
(0 flushes, 0 deletes). Danach kommen keine Lesevorgänge mehr.

`APS5_TIME_SCALE=<faktor>` verlangsamt die monotonen Gast-Uhren und den TSC
(`libkernel/Time/Time.cpp:57`), damit *„a title running far below its frame rate sees
plausible frame times"*. Bei 9 realen fps entspricht **0,3** etwa einem für den Titel
„normalen" 30-fps-Takt und **0,15** einem 60-fps-Takt. Echte Wartezeiten bleiben real, ein
15-Sekunden-Film dauert bei 0,15 also rund 100 Sekunden Wanduhr.

Was zwei Dinge auf einmal prüft: ob der Film weiterläuft, und ob danach überhaupt noch
etwas passiert.

## Lauf 1 — `APS5_TIME_SCALE=0.3`

```
APS5_TIME_SCALE=0.3 APS5_TRACE_VIDEODEC=1 APS5_TRACE_FILEIO=1 .pp.exe
```

**Fünf Minuten.**

**Zu berichten:**

1. **Alle** `[videodec2] ... decode calls ...`-Zeilen wörtlich mit Zeilennummer.
2. **Alle** `[fileio]`-Zeilen wörtlich mit Zeilennummer.
3. Alle `sceKernelOpen`-Pfade in Reihenfolge.
4. Die **Zahl** der Zeilen `creating a pipeline for` im ganzen Log, und die Zeilennummer der
   letzten davon.
5. Ein Satz: was war auf dem Bildschirm zu sehen?

Die Vergleichswerte aus den Läufen bei normaler Uhr, nur als Zahlen zum Gegenhalten:
455 Bilder, 1064 Leseaufrufe / 8,9 MiB, 29 Pipelines, letzte Pipeline im zweiten von 58
Telemetriefenstern.

## Lauf 2 — `APS5_TIME_SCALE=0.15`

```
APS5_TIME_SCALE=0.15 APS5_TRACE_VIDEODEC=1 APS5_TRACE_FILEIO=1 .pp.exe
```

**Fünf Minuten**, dieselben fünf Punkte berichten.

## Lauf 3 — nur falls Lauf 1 oder 2 weiterkommt

Kommt der Titel in einem der beiden Läufe sichtbar weiter (Menü, neue Pipelines, neue
Lesevorgänge), dann denselben Faktor noch einmal **zehn Minuten** laufen lassen und
berichten, wie weit er kommt. Sonst entfällt dieser Lauf.

## Was nicht zu tun ist

- **Nicht** interpretieren (außer der Bildschirm-Beobachtung).
- **Nicht** erneut Hang-Dumps, Sampler, `WATCH_ADDR`, `DUMP_GUEST`, Frame- oder
  Target-Dumps, `TRACE_SYSTEMEVENT` oder `TRACE_FLIP` fahren — alle sind durch.
- **Nicht** `APS5_GPU_NO_WRITEBACK` benutzen.
- **Keinen** Code ändern.

## Ergebnisform

Die zitierten Zeilen, die Pipeline-Zahl, der Satz zum Bildschirm, Logs nach
`_analytics/menu_blocker/`.
