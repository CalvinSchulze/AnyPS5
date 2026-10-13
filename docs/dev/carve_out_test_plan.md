# Messplan: Carve-out-Staging für adressbasierte Builds

> **Gelaufen am 13.10.** Logs unter `_analytics/carve_out_tests/`, Ergebnis und Urteil im
> Hauptdokument. Kurz: A/B trägt (66,8 → 27,6 ms, 6,4 → 8,3 fps, CPU-Seite ruhig). Lauf C
> brach ab und hat damit einen latenten Fehler in `owner()` gefunden, der behoben ist —
> **Lauf C ist mit dem Fix nachzuholen**, das 4096-KiB-Fenster war nicht die Ursache.

Auftrag für einen Messlauf, nicht für eine Code-Änderung. Was gebaut ist, steht in
[`immediate_shader_boost.md`](immediate_shader_boost.md) unter *Gebaut: der Carve-out*.
Ziel ist **eine Zahl pro Zeile der Tabelle unten** und ein Urteil: trägt der Carve-out,
oder frisst die CPU-Seite den Gewinn wie beim `NO_HOST_IMPORT`-Versuch?

## Was geprüft wird

Die Hypothese: `0x800038be00` kostet 66,4 ms pro Dispatch, weil seine geschriebenen
V#-Buffer in einem Host-Import in place gebunden sind und jeder Zugriff über PCIe geht.
`APS5_NO_HOST_IMPORT=1` hat 2,4x gebracht, war aber als Fix unbrauchbar (ganze Arena
gespiegelt, 44 ms Mirror-Vorbereitung pro Build, 1,2 fps). Der Carve-out soll denselben
Effekt für **nur die vier bis sechs geschriebenen Elemente** holen.

Zwei Ausgänge sind möglich und beide sind ein Ergebnis:

- **Trägt:** GPU-Zeit des Flaschenhalses fällt deutlich, die Kopien kosten wenige ms, die
  CPU-Seite bleibt ruhig, fps steigen.
- **Trägt nicht:** die Kosten wandern in die Kopien oder in den Tabellenbau pro Build.
  Dann ist die Richtung belegt, aber das Fenster oder die Sweep-Schwelle ist falsch.

## Aufbau

Build ist aktuell und grün (`ninja core/libs/libs/libSceAgcDriver.prx`). Gleiche Szene wie
die Basislinie, gleiche Stelle, warmer Disk-Cache, RTX 5080. Jeder Lauf **10 s stabil**
nach dem Einlaufen, damit die `[gputime]`- und `[address]`-Zeilen vergleichbar sind.

```
APS5_PROFILE_GPU=1 APS5_PROFILE_DRAW=1 APS5_TRACE_STAGING=1 .pp.exe
```

Drei Läufe, in dieser Reihenfolge:

| Lauf | Zusatz | Was er zeigt |
|---|---|---|
| **A** | `APS5_NO_ADDRESSABLE_STAGING=1` | Basislinie im *selben* Build — der ehrliche Vergleich |
| **B** | — (Carve-out aktiv) | der Eingriff |
| **C** | `APS5_SWEPT_SHADOW_MAX_KIB=4096` | ob das 16-MiB-Fenster zu groß oder zu klein ist |

A und B müssen aus demselben Binary kommen. Der alte Vergleich gegen die Sitzung vom
12.10. ist als Orientierung brauchbar, aber nicht als Beweis: dort unterschieden sich
Takt- und Cache-Regime.

## Was aus jedem Lauf zu notieren ist

**Greift der Eingriff überhaupt?** Ohne diese Kontrolle ist der Rest wertlos.

- `[staging]`-Zeilen (`APS5_TRACE_STAGING=1`): erscheinen die **großen** Ranges, 16,6 MB
  und 8,2 MB plus die beiden 4,1 MB? In Lauf A dürfen nur die acht kleinen ≤ 640 KiB
  auftauchen, in Lauf B müssen die großen dazukommen. Passiert das nicht, greift der
  Carve-out nicht und die Sweep-Erkennung ist der Verdächtige, nicht die Hypothese.
- `[buffers] staging`: Zahl der gestagten Regionen, KiB rein und KiB zurück pro 10 s.

**Die Zielgröße:**

- `[gputime] by program`: ms pro 10 s für `0x800038be00` und `0x80003e8700`, geteilt durch
  die Dispatch-Zahl → ms pro Dispatch. Basislinie 66,4 und 19,1; der
  `NO_HOST_IMPORT`-Lauf lag bei 27,6 und 3,0.
- Presents pro 10 s (fps) und `GPU busy` gegen `idle gaps`.

**Die Gegenrechnung — hier ist der Eingriff zuletzt gescheitert:**

- `[address] us per build`: `mirror prepare`, `compare`, `snapshots`, und die Zahl der
  adressbasierten Builds pro 10 s. Mit Carve-outs ist `regions` nicht mehr leer, also
  greift `CachedAddressTable` nicht und **jeder** Build baut die Tabelle neu. Wenn hier
  etwas explodiert, ist das der Grund für einen ausbleibenden fps-Gewinn.
- `[bda-table] hits / misses`: sollten von 679/204 in Richtung mehr Misses gehen. Um wie
  viel?
- `[dispatch] phase totals`: `resources` und `record: marks` — die Copy-in- und
  Copy-back-Kommandos landen dort.
- `[buffers] uploads`: GPU-Kopien und ihre Bytes.

**Korrektheit, nicht nur Geschwindigkeit:**

- Läuft die Szene **grafisch unverändert**? Ein Screenshot aus A und B an derselben
  Stelle. Der Copy-back schreibt den ganzen Element-Bereich zurück; falsche
  Sichtbarkeit von Partikeln, Froxeln oder Beleuchtung wäre genau der Fehler, den diese
  Mechanik machen kann.
- Keine BDA-Faults: eine `BDA fault`-Meldung oder ein Abbruch mit
  `FaultReason::Permission` oder `Unmapped` bedeutet, dass die Tabelle nicht stimmt.
- Kein `GPU address ranges overlap` / `are out of order`. Diese Prüfung ist neu
  (`requireTableOrder`). Springt sie an, **sofort melden** mit der ganzen Zeile — dann
  ist entweder der Carve-out falsch subtrahiert oder es gab schon vorher Überlappungen
  in der Tabelle, und Letzteres wäre der größere Fund.
- `[buffers] staging` darf nicht über `regions staged ... without copy-back` wachsen:
  das zählt Regionen, deren Ergebnisse im Schatten liegen geblieben sind.

## Reihenfolge und Abbruchkriterien

1. Lauf A, 10 s, alle Zeilen sichern. Zeigt A schon die großen Ranges unter `[staging]`,
   stimmt etwas mit dem Schalter nicht — stoppen und melden.
2. Lauf B. Erscheinen die großen Ranges nicht, mit `APS5_ALL_BUFFERS_WRITTEN=1`
   gegenprüfen: wenn sie dann auftauchen, liegt es an `bufferWritten`, nicht am
   Carve-out.
3. Nur wenn B grafisch sauber ist und Faults ausbleiben: Lauf C.
4. Bei Abbruch oder Device-Lost: die letzten 200 Zeilen des Logs sichern, Lauf
   wiederholen, und wenn es reproduziert, mit `APS5_NO_ADDRESSABLE_STAGING=1` prüfen, ob
   es ohne Carve-out auch passiert.

## Ergebnisform

Eine Tabelle A/B/C über: ms pro Dispatch für beide Shader, fps, gestagte Regionen, KiB
rein und zurück, `[address] us per build`, `[bda-table]` hits/misses — plus zwei Sätze
Urteil und die Rohlogs unter `_analytics/carve_out_tests/`. Keine Interpretation über das
hinaus, was die Zahlen hergeben; die Hypothese darf scheitern.

## Nicht in diesem Lauf

Die zweite Kostenquelle (der Lookup pro Zugriff, Binärsuche in `get_bda_pointer` und
`note_bda_write` mit Device-Scope-Atomics) wird hier **nicht** angefasst. Sie bleibt auch
nach einem erfolgreichen Carve-out offen, weil die 27,6 ms des `NO_HOST_IMPORT`-Laufs
immer noch 50–250x über den billigen 4K-Pässen lagen. Ihr Messplan steht im
Hauptdokument.
