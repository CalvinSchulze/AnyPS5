# Immediate Shader Boost

> Dieses Dokument führt **nur die Spitze der laufenden Operation**. Erledigtes und
> überholte Annahmen werden ersetzt, nicht angehängt. Es ist kein Verlauf.

## Aktueller Stand

Messgrundlage: `APS5_PROFILE_DRAW`-Sitzung, 38.441 Frames, ~94 min, **~6,8 fps**
(68 Presents / 10 s, 148 ms pro Frame).

Die GPU ist der Engpass, nicht CPU und nicht IO: `batch 8996 ms first to last command`
pro 10-s-Fenster → **~90 % Wall-Clock-Belegung**. Datei-IO spielt keine Rolle
(keine IO-Telemetrie in der Sitzung).

GPU-Zeit ist extrem schief verteilt (6201 ms pro 10 s):

| Programm | pro 10 s | Anteil | pro Frame |
|---|---|---|---|
| `0x800038be00` | 4411 ms | **71 %** | 65 ms |
| `0x80003e8700` | 1265 ms | 20 % | 19 ms |
| 10 weitere zusammen | 474 ms | 8 % | — |

## Aktives Ziel

**`0x800038be00` entlasten.** 65 ms pro Frame in einem einmal pro Frame
aufgerufenen Programm. Zwei Programme machen 92 % der GPU-Last — alles andere ist
dagegen Rauschen, und CPU-/IO-Arbeit kann die fps nicht heben, solange diese Wand steht.

### Nächste Schritte

1. Programm identifizieren: Disassembly und Dispatch-Geometrie von `0x800038be00`
   aus der Capture ziehen, Shader-Stage und Workgroup-Größe bestimmen.
2. Prüfen, ob die 65 ms real Rechenzeit sind oder Stalls: `[gputime]`-Klassen und
   `[landwait]` gegen das Programm korrelieren.
3. Erst danach über Recompiler-Optimierung oder HLE entscheiden.

## Nachgelagert (nicht starten, bevor das aktive Ziel steht)

**Resource-Cache-Anomalie.** Drei Zahlen passen nicht zusammen:

- Kapazität **1024** (`APS5_RESOURCE_CACHE_ENTRIES`, `ShaderResources.cpp:2422`),
  belegt aber nur **163** Einträge — der Cache läuft nicht über.
- Nur **10** Invalidierungen.
- Trotzdem **631.372 Misses mit unverändertem Key** von 960.898 Misses gesamt
  (gegen 2.075.345 Hits).

Verdacht: Einträge werden nicht eingefügt oder direkt wieder entfernt. Unverifiziert —
nicht cachebare Objekte sind eine legitime Erklärung. Treibt die ~960.000 vollen
Resource-Builds und damit den Großteil von `B images` (581 s) und
`[guestmem] collect` (466 s / 13,8 M Calls). Billigste potenzielle Einsparung im Log.

Zweiter Miss-Grund: **222.871 Misses aus V#-Wort 0** — Basisadresse von
Ring-Allocations churnt den Content-Key, obwohl die Ressource äquivalent ist.
Fix-Richtung: auf Offset-im-Ring statt Absolutadresse keyed.

**`B images` aus dem GPU-Mutex holen** — 581 s serialisiert unter dem globalen
Mutex. Erst relevant, wenn die GPU entlastet ist.

## Referenz: Kostenverteilung CPU-Seite

Thread-Summen über 3.037.000 Dispatches, nicht Wall-Clock. `stage A`/`stage B` in den
`[resources]`-Zeilen sind **Summen** der Unterphasen (`precollect` in A, `images` in B) —
nicht addieren.

| Posten | Zeit |
|---|---|
| `resources: B images` (unter GPU-Mutex) | 581 s |
| `[guestmem] collect` | 466 s |
| `resources A (unlocked)` | 208 s |
| `proof` | 109 s |
| `[guestmem] compare` | 78 s |
| `record` (davon `marks` 35 s) | 59 s |

`[storage]`: ~55 GB Uploads + Write-backs pro 10 s (≈5,5 GB/s PCIe-Churn).
