# Messplan: was wird gerendert, und was landet auf dem Schirm

Ziel ist nicht mehr fps, sondern das **3D-Hauptmenü**. Zwei Läufe, beide klein, und sie
beantworten die Vorfrage, ohne die alles andere Raten bleibt: rendert der Titel die Szene
schon und wir sehen sie nur nicht, oder rendert er sie wirklich nicht?

## Warum diese Frage zuerst

Die Telemetrie der letzten Läufe passt **nicht** zu Videowiedergabe. Pro Present, aus
`_analytics/frame_cost_tests/lauf_1_pipeline_stats.log`:

- **25 Draws** und **12 Compute-Programme**, darunter ein Froxel-Culling-artiger
  Voll-4K-Pass über 8,29 Mio. Invocations,
- **19 Images** pro Dispatch, **4K-Color-Targets mit DCC**, 4K-Texturen im
  `sampled-lookup`,
- `fill-clear` löscht **140 MiB pro Present**, `storage-upload`/`-writeback` bewegen
  721 MiB.

Ein Videodecoder braucht davon nichts. Entweder läuft der 3D-Renderer also schon und sein
Ergebnis erreicht den Bildschirm nicht, oder was wir für „nur Videos" halten, ist eine
Szene, die bei **8,3 fps** nur sehr langsam vorankommt.

## Lauf 1 — was präsentiert wird gegen das, was gerendert wird

```
APS5_DUMP_FRAMES=20 APS5_DUMP_FRAMES_EVERY=30 APS5_DUMP_SCALE=4 APS5_DUMP_TARGETS=8 APS5_PROFILE_GPU=1 .pp.exe
```

- `APS5_DUMP_FRAMES=<n>` speichert die ersten n **präsentierten** Frames als
  `frame_<index>.bmp`; `..._EVERY` nimmt nur jeden n-ten, `APS5_DUMP_SCALE` hält sie klein.
- `APS5_DUMP_TARGETS=<n>` speichert die ersten n Renders **jedes Color-Targets** als
  Rohdatei (u32 Breite, u32 Höhe, u32 VkFormat, dann dicht gepackte Zeilen).

**Zu notieren:**

- Zeigen die `frame_*.bmp` Video, Menü, Schwarz oder Standbild?
- Zeigen die Target-Dumps **andere** Inhalte als die präsentierten Frames? Das ist die
  Kernfrage. Wenn ja: die 3D-Szene entsteht und wird nicht präsentiert — ein Problem der
  Präsentation, nicht des Renderers.
- Wie viele **verschiedene** Color-Targets gibt es, mit welchen Auflösungen und Formaten?
- Laufen die Dumps lange genug: bitte den Titel **mehrere Minuten** laufen lassen, bevor
  geurteilt wird. Bei 8,3 fps dauert jeder Ladeschritt ein Vielfaches des Normalen, und
  „das Menü kommt nicht" kann schlicht „noch nicht" heißen.

## Lauf 2 — nur wenn Lauf 1 zeigt, dass nichts Neues gerendert wird

Dann steckt der Titel fest, und zwar nicht in der Grafik. Ein Lauf ohne Grafikschalter,
dafür mit den System-Traces, und **drei bis fünf Minuten** laufen lassen:

```
APS5_TRACE_EXIT=1 APS5_TRACE_AJM=1 APS5_TRACE_VIDEODEC=1 .pp.exe
```

(Alle drei sind im Quellcode geprüft. Ein AvPlayer-Trace existiert **nicht** — nicht
erfinden; wenn der Verdacht dorthin zeigt, sagen und wir bauen einen.)

**Zu notieren:**

- Wiederholt sich am Ende dieselbe Zeilenfolge endlos? Dann hängt eine Zustandsmaschine,
  und die letzte *neue* Zeile davor ist der Ansatzpunkt.
- Kommen Meldungen über nicht implementierte oder abgelehnte Aufrufe? In den bisherigen
  Logs steht davon **nichts** — kein `not implemented`, kein `stub`, keine abgelehnten
  Draws. Das ist selbst ein Befund: es scheitert nichts sichtbar.
- Dreht die Videowiedergabe in einer Schleife (dasselbe Video mehrfach), oder endet sie?

## Was nicht zu tun ist

- **Nicht** an fps optimieren. Die Fronten (Storage-Round-Trip, Shader-Reste) sind
  dokumentiert und warten; sie helfen dem Menü nicht, wenn der Titel woanders feststeckt.
- **Nicht** `APS5_GPU_NO_WRITEBACK` benutzen, um schneller durchzukommen — der Zustand ist
  kaputt, und ein damit erreichtes Menü beweist nichts.
- **Keinen** Code ändern.
- Die Dumps liegen im Arbeitsverzeichnis des Titels; bitte nach
  `_analytics/menu_blocker/` verschieben, Logs ebenfalls.

## Ergebnisform

Die Frame-Dumps und ein Satz pro Frage oben. Wenn die Target-Dumps etwas anderes zeigen
als die präsentierten Frames, bitte **beide** Bilder beilegen — das entscheidet die
Richtung der nächsten Arbeit vollständig.
