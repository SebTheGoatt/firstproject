"""Print what's said in one or more videos or audio files (English), with faster-whisper on the CPU.

    python3 transcribe.py <file> [<file> ...]

The audio is decoded with ffmpeg and handed over as samples, because the installed PyAV doesn't accept
faster-whisper's own file-opening options. The first run downloads the "small.en" model (~460 MB).
"""

import subprocess
import sys

import numpy as np


def samples(path: str) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    from faster_whisper import WhisperModel
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    for path in sys.argv[1:]:
        audio = samples(path)
        if not audio.size:
            print(f"===== {path}\n(no audio track)")
            continue
        segments, _ = model.transcribe(audio, beam_size=1, vad_filter=True)
        print(f"===== {path}\n" + " ".join(s.text.strip() for s in segments))


if __name__ == "__main__":
    main()
