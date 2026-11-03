from __future__ import annotations

import threading

from loguru import logger as log

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase

from .actions.list import RadarList
from .actions.scope import RadarScope
from .actions.tile import RadarTile
from .radar import mapdata
from .radar.config import Config
from .radar.frames import FrameCache
from .radar.service import RadarService

GITHUB = "https://github.com/radiotaiso/aircraft-radar-streamcontroller"
PLUGIN_VERSION = "1.0.0"
APP_VERSION = "1.5.0-beta.16"


class AdskeyPlugin(PluginBase):
    def __init__(self):
        super().__init__()

        self.lm = self.locale_manager
        self.has_plugin_settings = True
        self._settings_lock = threading.Lock()

        self.service = RadarService(config=Config.from_dict(self.get_settings()), logger=log)
        self.frames = FrameCache()
        self.list_frames = FrameCache(list_mode=True)
        mapdata.default()

        key_only = {
            Input.Key: ActionInputSupport.SUPPORTED,
            Input.Dial: ActionInputSupport.UNSUPPORTED,
            Input.Touchscreen: ActionInputSupport.UNSUPPORTED,
        }
        self.add_action_holder(
            ActionHolder(
                plugin_base=self,
                action_base=RadarScope,
                action_id_suffix="RadarScope",
                action_name=self.lm.get("actions.radar-scope.name"),
                action_support=key_only,
            )
        )
        self.add_action_holder(
            ActionHolder(
                plugin_base=self,
                action_base=RadarList,
                action_id_suffix="RadarList",
                action_name=self.lm.get("actions.radar-list.name"),
                action_support=key_only,
            )
        )
        self.add_action_holder(
            ActionHolder(
                plugin_base=self,
                action_base=RadarTile,
                action_id_suffix="RadarTile",
                action_name=self.lm.get("actions.radar-tile.name"),
                action_support=key_only,
            )
        )

        self.register(
            plugin_name=self.lm.get("plugin.name"),
            github_repo=GITHUB,
            plugin_version=PLUGIN_VERSION,
            app_version=APP_VERSION,
        )

        if self.registered:
            self.service.start()

    def update_config(self, **changes) -> Config:
        with self._settings_lock:
            raw = self.get_settings()
            raw.update(changes)
            config = Config.from_dict(raw)
            raw.update(config.to_dict())
            self.set_settings(raw)
        self.service.configure(config)
        return config

    def cycle_radius(self) -> None:
        self.update_config(radius_km=self.service.snapshot().config.next_radius())

    def get_settings_area(self):
        from .settings_ui import build_settings_group

        return build_settings_group(self)
