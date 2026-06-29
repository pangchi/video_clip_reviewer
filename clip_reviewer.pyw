"""
Clip Reviewer - GUI to review a folder of MP4 clips and label each as
Good or Bad.

- Good  -> moved into a 'good' subfolder when you click "Finish & Apply"
- Bad   -> deleted when you click "Finish & Apply"
- Back  -> revisit the previous clip and change its label
- Nothing touches disk until you explicitly click "Finish & Apply"
  (or close the window and confirm).

Playback uses ffplay (bundled with ffmpeg), so no extra Python video
library is required. You just need ffmpeg installed and on your PATH:
  - Windows: https://ffmpeg.org/download.html  (add the bin folder to PATH)
  - Mac:     brew install ffmpeg
  - Linux:   sudo apt install ffmpeg

On Linux, the video is embedded directly into the app window. On
Windows/Mac, ffplay opens as its own normal window titled "Preview -
<filename>", positioned near the app (there's no public embedding API
on those platforms), but playback is still automatic - you never have
to drive ffplay yourself. Clips that fail to play (e.g. corrupt or
incomplete files) are flagged as UNPLAYABLE in the GUI rather than
silently looping forever or auto-labeled.

Usage:
    python clip_reviewer.py [optional_folder_path]
"""

import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox


VIDEO_EXTS = {".mp4", ".m4v", ".mov"}


class ClipReviewer(tk.Tk):
    def __init__(self, folder=None):
        super().__init__()
        self.title("Clip Reviewer")
        self.geometry("900x650")
        self.minsize(640, 480)

        self.folder = None
        self.clips = []          # list of absolute file paths
        self.labels = {}         # path -> "good" | "bad" | None
        self.unplayable = set()  # paths that failed to play (flagged, not auto-labeled)
        self.index = -1

        # --- ffplay setup ---
        if shutil.which("ffplay") is None:
            messagebox.showerror(
                "ffmpeg not found",
                "Could not find 'ffplay' on your PATH.\n\n"
                "Install ffmpeg first:\n"
                "  Windows: https://ffmpeg.org/download.html (add bin/ to PATH)\n"
                "  Mac:     brew install ffmpeg\n"
                "  Linux:   sudo apt install ffmpeg"
            )
            self.destroy()
            sys.exit(1)
        self.ffplay_proc = None  # currently running ffplay subprocess
        self._ffplay_log = None  # open log file handle for current ffplay run

        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        if folder:
            self.load_folder(folder)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        top = tk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        tk.Button(top, text="Open Folder...", command=self.choose_folder).pack(side="left")
        self.path_label = tk.Label(top, text="No folder loaded", anchor="w")
        self.path_label.pack(side="left", padx=10)

        self.counter_label = tk.Label(top, text="", anchor="e")
        self.counter_label.pack(side="right")

        # Video surface
        self.video_frame = tk.Frame(self, bg="black")
        self.video_frame.pack(fill="both", expand=True, padx=8, pady=4)

        # Prominent banner shown only when the current clip fails to play.
        self.unplayable_banner = tk.Label(
            self, text="", bg="#e67e22", fg="white",
            font=("TkDefaultFont", 11, "bold"), pady=6,
        )
        # Not packed yet - shown/hidden by _update_tag_label()

        if not sys.platform.startswith("linux"):
            # On Windows/Mac, ffplay can't embed into this frame - it opens
            # its own window instead. Keep this hint visible so the black
            # frame here isn't mistaken for a playback failure.
            tk.Label(
                self.video_frame,
                text="Video plays in a separate 'Preview' window\n(this panel stays black - that's expected)",
                bg="black", fg="gray60", font=("TkDefaultFont", 10),
            ).place(relx=0.5, rely=0.5, anchor="center")

        self.status_label = tk.Label(self, text="Open a folder of MP4 clips to begin.",
                                      fg="gray20")
        self.status_label.pack(pady=(0, 4))

        # Label / status row
        info_row = tk.Frame(self)
        info_row.pack(fill="x", padx=8)
        self.filename_label = tk.Label(info_row, text="", font=("TkDefaultFont", 11, "bold"))
        self.filename_label.pack(side="left")
        self.tag_label = tk.Label(info_row, text="", font=("TkDefaultFont", 11, "bold"))
        self.tag_label.pack(side="right")

        # Controls
        controls = tk.Frame(self)
        controls.pack(fill="x", padx=8, pady=10)

        self.back_btn = tk.Button(controls, text="<< Back", width=12,
                                   command=self.go_back)
        self.back_btn.pack(side="left")

        self.bad_btn = tk.Button(controls, text="Bad", width=14, bg="#e74c3c", fg="white",
                                  font=("TkDefaultFont", 11, "bold"),
                                  command=lambda: self.label_and_advance("bad"))
        self.bad_btn.pack(side="left", padx=(20, 6))

        self.good_btn = tk.Button(controls, text="Good", width=14, bg="#2ecc71", fg="white",
                                   font=("TkDefaultFont", 11, "bold"),
                                   command=lambda: self.label_and_advance("good"))
        self.good_btn.pack(side="left", padx=6)

        self.next_btn = tk.Button(controls, text="Skip >>", width=12,
                                   command=self.go_next_unlabeled)
        self.next_btn.pack(side="left", padx=(20, 0))

        self.finish_btn = tk.Button(controls, text="Finish & Apply", width=16,
                                     bg="#34495e", fg="white",
                                     command=self.finish_and_apply)
        self.finish_btn.pack(side="right")

        # Keyboard shortcuts
        self.bind("<Left>", lambda e: self.go_back())
        self.bind("<g>", lambda e: self.label_and_advance("good"))
        self.bind("<b>", lambda e: self.label_and_advance("bad"))
        self.bind("<Right>", lambda e: self.go_next_unlabeled())

        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for btn in (self.back_btn, self.bad_btn, self.good_btn, self.next_btn, self.finish_btn):
            btn.config(state=state)

    # ----------------------------------------------------------- Folder
    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing MP4 clips")
        if folder:
            self.load_folder(folder)

    def load_folder(self, folder):
        if not os.path.isdir(folder):
            messagebox.showerror("Error", f"Not a valid folder:\n{folder}")
            return

        clips = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in VIDEO_EXTS
        )
        if not clips:
            messagebox.showwarning("No clips found", "No MP4/MOV/M4V files found in that folder.")
            return

        self.folder = folder
        self.clips = clips
        self.labels = {c: None for c in clips}
        self.unplayable = set()
        self.index = 0
        self.path_label.config(text=folder)
        self._set_controls_enabled(True)
        self.show_current()

    # ------------------------------------------------------------- Nav
    def show_current(self):
        if not (0 <= self.index < len(self.clips)):
            return

        path = self.clips[self.index]
        self.filename_label.config(text=os.path.basename(path))
        # Optimistically clear any previous "unplayable" flag - if it
        # fails again, _check_playback_started will re-flag it.
        self.unplayable.discard(path)
        self._update_tag_label()
        self.counter_label.config(text=f"Clip {self.index + 1} of {len(self.clips)}")
        self.status_label.config(text="")

        self.back_btn.config(state="normal" if self.index > 0 else "disabled")

        self._play(path)

    def _update_tag_label(self):
        path = self.clips[self.index]
        tag = self.labels.get(path)
        if tag == "good":
            self.tag_label.config(text="GOOD", fg="#2ecc71")
        elif tag == "bad":
            self.tag_label.config(text="BAD", fg="#e74c3c")
        elif path in self.unplayable:
            self.tag_label.config(text="UNPLAYABLE", fg="#e67e22")
        else:
            self.tag_label.config(text="(unlabeled)", fg="gray")

        if path in self.unplayable and tag is None:
            self.unplayable_banner.config(
                text="⚠ This file could not be played — likely corrupt or an unsupported format. "
                     "Mark it Bad to remove it, or Skip to leave it untouched."
            )
            self.unplayable_banner.pack(fill="x", before=self.video_frame)
        else:
            self.unplayable_banner.pack_forget()

    def _stop_playback(self):
        if self.ffplay_proc is not None and self.ffplay_proc.poll() is None:
            try:
                self.ffplay_proc.terminate()
                try:
                    self.ffplay_proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.ffplay_proc.kill()
            except Exception:
                pass
        self.ffplay_proc = None
        if getattr(self, "_ffplay_log", None) is not None:
            try:
                self._ffplay_log.close()
            except Exception:
                pass
            self._ffplay_log = None

    def _play(self, path):
        self._stop_playback()
        try:
            base_cmd = [
                "ffplay",
                "-loop", "0",          # loop forever
                "-autoexit",           # exit if window closed manually
                "-loglevel", "warning",
                "-an",                 # no audio (silent auto-review by default)
                "-window_title", f"Preview - {os.path.basename(path)}",
            ]

            if sys.platform.startswith("linux"):
                # Embed inside the tkinter frame using its X11 window id.
                self.update_idletasks()
                wid = self.video_frame.winfo_id()
                cmd = base_cmd + ["-noborder", "-window_id", str(wid), path]
            else:
                # Windows/Mac: there's no public embedding API for ffplay,
                # so it opens as its own normal window. We size it and try
                # to position it near the app, but do NOT force borderless/
                # always-on-top here - those flags have caused blank/black
                # SDL windows on some Windows GPU drivers. A normal window
                # is far more reliable; it just won't be literally inside
                # the app frame.
                self.update_idletasks()
                x = self.winfo_rootx() + self.video_frame.winfo_x()
                y = self.winfo_rooty() + self.video_frame.winfo_y()
                w = max(self.video_frame.winfo_width(), 480)
                h = max(self.video_frame.winfo_height(), 320)
                cmd = base_cmd + [
                    "-x", str(w), "-y", str(h),
                    "-left", str(x), "-top", str(y),
                    path,
                ]

            # Log ffplay's own stderr/stdout to a file instead of
            # discarding it, so playback failures aren't silent.
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffplay_last_run.log")
            self._ffplay_log = open(log_path, "w", encoding="utf-8", errors="replace")

            popen_kwargs = dict(stdout=self._ffplay_log, stderr=self._ffplay_log)
            if sys.platform == "win32":
                # Suppress the console ("DOS box") window ffplay/ffmpeg
                # would otherwise allocate. This only affects the console
                # window, not ffplay's own SDL video window, so it's safe
                # to use alongside normal (non-borderless) playback.
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            self.ffplay_proc = subprocess.Popen(cmd, **popen_kwargs)
            self.status_label.config(text="")

            # If ffplay exits almost immediately, something went wrong
            # (bad path, codec error, no display, etc) - surface it.
            self.after(700, lambda p=path: self._check_playback_started(p))
        except Exception as e:
            self.status_label.config(text=f"Playback error: {e}", fg="red")

    def _check_playback_started(self, path):
        # Guard against a stale callback firing after the user already
        # navigated to a different clip.
        if not (0 <= self.index < len(self.clips)) or self.clips[self.index] != path:
            return
        proc = self.ffplay_proc
        if proc is not None and proc.poll() is not None and proc.returncode != 0:
            self.unplayable.add(path)
            self._update_tag_label()
            error_detail = self._read_ffplay_error()
            self.status_label.config(
                text=f"Could not play this clip - {error_detail}",
                fg="red")

    def _read_ffplay_error(self):
        """Pull the most relevant line out of ffplay's log for display."""
        try:
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffplay_last_run.log")
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            if lines:
                # Last non-empty line is usually the actual failure reason.
                return lines[-1]
        except Exception:
            pass
        return "unknown error (see ffplay_last_run.log)"

    def label_and_advance(self, tag):
        if not (0 <= self.index < len(self.clips)):
            return
        path = self.clips[self.index]
        self.labels[path] = tag
        self._update_tag_label()
        self.after(150, self._advance)  # tiny delay so the tag flash is visible

    def _advance(self):
        if self.index + 1 < len(self.clips):
            self.index += 1
            self.show_current()
        else:
            self._stop_playback()
            self.status_label.config(
                text="End of list reached. Review labels, then click 'Finish & Apply'.",
                fg="blue")

    def go_back(self):
        if self.index > 0:
            self.index -= 1
            self.show_current()

    def go_next_unlabeled(self):
        """Skip forward without labeling the current clip."""
        if self.index + 1 < len(self.clips):
            self.index += 1
            self.show_current()

    # ------------------------------------------------------------ Apply
    def finish_and_apply(self):
        unlabeled = [c for c in self.clips if self.labels[c] is None]
        good = [c for c in self.clips if self.labels[c] == "good"]
        bad = [c for c in self.clips if self.labels[c] == "bad"]
        still_unplayable = [c for c in unlabeled if c in self.unplayable]

        msg = (f"Good: {len(good)} -> will be moved into '{os.path.join(self.folder, 'good')}'\n"
               f"Bad: {len(bad)} -> will be permanently DELETED\n"
               f"Unlabeled: {len(unlabeled)} -> left in place, untouched\n")
        if still_unplayable:
            msg += f"  (of which {len(still_unplayable)} failed to play - left in place too)\n"
        msg += "\nThis cannot be undone. Proceed?"
        if not messagebox.askyesno("Confirm apply", msg):
            return

        self._stop_playback()

        good_dir = os.path.join(self.folder, "good")
        if good:
            os.makedirs(good_dir, exist_ok=True)

        errors = []
        for path in good:
            try:
                shutil.move(path, os.path.join(good_dir, os.path.basename(path)))
            except Exception as e:
                errors.append(f"{os.path.basename(path)} (move failed: {e})")

        for path in bad:
            try:
                os.remove(path)
            except Exception as e:
                errors.append(f"{os.path.basename(path)} (delete failed: {e})")

        if errors:
            messagebox.showwarning("Done with some errors",
                                    "Finished, but some files had issues:\n" + "\n".join(errors))
        else:
            messagebox.showinfo("Done", f"Applied: {len(good)} moved to good/, {len(bad)} deleted.")

        self.destroy()

    def on_close(self):
        if self.folder and any(v is not None for v in self.labels.values()):
            if messagebox.askyesno(
                "Apply changes before closing?",
                "You have labeled clips that haven't been applied yet.\n"
                "Apply them now (move Good / delete Bad)?\n\n"
                "Choose 'No' to close without changing any files."
            ):
                self.finish_and_apply()
                return
        self._stop_playback()
        self.destroy()


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    app = ClipReviewer(folder)
    app.mainloop()


if __name__ == "__main__":
    main()
