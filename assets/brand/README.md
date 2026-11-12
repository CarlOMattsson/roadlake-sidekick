# Brand assets

The Roadlake Sidekick app icon, "Coastal road" (Swedish: *Kustvägen*): a road that curves around a lake.
All files share the same 108 x 108 design grid and colours (teal `#0f766e`, lake `#5eead4`, road `#f8f5ee`).

| File | Use |
| --- | --- |
| `sidekick-ikon.svg` | Full-bleed app icon. Source for the legacy launcher PNGs and for store listings. |
| `sidekick-forgrund.svg` | Adaptive icon foreground (108 dp canvas, no background). |
| `sidekick-bakgrund.txt` | Adaptive icon background colour. |
| `sidekick-mono.svg` | Monochrome silhouette for Android themed icons. |
| `sidekick-favicon.svg` | Rounded-square crop for favicons and the README header. |
| `sidekick-ordmark.svg` | Icon with the word mark. |

The Android resources are derived from these files: `drawable/ic_launcher_foreground.xml` and
`drawable/ic_launcher_monochrome.xml` are hand-converted VectorDrawables (the dashed centre line is expanded into
real sub-paths because VectorDrawable has no `stroke-dasharray`), and the `mipmap-*/ic_launcher*.png` files are
rendered from `sidekick-ikon.svg` cropped to the central 66 x 66 units.

The exploration script that produced the icon variants lives in the private repository only.
