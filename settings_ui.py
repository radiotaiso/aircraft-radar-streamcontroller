from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .radar import mapdata
from .radar.config import COUNT_CORNERS, INTERVAL_MAX_S, INTERVAL_MIN_S, RADIUS_CHOICES, VIEW_CHOICES


VIEW_LABELS = ("Radar (circle)", "Full size (square)")
CORNER_LABELS = {
    "bottom-right": "Bottom right",
    "bottom-left": "Bottom left",
    "top-right": "Top right",
    "top-left": "Top left",
}


def _spin_row(title, subtitle, value, lower, upper, step, digits, on_change):
    adjustment = Gtk.Adjustment(
        value=value,
        lower=lower,
        upper=upper,
        step_increment=step,
        page_increment=step * 10,
    )
    row = Adw.SpinRow(title=title, subtitle=subtitle, adjustment=adjustment, digits=digits)
    row.connect("notify::value", lambda widget, _param: on_change(widget.get_value()))
    return row


def _map_subtitle() -> str:
    data = mapdata.default()
    if data.bbox is None:
        return "Map data file not found"
    if data.worldwide:
        return "Coastlines, lakes, state borders and urban areas worldwide (Natural Earth 1:10m)"
    west, south, east, north = data.bbox
    return f"Coastlines, lakes, state borders and urban areas (lon {west:g} to {east:g}, lat {south:g} to {north:g})"


def build_settings_group(plugin) -> Adw.PreferencesGroup:
    config = plugin.service.snapshot().config

    group = Adw.PreferencesGroup(
        title="Aircraft",
        description="Applies to every radar key. Data from api.adsb.lol. Tap a radar key to cycle the radius.",
    )

    group.add(
        _spin_row(
            "Latitude",
            "Radar center, degrees north",
            config.lat,
            -90.0,
            90.0,
            0.0001,
            4,
            lambda value: plugin.update_config(lat=value),
        )
    )
    group.add(
        _spin_row(
            "Longitude",
            "Radar center, degrees east (negative = west)",
            config.lon,
            -180.0,
            180.0,
            0.0001,
            4,
            lambda value: plugin.update_config(lon=value),
        )
    )

    radius = Adw.ComboRow(
        title="Radius",
        subtitle="Distance from the center to the edge of the radar (or of the key in full size)",
        model=Gtk.StringList.new([f"{km} km" for km in RADIUS_CHOICES]),
    )
    radius.set_selected(RADIUS_CHOICES.index(config.radius_km))

    def on_radius(widget, _param):
        index = widget.get_selected()
        if index != Gtk.INVALID_LIST_POSITION:
            plugin.update_config(radius_km=RADIUS_CHOICES[index])

    radius.connect("notify::selected", on_radius)
    group.add(radius)

    view = Adw.ComboRow(
        title="Map size",
        subtitle="Radar keeps the round scope. Full size fills the whole key, corners included",
        model=Gtk.StringList.new(list(VIEW_LABELS)),
    )
    view.set_selected(VIEW_CHOICES.index(config.view))

    def on_view(widget, _param):
        index = widget.get_selected()
        if index != Gtk.INVALID_LIST_POSITION:
            plugin.update_config(view=VIEW_CHOICES[index])

    view.connect("notify::selected", on_view)
    group.add(view)

    group.add(
        _spin_row(
            "Refresh interval",
            "Seconds between requests",
            config.interval_s,
            INTERVAL_MIN_S,
            INTERVAL_MAX_S,
            5,
            0,
            lambda value: plugin.update_config(interval_s=int(value)),
        )
    )

    ground = Adw.SwitchRow(
        title="Hide aircraft on the ground",
        subtitle="Airport traffic is not shown",
        active=config.hide_ground,
    )
    ground.connect("notify::active", lambda widget, _param: plugin.update_config(hide_ground=widget.get_active()))
    group.add(ground)

    corner = Adw.ComboRow(
        title="Count position",
        subtitle="Corner of the radar (or of the 2x2 block) that shows how many aircraft are visible. Inner corners are never used",
        model=Gtk.StringList.new([CORNER_LABELS[name] for name in COUNT_CORNERS]),
    )
    corner.set_selected(COUNT_CORNERS.index(config.count_corner))

    def on_corner(widget, _param):
        index = widget.get_selected()
        if index != Gtk.INVALID_LIST_POSITION:
            plugin.update_config(count_corner=COUNT_CORNERS[index])

    corner.connect("notify::selected", on_corner)
    group.add(corner)

    coloured = Adw.SwitchRow(
        title="Colored aircraft",
        subtitle="Paint the nearest aircraft and the list entries with matching colors; turn off for plain white",
        active=config.colored,
    )
    coloured.connect("notify::active", lambda widget, _param: plugin.update_config(colored=widget.get_active()))
    group.add(coloured)

    outline = Adw.SwitchRow(title="Show map outline", subtitle=_map_subtitle(), active=config.show_map)
    outline.connect("notify::active", lambda widget, _param: plugin.update_config(show_map=widget.get_active()))
    group.add(outline)

    return group
