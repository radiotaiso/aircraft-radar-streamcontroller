# Development

Everything here is for running or hacking on the plugin from a checkout. For
users the supported path is the StreamController store.

## Local setup

```
git clone git@github.com:radiotaiso/aircraft-radar-streamcontroller.git ~/src/aircraft-radar
ln -s ~/src/aircraft-radar ~/.var/app/com.core447.StreamController/data/plugins/com_idimw_adskey
```

Then restart StreamController and add the actions to a page.

Two details that bite:

- The symlink **must be named after the plugin id** (`com_idimw_adskey`): the app
  derives the settings directory from the folder name.
- Plugins are imported once at startup. After editing a `.py` file you have to
  restart the app; there is no hot reload.

## Tests

```
python3 -m unittest discover -s tests -t .
```

220 tests, no network. They cover the API parsing and config sanitising, every
renderer (radar, full size, mosaic, list, colours, count corner, states), block
detection, the service (interval, backoff, stale, reconfigure, ground filter),
the map data format and the build script.

`radar/` only depends on Pillow, requests and the standard library, so the tests
run outside StreamController.

### Smoke test against the real app

```
/usr/local/lib/streamcontroller/bin/python scripts/smoke_app.py
```

It loads the plugin through StreamController's own `PluginManager`, in an
isolated temporary `--data` directory that symlinks back to this repo. It checks
registration, the three actions, that every key paints, block detection and
repair, the settings rows writing to the JSON, and the page id migration. It
never touches the real settings.

## Render CLI

Renders frames to PNG without StreamController, for eyeballing changes:

```
python3 scripts/render.py --demo --size 144 --scale 5 --gap 6 --out /tmp/radar.png
python3 scripts/render.py --live --size 72 --scale 8 --out /tmp/scope.png
python3 scripts/render.py --live --size 72 --full --scale 8 --out /tmp/full.png
python3 scripts/render.py --live --size 72 --no-map --max-icons 0 --out /tmp/plain.png
python3 scripts/render.py --live --list --scale 8 --out /tmp/list.png
python3 scripts/render.py --live --list --white --out /tmp/list-white.png
python3 scripts/render.py --demo --size 144 --count-corner top-left --out /tmp/corner.png
```

`--demo` uses synthetic aircraft, `--fixture` reads a saved adsb.lol JSON payload
(useful offline), `--live` hits the API. `--gap` simulates the bezel between the
four keys of a 2x2 block.

## Map data

`data/map.json` is generated, not hand-edited:

```
python3 scripts/build_map.py                                  # worldwide, 0.02 deg, 4.0 MB
python3 scripts/build_map.py --bbox -10 35 5 45               # one region, much smaller
python3 scripts/build_map.py --tolerance 0.01 --decimals 2    # more detail, bigger file
```

It downloads about 64 MB of [Natural Earth](https://www.naturalearthdata.com)
1:10m GeoJSON once (cached in `~/.cache/sc-adskey/natural-earth`), clips it to the
bounding box, simplifies with Douglas-Peucker and stores each layer as one flat
array of coordinates plus a count per line. The plugin computes one bounding box
per line at load and uses them to cull lines outside the visible window.

The bundled world file is 4.0 MB on disk, about 4 MB of RAM, ~125 ms to load and
5-8 ms for the first map render in a new area (cached afterwards). The earlier
nested-array format cost 50 MB of RAM for the same data.

## Renaming the plugin id

Renaming the package breaks every action already on a deck, because pages store
the action ids. The script moves the plugin folder, copies the settings and
rewrites the ids in the pages, backing up every file it touches. It is safe to
run twice.

```
python3 scripts/migrate_plugin_id.py --old com_example_old --new com_example_new --dry-run
python3 scripts/migrate_plugin_id.py --old com_example_old --new com_example_new
```

## Releasing a new version

1. Bump `version` in `manifest.json` and `PLUGIN_VERSION` in `main.py`.
2. Commit and push, then note the commit sha.
3. Fork [StreamController/StreamController-Store](https://github.com/StreamController/StreamController-Store)
   and add an entry to `Plugins.json` **on the `main` branch**:
   ```json
   { "url": "https://github.com/radiotaiso/aircraft-radar-streamcontroller", "hash": "<commit sha>" }
   ```
   (The branch the app reads is resolved from `versions.json` on the `versions`
   branch; for 1.5.0-beta.16 it is `main`.)
4. Open a pull request against `main`. Approval usually takes a few hours.

The store reads `manifest.json` and `attribution.json` from the root at the commit
you pin, so both must be up to date. `about.json` is optional. No
`requirements.txt` is needed: the plugin only uses modules StreamController
already ships (Pillow, requests, loguru, PyGObject).

## Layout

```
main.py            PluginBase subclass: settings, one shared service, action holders
settings_ui.py     the settings window (Adw rows)
radar/             pure logic, no StreamController imports
  adsb.py          API client and parsing
  config.py        Config dataclass, defaults, sanitising
  mapdata.py       map file loading, per-line bounding boxes, culling
  render.py        radar, full-size, list, icons, colours, map layer
  frames.py        one render per (snapshot version, size)
  service.py       the poller: interval, backoff, stale, subscribers
actions/           ActionCore subclasses and block detection
scripts/           render CLI, map builder, smoke test, id migration
data/              bundled world map
```
