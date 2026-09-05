#!/usr/bin/env python3
"""Flag speech the transcript never covered.

whisper.cpp locks onto ONE language per file. Sustained speech in the other
language is silently dropped -- no error, no gap marker. Verified 22 Aug 2026:
a pure-English sentence inside a Hindi-dominant recording vanished under both
`auto` and `hi`.

This compares ffmpeg's speech regions against the .srt timeline and reports
any stretch of speech the transcript has nothing for.

    check-coverage.py <audio.wav> <transcript.srt> [min_gap_seconds]
"""
import re, subprocess, sys

def noise_floor(wav):
    """Pick a silence threshold from the file itself.

    A hardcoded dB value calibrated on clean audio produces a flood of false
    positives on real room-tone recordings -- and a check that cries wolf is a
    check nobody reads. Anchor to the file's own mean level instead.
    """
    out = subprocess.run(["ffmpeg", "-nostdin", "-i", wav, "-af", "volumedetect",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", out)
    if not m:
        return -35.0
    # 10 dB under the mean separates speech from room tone across a wide range;
    # clamp so a pathological file can't push it somewhere useless.
    return max(-50.0, min(-20.0, float(m.group(1)) - 10.0))


def speech_regions(wav, noise=None, mindur="0.5"):
    if noise is None:
        noise = f"{noise_floor(wav):.1f}dB"
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", wav, "-af",
         f"silencedetect=n={noise}:d={mindur}", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", out)]
    ends   = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", out)]
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", wav], capture_output=True, text=True).stdout.strip())
    # invert silences into speech
    regions, cur = [], 0.0
    for i, s in enumerate(starts):
        if s > cur: regions.append((cur, s))
        cur = ends[i] if i < len(ends) else dur
    if cur < dur: regions.append((cur, dur))
    return [r for r in regions if r[1] - r[0] > 0.3], dur

def srt_regions(srt):
    t = open(srt, encoding="utf-8", errors="replace").read()
    pat = r"(\d\d):(\d\d):(\d\d)[,.](\d\d\d) --> (\d\d):(\d\d):(\d\d)[,.](\d\d\d)"
    out = []
    for m in re.finditer(pat, t):
        g = [int(x) for x in m.groups()]
        out.append((g[0]*3600+g[1]*60+g[2]+g[3]/1000,
                    g[4]*3600+g[5]*60+g[6]+g[7]/1000))
    return out

def uncovered(speech, covered, min_gap):
    gaps = []
    for s, e in speech:
        cur = s
        for cs, ce in sorted(covered):
            if ce <= cur or cs >= e: continue
            if cs > cur: gaps.append((cur, min(cs, e)))
            cur = max(cur, ce)
            if cur >= e: break
        if cur < e: gaps.append((cur, e))
    return [(a, b) for a, b in gaps if b - a >= min_gap]

def hms(x): return f"{int(x//60):02d}:{x%60:05.2f}"

if __name__ == "__main__":
    if len(sys.argv) < 3: print(__doc__); sys.exit(1)
    wav, srt = sys.argv[1], sys.argv[2]
    min_gap = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
    speech, dur = speech_regions(wav)
    gaps = uncovered(speech, srt_regions(srt), min_gap)
    if not gaps:
        print(f">> coverage ok: no untranscribed speech over {min_gap:.0f}s")
        sys.exit(0)
    lost = sum(b - a for a, b in gaps)
    print(f"!! {len(gaps)} stretch(es) of speech missing from the transcript "
          f"({lost:.1f}s of {dur:.0f}s):")
    for a, b in gaps:
        print(f"!!   {hms(a)} - {hms(b)}  ({b-a:.1f}s)")
    print("!! Likely a language whisper did not lock onto. Re-run that span with "
          "the other language and merge, e.g.:")
    print("!!   ffmpeg -i IN -ss <start> -to <end> clip.wav && transcribe.sh clip.wav out en")
    sys.exit(2)
