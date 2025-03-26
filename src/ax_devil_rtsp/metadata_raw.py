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
import logging

logger = logging.getLogger("ax-devil-rtsp.metadata-raw")

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
        logger.debug("----- Sending Request -----")
        logger.debug(request)
        self.sock.send(request.encode())
        response = self.sock.recv(4096).decode()
        logger.debug("----- Received Response -----")
        logger.debug(response)
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
        logger.debug("----- SDP Received -----")
        logger.debug(sdp)
        return sdp

    def setup(self, track_url):
        resp = self.send_rtsp("SETUP", track_url, "Transport: RTP/AVP/TCP;unicast;interleaved=0-1")
        if "200 OK" not in resp:
            raise Exception("SETUP failed.")
        session_match = re.search(r"Session: ([^;\r\n]+)", resp)
        if not session_match:
            raise Exception("Session ID not found in SETUP response.")
        self.session_id = session_match.group(1)
        logger.debug("RTSP Session ID: %s", self.session_id)

    def play(self):
        resp = self.send_rtsp("PLAY", self.base_url)
        if "200 OK" not in resp:
            raise Exception("PLAY failed.")
        return resp

    def teardown(self):
        """
        Close the RTSP session and socket connection.
        """
        logger.info("Tearing down RTSP session")
        try:
            resp = self.send_rtsp("TEARDOWN", self.base_url)
            if "200 OK" not in resp:
                logger.warning("TEARDOWN failed")
        except Exception as e:
            logger.error("Error during TEARDOWN: %s", e)
        finally:
            self.sock.close()
            logger.debug("RTSP session closed")

    def receive_data(self, handler_map, stop_event=None, timeout=2.0):
        """
        Receive and handle RTSP/RTP data.
        
        Args:
            handler_map: Dictionary mapping channel numbers to handlers
            stop_event: Optional threading.Event for controlled shutdown
            timeout: Socket timeout in seconds
        """
        logger.info("Starting data stream...")
        self.sock.settimeout(timeout)
        buffer = b""
        try:
            while not (stop_event and stop_event.is_set()):
                try:
                    data = self.sock.recv(4096)
                    if not data:
                        logger.warning("Server closed connection")
                        break
                    buffer += data
                except socket.timeout:
                    continue
                except (socket.error, OSError) as e:
                    if stop_event and stop_event.is_set():
                        break
                    logger.error("Socket error: %s", e)
                    break

                while len(buffer) >= 4:
                    if buffer[0] == 0x24:  # '$' indicating interleaved RTP/RTCP packet
                        header = buffer[:4]
                        _, channel, length = struct.unpack("!BBH", header)
                        if len(buffer) < 4 + length:
                            break
                        packet = buffer[4:4+length]
                        buffer = buffer[4+length:]
                        if channel in handler_map:
                            handler_map[channel].handle_packet(packet)
                        else:
                            logger.debug("No handler registered for channel %d", channel)
                    else:
                        end_idx = buffer.find(b"\r\n\r\n")
                        if end_idx != -1:
                            msg = buffer[:end_idx+4].decode()
                            logger.debug("RTSP Message: %s", msg)
                            buffer = buffer[end_idx+4:]
                        else:
                            break
        except KeyboardInterrupt:
            logger.info("Stream interrupted")

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
        logger.debug("----- Received XML Metadata -----")
        logger.debug(xml_text)
        try:
            root = ET.fromstring(xml_text)
            ns = {"tt": "http://www.onvif.org/ver10/schema", "bd": "http://www.onvif.org/ver20/analytics/humanbody"}
            for obj in root.findall('.//tt:Object', ns):
                obj_id = obj.get('ObjectId')
                type_elem = obj.find('.//tt:Type', ns)
                if type_elem is not None:
                    logger.info("Detected Object - ID: %s, Type: %s", obj_id, type_elem.text)
            for frame in root.findall('.//tt:Frame', ns):
                utc_time = frame.get('UtcTime')
                if utc_time:
                    logger.debug("UTC Time: %s", utc_time)
        except ET.ParseError as e:
            logger.error("XML Parse Error: %s", e)

# =============================
# Application Entry Points
# =============================

def run_metadata_client(args):
    """
    Run the metadata client with the provided arguments.
    """
    logger.info("Starting metadata client.")
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
        logger.info("Metadata Track URL: %s", track_url)
        client.setup(track_url)
        client.play()
        handler_map = {0: MetadataHandler()}
        client.receive_data(handler_map)
    except Exception as e:
        logger.error("Error in metadata client: %s", e)
    finally:
        client.teardown()
        logger.info("Metadata client stopped.")