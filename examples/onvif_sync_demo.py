#!/usr/bin/env python3
"""
Question: How do I sync video frame timestamps with ONVIF metadata timestamps
          on Axis cameras?

Answer (4 steps):
    1. Add `onvifreplayext=1` to the RTSP URL.
       This makes the camera embed an NTP timestamp (header ID 0xABAC) in every
       video RTP packet. No device configuration needed.

    2. Read the NTP timestamp from each video RTP extension header.
       → See extract_ntp_timestamp()

    3. Parse the UtcTime from the ONVIF metadata XML.
       → See extract_metadata_timestamp()

    4. Match: find the video frame whose NTP time is closest to the metadata
       UtcTime. They'll be within ~1-2ms of each other.
       → See find_closest_match()

    Precision note:
       Video NTP has sub-microsecond resolution (32-bit fractional seconds).
       Metadata UtcTime is millisecond-only (ISO 8601 with 3 decimal places).
       So ~1ms is the best sync you can achieve — the camera firmware truncates.

Prerequisites (nothing to configure):
    - Camera has NTP time sync (on by default)
    - Analytics running (on by default since AXIS OS 10.10)

Requirements:
    System: python3-gi python3-gst-1.0 gstreamer1.0-plugins-good gstreamer1.0-libav
    Pip:    PyGObject

Usage:
    export AXIS_USER="your-user" AXIS_PASSWORD="your-password"
    python onvif_sync_demo.py --ip 192.168.1.100
"""

import argparse
import os
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote as url_quote

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
gi.require_version("GstRtp", "1.0")
from gi.repository import Gst, GLib, GstRtp  # noqa: E402


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  THE ANSWER — Steps 1-4 above are implemented below.                        ║
# ║  Everything after this section is GStreamer plumbing to run the demo.        ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


# ─── Constants ────────────────────────────────────────────────────────────────

ONVIF_RTP_EXT_ID = 0xABAC  # Axis uses this ID for the NTP extension header
NTP_TO_UNIX_OFFSET = (
    2208988800  # Seconds between 1900 (NTP epoch) and 1970 (Unix epoch)
)
ONVIF_NS = {"tt": "http://www.onvif.org/ver10/schema"}

# Detect GLib.Bytes API once — newer PyGObject wraps raw bytes in GLib.Bytes
_GLIB_BYTES_HAS_GET_DATA = hasattr(GLib.Bytes.new(b""), "get_data")


def _unwrap_glib_bytes(data: bytes | GLib.Bytes) -> bytes:
    """Unwrap GLib.Bytes to raw bytes if needed. Detected once at import time."""
    if _GLIB_BYTES_HAS_GET_DATA:
        return data.get_data()
    return data


@dataclass
class TimestampedFrame:
    time: datetime
    frame_nr: int


# ─── Step 1: Build the RTSP URL with onvifreplayext=1 ─────────────────────────


def build_rtsp_url(ip, username, password, resolution="640x480"):
    """
    The magic parameter is `onvifreplayext=1` — this tells the Axis camera to
    include NTP timestamps in the RTP extension header of each video packet.

    `analytics=polygon` enables ONVIF metadata alongside the video stream.
    """
    return (
        f"rtsp://{url_quote(username, safe='')}:{url_quote(password, safe='')}"
        f"@{ip}/axis-media/media.amp"
        f"?camera=1"
        f"&videocodec=h264"
        f"&resolution={resolution}"
        f"&analytics=polygon"  # ← enables ONVIF metadata
        f"&onvifreplayext=1"  # ← enables NTP timestamps on video RTP packets
    )


# ─── Step 2: Extract the NTP timestamp from a video RTP packet ───────────────


def extract_ntp_timestamp_from_video_packet(rtp_buffer) -> datetime | None:
    """
    Each video RTP packet carries an extension header (ID 0xABAC) with:
        Bytes 0-3: NTP seconds (big-endian)
        Bytes 4-7: NTP fractional seconds (big-endian)
        Bytes 8-11: Flags

    We convert NTP time → Unix time → Python datetime (UTC).
    """
    result = GstRtp.RTPBuffer.get_extension_data(rtp_buffer)
    if result is None:
        return None

    ext_bytes, ext_id = result
    if ext_id != ONVIF_RTP_EXT_ID:
        return None

    data = _unwrap_glib_bytes(ext_bytes)
    if not data or len(data) < 12:
        return None

    ntp_sec = int.from_bytes(data[0:4], "big")
    ntp_frac = int.from_bytes(data[4:8], "big")
    unix_time = ntp_sec - NTP_TO_UNIX_OFFSET + ntp_frac / (1 << 32)

    return datetime.fromtimestamp(unix_time, tz=timezone.utc)


# ─── Step 3: Parse the UtcTime from ONVIF metadata XML ───────────────────────


def extract_metadata_timestamp(xml_text: str) -> datetime | None:
    """
    ONVIF metadata XML contains: <tt:Frame UtcTime="2024-01-15T12:34:56.123Z">
    This is the timestamp we match against the video NTP time.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    for frame in root.findall(".//tt:Frame", ONVIF_NS):
        utc_str = frame.get("UtcTime")
        if utc_str:
            return datetime.fromisoformat(utc_str.replace("Z", "+00:00"))

    return None


# ─── Step 4: Match video timestamps to metadata timestamps ───────────────────


def find_closest_match(target_time, buffer, max_delta=0.01):
    """
    Simple nearest-neighbor match: find the entry in buffer whose timestamp
    is closest to target_time (within max_delta seconds).

    Returns (entry, delta_seconds) or (None, None).
    """
    if not buffer:
        return None, None

    def seconds_from_target(entry):
        return abs((entry.time - target_time).total_seconds())

    closest = min(buffer, key=seconds_from_target)
    delta_sec = seconds_from_target(closest)

    if delta_sec < max_delta:
        return closest, delta_sec
    return None, None


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  PLUMBING — GStreamer pipeline that wires Steps 1-4 together.               ║
# ║  You can stop reading here if you only need the concepts.                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
#   Why a FIFO queue (not a single slot) for NTP↔frame pairing:
#     avdec_h264 with frame threading (the default on multi-core) delays output
#     by 1+ frames. A single-slot "latest NTP" would pair each decoded frame
#     with the *next* frame's NTP. The queue preserves correct ordering.
#
#   Data flow:
#     Video RTP packets  →  _on_video_rtp_packet (Step 2: extract NTP, enqueue on marker)
#                        →  _on_video_frame      (dequeue NTP, buffer the timestamp)
#     Metadata RTP pkts  →  _on_metadata_packet  (reassemble XML)
#                        →  Step 3: extract UtcTime
#                        →  Step 4: find closest video timestamp → print match
#


class SyncDemoPipeline:
    """
    GStreamer plumbing — receives video + metadata from an Axis camera
    and wires up the 4 conceptual steps defined above.
    """

    def __init__(self, rtsp_url, latency_ms=200):
        Gst.init(None)
        self._loop = GLib.MainLoop()
        self._current_frame_ntp = None  # NTP accumulator for in-flight RTP packets
        self._ntp_queue = deque()  # One NTP per complete frame, consumed by _on_video_frame
        self._video_buffer = deque(maxlen=90)  # ~3s of matched video NTP timestamps
        self._lock = threading.Lock()
        self._metadata_xml_buf = bytearray()
        self.stats = {"video": 0, "metadata": 0, "synced": 0}

        # Build pipeline
        self._pipeline = Gst.Pipeline.new("demo")
        src = Gst.ElementFactory.make("rtspsrc", "src")
        src.set_property("location", rtsp_url)
        src.set_property("latency", latency_ms)
        src.connect("pad-added", self._link_pad)
        self._pipeline.add(src)

        # Video chain: depay → decode → convert → appsink (as pipeline string)
        self._video_bin = Gst.parse_bin_from_description(
            "rtph264depay name=depay ! h264parse ! avdec_h264 ! videoconvert"
            " ! video/x-raw,format=RGB ! appsink name=vsink emit-signals=true sync=false",
            True,
        )
        self._pipeline.add(self._video_bin)
        self._depay = self._video_bin.get_by_name("depay")
        vsink = self._video_bin.get_by_name("vsink")
        vsink.connect("new-sample", self._on_video_frame)

        # Attach RTP probe to read NTP extension from video packets (Step 2)
        self._depay.get_static_pad("sink").add_probe(
            Gst.PadProbeType.BUFFER, self._on_video_rtp_packet
        )

        # Metadata branch (built on demand when the camera advertises it)
        self._metadata_jbuf = None

        # Bus
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    def _link_pad(self, _src, pad):
        caps = pad.get_current_caps()
        if not caps:
            return
        media = caps.get_structure(0).get_string("media") or ""

        if media == "video":
            pad.link(self._video_bin.get_static_pad("sink"))
        elif media == "application":
            if not self._metadata_jbuf:
                self._build_metadata_branch()
            pad.link(self._metadata_jbuf.get_static_pad("sink"))

    def _build_metadata_branch(self):
        self._metadata_jbuf = Gst.ElementFactory.make("rtpjitterbuffer", "jbuf")
        capsf = Gst.ElementFactory.make("capsfilter", "mcaps")
        capsf.set_property(
            "caps", Gst.Caps.from_string("application/x-rtp,media=application")
        )
        msink = Gst.ElementFactory.make("appsink", "msink")
        msink.set_property("emit-signals", True)
        msink.set_property("sync", False)
        msink.connect("new-sample", self._on_metadata_packet)
        for el in [self._metadata_jbuf, capsf, msink]:
            self._pipeline.add(el)
            el.sync_state_with_parent()
        self._metadata_jbuf.link(capsf)
        capsf.link(msink)

    def _on_video_rtp_packet(self, _pad, info):
        """Pad probe: reads NTP from each video RTP packet (Step 2).

        H.264 frames span multiple RTP packets sharing the same RTP timestamp.
        The last packet of each frame has the marker bit set. We capture the NTP
        from each packet and enqueue it when the marker bit signals frame-complete.
        This gives a 1:1 NTP-per-decoded-frame correspondence via the queue.
        """
        buf = info.get_buffer()
        if not buf:
            return Gst.PadProbeReturn.OK
        ok, rtp_buf = GstRtp.RTPBuffer.map(buf, Gst.MapFlags.READ)
        if not ok:
            return Gst.PadProbeReturn.OK
        try:
            ntp = extract_ntp_timestamp_from_video_packet(rtp_buf)
            if ntp:
                self._current_frame_ntp = ntp
            # Marker bit = last packet of this frame → enqueue for the decoder output
            if rtp_buf.get_marker() and self._current_frame_ntp:
                with self._lock:
                    self._ntp_queue.append(self._current_frame_ntp)
                self._current_frame_ntp = None
        finally:
            GstRtp.RTPBuffer.unmap(rtp_buf)
        return Gst.PadProbeReturn.OK

    def _on_video_frame(self, sink):
        """Buffer each decoded frame's NTP timestamp for later matching.

        Pops the next NTP from the queue (enqueued by _on_video_rtp_packet at
        each frame boundary). FIFO order guarantees correct frame↔NTP pairing.
        """
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.ERROR

        self.stats["video"] += 1

        with self._lock:
            if self._ntp_queue:
                video_ntp = self._ntp_queue.popleft()
                self._video_buffer.append(
                    TimestampedFrame(time=video_ntp, frame_nr=self.stats["video"])
                )

        return Gst.FlowReturn.OK

    def _on_metadata_packet(self, sink):
        """Reassemble XML from RTP fragments, then run Steps 3 & 4."""
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.ERROR

        # Use GstRtp to extract payload and marker bit (same API as video side)
        buf = sample.get_buffer()
        ok, rtp_buf = GstRtp.RTPBuffer.map(buf, Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        payload = bytes(_unwrap_glib_bytes(rtp_buf.get_payload()))  # copy before unmap
        is_last_fragment = rtp_buf.get_marker()
        GstRtp.RTPBuffer.unmap(rtp_buf)

        self._metadata_xml_buf.extend(payload)

        # Guard against malformed streams filling memory
        if len(self._metadata_xml_buf) > 65536:
            self._metadata_xml_buf = bytearray()
            return Gst.FlowReturn.OK

        if not is_last_fragment:
            return Gst.FlowReturn.OK

        # Full XML frame received — parse and match
        self._process_complete_xml()
        self._metadata_xml_buf = bytearray()
        return Gst.FlowReturn.OK

    def _process_complete_xml(self):
        """Steps 3 & 4: extract metadata timestamp, match to video frame."""
        start = self._metadata_xml_buf.find(b"<")
        if start < 0:
            return

        try:
            xml_text = self._metadata_xml_buf[start:].decode("utf-8")
        except UnicodeDecodeError:
            return

        meta_time = extract_metadata_timestamp(xml_text)
        self.stats["metadata"] += 1
        if not meta_time:
            return

        with self._lock:
            match, delta = find_closest_match(meta_time, self._video_buffer)
            buf_len = len(self._video_buffer)

        self._report_match(meta_time, match, delta, buf_len)

    def _report_match(self, meta_time, match, delta, buf_len):
        """Print sync result."""
        mt = meta_time.strftime("%H:%M:%S.%f")[:-3]
        if match:
            self.stats["synced"] += 1
            vt = match.time.strftime("%H:%M:%S.%f")[:-3]
            print(
                f"  [SYNCED] video frame {match.frame_nr:>4} "
                f"NTP={vt}  ←→  metadata UtcTime={mt}  "
                f"Δ={delta * 1000:.1f}ms"
            )
        else:
            reason = (
                "no video frames buffered"
                if buf_len == 0
                else f"closest Δ>10ms (buffer={buf_len} frames)"
            )
            print(f"  [MISS]  metadata UtcTime={mt}  — {reason}")

    def _on_message(self, _bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, _ = msg.parse_error()
            print(f"  [ERROR] {err.message}")
            self._loop.quit()
        elif msg.type == Gst.MessageType.EOS:
            self._loop.quit()

    def run(self, seconds=30):
        self._pipeline.set_state(Gst.State.PLAYING)

        def timeout():
            time.sleep(seconds)
            self._loop.quit()

        threading.Thread(target=timeout, daemon=True).start()
        try:
            self._loop.run()
        except KeyboardInterrupt:
            pass
        self._pipeline.set_state(Gst.State.NULL)


# ─── Entry Point ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="ONVIF RTP Extension Sync Demo")
    parser.add_argument("--ip", required=True, help="Camera IP")
    parser.add_argument(
        "--user",
        default=os.environ.get("AXIS_USER", "root"),
        help="Camera user (default: $AXIS_USER or 'root')",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("AXIS_PASSWORD"),
        help="Camera password (default: $AXIS_PASSWORD)",
    )
    parser.add_argument("--duration", type=int, default=30, help="Seconds to stream")
    parser.add_argument("--resolution", default="640x480")
    args = parser.parse_args()

    if not args.password:
        parser.error("Password required: set AXIS_PASSWORD env var or use --password")

    url = build_rtsp_url(args.ip, args.user, args.password, args.resolution)
    print()
    print("  ONVIF RTP Extension Sync Demo")
    print("  ─────────────────────────────")
    print(f"  Camera: {args.ip}  Duration: {args.duration}s")
    print("   Key URL params: analytics=polygon & onvifreplayext=1")
    print()

    pipeline = SyncDemoPipeline(url)
    pipeline.run(seconds=args.duration)

    print()
    print(
        f"  Done. Video={pipeline.stats['video']}  "
        f"Metadata={pipeline.stats['metadata']}  "
        f"Synced={pipeline.stats['synced']}"
    )


if __name__ == "__main__":
    main()
