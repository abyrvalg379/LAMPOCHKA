# LAMPOCHKA v2.0

Blender addon for managing all lights in the scene from a single panel.

Instead of searching for lights in the Outliner or switching between objects, you get a dedicated panel with instant access to every light's settings — color, power, shadow, type-specific parameters, and transforms.

## Features

### Light List
- All scene lights displayed with type icons (Point / Sun / Spot / Area)
- Filter by name
- Click to select in viewport
- Gear icon (⚙) opens inline settings

### Visibility Controls
- 👁 — toggle viewport visibility per light
- 📷 — toggle render visibility per light
- Global toggle all visibility / render from header

### Inline Settings (via ⚙)
- Light type, color, power
- Shadow toggle + shadow size
- **Point** — radius
- **Sun** — angle
- **Spot** — size, blend, show cone
- **Area** — shape, size X/Y
- **Cycles** — use nodes, emission strength
- Contact shadow (distance, bias, thickness)
- Volume factor
- Transform (collapsed by default): location, rotation, scale

### Light Management
- Add light (Point / Sun / Spot / Area) from header menu
- Duplicate / Delete buttons in settings
- Move up / down in list

### Viewport Sync
- Selecting a light in the viewport automatically highlights it in the panel
- Selecting a light in the panel selects it in the viewport
- Settings state transfers when switching between lights:
  - If settings were open → they open for the new light
  - If settings were closed → they stay closed

## Installation

### Ready-to-use archives
- `lampochka_legacy.zip` — for Blender 3.6+
- `lampochka_extension.zip` — for Blender 4.2+

### Legacy (Blender 3.6+)
1. `Edit → Preferences → Add-ons → Install`
2. Select `lampochka_legacy.zip`
3. Enable "LAMPOCHKA"

### Extension (Blender 4.2+)
1. `Edit → Preferences → Get Extensions`
2. ⚙ → `Install from Disk...`
3. Select `lampochka_extension.zip`

## Usage

`View3D → Sidebar (N) → LAMPOCHKA`

## Project Structure

```
LAMPOCHKA/
├── README.md
├── lampochka_legacy.zip
├── lampochka_extension.zip
├── legacy/
│   └── lampochka/
│       └── __init__.py
└── extension/
    ├── __init__.py
    └── blender_manifest.toml
```

## Requirements

Blender 3.6+ (legacy) or 4.2+ (extension)

## Author

Maksim Kovalev


---

## 🔗 Related Tools

| Tool | Description |
|------|-------------|
| [STUKACH](https://github.com/abyrvalg379/STUKACH) | Pipeline asset validator for Blender |
| [LAMPOCHKA](https://github.com/abyrvalg379/LAMPOCHKA) | Scene light manager |
| [Switch_UDIM](https://github.com/abyrvalg379/Switch_UDIM) | Single ↔ UDIM texture switcher |
| [FLOMASTER](https://github.com/abyrvalg379/FLOMASTER) | OCIO launcher for DCC apps |
| [FILTER](https://github.com/abyrvalg379/FILTER) | Toggle visibility/selection by type, name, collection |
