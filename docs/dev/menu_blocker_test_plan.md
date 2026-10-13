# Messplan: worauf der Titel im Ladekreisel wartet

Ziel ist das **3D-Hauptmenü**. Beobachtung, die alles umstellt: über eine Stunde bei ~7 fps
lief **95 % der Sitzung der Ladekreisel**, eine Szene war nie zu sehen. Das ist kein
fps-Problem. Der Titel **wartet**, und dieser Plan findet heraus, auf was.

## Was die vorhandenen Logs schon ausschließen

Aus `_analytics/frame_cost_tests/lauf_1_pipeline_stats.log`:

- **Datei-IO ist es nicht.** In einem 10-s-Fenster gibt es **7** `sceKernelOpen`-Aufrufe,
  und zwar `/app0/cache_ps5/loc/noloc.larc` (4x), `save_icon.png`, `t26344.dat`,
  `playgo.pgm`. Ein Titel, der sein Menü lädt, würde hunderte Archive anfassen. Es wird
  **nichts gestreamt**.
- **PlayGo ist es nicht.** `[libScePlayGo] Loaded 36 chunks from
  /app0/sce_sys/playgo-chunk.dat`, und die Implementierung meldet alles als installiert.
- **Die GPU ist es nicht.** Sie rechnet einen vollen 3D-Frame: 25 Draws, 12
  Compute-Programme, 19 Images pro Dispatch, 4K-Targets mit DCC, Froxel-Culling,
  `fill-clear` über 140 MiB pro Present. 8,3 fps sind langsam, aber es läuft.
- **Es scheitert nichts sichtbar.** Kein `not implemented`, kein `stub`, keine abgelehnten
  Draws in irgendeinem Log.

Bleibt: ein Thread wartet auf etwas, das nie kommt.

## Lauf 1 — der Hang-Dump (das Kernstück)

```
APS5_HANG_DUMP_SECS=240 .pp.exe
```

Der Schalter startet einen Watchdog, der nach n Sekunden **absichtlich abbricht** und dabei
`ReportAllThreads()` ausführt: Backtraces **jedes** Threads. Der Abbruch ist der Zweck des
Laufs, **kein** Fehler — bitte nicht als Absturz melden.

240 s heißt: der Kreisel soll schon eine Weile laufen, wenn es abbricht. Lieber einmal mit
240 s und einmal mit 600 s, um zu sehen, ob sich die Wartepositionen **verändern** (dann
läuft etwas, nur unendlich langsam) oder **gleich bleiben** (dann hängt es wirklich).

**Zu notieren — das ist das Ergebnis des Laufs:**

- Für jeden Thread die obersten Frames, zusammengefasst nach **gleicher Warteposition**:
  „N Threads in X". Nicht jeden Stack einzeln zitieren.
- Besonders auf Warteprimitive achten: `sceKernelWaitEqueue`, `pthread_cond_wait`,
  Semaphore, `sceKernelWaitEventFlag`, `sync_on_address`, Mutexe.
- Welcher Thread sieht nach dem **Hauptthread** des Spiels aus, und wo steht er?
- Steht ein Thread in einem unserer HLE-Module (`libSceSaveData`, `libSceNp*`,
  `libSceSystemService`, `libSceVideoOut`, `libSceAjm`, `libScePlayGo`)? Dann ist das der
  Kandidat, und der Name der Funktion ist die Antwort.
- Dreht ein Thread in einer **Schleife** statt zu warten (hoher CPU-Verbrauch, wechselnde
  Frames über zwei Dumps)? Dann pollt er auf eine Bedingung, die wir falsch melden.

## Lauf 2 — Savedata, falls Lauf 1 dorthin zeigt (oder als Parallelprobe)

```
APS5_SAVEDATA_TRACE=1 APS5_HANG_DUMP_SECS=240 .pp.exe
```

`APS5_SAVEDATA_TRACE=1` hebt das Limit der Savedata-Protokollierung auf (ohne ihn werden
nur die ersten 3 Aufrufe je Stelle gezeigt). Der Verdacht kommt aus Lauf 1 der letzten
Runde: der Titel öffnet `ui/vshell/content_ps5/save_icon.png` und arbeitet in
`cache_ps5` — das riecht nach einem Savedata- oder Profil-Flow, und ein Titel, der seine
Speicherdaten nicht mounten oder aufzählen kann, dreht sich gern endlos.

**Zu notieren:** jeder Savedata-Aufruf mit Rückgabewert. Wiederholt sich einer endlos?
Gibt einer einen Fehler zurück, den der Titel offenbar nicht erwartet?

## Lauf 3 — optional, nur zur Einordnung

```
APS5_DUMP_FRAMES=12 APS5_DUMP_FRAMES_EVERY=60 APS5_DUMP_SCALE=4 APS5_DUMP_TARGETS=6 .pp.exe
```

Beantwortet, **ob hinter dem Kreisel schon eine 3D-Szene gerendert wird** (`APS5_DUMP_FRAMES`
speichert die präsentierten Frames als BMP, `APS5_DUMP_TARGETS` die ersten Renders jedes
Color-Targets als Rohdatei). Interessant für das Verständnis, aber **nicht** blockierend:
selbst wenn die Szene da ist, kommt das Menü erst, wenn der wartende Thread weiterläuft.
Deshalb zuletzt.

## Was nicht zu tun ist

- **Nicht** an fps arbeiten. Die Fronten sind dokumentiert und warten; sie bringen das
  Menü nicht.
- **Nicht** `APS5_GPU_NO_WRITEBACK` benutzen, um schneller durchzukommen — der Zustand ist
  kaputt und ein damit erreichtes Menü beweist nichts.
- **Keinen** Code ändern.
- Den Abbruch aus Lauf 1 nicht als Fehlschlag melden; er ist das Messinstrument.

## Ergebnisform

Aus Lauf 1 die Warteposition**gruppen** mit Thread-Zahl, aus Lauf 2 die Savedata-Aufrufe
mit Rückgabewerten, Logs nach `_analytics/menu_blocker/`. Ein Satz Urteil: wartet der
Titel, pollt er, oder kommt er langsam voran?
