#!/usr/bin/env python3
"""Drop near-identical slide frames.

A lecturer holds one slide for minutes, so a fixed-interval screen capture produces
dozens of copies of it. Each one costs image tokens when Claude reads it. This keeps
only frames that actually differ from the last one KEPT (not the previous one), so
slow fades and gradual builds don't sneak through as a chain of "small" changes.

    dedup-frames.py <frames-dir> [threshold]     # threshold is mean abs diff, 0-255
"""
import os, subprocess, sys

def thumbs(d, files):
    """One ffmpeg pass -> 16x16 grayscale bytes per frame.

    Uses the image2 demuxer with passthrough timing. The concat demuxer RETIMES an
    image sequence against an output frame rate, which silently drops/duplicates
    frames and desyncs the thumbnails from the files.
    """
    lst = os.path.join(d, ".seq")
    os.makedirs(lst, exist_ok=True)
    for i, p in enumerate(files, 1):                    # stable numbering for glob order
        os.symlink(os.path.abspath(p), os.path.join(lst, f"{i:06d}.jpg"))
    try:
        out = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error",
             "-f", "image2", "-pattern_type", "glob", "-i", os.path.join(lst, "*.jpg"),
             "-fps_mode", "passthrough",
             "-vf", "scale=16:16,format=gray", "-f", "rawvideo", "-"],
            capture_output=True).stdout
    finally:
        for f in os.listdir(lst):
            os.unlink(os.path.join(lst, f))
        os.rmdir(lst)
    n = 256
    return [out[i*n:(i+1)*n] for i in range(len(out)//n)]

def main():
    d = sys.argv[1]
    thr = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    files = sorted(f for f in (os.path.join(d, x) for x in os.listdir(d))
                   if f.endswith(".jpg"))
    if len(files) < 2:
        return
    t = thumbs(d, files)
    if len(t) != len(files):
        print(f"!! thumbnail count {len(t)} != frame count {len(files)}; skipping dedup",
              file=sys.stderr)
        return

    # Group consecutive near-identical frames into runs, and keep the LAST frame of
    # each run. Lecture slides BUILD -- bullets appear one at a time, and each addition
    # is far below the threshold. Keeping the first frame of a run would preserve the
    # half-empty slide and discard the completed one. The last frame is the finished
    # state just before the lecturer moves on.
    runs, ref = [[files[0]]], t[0]
    for path, cur in zip(files[1:], t[1:]):
        if sum(abs(a - b) for a, b in zip(cur, ref)) / 256.0 > thr:
            runs.append([path]); ref = cur          # genuinely new slide
        else:
            runs[-1].append(path)                   # same slide, possibly still building

    keep = {r[-1] for r in runs}
    for f in files:
        if f not in keep:
            os.remove(f)
    for i, p in enumerate(sorted(keep), 1):
        new_name = os.path.join(d, f"slide-{i:04d}.jpg")
        if p != new_name:
            os.rename(p, new_name)


if __name__ == "__main__":
    main()
