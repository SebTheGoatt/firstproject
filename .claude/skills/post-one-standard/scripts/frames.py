"""Contact sheet of a video: 20 evenly spaced frames in one image (5 x 4), for reading with the Read tool.

    python3 frames.py <video> <out dir>        ->  <out dir>/sheet.png
"""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    video, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                               capture_output=True, text=True, check=True).stdout.strip() or 0)
    step = max(1.0, dur / 20)
    sheet = out / "sheet.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", f"fps=1/{step:.3f},scale=300:-1,tile=5x4",
                    "-frames:v", "1", str(sheet)], check=True)
    print(f"{dur:.0f}s video, one frame every {step:.1f}s -> {sheet}")


if __name__ == "__main__":
    main()
