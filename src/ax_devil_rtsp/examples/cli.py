from __future__ import annotations
import argparse
import logging
import multiprocessing as mp
import cv2
import urllib.parse

from ..gstreamer_data_grabber import CombinedRTSPClient


def parse_args():
    parser = argparse.ArgumentParser(
        description="CLI for CombinedRTSPClient (video, metadata, RTP extension, session metadata)"
    )
    parser.add_argument("--ip", help="Camera IP address (required unless --rtsp-url provided)")
    parser.add_argument("--username", default="", help="Device username")
    parser.add_argument("--password", default="", help="Device password")
    parser.add_argument("--source", default="1", help="What device \"source\"/\"camera head\" to use")
    parser.add_argument("--latency", type=int, default=100, help="RTSP latency in ms")
    parser.add_argument("--no-video", action="store_true", help="Disable video frames", default=False)
    parser.add_argument("--no-metadata", action="store_true", help="Disable metadata XML", default=False)
    parser.add_argument("--rtp-ext", action="store_true", help="Enable RTP extension", default=False)
    parser.add_argument("--rtsp-url", help="Full RTSP URL, overrides all other arguments")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args()


def build_rtsp_url(args):
    if args.rtsp_url:
        return args.rtsp_url

    if not args.ip:
        raise ValueError("No IP address provided")
    
    if args.no_video and args.no_metadata:
        raise ValueError("You cannot ask for nothing and expect to receive something.")

    cred = f"{args.username}:{args.password}@" if args.username or args.password else ""
    url = f"rtsp://{cred}{args.ip}/axis-media/media.amp"

    # Build query parameters in a dictionary.
    params = {}
    if args.no_video:
        params["video"] = "0"
    params["audio"] = "0"
    
    if args.rtp_ext:
        params["onvifreplayext"] = "1"

    if args.no_video:
        params["resolution"] = "500x500"

    if not args.no_metadata:
        params["analytics"] = "polygon"
    params["camera"] = args.source

    # If there are any query parameters, append them to the URL.
    if params:
        query_string = urllib.parse.urlencode(params)
        url += "?" + query_string
    return url


def client_runner(
    rtsp_url: str,
    latency: int,
    queue: mp.Queue,
) -> None:
    def video_cb(pl: dict):
        queue.put({"kind": "video", **pl})

    def metadata_cb(pl: dict):
        queue.put({"kind": "metadata", **pl})

    def session_cb(md: dict):
        queue.put({"kind": "session", "data": md})

    client = CombinedRTSPClient(
        rtsp_url,
        latency=latency,
        video_frame_callback=video_cb,
        metadata_callback=metadata_cb,
        session_metadata_callback=session_cb,
    )
    client.start()


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(process)d] %(asctime)s - %(levelname)s - %(message)s",
    )
    try:
        rtsp_url = build_rtsp_url(args)
    except ValueError as e:
        logging.error(e)
        return

    # Multiprocessing setup
    if mp.get_start_method(allow_none=True) != "spawn":
        mp.set_start_method("spawn", force=True)
    queue: mp.Queue = mp.Queue()

    proc = mp.Process(
        target=client_runner,
        args=(
            rtsp_url,
            args.latency,
            queue,
        ),
        daemon=True,
    )
    proc.start()
    logging.info("Spawned CombinedRTSPClient with PID %d", proc.pid)

    try:
        while True:
            item = queue.get(timeout=1)
            kind = item.get("kind")
            if kind == "video":
                frame = item["data"]
                diag = item["diagnostics"]
                print(f"[VIDEO] frame shape={frame.shape}, diag={diag}")
                cv2.imshow("Video", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            elif kind == "metadata":
                xml = item["data"]
                diag = item["diagnostics"]
                print(f"[METADATA] {len(xml)} bytes, diag={diag}")
                print(xml)
            elif kind == "session":
                print(f"[SESSION METADATA] {item['data']}")
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
    finally:
        logging.info("Terminating client")
        proc.terminate()
        proc.join()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
