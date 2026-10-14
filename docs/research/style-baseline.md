# Style baseline: Tron 2.0's single-player levels as numbers

Ticket #39. Question: what do the single-player levels look like as numbers (room sizes, connectivity,
surface mix, object density, light), for the sibling project mus-y-sinak, whose generator samples them?

Data: `docs/research/style-baseline.json` (schema 1), written by `tools/baseline.py`:

```zsh
.venv/bin/python -I tools/baseline.py extracted docs/research/style-baseline.json   # ~8 min
```

All lengths are metres and areas m², at 0.017 m per LithTech unit (see Units). The `baseline` section
holds p5/p25/p50/p75/p95 over the **interior** levels; `levels` holds every level's raw samples, so a
consumer can sample them directly instead of assuming a distribution.

## Answer (medians over the 18 interior levels)

| Measure | p25 | p50 | p75 |
|---|---|---|---|
| Room area | 35 m² | 73 m² | 135 m² |
| Room width (cross-section) | 6.0 m | 7.6 m | 9.8 m |
| Room footprint, short × long side | 5.7 × 7.1 m | 7.3 × 10.9 m | 10.3 × 16.6 m |
| Room ceiling height | 4.7 m | 7.6 m | 14.2 m |
| Corridor width | 1.9 m | 3.5 m | 4.4 m |
| Corridor length | 3.1 m | 5.9 m | 12.8 m |
| Corridor ceiling height | 4.4 m | 6.5 m | 11.8 m |
| Rooms per level | 9 | 22 | 24 |
| Corridors per level | 15 | 24 | 47 |
| Reachable floor per level | 1,950 m² | 3,290 m² | 5,870 m² |
| Room degree (links to rooms/corridors) | 2 | 2 | 4 |
| Cycles per level (edges − nodes + components) | 1.5 | 4.5 | 7.8 |
| Dead-end share of nodes | 0.20 | 0.26 | 0.44 |

- **Surfaces** near the reachable floor, by area: wall 47%, floor-interior 19%, ceiling 18%, emissive 12%,
  floor-exterior 3%, glass 1%.
- **Light colour**: 80% of lights are grey/white; the rest lean azure (6.5%), yellow (5%), green (3%) and violet
  (2.5%). Tron 2.0's colour comes from its textures, not its lights.
- **Placement** (share of objects standing within ~0.8 m of a room's edge): lights 89% center (they
  hang over the floor), characters 95% center, panels 27% wall + 17% corner, props 31% wall + 16% corner.
- **Density** is sparse: per 100 m² of room, lights p75 1.8 (p95 13), characters p75 0.4, doors and
  panels p95 about 0.5–1. Placed models (`Prop`) are rare: Tron 2.0 builds its detail from world geometry.
- The scale is vertical: half the rooms are over 7.6 m tall, and 5% of them over 46 m (server halls).

## Method

**Reachable floor.** A grid of 16-unit (0.27 m) cells over the physics BSP's up-facing solid polygons
(`|n.y| >= 0.7`, sky polygons left out), flooded from the `GameStartPoint`s, `TeleportPoint`s,
`ExitTrigger`s and every AI volume's floor: steps up to 18 units (the player's), no wall crossing 20–90
units above the floor, at least 60 units of headroom. Floors, ceilings and sky are looked up per column
when the flood first reaches it; walls through a bucketed polygon index with an exact clip-and-overlap
test. Seeding from the AI volumes reaches parts joined only by elevators or teleports.

**Rooms and corridors** (`baseline.segment`). Door cells are cut out. A cell's distance to the edge is
taken in 8-neighbour steps; the edge is where the floor stops, except enclosed gaps of up to 64 cells
(pillars, consoles), which a room flows around. Cells at least 10 cells (2.7 m) from the edge are room
cores; a room is a connected core grown back by 9 cells (a morphological opening), so a room is at least
about 5.2 m wide somewhere. The rest is corridors, except alcoves (under 100 cells, opening into one
room) and scraps under 10 cells between rooms (openings), which join the room they touch most.

**Doors**: `SlidingDoor`/`RotatingDoor`/`Door` world models that are upright thin panels (≥ 96 units
tall, ≤ 64 thick), cutting every cell they overlap within 40 units of their bottom. Doors are often 12
units thick, thinner than a cell. `SlidingDoor` is also used for elevators (flat) and `InfoString`
displays (off the floor); the shape test leaves those out.

**Per room**: area; width, the median over its cells of the shorter of the straight x and z runs through
the cell; footprint extents; median floor-to-ceiling height over cells with a ceiling; sky share.
Corridor length is area / width.

**Graph**: nodes are rooms and corridors; edges join nodes whose cells touch or that touch the same door.

**Surfaces** (`tools/surfaces.py`): every drawn world triangle (render blocks, world models under their
object's `BlendMode`, sky objects left out). Translucent world models are glass, Additive ones emissive;
otherwise floor (interior if the first thing straight above is geometry, not sky) / wall / ceiling by
the normal. Only triangles near the reachable floor are counted (a column within one cell, between the
floor and its ceiling, or 512 units above an open floor).

**Level kinds**: *interior* when at least 70% of the reachable floor has a ceiling; *open* below that or
when the flood passes 400,000 cells (29,600 m²); *minor* under 500 m² (`fin`, `m11-01`). Only interior
levels feed the `baseline` section. Open: m02-01, m02-02, m04-03, m05-01, m05-03, m06-01, m06-03, m07-02,
m07-03, m09-01, m09-03, m10-03.

## Units

0.017 m per unit, as the viewer's `LT.Scale`: the player's dims are 106 units tall (≈ 1.8 m). Doors
agree: the commonest door is 128 units tall (91 of 333 door world models) and 128 wide, ≈ 2.18 m.

## Findings that shaped the method

- **AI volumes are not rooms.** They are thin floor tiles (half-height 8), median 7 m²; **AI regions** are
  AI territories (median 21 volumes, 1–29 per level). Neither marks a room, so rooms are derived from
  the floor. AI volumes still cover 35–85% of an interior level's reachable floor (`aiVolumeShare`); `fin`,
  `m08-01` and `m11-01` have none.
- **Most up-facing area in the physics BSP isn't floor**: sky and the level's hull are 60–90% of it, and
  big decorative floors (pit bottoms) lie under the sky far below. Invisible surfaces can't be dropped:
  many real collision floors are invisible.
- **Render triangles carry no surface flags**: their poly ids don't map onto the physics BSP's polygons
  (the texture matches in 18% of a sample), so glass and emissive come from the world model's `BlendMode`.
- **Fullbright is no sign of a light**: 150 of m01-01's 207 textures are fullbright; their light is baked
  into the vertex colours.
- **A level's graph comes apart** into components (median 14, the largest holding median 48% of the
  nodes, diameter median 10 nodes): elevators, moving platforms and teleports aren't in the physics BSP.
  Exit triggers often hang over a platform's path with no floor below. So there's no start-to-exit depth;
  `largestComponentDiameter` stands in for it.

## Caveats

- Walls on a cell boundary remove the cell on one side, so widths read up to one cell (0.27 m) narrow.
- 8.6% of corridors are narrower than the player (0.82 m): strips along ledges and between obstacles.
  A consumer that wants walkable corridors should filter `width >= 0.82`.
- Room width is exact for axis-aligned rooms and overstates diagonal ones (up to √2).
- The segmentation is a model of "room", tuned on m01-01 and m04-01 by eye: `CORE` (10 cells) decides
  where a room ends and a corridor begins. The parameters are in the JSON's `method` section.
- Objects are counted per room only; doors and panels standing in corridors aren't in the room density.
