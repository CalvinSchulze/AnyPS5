# Messplan: welcher Fence-Slot stillsteht

## Regel für diesen Auftrag: **nicht interpretieren**

Berichte **Zahlen mit ihrer Quelle**, nichts weiter. Kein Urteil, keine Ursache, keine
Hypothese, kein „damit ist bewiesen / widerlegt / ausgeschlossen". Die Deutung passiert
hier, nicht im Lauf — in den letzten Runden war jede mitgelieferte Interpretation falsch,
und das kostet mehr Zeit als es spart.

Konkret heißt das:

- **Zitiere** die Zeilen, die gefragt sind, wörtlich, mit Datei und Zeilennummer.
- **Zähle** und **tabelliere**, wenn eine Verteilung gefragt ist.
- Wenn eine Beobachtung nicht zur Frage passt, **nenne sie unkommentiert** und sortiere sie
  nicht ein.
- Wenn ein Lauf nicht durchführbar ist oder ein Schalter fehlt: sagen, nicht ersetzen.
- Ein Satz „fertig, hier sind die Zahlen" am Ende reicht. **Kein Fazit-Abschnitt.**

## Bauen und Deployen: ja, nötig

Dieser Auftrag braucht einen **neuen Build**, weil der Schalter aus Lauf 1 neu ist.

**Was zu bauen ist:** `libc.prx` — der Dump sitzt in
`core/libs/prx/libc/src/specifics/windows/CrashReport.cpp`.

```
ninja core/libs/libs/libc.prx
```

Mit dem Toolchain-`bin` dieses Rechners im `PATH` (Ninja und g++ liegen im Scratchpad einer
früheren Sitzung, `cmake` ist **nicht** im `PATH`):

```
C:\Users\CptWhuti\AppData\Local\Temp\claude\I--Emulation-PS5-Emu-Software-AnyPS5\685ea80c-0bfb-4ab4-b237-3f3880416715\scratchpad\mingw64\bin
```

Ergebnis liegt als `build/core/libs/libs/libc.prx` (NID-gepatcht) und
`build/core/libs/libs/unpatched/libc.prx`.

**Deployen:** so, wie dieser Rechner den Titel mit unseren PRX-Modulen versorgt — diesen
Schritt bitte **im Bericht benennen**, damit er nachvollziehbar bleibt.

**Und dann prüfen, dass es greift.** Ohne diese Kontrolle ist der Lauf wertlos, weil ein
alter Binary stillschweigend dieselben Logzeilen liefert wie vorher:

> Im Log muss mindestens **eine** `[guestdump]`-Zeile stehen. Fehlt sie, hat Build oder
> Deploy nicht gegriffen — **abbrechen und melden**, nicht weiterlaufen lassen.

## Stand, soweit gemessen

Aus den Läufen in `_analytics/menu_blocker/`:

- `r15` = 1896 bei 240 s, 5140 bei 600 s → +9,01/s, die Bildrate. Kein Deadlock.
- Der Hauptthread verbringt **97,4 %** seiner Zeit in **fünf** rdtsc-Spin-Schleifen, die
  alle auf dasselbe Fence-Array über `[0x14465afe8]` → `0x2000000000` warten. Verteilung:
  `0xdf3ec2` 70,5 %, `0x125bc42` 17,1 %, `0xdf4a40` 4,4 %, `0xeb74e0` 2,8 %,
  `0xdf4060` 2,6 %.
- Stationär: über 15 Blöcke à 20 s ändert sich nichts.
- Über 600 s entstehen 29 Pipelines, die letzte im zweiten von 58 Telemetriefenstern.
- Das Fence-Array indexiert mit `shl $5`, also **32 Byte pro Slot**.

**Was damit offen ist:** der Sampler zeigt, *wo* der Code wartet, nicht *worauf*. Fünf
Schleifen auf demselben Array heißt möglicherweise fünf **verschiedene Slots** — und wenn
einer davon nie hochzählt, wartet das Spiel auf eine Vollzugsmeldung, die nie kommt.

**Ausdrücklich noch nicht gezeigt:** dass der Titel keine HLE-Funktion pollt. Ein Aufruf,
der pro Frame einmal kommt und unter einer Mikrosekunde dauert, erzeugt bei 2-ms-Sampling
über 2.900 Frames null bis ein Sample. Das Fehlen von PRX-Samples ist deshalb **kein**
Beweis; diese Frage bleibt offen und wird hier nicht behandelt.

## Was neu im Build ist

`APS5_DUMP_GUEST=<hex>[:<count>[:<stride>]]` druckt alle zwei Sekunden `count` 64-Bit-Werte
ab der Gast-Adresse, `stride` Byte auseinander, und markiert mit `*`, welche sich seit dem
letzten Druck geändert haben. Rein lesend. `libc.prx` ist neu gebaut.

Das war nötig, weil `APS5_WATCH_ADDR` für GPU-DMA blind ist (`VirtualProtect` sieht die
Schreibzugriffe nicht) und der Sampler die Slots nicht unterscheidet.

## Lauf 1 — die Fence-Slots über die Zeit

```
APS5_DUMP_GUEST=2000000000:16:32 .pp.exe
```

Mindestens **drei Minuten** laufen lassen, dann beenden.

**Zu berichten:**

1. Die **erste** `[guestdump]`-Zeile wörtlich.
2. Die **letzte** `[guestdump]`-Zeile wörtlich.
3. Drei Zeilen aus der Mitte, wörtlich, mit Abstand von etwa einer Minute.
4. Eine Tabelle: **pro Slot 0–15** der erste Wert, der letzte Wert, und wie oft er in allen
   Zeilen mit `*` markiert war.

Nichts weiter. Keine Zuordnung, welcher Slot „der richtige" ist.

## Lauf 2 — dieselbe Stelle mit weiterem Stride

```
APS5_DUMP_GUEST=2000000000:24:8 .pp.exe
```

Zwei Minuten. Begründung: falls die Slots doch 8 Byte auseinander liegen und die 32 aus der
Disassembly eine andere Bedeutung haben, zeigt dieser Lauf die Werte dicht an dicht.

**Zu berichten:** erste und letzte Zeile wörtlich, dazu dieselbe Tabelle wie oben.

## Was nicht zu tun ist

- **Nicht** interpretieren (siehe oben).
- **Nicht** erneut Hang-Dumps, Frame-Dumps, `WATCH_ADDR` oder den Sampler fahren — alle vier
  sind durch.
- **Nicht** an fps arbeiten.
- **Keinen** Code ändern.

## Ergebnisform

Die zitierten Zeilen und die zwei Tabellen, Logs nach `_analytics/menu_blocker/`.
