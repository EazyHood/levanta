# Eight real rooms instead of two: the protocol, written before anything is downloaded

Everything said today "on a real floor" rests on two ARKitScenes rooms with video, 41069021 and
42897526. The threshold of floor IoU 0.60 used all afternoon is 0.65 of one of them minus 0.05.
This turns "0.65 in one room" into a distribution.

## The scenes, chosen before any result

Six more from the ARKitScenes validation fold, under a 6 GB cap, sizes read from the official
server's headers without downloading (`https://docs-assets.developer.apple.com/ml-research/datasets/arkitscenes/v1/raw/Validation/`):

| scene | walk | video | also needed | why it is in |
|---|---|---|---|---|
| 45260905 | 77 s | 686 MB | mesh, trajectory on disk | round 4 bench room, its video deleted in today's cleanup |
| 47331964 | 127 s | 1 116 MB | on disk | round 4, two rooms |
| 47430051 | 61 s | 541 MB | on disk | round 4, the mirror bathroom levanta flags |
| 42897599 | 300 s | 2 641 MB | mesh 92 MB | the longest walk in the fold's bench, 15 chunks at 1 fps: the first real floor past 9 |
| 48018386 | about 43 s | 374 MB | mesh 10 MB, trajectory, intrinsics | new; one of the two sampled scenes closest to 400 MB that fit the cap |
| 47429977 | about 43 s | 382 MB | mesh 28 MB, trajectory, intrinsics | new; same rule |

About 5.9 GB in all. The two new ones were picked mechanically: from a sample of 39 validation
scenes with a mesh (every 14th in the metadata), the two whose video and mesh together come
closest to 400 MB, after the four above left 0.9 GB of the cap.

## What runs, and how it is reported

- **The product path at 1 fps on all eight**: `levanta video` with no focal length, because no
  ARKitScenes `.mov` names its phone, so that is what the product does with these files.
- **The rule, written now: all eight are reported and none is excluded after its result is
  seen**, including the mirror bathroom that levanta stamps NOT RECONSTRUCTIBLE, which is
  reported with its stamp.
- Per scene: floor IoU, scale, rooms found against rooms in the mesh, area with its scale
  (`bench/area_report.py`), camera error, chunks, and whether a warning or stamp fired.
- Across the eight: **median and range** of floor IoU and of the scale error. The 0.60 used
  today is then read against that distribution, not against one room.

The download itself is Jhona's to approve: files, source and size are above.
