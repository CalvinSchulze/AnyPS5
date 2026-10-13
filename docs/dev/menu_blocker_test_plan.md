# Messplan: welchen Zähler der Hauptthread pollt

Ziel ist das **3D-Hauptmenü**. Die erste Runde ist durch und hat das Bild vollständig
gedreht. Logs unter `_analytics/menu_blocker/`.

## Was Runde 1 ergeben hat

**Der Hauptthread wartet in keinem Betriebssystem-Primitiv.** Er dreht in einer
rdtsc-getakteten Polling-Schleife (`GhostOfYotei.exe+0xdf3ec2`):

```
140df3ed0: movsxd rcx, [r13+0xcc]   ; Index
140df3ee2: mov    rcx, [rax+rcx*8]  ; Fortschrittszähler lesen
140df3ee6: cmp    rcx, r15          ; gegen Zielwert
140df3ee9: jl     0x140df3e90       ; nicht erreicht -> wieder von vorn
```

Drum herum: **20 JobWorker schlafen** in `sceKernelWaitSema`, 6 Threads in
`scePthreadCondWait`, 3 in `sceKernelWaitEqueue`. **Kein einziger Thread steht in einem
HLE-Modul** — nicht in `libSceSaveData`, `libSceNp*`, `libSceSystemService`, `libSceAjm`,
`libScePlayGo`.

**Savedata ist aus:** im ganzen 240-s-Lauf drei Aufrufe, alle in den ersten zwei Sekunden,
alle mit `SCE_OK`, danach 238 Sekunden gar nichts.

**Die präsentierten Frames sind komplett schwarz** (alle RGB 0, Alpha 255). Der Ladekreisel,
den man sieht, steckt also **nicht** im Framebuffer des Spiels — er kommt von außerhalb.
Damit ist auch klar, was die GPU die ganze Zeit rechnet: die Engine rendert ihre leere Welt,
25 Draws und 12 Compute-Programme über nichts, Ergebnis schwarz.

Das Gesamtbild ist konsistent: die Initialisierung kommt nicht über eine Stufe hinaus, die
Worker haben nichts zu tun, der Render-Thread läuft trotzdem, und der Hauptthread wartet
auf einen Zähler, den niemand hochzählt.

## Was dafür neu im Build ist

`ReportAllThreads` gab bisher nur `rip`, `rsp` und `rbp`. **Die Integer-Register fehlten** —
und genau dort stehen die Adresse des Zählers und der Zielwert. Das ist jetzt drin
(`CrashReport.cpp`, `libc.prx` ist neu gebaut): pro Thread drei Zeilen mit `rax`–`r15`.

## Lauf 1 — Hang-Dump mit Registern

```
APS5_HANG_DUMP_SECS=240 .pp.exe
```

**Zu notieren, nur für den Hauptthread** (der ohne Namen, dessen `rip` in
`GhostOfYotei.exe+0xdf3ec2` oder in der Nähe steht):

- **`rax`** — die Basis des Zähler-Arrays. Das ist die wichtigste Zahl des Laufs.
- **`r15`** — der Zielwert, auf den gewartet wird.
- **`r13`** — der Struct-Zeiger, aus dem der Index kommt.
- Dazu die ganze Registerzeile unverändert zitieren, nicht zusammenfassen.

**Die Adresse selbst beantwortet schon die halbe Frage:**

- Liegt `rax` in **`0x5000000000`–`0x50d5800000`**, ist es die Gast-Arena, also Speicher,
  den die **GPU** schreiben kann — dann ist der Zähler sehr wahrscheinlich ein GPU-Label,
  und die Frage wird, warum unser Label-Pfad ihn nicht hochzählt.
- Liegt `rax` woanders (im Heap des Titels, `0x7ff6...` im Image), ist es CPU-Buchhaltung,
  und ein anderer Gast-Thread müsste ihn schreiben.

Bitte **zweimal** laufen lassen, mit 240 s und mit 600 s, und `r15` sowie `rax` vergleichen:
bleiben sie gleich, hängt es; verändern sie sich, kommt die Initialisierung stufenweise
voran und ist nur unerträglich langsam.

## Lauf 2 — wer schreibt diese Adresse?

Erst wenn `rax` aus Lauf 1 bekannt ist:

```
APS5_WATCH_ADDR=<rax als Hex, ohne 0x> APS5_HANG_DUMP_SECS=240 .pp.exe
```

Der Schalter wartet, bis die Seite committed ist, schützt sie und meldet **jeden
Schreibzugriff** mit `[watch]`-Zeile. Erwartung und Lesart:

- Es gibt Schreiber, aber der Wert erreicht `r15` nie → wir sehen **wer** zählt und können
  fragen, warum zu wenig.
- Es gibt **keinen** Schreiber → der Signalweg fehlt komplett. Dann ist die nächste Frage,
  welches Subsystem ihn bedienen müsste, und die Adresslage aus Lauf 1 sagt es.

**Zu notieren:** die `[watch]`-Zeilen mit Backtrace, gruppiert nach Schreiber, und wie oft
pro Sekunde geschrieben wird.

## Was nicht zu tun ist

- **Nicht** an fps arbeiten. Die Engine rendert eine leere Welt; schneller leer bleibt leer.
- **Nicht** `APS5_GPU_NO_WRITEBACK` benutzen.
- **Keinen** Code ändern.
- Den Abbruch des Hang-Dumps nicht als Fehlschlag melden; er ist das Messinstrument.
- Die Frame-Dumps **nicht** wiederholen — schwarz ist beantwortet.

## Ergebnisform

Die Registerzeile des Hauptthreads wörtlich, `rax`/`r15`/`r13` benannt, der Vergleich der
zwei Timeouts, und aus Lauf 2 die Schreiber. Logs nach `_analytics/menu_blocker/`.
