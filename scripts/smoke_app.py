#!/usr/bin/env python3
"""Load the plugin through the real StreamController code in an isolated data dir.

Run with the app's interpreter so its dependencies resolve:

    /usr/local/lib/streamcontroller/bin/python scripts/smoke_app.py

Nothing under ~/.var/app/com.core447.StreamController is touched: the app is
pointed at a temporary --data directory that holds a symlink to this repo.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = Path("/usr/lib/streamcontroller")

TMP = Path(tempfile.mkdtemp(prefix="adskey-smoke-"))
PLUGINS = TMP / "data" / "plugins"
PLUGINS.mkdir(parents=True)
(PLUGINS / "com_idimw_adskey").symlink_to(ROOT)

sys.argv = ["streamcontroller", "--data", str(TMP / "data")]
os.chdir(APP)
sys.path.insert(0, str(APP))

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {name}{('  -> ' + detail) if detail and not condition else ''}")
    if not condition:
        failures.append(name)


def main() -> None:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    import globals as gl
    from src.backend.DeckManagement.InputIdentifier import Input
    from src.backend.PluginManager.PluginBase import PluginBase
    from src.backend.PluginManager.PluginManager import PluginManager

    manager = PluginManager()
    manager.load_plugins()

    check("plugin registered", "com_idimw_adskey" in PluginBase.plugins, str(list(PluginBase.disabled_plugins)))
    check("plugin not disabled", "com_idimw_adskey" not in PluginBase.disabled_plugins)
    ours = [c for c in PluginBase.__subclasses__() if c.__module__.startswith("plugins.com_idimw_adskey")]
    check("exactly one PluginBase subclass", len(ours) == 1, str(ours))
    if "com_idimw_adskey" not in PluginBase.plugins:
        return

    plugin = PluginBase.plugins["com_idimw_adskey"]["object"]
    check("plugin.registered", plugin.registered)
    check("app version is the one the plan targets", gl.app_version == "1.5.0-beta.16", gl.app_version)
    check("plugin settings enabled", plugin.has_plugin_settings)
    check("display name is Aircraft Radar", plugin.plugin_name == "Aircraft Radar", plugin.plugin_name)
    check("manifest name matches", plugin.get_manifest().get("name") == "Aircraft Radar", plugin.get_manifest().get("name"))
    holders = sorted(plugin.action_holders)
    check(
        "three action holders",
        holders == ["com_idimw_adskey::RadarList", "com_idimw_adskey::RadarScope", "com_idimw_adskey::RadarTile"],
        str(holders),
    )
    from plugins.com_idimw_adskey.radar import mapdata

    check("map data loaded at startup", mapdata.default().line_count > 500, str(mapdata.default().line_count))
    check("service thread running", plugin.service._thread is not None and plugin.service._thread.is_alive())

    plugin.service.stop()
    plugin.service._fetch = lambda lat, lon, radius_km: []

    plugin.set_settings({"first-setup": False})
    plugin.update_config(radius_km=150)
    stored = json.loads((TMP / "data" / "settings" / "plugins" / "com_idimw_adskey" / "settings.json").read_text())
    check("settings file is v2.0", stored.get("file-version") == "2.0", str(stored))
    check("first-setup preserved", stored["settings"].get("first-setup") is False, str(stored))
    check("config persisted", stored["settings"].get("radius_km") == 150 and stored["settings"].get("lat") == 32.5424, str(stored))
    check("service got the config", plugin.service.snapshot().config.radius_km == 150)
    plugin.update_config(radius_km=100)

    class FakeDeck:
        def key_layout(self):
            return (3, 5)

    class FakeController:
        deck = FakeDeck()

        def get_key_image_size(self):
            return (72, 72)

    class FakePage:
        def __init__(self):
            self.cells = {}

        def get_all_actions_for_input(self, ident, state, only_action_cores=False):
            return list(self.cells.get(ident.coords, []))

    page = FakePage()
    controller = FakeController()
    painted: dict[tuple[int, int], list] = {}

    def make(kind: str, x: int, y: int):
        holder = plugin.action_holders[f"com_idimw_adskey::{kind}"]
        action = holder.action_core(
            action_id=holder.action_id,
            action_name=holder.action_name,
            deck_controller=controller,
            page=page,
            plugin_base=plugin,
            state=0,
            input_ident=Input.Key(f"{x}x{y}"),
        )
        painted[(x, y)] = []
        action.set_media = lambda image=None, _key=(x, y), **kwargs: painted[_key].append(image)
        page.cells[(x, y)] = [action]
        return action

    tiles = [make("RadarTile", x, y) for x, y in ((3, 1), (4, 1), (3, 2), (4, 2))]
    scope = make("RadarScope", 3, 0)
    listing = make("RadarList", 2, 0)
    everyone = tiles + [scope, listing]

    check("actions are ActionCore subclasses", all(a.__class__.__mro__[1].__name__ == "RadarActionBase" for a in everyone))
    check(
        "cycle-radius event assigner registered",
        all(a.event_manager.get_event_assigner_by_id("cycle-radius") is not None for a in everyone),
    )

    plugin.service._fetch = lambda lat, lon, radius_km: []
    for action in everyone:
        action.on_ready_called = True
        action.on_ready()
        action.on_update()
    plugin.service.process()

    check("every key painted", all(painted[key] for key in painted), str({k: len(v) for k, v in painted.items()}))
    check("every image is 72x72 RGB", all(img.size == (72, 72) and img.mode == "RGB" for v in painted.values() for img in v if img is not None))
    check("subscriptions are not duplicated", len(plugin.service._subscribers) == 6, str(len(plugin.service._subscribers)))
    check("the list key paints a 72x72 frame", painted[(2, 0)][-1].size == (72, 72) and painted[(2, 0)][-1].mode == "RGB")
    check("the list is not the radar scope", painted[(2, 0)][-1].tobytes() != painted[(3, 0)][-1].tobytes())

    from plugins.com_idimw_adskey.radar.render import crop_tile, render_warning

    frame = plugin.frames.get(plugin.service.snapshot(), 144)
    expected = {(3, 1): (0, 0), (4, 1): (1, 0), (3, 2): (0, 1), (4, 2): (1, 1)}
    for coords, (col, row) in expected.items():
        check(f"tile {coords} paints its own quarter", painted[coords][-1].tobytes() == crop_tile(frame, col, row).tobytes())
    check("scope paints a full 72x72 scope", painted[(3, 0)][-1].tobytes() != painted[(3, 1)][-1].tobytes())

    page.cells.pop((4, 2))
    tiles[0].redraw()
    warning = render_warning(72).tobytes()
    check("a broken 2x2 shows the warning glyph", painted[(3, 1)][-1].tobytes() == warning)
    scope.redraw()
    check("scope next to a broken block is unaffected", painted[(3, 0)][-1].tobytes() != warning)
    page.cells[(4, 2)] = [tiles[3]]
    tiles[0].redraw()
    check("repairing the block restores the quarter", painted[(3, 1)][-1].tobytes() == crop_tile(frame, 0, 0).tobytes())

    tiles[1].on_cycle_radius()
    check("tap cycles the radius 100 -> 150", plugin.service.snapshot().config.radius_km == 150)

    before = len(plugin.service._subscribers)
    tiles[3].on_removed_from_cache()
    check("on_removed_from_cache unsubscribes", len(plugin.service._subscribers) == before - 1)

    group = plugin.get_settings_area()
    check("settings area is an Adw.PreferencesGroup", isinstance(group, Adw.PreferencesGroup))
    check("settings group uses the display name", group.get_title() == "Aircraft Radar", group.get_title())
    rows = []
    child = group.get_first_child()

    def collect(widget):
        if isinstance(widget, (Adw.SpinRow, Adw.ComboRow, Adw.SwitchRow)):
            rows.append(widget)
        child = widget.get_first_child()
        while child is not None:
            collect(child)
            child = child.get_next_sibling()

    collect(group)
    kinds = sorted(type(row).__name__ for row in rows)
    check(
        "settings rows: 3 spin, 3 combo, 3 switch",
        kinds
        == ["ComboRow", "ComboRow", "ComboRow", "SpinRow", "SpinRow", "SpinRow", "SwitchRow", "SwitchRow", "SwitchRow"],
        str(kinds),
    )

    combos = {r.get_title(): r for r in rows if isinstance(r, Adw.ComboRow)}
    check("all combos are present", set(combos) == {"Radius", "Map size", "Count position"}, str(set(combos)))
    combos["Radius"].set_selected(4)
    check("combo row writes the radius", plugin.service.snapshot().config.radius_km == 200)

    view_row = combos["Map size"]
    labels = [view_row.get_model().get_string(i) for i in range(view_row.get_model().get_n_items())]
    check("map size offers radar and full", labels == ["Radar (circle)", "Full size (square)"], str(labels))
    check("map size defaults to radar", view_row.get_selected() == 0 and plugin.service.snapshot().config.view == "radar")
    radar_frame = plugin.frames.get(plugin.service.snapshot(), 144).tobytes()
    view_row.set_selected(1)
    snap = plugin.service.snapshot()
    check("map size writes the view", snap.config.view == "full" and snap.config.full)
    check("full view asks the API for the corner radius", abs(snap.config.fetch_radius_km - 200 * 2 ** 0.5) < 1e-6, str(snap.config.fetch_radius_km))
    check("full view changes what the keys draw", plugin.frames.get(snap, 144).tobytes() != radar_frame)
    stored_view = json.loads((TMP / "data" / "settings" / "plugins" / "com_idimw_adskey" / "settings.json").read_text())["settings"]
    check("the view reaches the settings file", stored_view.get("view") == "full", str(stored_view))

    plugin.service._raw = ()
    plugin.service._fetched_at = plugin.service._clock()
    plugin.service.request_redraw()
    plugin.service.process()

    corner_row = combos["Count position"]
    corner_labels = [corner_row.get_model().get_string(i) for i in range(corner_row.get_model().get_n_items())]
    check(
        "count position offers the four outer corners",
        corner_labels == ["Bottom right", "Bottom left", "Top right", "Top left"],
        str(corner_labels),
    )
    check("count position defaults to bottom right", corner_row.get_selected() == 0 and plugin.service.snapshot().config.count_corner == "bottom-right")
    before_corner = plugin.frames.get(plugin.service.snapshot(), 144).tobytes()
    corner_row.set_selected(3)
    check("count position writes the corner", plugin.service.snapshot().config.count_corner == "top-left")
    _snap = plugin.service.snapshot()
    _after = plugin.frames.get(_snap, 144).tobytes()
    check(
        "moving the count changes what the keys draw",
        _after != before_corner,
        f"aircraft={_snap.aircraft!r} corner={_snap.config.count_corner} view={_snap.config.view} version={_snap.version}",
    )
    stored_corner = json.loads((TMP / "data" / "settings" / "plugins" / "com_idimw_adskey" / "settings.json").read_text())["settings"]
    check("the corner reaches the settings file", stored_corner.get("count_corner") == "top-left", str(stored_corner))
    corner_row.set_selected(0)

    plugin.service._raw = ()
    plugin.service._fetched_at = plugin.service._clock()
    plugin.service.request_redraw()
    plugin.service.process()
    full_paint = {key: v[-1].tobytes() for key, v in painted.items() if v}
    view_row.set_selected(0)
    plugin.service._raw = ()
    plugin.service._fetched_at = plugin.service._clock()
    plugin.service.request_redraw()
    plugin.service.process()
    unchanged = sorted(key for key in full_paint if painted[key][-1].tobytes() == full_paint[key])
    check(
        "switching the view repaints every still-subscribed radar key",
        unchanged == [(2, 0), (4, 2)],
        f"unchanged: {unchanged}",
    )
    check("the key removed from the cache is left alone", (4, 2) in unchanged)
    check("the list does not depend on the view with no aircraft in range", (2, 0) in unchanged)

    switches = {r.get_title(): r for r in rows if isinstance(r, Adw.SwitchRow)}
    check(
        "all switches are present",
        set(switches) == {"Hide aircraft on the ground", "Show map outline", "Colored aircraft"},
        str(set(switches)),
    )
    switches["Hide aircraft on the ground"].set_active(False)
    check("switch row writes hide_ground", plugin.service.snapshot().config.hide_ground is False)
    check("map switch reflects the default", switches["Show map outline"].get_active() is True)
    check(
        "map switch subtitle names the coverage",
        "worldwide" in switches["Show map outline"].get_subtitle(),
        switches["Show map outline"].get_subtitle(),
    )
    with_map = plugin.frames.get(plugin.service.snapshot(), 144).tobytes()
    switches["Show map outline"].set_active(False)
    check("map switch writes show_map", plugin.service.snapshot().config.show_map is False)
    without_map = plugin.frames.get(plugin.service.snapshot(), 144).tobytes()
    check("toggling the map changes what the keys draw", with_map != without_map)
    switches["Show map outline"].set_active(True)

    from plugins.com_idimw_adskey.radar.adsb import Aircraft

    plugin.service._raw = (
        Aircraft(hex="aa0001", lat=plugin.service.snapshot().config.lat + 0.012, lon=plugin.service.snapshot().config.lon + 0.010, callsign="TEST1", alt_ft=10000),
        Aircraft(hex="aa0002", lat=plugin.service.snapshot().config.lat + 0.002, lon=plugin.service.snapshot().config.lon - 0.015, callsign="TEST2", alt_ft=20000, track=90.0),
    )
    plugin.service._fetched_at = plugin.service._clock()
    plugin.service.request_redraw()
    plugin.service.process()

    check("aircraft are colored by default", switches["Colored aircraft"].get_active() is True and plugin.service.snapshot().config.colored)
    radar_before = plugin.frames.get(plugin.service.snapshot(), 72).tobytes()
    list_before = plugin.list_frames.get(plugin.service.snapshot(), 72).tobytes()
    switches["Colored aircraft"].set_active(False)
    check("the color switch writes the config", plugin.service.snapshot().config.colored is False)
    check("the color switch repaints the radar", plugin.frames.get(plugin.service.snapshot(), 72).tobytes() != radar_before)
    check("the color switch repaints the list", plugin.list_frames.get(plugin.service.snapshot(), 72).tobytes() != list_before)
    stored_colored = json.loads((TMP / "data" / "settings" / "plugins" / "com_idimw_adskey" / "settings.json").read_text())["settings"]
    check("the color choice reaches the settings file", stored_colored.get("colored") is False, str(stored_colored))
    switches["Colored aircraft"].set_active(True)
    spins = [r for r in rows if isinstance(r, Adw.SpinRow)]
    lat_row = next(r for r in spins if r.get_title() == "Latitude")
    lat_row.set_value(19.4326)
    check("spin row writes latitude", plugin.service.snapshot().config.lat == 19.4326)
    final = json.loads((TMP / "data" / "settings" / "plugins" / "com_idimw_adskey" / "settings.json").read_text())["settings"]
    check(
        "UI edits reach the settings file",
        final["radius_km"] == 200
        and final["hide_ground"] is False
        and final["lat"] == 19.4326
        and final["show_map"] is True
        and final["count_corner"] == "bottom-right"
        and final["colored"] is True,
        str(final),
    )
    check("first-setup still preserved after UI edits", final.get("first-setup") is False)


try:
    main()
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    raise SystemExit(1)
print("all smoke checks passed")
