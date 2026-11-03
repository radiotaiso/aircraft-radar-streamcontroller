# Aircraft Radar

Live aircraft radar for [StreamController](https://github.com/StreamController/StreamController)
(Stream Deck). Three actions:

- **Radar (1 key)** — a 72x72 scope on a single key.
- **Radar (2x2 tile)** — four keys forming one 144x144 radar. Place four
  tiles as an aligned 2x2 block; the shape is detected automatically. Any other
  shape shows `!`.
- **Radar list (1 key)** — the nearest aircraft as rows: colour swatch, callsign
  and distance. Up to six rows; the swatch colour matches the same aircraft on
  the radar keys, so a row and a dot can be paired.

Tap any radar key to cycle the radius (25 / 50 / 100 / 150 / 200 km).
Data comes from [api.adsb.lol](https://api.adsb.lol) through one shared poller.
Planes are drawn as small aircraft icons pointing along their track (the
nearest few; the rest are squares) over a dim map outline of coastlines, lakes,
state borders and urban areas from [Natural Earth](https://www.naturalearthdata.com)
(public domain, bundled, no API key, no network needed for the map). The outline
covers the whole world, so the plugin works wherever the user is.

## Installing

Install it from the StreamController store: open **Plugins → Store**, search for
"Aircraft Radar" and install it. Then drop any of the three actions on your deck.

The first time you add a radar action, the plugin settings window opens.
Latitude, longitude, radius, refresh interval, "hide aircraft on the ground",
"show map outline", "map size", "count position" and "colored aircraft" are set
once and apply to every radar key. The default center is `0, 0`, so set your
location there. With colours on, the six nearest aircraft and the six list rows
share a palette (red, orange, yellow, green, blue, violet); turning it off draws
everything in white.

**Count position** picks which of the four outer corners shows how many aircraft
are visible: bottom right (default), bottom left, top right or top left. On a 2x2
block the number sits on an outer corner of the whole block; the inner cross is
never used.

**Map size** has two values:

- **Radar (circle)** — the round scope. The radius is the distance to the ring.
- **Full size (square)** — the map and the aircraft fill the whole key, corners
  included. The radius is the distance to the straight edge, so the corners reach
  `radius * sqrt(2)`; the plugin fetches that larger circle from the API (still
  under the 250 nm cap) and any aircraft outside the visible square are not drawn
  nor counted.

Settings live in
`~/.var/app/com.core447.StreamController/data/settings/plugins/com_idimw_adskey/settings.json`
and can be edited by hand.

To run a local checkout instead of the store version, see
[DEVELOPMENT.md](DEVELOPMENT.md).

## Key states

| Look | Meaning |
|---|---|
| solid ring, blips, count | live data |
| dotted ring, `0` | fresh data, nothing in range |
| dotted ring, `--` | no data yet |
| dotted ring + dotted border | data older than 3 refresh intervals |
| `!` | the keys do not form a valid 1x1 / 2x2 block |

The list key shows `--` before the first fetch, `0` when nothing is in range and a
dotted border when the data is stale. If a callsign is too long for its row, the
distance is dropped first; the callsign itself is only truncated as a last resort.

## Map outline

The outline is bundled with the plugin (`data/map.json`): Natural Earth 1:10m
coastlines, lakes, state/province borders and urban areas, simplified to 0.02
degrees. It needs no network and no API key, weighs about 4 MB, uses about 4 MB
of RAM and takes ~125 ms to load once at startup. If the file is missing the
radar still works, just without an outline.

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for local setup, the tests, the render CLI,
regenerating the map data and releasing a new version.

GPL-3.0.
