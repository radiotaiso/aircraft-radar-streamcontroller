# sc-adskey

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

## Install

```
ln -s ~/src/sc-adskey ~/.var/app/com.core447.StreamController/data/plugins/com_idimw_adskey
```

Restart StreamController. Add the actions to your page; the plugin settings
(Settings > Plugins > Aircraft Radar) open the first time. Latitude, longitude,
radius, refresh interval, "hide aircraft on the ground", "show map outline",
"map size", "count position" and "colored aircraft" are set once and apply to
every radar key. With colours on, the six nearest aircraft and the six list rows
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
  nor counted. The default center is `0, 0`; set your own location in the plugin
settings (the window opens the first time you add an action).

Settings live in
`~/.var/app/com.core447.StreamController/data/settings/plugins/com_idimw_adskey/settings.json`
and can be edited by hand.

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

The map outline covers the whole world (`data/map.json`, 4 MB, Natural Earth 1:10m
simplified to 0.02 degrees and stored as flat coordinate arrays). It costs about
4 MB of RAM and 125 ms to load once. To ship a smaller build for one region:

```
python3 scripts/build_map.py --bbox W S E N     # e.g. --bbox -10 35 5 45
```

This downloads about 64 MB of Natural Earth data once and rewrites
`data/map.json`. If the data file is missing the plugin still draws the radar,
just without an outline.

## Publishing to the StreamController store

Verified against StreamController 1.5.0-beta.16 and the store repo as of 2026-11-01.

1. Push this repository to a **public** GitHub repo. The store reads `manifest.json`
   and `attribution.json` from the root at the commit you pin.
2. Fork [StreamController/StreamController-Store](https://github.com/StreamController/StreamController-Store).
3. Add one entry to `Plugins.json` **on the `main` branch** (that is the branch the
   app selects for 1.5.0-beta.16; the mapping lives in `versions.json` on the
   `versions` branch):

```json
{ "url": "https://github.com/idimw/sc-adskey", "hash": "<commit sha of the release>" }
```

4. Open a pull request against `main` and wait for approval (usually a few hours).

To ship an update: push the new commit and update the `hash` with another PR.
Requirements the store checks: `manifest.json` (name, version, app-version,
minimum-app-version, id, github, thumbnail, descriptions, short-descriptions,
tags) and `attribution.json` with a `generic` key. `about.json` is optional.
No `requirements.txt` is needed: the plugin only uses modules the app already
ships (Pillow, requests, loguru, PyGObject).

## Renaming the plugin id

Renaming the package breaks every action already placed on a deck, because pages
store the action ids. Use the migration script (it backs up each file it
rewrites and is safe to run twice):

```
python3 scripts/migrate_plugin_id.py --dry-run
python3 scripts/migrate_plugin_id.py
```

## Development

```
python3 -m unittest discover -s tests -t .                      # unit tests, no network
python3 scripts/render.py --demo --size 144 --scale 5 --gap 6 --out /tmp/radar.png
python3 scripts/render.py --live --size 72 --scale 8 --out /tmp/scope.png
python3 scripts/render.py --live --size 72 --no-map --max-icons 0 --out /tmp/plain.png   # classic look
python3 scripts/render.py --live --size 72 --full --scale 8 --out /tmp/full.png          # square, 100% of the key
python3 scripts/render.py --demo --size 144 --count-corner top-left --out /tmp/corner.png
python3 scripts/render.py --live --list --scale 8 --out /tmp/list.png     # the list action
python3 scripts/render.py --live --list --white --out /tmp/list-white.png
/usr/local/lib/streamcontroller/bin/python scripts/smoke_app.py  # loads the plugin with the real app code
```

`radar/` is pure Python (Pillow + requests) and never imports StreamController.
`scripts/smoke_app.py` runs against an isolated temporary data directory and
does not touch your StreamController settings.

See [PLAN.md](PLAN.md) for the design and the verified StreamController contracts.

GPL-3.0.
