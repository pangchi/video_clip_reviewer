# Clip Reviewer

A small Python/Tkinter GUI for quickly reviewing a folder of MP4 clips and
sorting them into **Good** and **Bad**, with the ability to go back and
re-label previous clips before anything is changed on disk.

## What it does

- Loads every `.mp4` / `.m4v` / `.mov` file in a folder, sorted by filename.
- Auto-plays and loops each clip as you review it (silent by default).
- **Good** / **Bad** buttons label the current clip and move to the next one.
- **Back** returns to the previous clip so you can re-check or change its label.
- **Skip** moves forward without labeling.
- If a clip fails to play (e.g. it's corrupt or incomplete - a common
  `moov atom not found` error), it's flagged **UNPLAYABLE** in the tag
  area and the status bar shows the actual ffmpeg error. It is **not**
  auto-labeled Good or Bad - you decide what to do with it (label it Bad
  to delete it, or leave it unlabeled to deal with separately).
- **Finish & Apply** is the only point where files are actually changed:
  - `Bad` clips are **permanently deleted**.
  - `Good` clips are **moved into a `good/` subfolder** inside the reviewed folder.
  - Unlabeled clips (including unplayable ones) are left untouched.
- Closing the window also offers to apply pending labels, or you can close
  without changing anything.

Nothing is deleted or moved until you confirm via "Finish & Apply" (or
confirm on close), so mislabeling a clip is always recoverable until then.

## Requirements

- Python 3.8+ with Tkinter (included in standard Python installs on
  Windows/Mac; on Linux you may need `sudo apt install python3-tk`).
- **ffmpeg** installed and available on your PATH (provides `ffplay`,
  used for video playback — no extra Python packages needed):
  - **Windows**: download from https://ffmpeg.org/download.html and add
    the `bin` folder to your PATH.
  - **Mac**: `brew install ffmpeg`
  - **Linux**: `sudo apt install ffmpeg`

Verify ffmpeg is set up correctly:

```bash
ffplay -version
```

## Usage

```bash
python clip_reviewer.py                 # then use "Open Folder..." in the GUI
python clip_reviewer.py /path/to/clips  # or pass a folder directly
```

### Keyboard shortcuts

| Key          | Action              |
|--------------|---------------------|
| `g`          | Label clip as Good  |
| `b`          | Label clip as Bad   |
| Left arrow   | Go back             |
| Right arrow  | Skip (no label)     |

## Platform notes on video playback

- **Linux**: video is embedded directly inside the app window (via X11
  window embedding).
- **Windows / Mac**: `ffplay` has no public API for embedding into another
  app's window, so it opens in its **own separate window**, titled
  "Preview - <filename>", positioned near the app. The black panel inside
  the app itself is expected to stay black on these platforms — that's
  not the video; it's just empty space. The actual video is in the
  separate ffplay window.

Playback is silent by default (`-an` flag in the ffplay command). If you
want audio, remove `"-an"` from the `base_cmd` list in `_play()`.

## Unplayable / corrupt files

If a clip fails to play (corrupt file, unsupported codec, truncated
recording, etc.), the app detects this automatically:

- An orange **"UNPLAYABLE"** banner appears above the video area, with a
  one-line explanation.
- The tag in the top-right shows **UNPLAYABLE** instead of "(unlabeled)".
- The status bar shows the actual ffplay error.
- The clip is **not** auto-labeled — you decide: click **Bad** to remove
  it on Finish & Apply, or **Skip** to leave it untouched for now.
- If a clip you previously flagged starts working later (e.g. you fixed
  it externally), navigating back to it clears the flag automatically.

The detection works by giving ffplay ~0.7 seconds to start; if it exits
with a non-zero code in that window, the file is flagged. The exact
error is read from `ffplay_last_run.log`.

## Troubleshooting

**Black screen / no video visible (Windows or Mac)**

This is expected *inside the app* — see the platform note above. Look for
a separate small window titled "Preview - <filename>"; it may open behind
the main app or off to the side. If you genuinely don't see any ffplay
window at all:

1. Check `ffplay_last_run.log`, created next to the script after each
   playback attempt. It contains ffplay's actual error output (codec
   issues, bad path, etc.) — this used to be silently discarded, but is
   now always logged.
2. If the status bar under the video area shows "ffplay failed to play
   this clip (exit code ...)", that confirms ffplay crashed immediately —
   check the log for the reason.
3. Run `ffplay -version` in a terminal to confirm ffmpeg is actually
   installed and on PATH, not just present somewhere on disk.
4. Some Windows GPU drivers render SDL (ffplay's video backend) windows
   incorrectly when forced borderless/always-on-top — this script no
   longer uses those flags for that reason. If you still see issues, try
   updating your GPU driver.

**`moov atom not found` / clip flagged UNPLAYABLE**

This means the specific MP4 file is corrupt or incomplete — most often
because recording was cut short or the file copy/transfer was interrupted
before the file's index data (`moov` atom) got written. It's not a script
or ffmpeg installation problem. The reviewer now detects this automatically
and marks the clip **UNPLAYABLE** instead of showing a blank/looping
preview — check the status bar for the exact ffmpeg error, or
`ffplay_last_run.log`. You can verify independently with:

```bash
ffprobe "path\to\clip.mp4"
```

Unplayable clips are left unlabeled by default (not auto-deleted) so you
can decide — label them Bad if you want them removed, or investigate the
source (camera/recorder) if many clips show this.

## File layout after review

```
your_folder/
├── good/              <- created automatically, contains all "Good" clips
├── clip_not_yet_labeled.mp4
└── ...                <- "Bad" clips are gone; unlabeled clips stay here
```

## Known limitations

- Only handles `.mp4`, `.m4v`, `.mov` extensions (edit `VIDEO_EXTS` in the
  script to add more).
- On Windows/Mac, video plays in a separate ffplay window rather than
  embedded in the app (see Platform notes above) — it can drift out of
  alignment with the app if you resize the app window while a clip is
  playing.
- No undo after "Finish & Apply" — deleted Bad clips are gone for good.

## Changelog

- **v6**: Suppressed the console ("DOS box") window that ffplay/ffmpeg
  pop up on Windows. This only hides the console, not the video window —
  it's unrelated to the earlier black-screen fix (that was caused by
  `-noborder`/`-alwaysontop`, not by console suppression).
- **v5**: Added a prominent orange banner above the video area when the
  current clip is unplayable, on top of the existing UNPLAYABLE tag and
  status-bar error — much harder to miss at a glance while reviewing.
- **v4**: Clips that fail to play (e.g. corrupt/incomplete files causing
  `moov atom not found`) are now detected and flagged **UNPLAYABLE** in
  the GUI with the actual error shown, instead of silently looping a
  blank window. Unplayable clips are never auto-labeled - left for you
  to decide. The "Finish & Apply" summary also calls out how many
  unlabeled clips were unplayable.
- **v3**: Fixed black-screen issue on Windows. Removed `-noborder`/
  `-alwaysontop` flags (could cause blank SDL windows on some GPU
  drivers), stopped discarding ffplay's stderr (now logged to
  `ffplay_last_run.log`), added an exit-code check that surfaces failed
  playback in the status bar, and added an in-app hint that the black
  panel is expected on Windows/Mac since ffplay opens its own window there.
- **v2**: Switched playback engine from `python-vlc`/VLC to `ffplay`
  (bundled with ffmpeg) to remove the VLC installation dependency.
- **v1**: Initial version using `python-vlc` for playback.
