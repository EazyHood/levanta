# How to film a house so the plan comes out right

*(Versión en español: [guia-de-captura.md](guia-de-captura.md))*

levanta rebuilds what the camera **saw**. Nothing more, nothing invented. So the whole
game is coverage: every wall, floor to ceiling, from inside the room, plus a look
through every door. Ten minutes of care here save an hour of wondering why a wall is
missing.

## Before you start

- **Doors open, closets closed.** An open closet door or a wardrobe looks like a wall.
- **Lights on, curtains open.** Blur and darkness are the enemy; the network needs texture.
- **Clear the floor edges** if you can. The planner finds rooms by the floor it can see.
- Phone in **landscape**, 1080p or better, normal lens (no ultra-wide, no zoom).
- Wipe the lens.

## The walk

1. Stand in the middle of the room. **Turn slowly** (a full turn in about 20 seconds),
   keeping the phone level, so every wall passes through the frame.
2. **Tilt up and down** once per wall: the junction with the ceiling and the skirting
   board with the floor are what tell a wall from a wardrobe.
3. Walk to each **corner** and film the two walls that meet there from about 1.5 m.
4. Stand in every **doorway** and film into the next room, then step through. The
   planner marks a gap as a door only if it saw through it.
5. Windows: film them from inside, including the wall under and above them.
6. Repeat for every room. Pace yourself: **30–60 seconds per room**, never a quick pan.

## What not to do

- Don't run, don't swing the phone, don't walk while turning fast: motion blur.
- Don't film mirrors, TV screens or glass walls as if they were walls; they return
  nothing usable. levanta will show that side as "not scanned" instead of inventing it.
- Don't switch lenses or zoom mid-video; the focal length must stay constant.
- Don't stop and restart recording; one continuous clip per floor.
- Don't hand over an edited video: title cards, fades and cuts are skipped (text on black
  looks *sharper* than any room to a computer) but every cut breaks the overlap between
  consecutive frames that the reconstruction depends on. The raw clip is always better.

## What the benchmark taught

Measured on five ARKitScenes rooms (real iPhone walks with a LiDAR floor as truth,
[numbers here](../bench/results/arkitscenes_2026-09-05.md)):

- **Measure one door. Nothing else fixes the scale.** The network's scale was within 5 %
  on three rooms, 30 % short on one and 4× off on a small bathroom; giving it the exact
  focal length changed the result by at most 7 %, and not towards the truth. Until you
  pass `--door-width`, every sheet is stamped PRELIMINARY on purpose.
- **Film the floor where it meets the wall, along every wall.** Room areas came out
  22–44 % below the LiDAR floor even at the right scale: the outline follows the floor
  the camera saw, and those scans looked at objects, not at the skirting. Walk the
  perimeter with the phone pointing at the wall–floor edge, not only at the middle.
- **Small rooms are the worst case, mirrors and tiles the reason.** Two bathrooms of
  4–5 m² came out 31 % and 78 % too big; in one the network kept 56 k points for 57 frames,
  found one wall and its scale fell to 0.26. levanta now notices (a chunk scaled by less
  than 0.5 or more than 2 to meet the previous one, or under 15 % of a frame kept) and
  stamps the sheet *NOT RECONSTRUCTIBLE · mirror or glass* instead of drawing a room.
  Stand in the doorway, keep 1.5 m from what you film, include the door frame and the
  floor, and measure that room by hand.
- **Keep one room to one or two minutes.** The camera track drifted 0.4–0.9 m over one
  to three minute walks; there is no loop closure yet, so a long wander degrades the
  plan more than a second, shorter clip would.
- Doors are found where the camera looked through them: in the benchmark rooms the
  doors were closed and levanta found one in five. Open the doors before you film.

## Check before spending GPU time

```bash
levanta check walk.mp4
```

It reports length, resolution, sharpness and how many usable frames there are, with
warnings you can act on. Then:

```bash
levanta video walk.mp4 -o out/house --lang en --names "Living,Kitchen,Bedroom,Bath"
```

## Scale

From plain video the size can come out 5–15 % small (see the README's measurements).
Two fixes, best first:

- `--focal-px 1500` (or whatever your phone's focal length in pixels is at the frame
  size levanta uses; 1080p phones are typically 1400–1700 px). It lets the network
  solve the geometry with the focal length fixed.
- `--door-width 0.90` rescales the plan so the median detected door is 0.90 m wide.
  Measure one of your doors with a tape and pass its width.

Both can be applied later with `levanta render plan.json --door-width 0.85`, no need to
reconstruct again.
