from __future__ import annotations
import json
import os
from dataclasses import dataclass, field, asdict

CONFIG_DIR = os.path.expanduser("~/.config/mimaki-gui")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


@dataclass
class ToolPreset:
    name: str = "Default"
    tool_diameter_mm: float = 2.0
    xy_travel_mm_min: float = 5000.0
    xy_machining_mm_min: float = 1000.0
    z_travel_mm_min: float = 1000.0
    z_machining_mm_min: float = 500.0


@dataclass
class SerialConfig:
    port: str = ""
    baud: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    use_zi_sync: bool = False
    throttle_factor: float = 0.8


@dataclass
class UIConfig:
    canvas_bg_color: str = "#F0F0EC"
    travel_color: str = "#0055CC"
    machining_color: str = "#CC2200"
    bbox_color: str = "#228800"
    pivot_color: str = "#FF8800"
    zone_color: str = "#CC0000"
    transmission_log_lines: int = 200


@dataclass
class AppConfig:
    recent_files: list = field(default_factory=list)
    last_import_dir: str = ""
    last_project_dir: str = ""
    serial: SerialConfig = field(default_factory=SerialConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    tool_presets: list = field(default_factory=list)

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = {
            "recent_files": self.recent_files,
            "last_import_dir": self.last_import_dir,
            "last_project_dir": self.last_project_dir,
            "serial": asdict(self.serial),
            "ui": asdict(self.ui),
            "tool_presets": [asdict(tp) for tp in self.tool_presets],
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls) -> AppConfig:
        if not os.path.exists(CONFIG_FILE):
            return cls()
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            cfg = cls()
            cfg.recent_files = data.get("recent_files", [])[:10]
            cfg.last_import_dir = data.get("last_import_dir", "")
            cfg.last_project_dir = data.get("last_project_dir", "")
            serial = data.get("serial", {})
            cfg.serial = SerialConfig(**{
                k: v for k, v in serial.items()
                if k in SerialConfig.__dataclass_fields__
            })
            ui = data.get("ui", {})
            cfg.ui = UIConfig(**{
                k: v for k, v in ui.items()
                if k in UIConfig.__dataclass_fields__
            })
            cfg.tool_presets = [
                ToolPreset(**{k: v for k, v in tp.items()
                              if k in ToolPreset.__dataclass_fields__})
                for tp in data.get("tool_presets", [])
            ]
            return cfg
        except Exception:
            return cls()

    def add_recent_file(self, filepath: str):
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
        self.recent_files.insert(0, filepath)
        self.recent_files = self.recent_files[:10]
