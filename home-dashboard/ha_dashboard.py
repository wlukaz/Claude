#!/usr/bin/env python3
"""Home Hub: back up, build and restore a Home Assistant dashboard.

    python3 ha_dashboard.py install     # backup, then build the "Home Hub" dashboard
    python3 ha_dashboard.py backup      # backup only
    python3 ha_dashboard.py preview     # build dashboard JSON locally, change nothing
    python3 ha_dashboard.py restore     # put dashboards back exactly as before the first install
    python3 ha_dashboard.py report      # what was found, what's missing, what HA has discovered

Connection settings come from HA_URL and HA_TOKEN (or you are asked for them).
Only the Python standard library is needed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ha_client import HAError, HomeAssistant  # noqa: E402

HERE = Path(__file__).resolve().parent
BACKUP_DIR = HERE / "backups"
OUT_DIR = HERE / "output"
DASHBOARD_URL = "home-hub"
DASHBOARD_TITLE = "Home Hub"

TESLA_PLATFORMS = {"tesla_fleet", "tessie", "teslemetry", "tesla_custom", "tesla"}
TV_PLATFORMS = {
    "samsungtv", "webostv", "androidtv", "androidtv_remote", "apple_tv", "roku",
    "braviatv", "vizio", "philips_js", "panasonic_viera", "bang_olufsen",
}
# Platforms whose switches are infrastructure toggles, not things you want on a home screen.
NOISY_SWITCH_PLATFORMS = {
    "unifi", "adguard", "pi_hole", "hacs", "mqtt_room", "esphome_restart",
    "synology_dsm", "tplink_omada", "fritz", "proxmoxve", "shelly_config",
} | TESLA_PLATFORMS

# How to send D-pad presses for each TV integration.
# Each entry: (domain.service, target domain, data key, {button: command}).
REMOTE_PROFILES = {
    "androidtv_remote": ("remote.send_command", "remote", "command", dict(
        up="DPAD_UP", down="DPAD_DOWN", left="DPAD_LEFT", right="DPAD_RIGHT",
        ok="DPAD_CENTER", back="BACK", home="HOME")),
    "apple_tv": ("remote.send_command", "remote", "command", dict(
        up="up", down="down", left="left", right="right", ok="select",
        back="menu", home="home")),
    "roku": ("remote.send_command", "remote", "command", dict(
        up="up", down="down", left="left", right="right", ok="select",
        back="back", home="home")),
    "samsungtv": ("remote.send_command", "remote", "command", dict(
        up="KEY_UP", down="KEY_DOWN", left="KEY_LEFT", right="KEY_RIGHT",
        ok="KEY_ENTER", back="KEY_RETURN", home="KEY_HOME")),
    "braviatv": ("remote.send_command", "remote", "command", dict(
        up="Up", down="Down", left="Left", right="Right", ok="Confirm",
        back="Return", home="Home")),
    "webostv": ("webostv.button", "media_player", "button", dict(
        up="UP", down="DOWN", left="LEFT", right="RIGHT", ok="ENTER",
        back="BACK", home="HOME")),
    "androidtv": ("androidtv.adb_command", "media_player", "command", dict(
        up="UP", down="DOWN", left="LEFT", right="RIGHT", ok="CENTER",
        back="BACK", home="HOME")),
}


# --------------------------------------------------------------------------- connection

def connect() -> HomeAssistant:
    url = os.environ.get("HA_URL") or input(
        "Home Assistant address [http://homeassistant.local:8123]: "
    ).strip() or "http://homeassistant.local:8123"
    token = os.environ.get("HA_TOKEN") or getpass.getpass(
        "Long-lived access token (Profile > Security > Long-lived access tokens): "
    ).strip()
    try:
        ha = HomeAssistant(url, token)
    except (OSError, HAError) as e:
        sys.exit(f"Could not connect to Home Assistant at {url}: {e}")
    print(f"Connected to Home Assistant {ha.version} at {url}")
    return ha


# --------------------------------------------------------------------------- backup

def backup(ha: HomeAssistant, full_backup: bool = True) -> Path:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder = BACKUP_DIR / stamp
    n = 1
    while folder.exists():
        n += 1
        folder = BACKUP_DIR / f"{stamp}_{n}"
    folder.mkdir(parents=True)

    dashboards = ha.call("lovelace/dashboards/list") or []
    saved = []
    # url_path None is the built-in "Overview" dashboard.
    for d in [{"url_path": None, "title": "Overview (default)", "mode": "storage"}] + dashboards:
        url_path = d.get("url_path")
        name = url_path or "_default"
        entry = {"url_path": url_path, "meta": d}
        if d.get("mode") == "yaml":
            entry["status"] = "yaml"  # lives in configuration files; we never touch it
        else:
            kwargs = {"url_path": url_path} if url_path else {}
            try:
                cfg = ha.call("lovelace/config", force=True, **kwargs)
                (folder / f"dashboard_{name}.json").write_text(json.dumps(cfg, indent=2))
                entry["status"] = "saved"
            except HAError as e:
                if "config_not_found" in str(e):
                    entry["status"] = "auto_generated"  # HA builds it automatically
                else:
                    entry["status"] = f"error: {e}"
        saved.append(entry)
        print(f"  dashboard {name:<28} {entry['status']}")

    (folder / "dashboards.json").write_text(json.dumps(saved, indent=2))
    for name, cmd in [
        ("resources", "lovelace/resources"),
        ("areas", "config/area_registry/list"),
        ("floors", "config/floor_registry/list"),
        ("devices", "config/device_registry/list"),
        ("entities", "config/entity_registry/list"),
        ("states", "get_states"),
    ]:
        res = ha.try_call(cmd)
        if res is not None:
            (folder / f"{name}.json").write_text(json.dumps(res, indent=2))
    (folder / "info.json").write_text(json.dumps(
        {"created": stamp, "ha_version": ha.version}, indent=2))
    print(f"Dashboard backup saved to {folder}")

    if full_backup:
        create_full_backup(ha)
    return folder


def create_full_backup(ha: HomeAssistant) -> None:
    """Ask HA itself to make a full system backup (Settings > System > Backups)."""
    name = f"Before Home Hub {dt.date.today().isoformat()}"
    attempts = [
        ("hassio", "backup_full", {"name": name}),        # Home Assistant OS / Supervised
        ("backup", "create_automatic", {}),               # Core / Container, 2025.1+
        ("backup", "create", {}),                         # older Core / Container
    ]
    for domain, service, data in attempts:
        try:
            ha.call("call_service", domain=domain, service=service, service_data=data)
            print(f"Full Home Assistant backup started ({domain}.{service}). "
                  "It appears under Settings > System > Backups in a few minutes.")
            return
        except HAError:
            continue
    print("Note: could not start a full system backup automatically. The dashboard "
          "backup above is enough to undo this tool; for a full system backup use "
          "Settings > System > Backups > Back up now.")


# --------------------------------------------------------------------------- inventory

class Inventory:
    def __init__(self, ha: HomeAssistant, exclude_areas: list[str]):
        self.states = {s["entity_id"]: s for s in ha.call("get_states")}
        self.areas = {a["area_id"]: a for a in ha.try_call("config/area_registry/list") or []}
        self.floors = ha.try_call("config/floor_registry/list") or []
        self.devices = {d["id"]: d for d in ha.try_call("config/device_registry/list") or []}
        self.registry = {e["entity_id"]: e for e in ha.try_call("config/entity_registry/list") or []}
        self.flows = ha.try_call("config_entries/flow/progress") or []
        entries = ha.try_call("config_entries/get") or []
        self.integrations = sorted({e.get("domain") for e in entries if e.get("domain")})
        excl = {x.strip().lower() for x in exclude_areas if x.strip()}
        self.excluded_areas = {
            aid for aid, a in self.areas.items()
            if aid.lower() in excl or a.get("name", "").lower() in excl
        }

    # -- helpers
    def platform(self, eid: str) -> str | None:
        r = self.registry.get(eid)
        return r.get("platform") if r else None

    def device_id(self, eid: str) -> str | None:
        r = self.registry.get(eid)
        return r.get("device_id") if r else None

    def area(self, eid: str) -> str | None:
        r = self.registry.get(eid) or {}
        if r.get("area_id"):
            return r["area_id"]
        dev = self.devices.get(r.get("device_id") or "")
        return dev.get("area_id") if dev else None

    def name(self, eid: str) -> str:
        return self.states.get(eid, {}).get("attributes", {}).get("friendly_name", eid)

    def attr(self, eid: str, key: str, default=None):
        return self.states.get(eid, {}).get("attributes", {}).get(key, default)

    def visible(self, eid: str) -> bool:
        r = self.registry.get(eid) or {}
        if r.get("hidden_by") or r.get("disabled_by") or r.get("entity_category"):
            return False
        if self.area(eid) in self.excluded_areas:
            return False
        return eid in self.states

    def domain(self, domain: str) -> list[str]:
        return sorted(e for e in self.states if e.startswith(domain + ".") and self.visible(e))

    def by_area(self, eids: list[str]) -> dict[str | None, list[str]]:
        out: dict[str | None, list[str]] = defaultdict(list)
        for e in eids:
            out[self.area(e)].append(e)
        return out

    def area_order(self) -> list[str]:
        """Areas sorted by floor level, then name."""
        level = {f["floor_id"]: f.get("level") or 0 for f in self.floors}
        return sorted(
            (a for a in self.areas if a not in self.excluded_areas),
            key=lambda a: (level.get(self.areas[a].get("floor_id"), 0), self.areas[a]["name"].lower()),
        )

    def area_name(self, aid: str | None) -> str:
        return self.areas[aid]["name"] if aid in self.areas else "Other"

    def same_device(self, eid: str, domain: str) -> list[str]:
        dev = self.device_id(eid)
        if not dev:
            return []
        return [e for e, r in self.registry.items()
                if r.get("device_id") == dev and e.startswith(domain + ".") and e in self.states]


# --------------------------------------------------------------------------- card helpers

def heading(text: str, icon: str | None = None, subtitle: bool = False) -> dict:
    c = {"type": "heading", "heading": text}
    if icon:
        c["icon"] = icon
    if subtitle:
        c["heading_style"] = "subtitle"
    return c


def tile(eid: str, features: list[dict] | None = None, name: str | None = None, **extra) -> dict:
    c = {"type": "tile", "entity": eid}
    if name:
        c["name"] = name
    if features:
        c["features"] = features
    c.update(extra)
    return c


def full(card: dict) -> dict:
    card["grid_options"] = {"columns": "full"}
    return card


def action_button(icon: str, name: str, action: str, target: dict, data: dict | None = None,
                  show_name: bool = True) -> dict:
    tap = {"action": "perform-action", "perform_action": action, "target": target}
    if data:
        tap["data"] = data
    return {"type": "button", "icon": icon, "name": name, "show_name": show_name,
            "tap_action": tap, "hold_action": tap if not show_name else {"action": "none"}}


def section(cards: list[dict], column_span: int | None = None) -> dict:
    s = {"type": "grid", "cards": cards}
    if column_span:
        s["column_span"] = column_span
    return s


def light_features(inv: Inventory, eid: str) -> list[dict]:
    modes = inv.attr(eid, "supported_color_modes") or []
    if any(m != "onoff" for m in modes):
        return [{"type": "light-brightness"}]
    return []


# --------------------------------------------------------------------------- view builders

def find_tesla(inv: Inventory) -> dict[str, list[str]]:
    """Group Tesla entities per car (device)."""
    cars: dict[str, list[str]] = defaultdict(list)
    for eid in inv.states:
        if inv.platform(eid) in TESLA_PLATFORMS and inv.visible(eid):
            cars[inv.device_id(eid) or "car"].append(eid)
    # Only keep devices that look like vehicles (have a battery or a location).
    return {d: es for d, es in cars.items()
            if any(e.startswith(("device_tracker.", "climate.")) or
                   inv.attr(e, "device_class") == "battery" for e in es)}


def spotify_players(inv: Inventory) -> list[str]:
    return [e for e in inv.domain("media_player") if inv.platform(e) == "spotify"]


def tv_players(inv: Inventory) -> list[str]:
    tvs = []
    for e in inv.domain("media_player"):
        if inv.platform(e) in TV_PLATFORMS or inv.attr(e, "device_class") == "tv":
            tvs.append(e)
    return tvs


def other_players(inv: Inventory) -> list[str]:
    skip = set(spotify_players(inv)) | set(tv_players(inv))
    return [e for e in inv.domain("media_player")
            if e not in skip and inv.platform(e) not in TESLA_PLATFORMS]


def view_home(inv: Inventory) -> dict:
    sections = []

    top = [{
        "type": "markdown",
        "content": (
            "## {% set h = now().hour %}"
            "{{ 'Good morning' if h < 12 else 'Good afternoon' if h < 18 else 'Good evening' }}\n"
            "{{ now().strftime('%A, %B %-d') }}"
        ),
        "text_only": True,
    }]
    weather = inv.domain("weather")
    if weather:
        top.append(full({"type": "weather-forecast", "entity": weather[0],
                         "forecast_type": "daily", "show_forecast": True}))
    people = inv.domain("person")
    if people:
        top.append(heading("People", "mdi:account-group", subtitle=True))
        top += [tile(p) for p in people]
    sections.append(section(top))

    quick = [heading("Quick controls", "mdi:lightning-bolt")]
    lights = inv.domain("light")
    if lights:
        quick.append({
            "type": "button", "name": "Lights", "icon": "mdi:lightbulb-group",
            "tap_action": {"action": "navigate", "navigation_path": f"/{DASHBOARD_URL}/lights"},
        })
        quick.append(action_button("mdi:lightbulb-off", "All lights off", "light.turn_off",
                                   {"entity_id": "all"}))
    for e in inv.domain("alarm_control_panel")[:2]:
        quick.append(tile(e, [{"type": "alarm-modes", "modes": ["armed_home", "armed_away", "disarmed"]}]))
    for e in inv.domain("lock"):
        if inv.platform(e) not in TESLA_PLATFORMS:
            quick.append(tile(e))
    for e in inv.domain("climate"):
        if inv.platform(e) not in TESLA_PLATFORMS:
            quick.append(tile(e, [{"type": "target-temperature"}]))
    for e in inv.domain("cover"):
        if inv.platform(e) not in TESLA_PLATFORMS and inv.attr(e, "device_class") == "garage":
            quick.append(tile(e, [{"type": "cover-open-close"}]))
    scenes = inv.domain("scene")
    if scenes:
        quick.append(heading("Scenes", "mdi:palette", subtitle=True))
        quick += [tile(s, show_entity_picture=False) for s in scenes[:8]]
    if len(quick) > 1:
        sections.append(section(quick))

    status = [heading("At a glance", "mdi:eye")]
    for car_entities in find_tesla(inv).values():
        b = next((e for e in car_entities if inv.attr(e, "device_class") == "battery"
                  and e.startswith("sensor.")), None)
        if b:
            status.append(tile(b, name="Car battery", icon="mdi:car-electric",
                               tap_action={"action": "navigate",
                                           "navigation_path": f"/{DASHBOARD_URL}/car"}))
    for sp in spotify_players(inv)[:1]:
        status.append(full({"type": "media-control", "entity": sp}))
    for e in inv.domain("vacuum")[:2]:
        status.append(tile(e, [{"type": "vacuum-commands",
                                "commands": ["start_pause", "return_home"]}]))
    if len(status) > 1:
        sections.append(section(status))

    return {"title": "Home", "path": "home", "icon": "mdi:home", "type": "sections",
            "max_columns": 4, "sections": sections}


def view_lights(inv: Inventory) -> dict | None:
    lights = inv.domain("light")
    fans = inv.domain("fan")
    switches = [s for s in inv.domain("switch")
                if inv.platform(s) not in NOISY_SWITCH_PLATFORMS
                and inv.attr(s, "device_class") in (None, "outlet", "switch")]
    if not (lights or fans or switches):
        return None
    grouped = inv.by_area(lights + fans + switches)
    sections = []
    for aid in inv.area_order() + [None]:
        eids = grouped.get(aid)
        if not eids:
            continue
        cards = [heading(inv.area_name(aid), inv.areas.get(aid, {}).get("icon") or "mdi:floor-plan")]
        area_lights = [e for e in eids if e.startswith("light.")]
        if len(area_lights) > 1:
            cards.append(action_button("mdi:lightbulb-off-outline", "Room off", "light.turn_off",
                                       {"entity_id": area_lights}))
        for e in sorted(eids, key=lambda x: (not x.startswith("light."), inv.name(x))):
            if e.startswith("light."):
                cards.append(tile(e, light_features(inv, e)))
            elif e.startswith("fan."):
                cards.append(tile(e, [{"type": "fan-speed"}]))
            else:
                cards.append(tile(e))
        sections.append(section(cards))
    return {"title": "Lights", "path": "lights", "icon": "mdi:lightbulb-group", "type": "sections",
            "max_columns": 4, "sections": sections}


def remote_pad(inv: Inventory, tv: str) -> list[dict]:
    platform = inv.platform(tv)
    profile = REMOTE_PROFILES.get(platform)
    if not profile:
        return []
    action, target_domain, key, cmds = profile
    if target_domain == "remote":
        remotes = inv.same_device(tv, "remote")
        if not remotes:
            return []
        target = {"entity_id": remotes[0]}
    else:
        target = {"entity_id": tv}

    def b(icon: str, cmd: str) -> dict:
        return action_button(icon, cmd, action, target, {key: cmds[cmd]}, show_name=False)

    vol = lambda icon, svc: action_button(icon, svc, f"media_player.{svc}", {"entity_id": tv},
                                          show_name=False)
    rows = [
        [vol("mdi:volume-minus", "volume_down"), b("mdi:chevron-up", "up"), vol("mdi:volume-plus", "volume_up")],
        [b("mdi:chevron-left", "left"), b("mdi:circle-medium", "ok"), b("mdi:chevron-right", "right")],
        [b("mdi:arrow-u-left-top", "back"), b("mdi:chevron-down", "down"), b("mdi:home", "home")],
    ]
    return [{"type": "grid", "columns": 3, "square": False,
             "cards": [c for row in rows for c in row]}]


def view_media(inv: Inventory) -> dict | None:
    sp, tvs, others = spotify_players(inv), tv_players(inv), other_players(inv)
    if not (sp or tvs or others):
        return None
    sections = []
    if sp:
        cards = [heading("Spotify", "mdi:spotify")]
        for p in sp:
            cards.append(full({"type": "media-control", "entity": p}))
            cards.append(tile(p, [{"type": "media-player-volume-slider"}], name="Volume"))
            if inv.attr(p, "source_list"):
                cards.append({"type": "entities", "entities": [{
                    "entity": p, "type": "attribute", "attribute": "source", "name": "Playing on"}]})
        sections.append(section(cards))
    for tv in tvs:
        cards = [heading(inv.name(tv), "mdi:television")]
        cards.append(tile(tv, name="Power", show_entity_picture=False))
        cards.append(full({"type": "media-control", "entity": tv}))
        cards += remote_pad(inv, tv)
        sources = inv.attr(tv, "source_list") or []
        for src in sources[:6]:
            cards.append(action_button("mdi:import", src, "media_player.select_source",
                                       {"entity_id": tv}, {"source": src}))
        sections.append(section(cards))
    if others:
        cards = [heading("Speakers & players", "mdi:speaker-multiple")]
        for p in others:
            cards.append(full({"type": "media-control", "entity": p}))
        sections.append(section(cards))
    return {"title": "Media", "path": "media", "icon": "mdi:play-box-multiple", "type": "sections",
            "max_columns": 3, "sections": sections}


def view_car(inv: Inventory) -> dict | None:
    cars = find_tesla(inv)
    if not cars:
        return None
    sections = []

    def pick(es, pred):
        return [e for e in es if pred(e)]

    for dev_id, es in cars.items():
        dev = inv.devices.get(dev_id, {})
        car_name = dev.get("name_by_user") or dev.get("name") or "Tesla"
        nm = lambda e: inv.name(e).lower()
        battery = pick(es, lambda e: e.startswith("sensor.") and inv.attr(e, "device_class") == "battery")
        rng = pick(es, lambda e: e.startswith("sensor.") and "range" in nm(e))
        charging = pick(es, lambda e: e.startswith(("sensor.", "binary_sensor.")) and "charg" in nm(e)
                        and inv.attr(e, "device_class") not in ("power", "current", "voltage"))
        locks = pick(es, lambda e: e.startswith("lock."))
        climate = pick(es, lambda e: e.startswith("climate."))
        covers = pick(es, lambda e: e.startswith("cover."))
        switches = pick(es, lambda e: e.startswith("switch."))
        buttons = pick(es, lambda e: e.startswith("button.") and any(
            k in nm(e) for k in ("honk", "flash", "wake", "boombox", "play fart")))
        numbers = pick(es, lambda e: e.startswith("number.") and "limit" in nm(e))
        trackers = pick(es, lambda e: e.startswith("device_tracker."))
        tires = pick(es, lambda e: e.startswith("sensor.") and "tire" in nm(e))
        odo = pick(es, lambda e: e.startswith("sensor.") and "odometer" in nm(e))
        inside = pick(es, lambda e: e.startswith("sensor.") and inv.attr(e, "device_class") == "temperature")

        status = [heading(car_name, "mdi:car-electric")]
        status += [tile(e) for e in battery[:1] + rng[:1]]
        status += [tile(e) for e in charging[:3]]
        status += [tile(e, [{"type": "numeric-input", "style": "slider"}]) for e in numbers[:1]]
        status += [tile(e) for e in odo[:1] + inside[:2]]
        sections.append(section(status))

        controls = [heading("Controls", "mdi:gesture-tap-button")]
        controls += [tile(e, [{"type": "lock-commands"}]) for e in locks[:2]]
        controls += [tile(e, [{"type": "climate-hvac-modes", "hvac_modes": ["heat_cool", "off"]},
                              {"type": "target-temperature"}]) for e in climate[:1]]
        controls += [tile(e, [{"type": "cover-open-close"}]) for e in covers]
        controls += [tile(e) for e in switches[:6]]
        controls += [tile(e, show_entity_picture=False) for e in buttons[:4]]
        if tires:
            controls.append({"type": "entities", "title": "Tire pressure", "entities": tires[:4]})
        sections.append(section(controls))

        # "Model Y Battery" -> "Battery": the heading already names the car.
        prefix = car_name.lower() + " "
        for card in status + controls:
            ent = card.get("entity")
            if ent and "name" not in card and inv.name(ent).lower().startswith(prefix):
                short = inv.name(ent)[len(prefix):]
                card["name"] = short[:1].upper() + short[1:]

        if trackers:
            sections.append(section([
                heading("Where is it", "mdi:map-marker"),
                full({"type": "map", "entities": trackers[:1] + inv.domain("zone")[:1],
                      "hours_to_show": 24, "default_zoom": 14, "aspect_ratio": "4:3"}),
            ]))
    return {"title": "Car", "path": "car", "icon": "mdi:car-electric", "type": "sections",
            "max_columns": 3, "sections": sections}


def view_rooms(inv: Inventory, floorplan: str | None) -> dict | None:
    if not inv.area_order() and not floorplan:
        return None
    sections = []
    if floorplan:
        lights = inv.domain("light")
        elements = []
        # Spread light icons across the plan so they are easy to drag into place in the editor.
        for i, e in enumerate(lights[:24]):
            elements.append({
                "type": "state-icon", "entity": e, "tap_action": {"action": "toggle"},
                "style": {"left": f"{10 + (i % 6) * 16}%", "top": f"{15 + (i // 6) * 20}%"},
            })
        sections.append(section([heading("Floor plan", "mdi:floor-plan"), full({
            "type": "picture-elements", "image": floorplan, "elements": elements})], column_span=2))

    cards = [heading("Rooms", "mdi:home-group")]
    for aid in inv.area_order():
        has_stuff = any(inv.area(e) == aid and inv.visible(e) for e in inv.states)
        if has_stuff:
            cards.append({"type": "area", "area": aid, "navigation_path": f"/{DASHBOARD_URL}/lights"})
    if len(cards) > 1:
        sections.append(section(cards, column_span=2))

    # Robot vacuum maps (Roborock, Ecovacs, Dreame, Valetudo... expose them as image/camera entities).
    maps = [e for e in inv.domain("image") + inv.domain("camera") if "map" in inv.name(e).lower()]
    vacs = inv.domain("vacuum")
    if maps or vacs:
        vc = [heading("Vacuum", "mdi:robot-vacuum")]
        vc += [tile(v, [{"type": "vacuum-commands",
                         "commands": ["start_pause", "stop", "return_home", "locate"]}]) for v in vacs]
        vc += [full({"type": "picture-entity", "entity": m, "show_state": False}) for m in maps]
        sections.append(section(vc))
    return {"title": "Rooms", "path": "rooms", "icon": "mdi:floor-plan", "type": "sections",
            "max_columns": 4, "sections": sections}


def view_security(inv: Inventory) -> dict | None:
    not_car = lambda es: [e for e in es if inv.platform(e) not in TESLA_PLATFORMS]
    climate = not_car(inv.domain("climate"))
    locks = not_car(inv.domain("lock"))
    covers = not_car(inv.domain("cover"))
    cams = [c for c in not_car(inv.domain("camera")) if "map" not in inv.name(c).lower()]
    alarms = inv.domain("alarm_control_panel")
    openings = [b for b in inv.domain("binary_sensor")
                if inv.attr(b, "device_class") in ("door", "window", "garage_door", "opening")]
    motion = [b for b in inv.domain("binary_sensor")
              if inv.attr(b, "device_class") in ("motion", "occupancy", "presence")]
    temps = [s for s in inv.domain("sensor") if inv.attr(s, "device_class") == "temperature"
             and inv.platform(s) not in TESLA_PLATFORMS and inv.area(s)]
    if not any([climate, locks, covers, cams, alarms, openings, motion, temps]):
        return None
    sections = []
    if climate or temps:
        c = [heading("Climate", "mdi:thermostat")]
        c += [full({"type": "thermostat", "entity": e}) for e in climate]
        c += [tile(e, name=inv.area_name(inv.area(e))) for e in temps[:12]]
        sections.append(section(c))
    if alarms or locks or covers:
        c = [heading("Security", "mdi:shield-home")]
        c += [tile(e, [{"type": "alarm-modes", "modes": ["armed_home", "armed_away", "disarmed"]}])
              for e in alarms]
        c += [tile(e) for e in locks]
        c += [tile(e, [{"type": "cover-open-close"}]) for e in covers]
        sections.append(section(c))
    if openings or motion:
        c = [heading("Doors, windows & motion", "mdi:door-open")]
        c += [tile(e) for e in openings + motion]
        sections.append(section(c))
    if cams:
        c = [heading("Cameras", "mdi:cctv")]
        c += [full({"type": "picture-entity", "entity": e, "camera_view": "auto"}) for e in cams]
        sections.append(section(c, column_span=2))
    return {"title": "Climate & Security", "path": "security", "icon": "mdi:shield-home",
            "type": "sections", "max_columns": 4, "sections": sections}


def build_config(inv: Inventory, floorplan: str | None) -> dict:
    views = [view_home(inv), view_lights(inv), view_media(inv), view_car(inv),
             view_rooms(inv, floorplan), view_security(inv)]
    return {"title": DASHBOARD_TITLE, "views": [v for v in views if v]}


# --------------------------------------------------------------------------- report

SUGGESTIONS = {
    "tesla": ("Tesla", "Add your car: Settings > Devices & services > Add integration > "
              "'Tesla Fleet' (official, free) or 'Tessie' / 'Teslemetry' (paid, simpler setup)."),
    "spotify": ("Spotify", "Add Spotify: Settings > Devices & services > Add integration > 'Spotify'. "
                "Needs Spotify Premium for playback control."),
    "tv": ("TV", "Add your TV: most TVs are auto-discovered (look under Settings > Devices & services > "
           "Discovered). Otherwise add 'Samsung Smart TV', 'LG webOS', 'Android TV Remote', 'Apple TV', "
           "'Roku' or 'Sony Bravia'."),
    "weather": ("Weather", "Add a weather source: 'Met.no' is free and needs no account."),
}


def report(inv: Inventory) -> str:
    lines = [f"# Home Hub report ({dt.datetime.now():%Y-%m-%d %H:%M})", ""]
    count = lambda d: len(inv.domain(d))
    lines.append("## Found in your Home Assistant")
    for label, n in [
        ("Areas / rooms", len(inv.area_order())), ("Lights", count("light")),
        ("Switches", count("switch")), ("Media players", count("media_player")),
        ("TVs", len(tv_players(inv))), ("Spotify players", len(spotify_players(inv))),
        ("Tesla vehicles", len(find_tesla(inv))), ("Thermostats", count("climate")),
        ("Locks", count("lock")), ("Cameras", count("camera")), ("Vacuums", count("vacuum")),
        ("People", count("person")),
    ]:
        lines.append(f"- {label}: {n}")
    if inv.excluded_areas:
        lines.append(f"- Left out (excluded areas): {', '.join(inv.area_name(a) for a in inv.excluded_areas)}")

    todo = []
    if not find_tesla(inv):
        todo.append(SUGGESTIONS["tesla"])
    if not spotify_players(inv):
        todo.append(SUGGESTIONS["spotify"])
    if not tv_players(inv):
        todo.append(SUGGESTIONS["tv"])
    if not inv.domain("weather"):
        todo.append(SUGGESTIONS["weather"])
    for tv in tv_players(inv):
        if inv.platform(tv) in REMOTE_PROFILES and not remote_pad(inv, tv):
            todo.append((inv.name(tv), "No remote entity found, so the D-pad was skipped. "
                         "For Android/Google TV add the 'Android TV Remote' integration."))
        elif inv.platform(tv) not in REMOTE_PROFILES:
            todo.append((inv.name(tv), f"Integration '{inv.platform(tv) or 'unknown'}' has no known D-pad commands; "
                         "power, volume, playback and inputs are still on the Media tab."))
    unassigned = [e for e in inv.domain("light") if not inv.area(e)]
    if unassigned:
        todo.append(("Rooms", f"{len(unassigned)} light(s) have no area, so they show under 'Other'. "
                     "Assign areas in Settings > Devices & services > Devices, then run install again."))
    lines += ["", "## Worth doing next"]
    lines += [f"- **{t}**: {s}" for t, s in todo] or ["- Nothing missing. Nice."]

    if inv.flows:
        lines += ["", "## Devices Home Assistant found on your network but are not set up yet",
                  "Add them under Settings > Devices & services > Discovered, then run install again."]
        for f in inv.flows:
            ctx = f.get("context", {})
            title = (ctx.get("title_placeholders") or {}).get("name") or f.get("handler")
            lines.append(f"- {title} ({f.get('handler')})")
    lines += ["", "## Integrations already set up", ", ".join(inv.integrations) or "(none listed)"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- install / restore

def install(ha: HomeAssistant, config: dict, show_in_sidebar: bool = True) -> None:
    dashboards = ha.call("lovelace/dashboards/list") or []
    if not any(d.get("url_path") == DASHBOARD_URL for d in dashboards):
        ha.call("lovelace/dashboards/create", url_path=DASHBOARD_URL, title=DASHBOARD_TITLE,
                icon="mdi:home-heart", show_in_sidebar=show_in_sidebar, require_admin=False,
                mode="storage")
        print(f"Created new dashboard '{DASHBOARD_TITLE}'")
    ha.call("lovelace/config/save", url_path=DASHBOARD_URL, config=config)
    print(f"Saved dashboard: open /{DASHBOARD_URL} in Home Assistant (it is also in the sidebar).")


def original_backup() -> Path:
    """The first backup ever taken = your setup before Home Hub was installed."""
    if not BACKUP_DIR.exists():
        sys.exit("No backups found.")
    folders = sorted(p for p in BACKUP_DIR.iterdir() if (p / "dashboards.json").exists())
    if not folders:
        sys.exit("No backups found.")
    return folders[0]


def restore(ha: HomeAssistant, folder: Path, keep_new: bool) -> None:
    saved = json.loads((folder / "dashboards.json").read_text())
    print(f"Restoring dashboards from {folder}")
    existing = {d.get("url_path"): d for d in ha.call("lovelace/dashboards/list") or []}
    saved_paths = {e["url_path"] for e in saved}
    for entry in saved:
        url_path, status = entry["url_path"], entry["status"]
        name = url_path or "_default"
        kwargs = {"url_path": url_path} if url_path else {}
        if url_path and url_path not in existing and status in ("saved", "auto_generated"):
            meta = entry["meta"]
            ha.call("lovelace/dashboards/create", url_path=url_path, title=meta.get("title", url_path),
                    icon=meta.get("icon"), show_in_sidebar=meta.get("show_in_sidebar", True),
                    require_admin=meta.get("require_admin", False), mode="storage")
        if status == "saved":
            cfg = json.loads((folder / f"dashboard_{name}.json").read_text())
            ha.call("lovelace/config/save", config=cfg, **kwargs)
            print(f"  restored {name}")
        elif status == "auto_generated":
            ha.try_call("lovelace/config/delete", **kwargs)
            print(f"  {name}: back to automatic")
        else:
            print(f"  {name}: left alone ({status})")
    if not keep_new:
        for url_path, d in existing.items():
            if url_path not in saved_paths and url_path == DASHBOARD_URL:
                ha.call("lovelace/dashboards/delete", dashboard_id=d["id"])
                print(f"  removed {DASHBOARD_TITLE}")
    print("Done. Refresh your browser.")


# --------------------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["install", "backup", "preview", "restore", "report"])
    p.add_argument("--exclude-area", action="append", default=[],
                   help="Area name or id to leave off the dashboard (repeatable), e.g. 'Office'")
    p.add_argument("--floorplan", help="Floor plan image, e.g. /local/floorplan.png "
                   "(put the file in your HA config/www folder)")
    p.add_argument("--no-full-backup", action="store_true",
                   help="Skip asking HA for a full system backup")
    p.add_argument("--from", dest="from_folder", help="Backup folder to restore (default: the first/original backup)")
    p.add_argument("--keep-new", action="store_true", help="On restore, keep the Home Hub dashboard")
    args = p.parse_args()

    ha = connect()
    try:
        if args.command == "backup":
            backup(ha, not args.no_full_backup)
            return
        if args.command == "restore":
            folder = Path(args.from_folder) if args.from_folder else original_backup()
            restore(ha, folder, args.keep_new)
            return

        inv = Inventory(ha, args.exclude_area)
        OUT_DIR.mkdir(exist_ok=True)
        rep = report(inv)
        (OUT_DIR / "report.md").write_text(rep)
        config = build_config(inv, args.floorplan)
        (OUT_DIR / "home-hub-dashboard.json").write_text(json.dumps(config, indent=2))
        if args.command == "report":
            print(rep)
            return
        print(f"Built {len(config['views'])} views: {', '.join(v['title'] for v in config['views'])}")
        print(f"Wrote {OUT_DIR / 'home-hub-dashboard.json'} and {OUT_DIR / 'report.md'}")
        if args.command == "install":
            backup(ha, not args.no_full_backup)
            install(ha, config)
            print("\n" + rep)
            print("To undo everything: python3 ha_dashboard.py restore")
    finally:
        ha.close()


if __name__ == "__main__":
    main()
