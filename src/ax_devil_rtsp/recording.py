from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RecordingPath = str | Path


@dataclass(frozen=True)
class RawRecordingConfig:
    """Configuration for recording original RTSP video without re-encoding."""

    output_path: Path
    overwrite: bool = False
    create_parent_dirs: bool = True

    @classmethod
    def from_path(
        cls,
        output_path: RecordingPath,
        *,
        overwrite: bool = False,
        create_parent_dirs: bool = True,
    ) -> "RawRecordingConfig":
        """Create a raw recording config from a filesystem path."""
        return cls(
            output_path=Path(output_path),
            overwrite=overwrite,
            create_parent_dirs=create_parent_dirs,
        )

    def prepare_output_path(self) -> Path:
        """Validate and prepare the output path before the GStreamer pipeline starts."""
        output_path = self.output_path.expanduser()
        if output_path.suffix.lower() != ".mp4":
            raise ValueError(
                f"Raw RTSP recording currently writes MP4 files only: {output_path}"
            )

        parent = output_path.parent
        if self.create_parent_dirs:
            parent.mkdir(parents=True, exist_ok=True)
        elif not parent.exists():
            raise FileNotFoundError(
                f"Recording output directory does not exist: {parent}"
            )

        if output_path.exists() and not self.overwrite:
            raise FileExistsError(f"Recording output already exists: {output_path}")
        if output_path.exists() and self.overwrite:
            output_path.unlink()

        return output_path


def coerce_raw_recording_config(
    recording: RawRecordingConfig | RecordingPath | None,
    *,
    overwrite: bool = False,
) -> RawRecordingConfig | None:
    """Normalize supported recording inputs to a RawRecordingConfig."""
    if recording is None:
        return None
    if isinstance(recording, RawRecordingConfig):
        return recording
    return RawRecordingConfig.from_path(recording, overwrite=overwrite)