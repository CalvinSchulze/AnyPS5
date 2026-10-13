# Messplan: was der Hauptthread tut, wenn er nicht auf den Frame wartet

Ziel ist das **3D-Hauptmenü**. Zwei Runden sind durch, Logs unter `_analytics/menu_blocker/`.
Die zweite hat die Diagnose der ersten umgestoßen — bitte den Verlauf unten lesen, damit
nichts doppelt untersucht wird.

## Was wir jetzt wissen

**Es ist kein Deadlock.** Die Registerzeilen zeigen es eindeutig:

| | 240 s | 600 s |
|---|---|---|
| `r15` (Zielwert) | `0x768` = 1896 | `0x1414` = 5140 |

**+3244 in 360 s = 9,01 pro Sekunde** — exakt die Bildrate. `r15` ist der Frame-Zähler, und
die rdtsc-Schleife bei `GhostOfYotei.exe+0xdf3ec2` ist **normales Frame-Pacing**: der
Hauptthread wartet auf die Fertigstellung des aktuellen GPU-Frames. Dass jeder Hang-Dump
ihn dort antrifft, liegt daran, dass ein leerer Frame 110–130 ms braucht und er deshalb
über 90 % der Zeit dort steht. Die frühere Lesart „wartet auf ein Signal, das nie kommt"
ist mit dieser Begründung **widerlegt**.

**Aber er kommt auch nicht voran.** Über den 600-s-Lauf:

- **29 Pipelines insgesamt**, 28 distinkte Programme — und die **letzte neue entsteht im
  zweiten** von **58** Telemetriefenstern. Danach **560 Sekunden ohne einen einzigen neuen
  Shader**.
- **7 `sceKernelOpen`** in 10 s, es wird nichts gestreamt.
- Drei Savedata-Aufrufe in den ersten zwei Sekunden, alle `SCE_OK`, danach nichts.
- 20 JobWorker schlafen durchgehend, kein Thread in einem HLE-Modul.

Der Titel ist also in einem **stabilen Leerlauf**: er rendert Frame für Frame dieselben
zwölf Programme über eine leere Welt, ohne je eine weitere Stufe zu betreten. Weder Hänger
noch Fortschritt.

**Und ein Werkzeughinweis:** `APS5_WATCH_ADDR` kam mit **0 Treffern** zurück. Das beweist
nichts — der Schalter arbeitet mit `VirtualProtect`, und GPU-DMA-Schreibzugriffe umgehen die
CPU-Seitentabellen. Für GPU-geschriebene Zähler ist er blind. (Nebenbei: `0x2000000000` ist
eine Gast-Range, aber **nicht** die 3416-MiB-Arena bei `0x5000000000`, die wir im
Host-Import-Trace gesehen haben. Für das Ergebnis unerheblich, aber nicht verwechseln.)

## Lauf 1 — der Thread-Sampler (das Kernstück)

```
APS5_SAMPLE_THREADS=I:\Emulation\PS5 Emu\Software\AnyPS5\_analytics\menu_blocker\sampler.txt .pp.exe
```

Der Schalter sampelt **jeden Thread alle 2 ms** und schreibt alle 20 s die heißesten Frames
jedes beschäftigten Threads als `module+offset self inclusive` in die Datei. Mindestens
**fünf Minuten** laufen lassen.

**Die Frage, die er beantwortet:** der Hauptthread steht 90 % im Frame-Pacing — was tut er
in den anderen 10 %? Dort liegt die Zustandsmaschine, die nicht weiterschaltet.

**Zu notieren:**

- Für den Hauptthread die heißesten Frames **ohne** die Pacing-Schleife (`+0xdf3ec2` und
  ihre Aufrufer `+0xc4edfd`, `+0xf4f351`, `+0xf4e263`). Was bleibt übrig, nach
  Selbstzeit sortiert?
- **Ruft er in ein PRX-Modul von uns?** Jeder Treffer in `libkernel.prx`,
  `libSceSystemService`, `libSceUserService`, `libSceNp*`, `libSceVideoOut`, `libSceAjm`,
  `libSceAvPlayer` ist der heiße Kandidat — mit `module+offset`, damit wir die Funktion
  zuordnen können.
- Ändert sich das Profil über die 20-s-Blöcke, oder ist es von Block zu Block identisch?
  Identisch heißt: echte Endlosschleife ohne Zustandswechsel.
- Dasselbe für die drei Equeue-Threads (`Uds`, `Trophy`, `ProxySetSync`): wachen sie je auf?

## Lauf 2 — nur falls Lauf 1 auf ein Modul zeigt

Dann gezielt dessen Trace einschalten (die geprüften Namen: `APS5_TRACE_EXIT`,
`APS5_TRACE_AJM`, `APS5_TRACE_VIDEODEC`, `APS5_SAVEDATA_TRACE`) und protokollieren, welcher
Aufruf wiederholt mit welchem Rückgabewert kommt. Ein Titel, der vor dem Menü steht, wartet
typischerweise auf ein **Systemevent** oder einen **User-Service-Zustand** — wenn wir dort
dauerhaft „kein Event" melden, schaltet seine Zustandsmaschine nie weiter.

## Was nicht zu tun ist

- **Nicht** erneut Hang-Dumps fahren. Die Frage „hängt oder kriecht" ist beantwortet: es
  kriecht, und das Pacing ist normal.
- **Nicht** `APS5_WATCH_ADDR` auf GPU-geschriebene Adressen ansetzen; er ist dafür blind.
- **Nicht** die Frame-Dumps wiederholen — schwarz ist beantwortet.
- **Nicht** an fps arbeiten. Die Fronten sind dokumentiert; solange der Titel die Stufe
  nicht verlässt, bringt Tempo kein Menü.
- **Keinen** Code ändern.

## Ergebnisform

Das Profil des Hauptthreads ohne die Pacing-Frames, nach Selbstzeit sortiert, mit
`module+offset`; dazu ob und wo es in unsere Module geht, und ob sich die 20-s-Blöcke
unterscheiden. Logs und die Sampler-Datei nach `_analytics/menu_blocker/`.
