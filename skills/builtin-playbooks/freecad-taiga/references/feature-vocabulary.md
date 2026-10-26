# Taiga-S1 feature vocabulary

Units: millimetres. `r` is radius (Ø6 → `r: 3`). Origin is the base center; +Z up.

| Kind | Params | Meaning |
|------|--------|---------|
| `base_box` | w, d, h | Rectangular plate / block (first feature) |
| `base_cyl` | r, h | Cylinder pad |
| `base_hex` | r, h | Hexagon pad |
| `base_ring` | ri, ro, h | Revolved ring |
| `boss_cyl` | r, h, x, y | Cylindrical boss on top face |
| `boss_box` | w, d, h, x, y | Box boss on top face |
| `hole` | r, x, y | Through pocket (circle) |
| `hole_std` | r, x, y | PartDesign Hole |
| `pocket_rect` | w, d, depth, x, y | Rectangular pocket |
| `polar_pattern` | n | Polar repeat of previous tip feature |
| `linear_pattern` | n, length | Linear repeat |
| `mirror` | _(none)_ | Mirror previous tip feature |
| `fillet_top` | r | Fillet edges of +Z face |
| `fillet_vertical` | r | Fillet vertical edges (box bases) |
| `chamfer_top` | size | Chamfer +Z edges |
| `shell` | t | Thickness / shell |

Patterns and mirrors must immediately follow the feature they operate on.
Keep goals short (about 1–7 features) for reliable builds.
