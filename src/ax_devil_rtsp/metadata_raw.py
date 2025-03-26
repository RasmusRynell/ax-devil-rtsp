#!/usr/bin/env python3
"""
RTSP Client for Axis Camera with separate Metadata streams.

- The metadata client uses our custom RTSPProtocolClient and MetadataHandler.
"""

import socket
import re
import hashlib
import struct
import os
import xml.etree.ElementTree as ET
import cv2
import numpy as np
from datetime import datetime
import argparse

# =============================
# RTSP Protocol Client (for Metadata)
# =============================

class RTSPProtocolClient:
    def __init__(self, ip, username, password, base_url, user_agent="ax-devil-RTSPClient/1.0"):
        self.ip = ip
        self.username = username
        self.password = password
        self.user_agent = user_agent
        self.base_url = base_url
        self.cseq = 1
        self.session_id = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((ip, 554))

    def send_request(self, request):
        print("----- Sending Request -----")
        print(request)
        self.sock.send(request.encode())
        response = self.sock.recv(4096).decode()
        print("----- Received Response -----")
        print(response)
        return response

    def _build_request(self, method, url, extra_headers="", auth=None):
        headers = [
            f"{method} {url} RTSP/1.0",
            f"CSeq: {self.cseq}",
            f"User-Agent: {self.user_agent}"
        ]
        if self.session_id:
            headers.append(f"Session: {self.session_id}")
        if extra_headers:
            headers.append(extra_headers.strip())
        if auth:
            headers.append(f"Authorization: {auth}")
        return "\r\n".join(headers) + "\r\n\r\n"

    def send_rtsp(self, method, url, extra_headers=""):
        req = self._build_request(method, url, extra_headers)
        response = self.send_request(req)
        auth = self.handle_401(response, method, url)
        req = self._build_request(method, url, extra_headers, auth)
        response = self.send_request(req)
        self.cseq += 1
        return response

    def compute_digest_auth(self, www_auth, method, uri):
        realm = re.search(r'realm="([^"]+)"', www_auth).group(1)
        nonce = re.search(r'nonce="([^"]+)"', www_auth).group(1)
        qop_match = re.search(r'qop="([^"]+)"', www_auth)
        qop = qop_match.group(1) if qop_match else None

        ha1 = hashlib.md5(f"{self.username}:{realm}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()

        if qop:
            nc = "00000001"
            cnonce = os.urandom(8).hex()
            response_hash = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
            return (f'Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
                    f'response="{response_hash}", algorithm="MD5", qop={qop}, nc={nc}, cnonce="{cnonce}"')
        else:
            response_hash = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
            return (f'Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
                    f'response="{response_hash}", algorithm="MD5"')

    def handle_401(self, response, method, uri):
        match = re.search(r'WWW-Authenticate:\s*(Digest.*)', response, re.IGNORECASE)
        if match:
            return self.compute_digest_auth(match.group(1).strip(), method, uri)
        raise Exception("Missing WWW-Authenticate header with digest in 401 response.")

    def describe(self):
        resp = self.send_rtsp("DESCRIBE", self.base_url, "Accept: application/sdp")
        if "200 OK" not in resp:
            raise Exception("DESCRIBE failed.")
        sdp_start = resp.find("v=")
        if sdp_start == -1:
            raise Exception("SDP not found in response.")
        sdp = resp[sdp_start:]
        print("----- SDP Received -----")
        print(sdp)
        return sdp

    def setup(self, track_url):
        resp = self.send_rtsp("SETUP", track_url, "Transport: RTP/AVP/TCP;unicast;interleaved=0-1")
        if "200 OK" not in resp:
            raise Exception("SETUP failed.")
        session_match = re.search(r"Session: ([^;\r\n]+)", resp)
        if not session_match:
            raise Exception("Session ID not found in SETUP response.")
        self.session_id = session_match.group(1)
        print("RTSP Session ID:", self.session_id)

    def play(self):
        resp = self.send_rtsp("PLAY", self.base_url)
        if "200 OK" not in resp:
            raise Exception("PLAY failed.")
        return resp

    def teardown(self):
        try:
            resp = self.send_rtsp("TEARDOWN", self.base_url)
            if "200 OK" not in resp:
                print("TEARDOWN failed.")
        finally:
            self.sock.close()

    def receive_data(self, handler_map, timeout=2.0):
        print("Starting data stream... (Ctrl+C to exit)")
        self.sock.settimeout(timeout)
        buffer = b""
        try:
            while True:
                try:
                    data = self.sock.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    print("Server closed connection.")
                    break
                buffer += data
                while len(buffer) >= 4:
                    if buffer[0] == 0x24:  # '$' indicating interleaved RTP/RTCP packet
                        header = buffer[:4]
                        _, channel, length = struct.unpack("!BBH", header)
                        if len(buffer) < 4 + length:
                            break  # Wait for full packet.
                        packet = buffer[4:4+length]
                        buffer = buffer[4+length:]
                        if channel in handler_map:
                            handler_map[channel].handle_packet(packet)
                        else:
                            print(f"No handler registered for channel {channel}")
                    else:
                        end_idx = buffer.find(b"\r\n\r\n")
                        if end_idx != -1:
                            msg = buffer[:end_idx+4].decode()
                            print("RTSP Message:", msg)
                            buffer = buffer[end_idx+4:]
                        else:
                            break
        except KeyboardInterrupt:
            print("Stream interrupted.")

# =============================
# Stream Handlers
# =============================

class StreamHandler:
    def handle_packet(self, packet: bytes):
        raise NotImplementedError("handle_packet must be implemented by subclasses.")

class MetadataHandler(StreamHandler):
    def __init__(self):
        self.xml_buffer = b""

    def handle_packet(self, packet: bytes):
        if len(packet) < 12:
            return
        marker = (packet[1] >> 7) & 0x01
        rtp_payload = packet[12:]
        self.xml_buffer += rtp_payload
        if marker == 1:
            self.process_xml(self.xml_buffer)
            self.xml_buffer = b""

    def process_xml(self, xml_data):
        try:
            xml_text = xml_data.decode('utf-8')
        except UnicodeDecodeError:
            xml_text = xml_data.decode('utf-8', errors='ignore')
        print("----- Received XML Metadata -----")
        print(xml_text)
        try:
            root = ET.fromstring(xml_text)
            ns = {"tt": "http://www.onvif.org/ver10/schema", "bd": "http://www.onvif.org/ver20/analytics/humanbody"}
            for obj in root.findall('.//tt:Object', ns):
                obj_id = obj.get('ObjectId')
                type_elem = obj.find('.//tt:Type', ns)
                if type_elem is not None:
                    print(f"Detected Object - ID: {obj_id}, Type: {type_elem.text}")
            for frame in root.findall('.//tt:Frame', ns):
                utc_time = frame.get('UtcTime')
                if utc_time:
                    print(f"UTC Time: {utc_time}")
        except ET.ParseError as e:
            print("XML Parse Error:", e)

# =============================
# Application Entry Points
# =============================

import os

def run_metadata_client(args):
    base_url = f"rtsp://{args.ip}/axis-media/media.amp?analytics=polygon"
    client = RTSPProtocolClient(args.ip, args.username, args.password, base_url)
    try:
        sdp = client.describe()
        track_control = None
        current_media = None
        for line in sdp.splitlines():
            if line.startswith("m="):
                parts = line.split()
                current_media = parts[0][2:].lower() if parts else None
            elif line.startswith("a=control:") and current_media == "application":
                track_control = line[len("a=control:"):].strip()
                break
        if not track_control:
            raise Exception("Metadata track control URL not found in SDP.")
        # Resolve relative URL if necessary.
        track_url = track_control if track_control.startswith("rtsp://") else f"{client.base_url.rstrip('/')}/{track_control}"
        print("Metadata Track URL:", track_url)
        client.setup(track_url)
        client.play()
        handler_map = {0: MetadataHandler()}
        client.receive_data(handler_map)
    except Exception as e:
        logger.error("Error in metadata client: %s", e)
    finally:
        client.teardown()

def main():
    parser = argparse.ArgumentParser(
        description="RTSP Client for Axis Camera with separate Metadata streams."
    )
    parser.add_argument("--ip", default=os.getenv("RTSP_IP", "192.168.1.81"), help="Camera IP address")
    parser.add_argument("--username", default=os.getenv("RTSP_USERNAME", "root"), help="RTSP username")
    parser.add_argument("--password", default=os.getenv("RTSP_PASSWORD", "fusion"), help="RTSP password")
    args = parser.parse_args()

    run_metadata_client(args)

if __name__ == "__main__":
    main()