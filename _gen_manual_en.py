# -*- coding: utf-8 -*-
r"""LAMPOCHKA - User Guide (EN). Generator on the family template (_docstyle.py).
Run:  python _gen_manual_en.py    Output:  docs\LAMPOCHKA_Manual_EN.docx
"""

import json

import _docstyle as ds

OUT = r'D:\AI\ZCode\Project\LAMPOCHKA\work\docs\LAMPOCHKA_Manual_EN.docx'


def h1(doc, text):
    return ds.h1(doc, text)


def h2(doc, text):
    return ds.h2(doc, text)


def p(doc, text, bullet=False, italic=False, grey=False):
    return ds.p(doc, text, bullet=bullet, italic=italic, grey=grey)


def kv_note(doc, text):
    return ds.kv(doc, text)


def add_table(doc, rows, widths, sev_col=None):
    return ds.add_table(doc, rows, widths, sev_col=sev_col)


def _save(doc, out):
    ds.footer(doc.sections[1], 'LAMPOCHKA')
    ds.strip_tail(doc)
    doc.save(out)
    h1s = [t for t in ds.H1_REGISTRY if t.lower() not in ('table of contents', 'contents')]
    json.dump(h1s, open(out.replace('.docx', '.h1.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    print('saved:', out)


doc = ds.new_doc('LAMPOCHKA', 'User Guide', 'V3.4.7  -  BLENDER 4.2+')

p(doc, 'LAMPOCHKA brings the management of every light source in the scene into one panel: '
       'a list of lights with settings right in the row, HDRI / IES / gobo browsers, light '
       'rig presets, a sun helper driven by time and place, and interactive placement across '
       'surfaces. Instead of hunting lights in the outliner and walking through properties - '
       'one screen where all the light is visible and editable at once.')

kv_note(doc, 'github.com/abyrvalg379/LAMPOCHKA')

h1(doc, 'Contents')
ds.toc_field(doc, 'Table of contents: open the document in Word/LibreOffice and refresh '
                  'the field (F9) to fill in page numbers.')

h1(doc, '1. About LAMPOCHKA')

h2(doc, '1.1 What LAMPOCHKA does')
p(doc, 'Key features:', bullet=False)
for b in (
    'a list of all scene lights with inline settings: color, power, shadows, per-type '
    'parameters, transforms;',
    'Kelvin temperature with one slider (1500-12000 K) while the original color is preserved;',
    'an HDRI browser with a preview carousel, rotation and Hide from Camera;',
    'an IES profile browser with Power and Mix handles;',
    'gobo projections: a texture pattern from a spot or area light with per-light handles;',
    'light rig presets: blend packages with a carousel, master intensity, rotation and flip;',
    'a sun helper: aiming by time, date and location (NOAA algorithm);',
    'interactive placement: the light slides behind the cursor across scene surfaces;',
    'Light and Shadow Linking: assigning receivers and blockers by clicking the viewport;',
    'group operations: Solo, Cycle Select and Batch mode for editing several lights at once.',
):
    p(doc, b, bullet=True)

h2(doc, '1.2 Philosophy')
p(doc, 'Three principles hold the panel together. One screen: any action on light, from a '
       'color change to a full rig swap, happens without leaving the N-panel. Instant '
       'application: browsers apply the environment as you browse, no apply button, and the '
       'light settings live in the same list row. Care: the addon never destroys foreign '
       'node trees (HDRI, IES and gobo embed into the existing world or light tree), is '
       'friendly to Ctrl+Z, and never hijacks viewport navigation without an explicit switch.')

h2(doc, '1.3 What the panel is made of')
add_table(doc, [
    ('Block', 'Where', 'What it does'),
    ('Header', 'top of the panel', 'adding lights, light-on-surface, Cycle Select, Batch '
     'mode, global viewport/render toggles'),
    ('Light list', 'center', 'light rows: selection, Solo, viewport/render visibility, '
     'deletion, the interactive placement button'),
    ('Inline settings', 'the gear in the row', 'full light parameters: color, Kelvin, '
     'shadows, per-type settings, nodes, linking, transforms'),
    ('HDRI', 'sub-panel', 'environment browser: carousel, rotation, strength, Hide from Camera'),
    ('Sun', 'sub-panel', 'sun aiming by time, date and location, day presets'),
    ('IES', 'sub-panel', 'IES profile browser for Point and Spot lights'),
    ('Presets', 'sub-panel', 'light rigs: packages, carousel, master intensity, rotation, '
     'flip, favorites'),
    ('Gobo', 'sub-panel', 'texture projection from the active light with per-light handles'),
], [4.2, 3.2, 9.6])

h1(doc, '2. Installation')
for b in (
    'Download the zip of the latest release: github.com/abyrvalg379/LAMPOCHKA - Releases - '
    'Latest - the lampochka_extension.zip asset.',
    'Blender - Edit - Preferences - Get Extensions - the corner menu - Install from Disk - '
    'pick the zip. Drag-and-drop installation works as well.',
    'Make sure the LAMPOCHKA extension is enabled (the checkbox).',
    'The panel appears in the 3D viewport N-panel (N key) - LAMPOCHKA tab. The version is '
    'printed right in the panel header.',
    'Updating: download the new zip and install it the same way, on top of the old version. '
    'Settings and library folders survive.',
):
    p(doc, b, bullet=True)
p(doc, 'After installation open Preferences - Add-ons (or Get Extensions) - LAMPOCHKA: that '
       'is where the default folders for HDRI, IES, gobo and presets live, along with the '
       'list of installed preset packages. You can also set the folders later, right from '
       'the panel.')

h1(doc, '3. Quick start')
p(doc, 'Six steps to place a light and get the first frame:')
for b in (
    'Open the N-panel (N) - the LAMPOCHKA tab. In the list header press Add and pick a type: '
    'Point, Sun, Spot or Area.',
    'The FACESEL button next to Add is light-on-surface: the light is created under the '
    'cursor and slides across surfaces, oriented by the normals. LMB or Enter places it, '
    'RMB or Esc cancels.',
    'Click a light name - it is selected in the viewport. The gear in the row opens the '
    'settings: color, power, shadows. For household light switch on Kelvin and set a '
    'temperature instead of eyeballing the color.',
    'Unfold the HDRI sub-panel, point at a folder with .exr/.hdr and browse the carousel '
    'with the arrows - every environment applies instantly. Rotation: the Rotate: Shift+RMB '
    'toggle, then drag Shift + RMB.',
    'Nail the position with the cursor button in the light row (interactive placement): the '
    'light follows the cursor, Alt pins it to a surface, the wheel changes power.',
    'Render. Save the rig for later - the Presets sub-panel, Save Setup.',
):
    p(doc, b, bullet=True)

h1(doc, '4. The light list')

h2(doc, '4.1 A light row')
p(doc, 'Every scene light is a row: a type icon (Point / Sun / Spot / Area), the name, and '
       'service buttons on the right. The list has a fixed height of eight rows with a '
       'scrollbar - the panel never jumps, no matter how many lights there are. A name '
       'filter above the list cuts the noise.')
add_table(doc, [
    ('Element', 'Action'),
    ('a click on the name', 'select the light in the viewport (and the other way: a viewport '
     'selection highlights the row)'),
    ('the gear', 'open the inline light settings (section 5)'),
    ('SOLO', 'isolate the light: everything else hides in the viewport and render until the '
     'solo is lifted or moved to another light'),
    ('the eye', 'viewport visibility of the light'),
    ('the camera', 'render visibility of the light'),
    ('the bin', 'delete the light right from the row (Ctrl+Z friendly)'),
    ('the cursor button', 'the master switch of interactive placement (section 6.3)'),
], [4.4, 12.6])

h2(doc, '4.2 The list header')
for b in (
    'Add - the add-light menu: Point, Sun, Spot, Area.',
    'FACESEL - light-on-surface: a light under the cursor, sliding along normals.',
    'the arrows - Cycle Select: stepping through the scene lights without scrolling the list.',
    'the Batch checkbox - group editing (section 4.5).',
    'global toggles - viewport and render visibility of every light in one press.',
):
    p(doc, b, bullet=True)

h2(doc, '4.3 Solo Light')
p(doc, 'The SOLO button in a row isolates one light: all the others hide in the viewport and '
       'render. Pressing it again lifts the solo; pressing SOLO on another row moves the '
       'isolation there. This is the main debugging tool: "what does this exact light do to '
       'the frame" is one click away, no manual disabling of a dozen objects.')

h2(doc, '4.4 Cycle Select')
p(doc, 'The arrows in the header step through the scene lights in a circle, highlighting the '
       'active one in the panel and the viewport. Handy on dense frames: walk every light in '
       'order and judge its contribution without touching the mouse or the list.')

h2(doc, '4.5 Batch mode')
p(doc, 'The Batch checkbox in the header switches the list into group editing: clicks on '
       'names collect a group of lights, after which a master power slider works on the '
       'whole group, plus Show/Hide for the group and releasing the group. The typical case: '
       'raise or kill an entire practical group without touching the key light.')

h2(doc, '4.6 Viewport synchronization')
p(doc, 'Selection is synchronized both ways: pick a light in the viewport - the panel '
       'highlights the row and scrolls to it; pick a row - the light is selected in the '
       'viewport. The panel also remembers the state of the settings: an unfolded gear block '
       'stays unfolded for the next selected light, a folded one stays folded.')

h1(doc, '5. Light settings (the gear)')

h2(doc, '5.1 Basic parameters')
p(doc, 'The gear block holds everything that normally lives in object properties and light '
       'data: type, color, power, shadows and shadow size. The parameters follow the light '
       'type:')
add_table(doc, [
    ('Type', 'Panel parameters'),
    ('Point', 'radius - softness of the point light shadow'),
    ('Sun', 'angle - the size of the sun disc, hardness of the shadow edge'),
    ('Spot', 'cone size, blend (edge softness), cone display in the viewport'),
    ('Area', 'shape and X/Y size - square, rectangle, disc, ellipse'),
], [3.6, 13.4])

h2(doc, '5.2 Kelvin temperature')
p(doc, 'The Kelvin toggle drives the light color from black-body temperature: the '
       '1500-12000 K slider covers everything from a match flame to a clear sky. The '
       'original light color is remembered and restored when the toggle goes off - '
       'temperature experiments break nothing.')
p(doc, 'If the light already carries a node tree (an IES profile from section 9, for '
       'example), the temperature is driven through a Blackbody node embedded into the '
       'existing chain. Works in Cycles and EEVEE.')

h2(doc, '5.3 Cycles, contact shadows and volume')
p(doc, 'For Cycles the gear offers the light nodes and emission strength. Contact shadows '
       '(distance, bias, thickness) and the volume contribution (volume factor) sit in their '
       'own block - the settings that are buried deepest in the stock UI.')

h2(doc, '5.4 Transforms')
p(doc, 'Location, rotation and scale of the light live in a block collapsed by default: the '
       'position is normally edited by interactive placement (section 6.3), not by numbers.')

h2(doc, '5.5 Light and Shadow Linking')
p(doc, 'The gear block offers Light Linking: Pick and Shadow Linking: Pick. After pressing, '
       'click objects in the viewport: that is how receivers and shadow blockers are '
       'assigned - without digging through outliner collections. Enter accepts, RMB or Esc '
       'rolls back to the state before the linking session. The Clear Receivers and Clear '
       'Blockers buttons clean the light assignments.')

h1(doc, '6. Adding and placing lights')

h2(doc, '6.1 The Add menu')
p(doc, 'Add in the header creates a light of the chosen type in the scene. A light you just '
       'created appears in the list at once - no hunting for it in the outliner.')

h2(doc, '6.2 Light on surface (FACESEL)')
p(doc, 'The FACESEL menu next to Add is the fast way to put a light exactly on an object: '
       'the light is created under the mouse cursor and slides across the scene surfaces, '
       'oriented by the normals. LMB or Enter places it, RMB or Esc cancels. Perfect for '
       'practicals: a floor lamp, a desk lamp and a wall fixture are one gesture each.')

h2(doc, '6.3 Interactive placement (Placement Mode)')
p(doc, 'The cursor button in a light row is the master switch of the mode. Manual only: the '
       'button state resets on file load, so the mode never activates unexpectedly.')
for b in (
    'ON - the light moves freely behind the cursor (unconstrained), viewport navigation keeps '
    'working.',
    'Alt (held) - the light snaps to the surface under the cursor.',
    'G - works as the placement operator while the button is on: applies the current pass, '
    'pressing again places it again; with the button off, G is the native Grab.',
    'LMB / Enter - apply the current pass, RMB / Esc - roll the pass back to the start point.',
    'OFF - everything returns to normal, nothing works.',
):
    p(doc, b, bullet=True)
p(doc, 'The mouse wheel edits the light without leaving the placement:')
add_table(doc, [
    ('Gesture', 'Result'),
    ('wheel', 'light power'),
    ('Shift + wheel', 'light size'),
    ('Ctrl + wheel', 'depth of the movement plane (closer/further along the view)'),
], [5.0, 12.0])

h1(doc, '7. The HDRI browser')

h2(doc, '7.1 Folder and previews')
p(doc, 'Unfold the HDRI sub-panel and point at a folder - every .exr and .hdr in it appears '
       'as previews. The last folder is remembered in the addon settings and substituted in '
       'every new project; a separate .blend can override it with its own folder.')

h2(doc, '7.2 The carousel')
p(doc, 'A compact row of three cards - previous, active, next - with large previews. The '
       'prev/next arrows flip through the folder, every switch applies the HDRI instantly, '
       'no Apply button. A click on a neighboring card jumps to it.')

h2(doc, '7.3 Apply and Clear')
p(doc, 'Applying builds the world node chain (TexCoord - Mapping - Environment - '
       'Background). If the world already has an environment - only the image is swapped, '
       'the nodes are not destroyed. Clear HDRI tears the HDRI chain down and leaves a '
       'pitch-black Background with zero strength: a scene without environment light. The '
       'rotation resets and the panel Strength returns to its default 1 - the next HDRI '
       'applies at full power.')

h2(doc, '7.4 Hide from Camera')
p(doc, 'The camera sees a flat color (black by default) while the lighting and reflections '
       'keep coming from the HDRI. The case for a clean plate: rendering on an empty set '
       'with real lighting.')

h2(doc, '7.5 Rotation and strength')
p(doc, 'Rotation spins the environment: Z for a turntable spin, X and Y for tilts. Strength '
       'is the environment intensity, updating live; both handles keep working on the node '
       'chain after another HDRI is applied.')
p(doc, 'For mouse rotation enable the Rotate: Shift+RMB toggle - dragging Shift + RMB in '
       'the viewport spins the HDRI around Z, Ctrl+Z undoes the whole drag. The toggle is '
       'always off in a fresh session: it resets on every file load, so it never hijacks '
       'navigation unexpectedly.')

h2(doc, '7.6 Automatic folder repair')
p(doc, 'If a saved folder vanished from disk (a library was moved or deleted), it repairs '
       'itself on file load: first from the addon settings, then from the built-in library. '
       'The same repair triggers when the folder is edited in the settings. An unrepairable '
       'path is shown honestly - "Folder not found: ..." - instead of a misleading empty '
       'list. The mechanism is shared by all browsers: HDRI, IES, Gobo and Presets.')

h1(doc, '8. The Sun')
p(doc, 'The Sun sub-panel aims any scene sun by real astronomy: set the time, date, '
       'latitude, longitude, UTC offset and north direction - the panel turns the Sun light '
       'to where the sun stands at that moment in that place. Distance controls the light '
       'offset.')
p(doc, 'Day presets:', bullet=False)
for b in (
    'Noon - midday;',
    'Golden Hour - the hour before sunset, low warm sun;',
    'Sunset - the sunset itself.',
):
    p(doc, b, bullet=True)
p(doc, 'The panel reports the computed sun altitude and azimuth, sunrise and sunset times. '
       'The position is computed with the NOAA algorithm (public domain).')
p(doc, 'A day animation: set a keyframe on the Time parameter - and the sun follows every '
       'frame, from sunrise to sunset, pausing for renders and bakes.')

h1(doc, '9. The IES browser')
p(doc, 'The IES sub-panel works with light distribution profiles - .ies files describing '
       'real fixtures: spotlights, wall lamps, street lanterns. Point at a folder - the '
       'profiles appear as a grid; thumbnails are picked up from a thumbnails subfolder '
       'next to them, <name>.jpg for <name>.ies.')
for b in (
    'Apply IES builds an IES setup on the active Point or Spot light: the chain IES - '
    'Emission - Output.',
    'If the light already carries a LAMPOCHKA IES setup - only the file is swapped; if it '
    'has a plain Emission chain - the IES node is embedded without destroying nodes.',
    'Power - a multiplier of the profile brightness; Mix - how much the profile shapes the '
    'light against an even distribution (0-100%).',
    'Remove IES takes the IES node off the active light.',
    'IES profiles work in Cycles only - the panel warns on other engines.',
    'The last folder is remembered, like in the HDRI browser.',
):
    p(doc, b, bullet=True)

h1(doc, '10. Gobo projections')
p(doc, 'The Gobo sub-panel projects a texture from the active light: a pattern of blinds, '
       'foliage, a window frame drawn over the base light. Point at a folder of textures - '
       'they appear as a preview grid, Apply applies the picked one.')
add_table(doc, [
    ('Active light', 'What happens'),
    ('Spot', 'the classic cone projection'),
    ('Area', 'a flat projection - a "softbox with a pattern"'),
    ('Point', 'converted to a spot automatically on Apply'),
    ('Sun', 'a gobo is impossible - the sun has no position to project from'),
], [5.4, 11.6])
p(doc, 'The gobo is built on the active light carefully: with no nodes a clean chain is '
       'created (TexCoord - Mapping - Image - Emission - Output); with an existing Emission '
       'chain the gobo is woven in by multiplication, destroying nothing.')
p(doc, 'The projection handles are stored per light, so gobos are independent:')
for b in (
    'Rotation - the pattern rotation;',
    'Scale X / Scale Y - stretching into blinds or stripes;',
    'Offset X / Offset Y - the pattern shift;',
    'Mix - the share of the gobo in the light: an accent over the base light, 0-100%;',
    'Invert and Flip X - pattern inversion and mirroring.',
):
    p(doc, b, bullet=True)
p(doc, 'Remove Gobo takes the gobo nodes off and restores the previous color source. Light '
       'rig presets keep the gobo texture and the node chain (the per-light handles reset to '
       'defaults when a preset is applied). The last folder is remembered, like for HDRI and '
       'IES.')

h1(doc, '11. Light rig presets')

h2(doc, '11.1 How packages work')
p(doc, 'Rigs live as blend packages and are applied by appending the setup collection: '
       'empty hierarchies, node trees and world transforms arrive exactly as authored. '
       'Point at a preset folder - every collection of every .blend inside (recursively) '
       'appears in the carousel as a rig; previews come from thumbs/<name>.png or '
       'thumbnails/<name>.png next to the package.')

h2(doc, '11.2 Install from Zip')
p(doc, 'The button installs one or several preset packages from zip archives: every zip '
       'becomes a subfolder of the preset folder. A PLS-compatible structure '
       '(library/*.blend + library/thumbs/) is unpacked automatically.')

h2(doc, '11.3 The carousel and instant application')
p(doc, 'The preset carousel is built like the HDRI one: previous / active / next cards, '
       'prev-next arrows, a click on a neighboring card jumps to it. Switching presets '
       'applies them instantly, no separate button; the catalog is looped. Apply re-applies '
       'the picked rig on demand.')

h2(doc, '11.4 Save Setup')
p(doc, 'The button records the scene lights (together with parent empties and rig '
       'subtrees) as a .blend rig into the preset folder. Give the lights meaningful names - '
       'Key, Rim, Fill: the rig then reads as a lighting scheme, not a junk drawer.')

h2(doc, '11.5 The application handles')
for b in (
    'Master intensity - one slider scales the energy of every light of the applied rig '
    'relative to the authored values; repeated applications never accumulate.',
    'Root rotation around Z - rotating the applied rig around its parent empty on the world '
    'Z axis; returning the slider to zero restores the authored orientation.',
    'Flip Preset - Flip X / Flip Y mirror the rig across the root axes; a double flip '
    'returns it as it was.',
):
    p(doc, b, bullet=True)

h2(doc, '11.6 Favorites')
p(doc, 'A heart next to a rig name marks it as a favorite; the heart switch in the panel '
       'header turns the carousel into favorites-only mode. The marks live in the settings '
       'and survive a library move.')

h2(doc, '11.7 Deletion')
for b in (
    'Clear Lights - removes every object that came from LAMPOCHKA presets.',
    'Preferences - Installed Preset Packages - the list of installed packages with a blend '
    'counter and a delete button each, plus Remove All Packages with a confirmation. Package '
    'deletion lives in Preferences only - too dangerous for the sidebar.',
    'Unresolved textures (a package installed without its textures/ folder) are reported '
    'honestly on application, never silently skipped.',
):
    p(doc, b, bullet=True)

h1(doc, '12. Workflows')

h2(doc, '12.1 A quick backdrop: HDRI in thirty seconds')
p(doc, 'Opened a scene without light - panel - HDRI - folder - a couple of arrow presses to '
       'a pleasing environment. Rotate it with Shift + RMB to turn the interesting part of '
       'the sky into the frame. If the backdrop is not wanted in the render - Hide from '
       'Camera, and the object stands on a clean plate lit by the real environment.')

h2(doc, '12.2 A rig from a preset')
p(doc, 'A three-point preset lands with one carousel click. Then the application handles: '
       'intensity to the scene exposure, Z rotation to the camera angle, Flip when the light '
       'falls from the wrong side. Save the schemes you like with Save Setup under Key / '
       'Rim / Fill names - a month later the rig still reads without decoding.')

h2(doc, '12.3 Accents and atmosphere')
p(doc, 'A practical outside the window: FACESEL puts a Spot exactly on the cornice, a gobo '
       'with a Y-stretched pattern makes blinds, Mix at 30-50% keeps the accent delicate. '
       'For interiors take a real fixture IES profile - the light gets the correct '
       'distribution without eyeballing the cone.')

h2(doc, '12.4 Working habits')
for b in (
    'Kelvin instead of eyeballing color: 3200 K - a warm lamp, 5600 K - daylight. The color '
    'is remembered as a number, not a pipette hunt.',
    'Solo while debugging: one light, one question to the frame. Lift the solo - the whole '
    'rig is back.',
    'Batch for global decisions: the entire practical group goes down with one slider, not '
    'a dozen clicks.',
    'Light Linking - light the hero selectively without touching the background; Shadow '
    'Linking - keep an awning shadow only where it belongs.',
    'A sun animation through a keyframe on Time - a day timelapse with zero rotation keys '
    'on the light.',
):
    p(doc, b, bullet=True)

h1(doc, '13. Troubleshooting')
add_table(doc, [
    ('Symptom', 'Cause', 'What to do'),
    ('A browser shows "Folder not found: ..."', 'the saved folder vanished from disk',
     'pick the folder again; on file load the repair from the addon settings runs by itself'),
    ('IES applied but no effect', 'IES works in Cycles only',
     'switch the render engine to Cycles'),
    ('Apply Gobo does nothing on a Sun', 'the sun has no position to project from',
     'use a Spot or Area; a Point is converted to a spot by Apply itself'),
    ('The Shift + RMB drag does not rotate the HDRI', 'the Rotate: Shift+RMB toggle is off '
     '(it resets on every file load)', 'enable the toggle in the HDRI section'),
    ('The light stopped following the cursor', 'the placement mode resets on file load',
     'enable the cursor button in the light row again'),
    ('The next HDRI looks "dim"', 'after Clear HDRI the world strength returns to default',
     'raise the Strength for the new environment'),
    ('Presets vanished after a library move', 'the old path is off disk, the auto-repair '
     'found no replacement', 'pick the folder again or repair it in Preferences - Installed '
     'Preset Packages'),
    ('The preset intensity slider "accumulated"', 'there is no accumulation by design: the '
     'scale is always computed from the authored values', 'return the slider to zero - the '
     'authored light power comes back'),
], [5.2, 5.6, 6.2])

_save(doc, OUT)
