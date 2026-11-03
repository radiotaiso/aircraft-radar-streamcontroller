from __future__ import annotations

from loguru import logger as log

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..radar.render import crop_tile, render_warning
from .block import Block, detect_block


class RadarActionBase(ActionCore):
    SHAPE = (1, 1)
    FRAMES = "frames"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_event_assigner(
            EventAssigner(
                id="cycle-radius",
                ui_label="Cycle radius",
                default_events=[Input.Key.Events.SHORT_UP],
                callback=self.on_cycle_radius,
            )
        )

    def on_ready(self):
        service = self.plugin_base.service
        service.subscribe(self._on_snapshot)
        self.redraw(service.snapshot())
        service.request_redraw()

    def on_update(self):
        self.redraw()

    def on_tick(self):
        pass

    def on_remove(self):
        self._unsubscribe()
        super().on_remove()

    def on_removed_from_cache(self):
        self._unsubscribe()
        super().on_removed_from_cache()

    def on_cycle_radius(self, *args, **kwargs):
        self.plugin_base.cycle_radius()

    def _unsubscribe(self):
        service = self.plugin_base.service
        service.unsubscribe(self._on_snapshot)
        service.request_redraw()

    def _on_snapshot(self, snapshot):
        self.redraw(snapshot)

    def redraw(self, snapshot=None):
        if not self.on_ready_called:
            return
        try:
            self._paint(snapshot or self.plugin_base.service.snapshot())
        except Exception as exc:
            log.warning(f"sc-adskey: redraw failed: {exc.__class__.__name__}: {exc}")

    def _paint(self, snapshot):
        key = int(min(self.deck_controller.get_key_image_size()))
        block = self.find_block()
        if block is None:
            image = render_warning(key)
        else:
            frames = getattr(self.plugin_base, self.FRAMES)
            frame = frames.get(snapshot, key * block.w)
            image = frame.copy() if block.w == 1 else crop_tile(frame, block.col, block.row, key)
        self.set_media(image=image)

    def find_block(self) -> Block | None:
        coords = getattr(self.input_ident, "coords", None)
        page = self.page
        if coords is None or page is None:
            return None

        rows, cols = self.deck_controller.deck.key_layout()
        action_id = self.action_id
        state = self.state

        def is_member(x: int, y: int) -> bool:
            actions = page.get_all_actions_for_input(Input.Key(f"{x}x{y}"), state, True)
            return any(action.action_id == action_id for action in actions)

        return detect_block(coords, rows, cols, is_member, {self.SHAPE})
