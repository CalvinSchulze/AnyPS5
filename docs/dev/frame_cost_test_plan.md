# Messplan: woraus der Frame wirklich besteht

Auftrag für Messläufe, **nicht** für Code-Änderungen. Vorgeschichte und Zahlen in
[`immediate_shader_boost.md`](immediate_shader_boost.md); der Carve-out ist gebaut,
gemessen und bleibt an (16 MiB Default). Was hier geprüft wird, ist **nicht** mehr
Speicherzugriff — das ist zweifach ausgeschlossen.

**Referenzlauf ist Lauf B** aus `_analytics/carve_out_tests/run_B_carveout.log`, Build mit
dem `owner()`-Fix (`7baa0ab9` oder neuer), 83 Presents / 10 s, 100 ms pro Frame:

| Posten | pro Present |
|---|---|
| `0x800038be00` | 27,6 ms |
| `0x80003e8700` | 19,8 ms |
| `draw` | 18,4 ms |
| `storage-writeback` | 13,9 ms (375 MiB) |
| `storage-upload` | 10,1 ms (347 MiB) |

Jeder Lauf: **10 s stabil nach dem Einlaufen**, dieselbe Szene, dieselbe Stelle, warmer
Disk-Cache. Zahlen immer aus **demselben** Telemetriefenster lesen, nie aus dem ersten
(da sind 0 Presents). Basis für alle Läufe:

```
APS5_PROFILE_GPU=1 APS5_PROFILE_DRAW=1 .pp.exe
```

Logs nach `_analytics/frame_cost_tests/`.

## Lauf 1 — `APS5_PIPELINE_STATS=1` (zuerst, billigster Erkenntnisgewinn)

Schaltet `VK_KHR_pipeline_executable_properties` ein und schreibt `[pipeline-stats]`-Zeilen
pro Pipeline: Name, Subgroup-Größe und die Statistiken des Treibers (auf NVIDIA
typischerweise Registerzahl, Binärgröße, Instruktionszahl, Spills).

**Warum:** die These „der Rest sind die 27,6 ms des emittierten Codes" stützt sich auf eine
Rechnung, die **volle Occupancy unterstellt**. Die Registerzahl entscheidet darüber. Hohe
Registerzahl oder Spills würden die Rechnung umdrehen: dann ist nicht die Codemenge das
Problem, sondern die Occupancy.

**Zu notieren:** für `0x800038be00`, `0x80003e8700` und als Kontrast einen billigen Pass
(`0x80003f3600`, gleiches Grid, 0,55 ms) **jede** Statistikzeile. Besonders Registerzahl
und ob Spilling gemeldet wird.

**Abbruch:** verlangt die Erweiterung (`APS5_PIPELINE_STATS requires ...`) und bricht sonst
sofort ab — dann melden, nicht umgehen.

## Lauf 2 — `APS5_SINGLE_LANE=all`

Setzt `laneCount` auf 1 und halbiert den emittierten Code (131.449 → 69.258 Words beim
Flaschenhals, Faktor 1,90x).

**Warum:** das ist das erste echte A/B zur Codemenge. Früher war der Lauf wertlos, weil
PCIe dominierte; jetzt nicht mehr.

**Wichtig:** das ist **nur eine Messung, kein Fix**. Die Wave64-Emulation wird dabei
semantisch falsch, Bildfehler sind zu erwarten und **kein** Abbruchgrund. Nur wenn der
Titel abstürzt oder gar nicht mehr rendert, ist der Lauf unbrauchbar — dann melden.

**Zu notieren:** ms pro Dispatch für beide heißen Shader, Presents pro 10 s, und ob
`recompile` in der `[gpu]`-Zeile fällt.

## Lauf 3 — `APS5_SPIRV_OPT=full`

Schaltet die volle SPIRV-Tools-Performance-Pipeline samt exhaustivem Inlining ein. Der
Default lässt das Inlining dem Treiber, weil es **Modulgröße ~10x und Optimierungszeit
~20x** kostet.

**Warum:** wenn besser optimierter Code schneller läuft, ist die Codequalität die Ursache
und nicht nur die Menge.

**Erwartung an die Geduld:** die Startphase wird **sehr** lang (die Basislinie hat schon
`recompile 49,8 s`). Lange einlaufen lassen, bis die Shader-Caches warm sind, und erst dann
das Messfenster nehmen. `APS5_SPIRV_OPT=none` ist die Gegenrichtung, falls Zeit bleibt.

**Zu notieren:** ms pro Dispatch beider Shader, `recompile` aus der `[gpu]`-Zeile, Presents.

## Lauf 4 — `APS5_TRACE_UPLOAD=1` (die unangetastete Hälfte des Frames)

Nennt pro Storage-Image, **warum** es erneut hochgeladen wird.

**Warum:** 31 Uploads und 43 Write-backs pro Present bewegen zusammen **721 MiB** und
kosten 24 ms — ein Viertel des Frames, nie untersucht. Die Frage ist nicht „wie schnell",
sondern „warum so oft".

**Zu notieren:**

- Die häufigsten Gründe aus dem Trace, mit Zählung. Wiederholen sich dieselben Adressen
  Present für Present?
- `[texture-cache]`-Zeile: gecachte Texturen, `found changed`, Evictions, belegte MiB
  gegen `budget`.
- Aus `[dispatch] phase totals` die Posten `resources: B images` und
  `images: ...`-Unterzeilen.
- Ob wenige große oder viele kleine Images den Traffic machen.

## Lauf 5 — `APS5_GPU_NO_WRITEBACK=1` (nur als Obergrenze)

Hält GPU-Ergebnisse aus dem Gastspeicher heraus.

**Warum:** beantwortet „was wäre überhaupt zu holen", bevor jemand am Write-back-Pfad
arbeitet. Wenn `storage-writeback` damit verschwindet und der Frame um ~14 ms fällt, lohnt
die Front; bleibt er stehen, ist der Posten anders verteilt als gedacht.

**Wichtig:** bricht die Korrektheit per Definition. Bildfehler und Hänger sind zu erwarten,
der Lauf zählt nur als Obergrenze. Nicht als Fix vorschlagen.

## Was nicht zu tun ist

- **Nicht** erneut PCIe oder Staging messen. Lauf B und D haben das erledigt: 27,6 ms mit
  vier Elementen device-lokal, 28,0 ms mit allen.
- **Nicht** am Carve-out, am Fenster oder an `owner()` drehen. 16 MiB ist gemessen
  (4 MiB kostet 17 ms).
- **Keinen** Code ändern. Wenn ein Lauf eine Codeänderung nahelegt, gehört das in den
  Bericht, nicht in den Baum.
- **Nicht** aus einem einzelnen Telemetriefenster schließen, und nicht gegen die Sitzung
  vom 12.10. vergleichen — nur gegen Lauf B aus demselben Build.

## Ergebnisform

Eine Tabelle über alle Läufe mit: ms pro Dispatch für `0x800038be00` und `0x80003e8700`,
Presents pro 10 s, `draw`, `storage-upload`, `storage-writeback` pro Present (aus der
`by class`-Zeile), plus für Lauf 1 die Pipeline-Statistiken und für Lauf 4 die Trace-Gründe
mit Zählung. Dazu zwei Sätze Urteil pro Lauf und die Rohlogs unter
`_analytics/frame_cost_tests/`.

**Jede Zahl mit ihrer Quelle** (Logzeile), und wo eine These nicht trägt, das bitte
schreiben — die beiden bisherigen Runden haben ihren Wert daraus gezogen, dass Hypothesen
gefallen sind.

## Werkzeug am Rande

`agc_shader_replay` braucht **beide** Verzeichnisse im `PATH`, sonst startet es wortlos
nicht (`0xC0000135`): `build/core/libs/libs/unpatched` und das MinGW-`bin` der Toolchain.
`--spv` schreibt `shader_<adresse>.req.spv` neben die Eingabe, `tools/spirv_stats.py`
wertet sie aus.
