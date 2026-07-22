# Hoops look mechanics

Hoops is a compact pixel-art chibi basketball player: a rounded orange basketball body in a black uniform, white sneakers, shaggy pale-gray hair, round glasses, and a basketball held at screen-left. The feet and lower torso remain anchored on the same baseline throughout the look loop.

The large round glasses and eyes lead each gaze. The eyes redraw within the existing glasses as physical eye/glasses units rather than adding new eye designs; pupils, lids, and the visible white eye surface turn together. The hair fringe follows the head with a very small one-pixel-style shift. The torso and basketball remain nearly stable, with a restrained upper-body lean in the gaze direction. The held basketball stays attached at screen-left and may lag by a tiny amount with the upper body; it never floats, swaps sides, or rotates independently.

Cardinal pose families in viewer coordinates:

- **000 up:** chin and face subtly lift; the eyes look toward the top rim of the glasses, with a slight upward hair lift. The basketball and feet stay anchored.
- **090 screen-right:** head/face and glasses turn toward the viewer's right; right-side face contour becomes slightly more visible, pupils/nose shift right of head center, and the basketball remains attached at screen-left with a tiny lag.
- **180 down:** chin dips, eyelids lower, and pupils point down inside the glasses; hair fringe settles slightly forward. The pose does not become neutral.
- **270 screen-left:** head/face and glasses turn toward the viewer's left; left-side face contour and the screen-left basketball contact become more prominent, pupils/nose shift left of head center.

Motion budget: each 22.5-degree step makes a comparable small head/eye/upper-body change. The loop moves clockwise in this order without whole-sprite rotation, affine skew, scale jumps, or prop detachment. Diagonals interpolate these cardinal families smoothly.
