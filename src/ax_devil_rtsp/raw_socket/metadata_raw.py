import socket
import re
import hashlib
import struct
import os
import threading
from typing import Optional

from ..logging import get_logger

logger = get_logger("raw_socket.metadata_raw")


class SceneMetadataRawClient:
    """
    A raw socket implementation of RTSP client for retrieving Axis Scene Metadata.
    This implementation avoids using GStreamer and implements the RTSP protocol directly.
    """

    def __init__(self, rtsp_url, latency=100, raw_data_callback=None, timeout: Optional[float] = None,):
        """
        Initialize the RTSP client.

        Args:
            rtsp_url (str): The full RTSP URL.
            latency (int): The latency setting (in milliseconds).
            raw_data_callback (callable): A callback function accepting raw XML string.
        """
        self.rtsp_url = rtsp_url
        self.latency = latency
        self.raw_data_callback = raw_data_callback

        # Extract connection details from URL
        match = re.match(
            r'rtsp://(?:([^:@]+)(?::([^@]+))?@)?([^:/]+)(?::(\d+))?(?:/.*)?', rtsp_url)
        if not match:
            raise ValueError("Invalid RTSP URL format")

        self.username = match.group(1) or ''
        self.password = match.group(2) or ''
        self.ip = match.group(3)
        self.port = int(match.group(4) or 554)

        # RTSP state
        self.cseq = 1
        self.session_id = None
        self.sock = None
        self.xml_buffer = b""

        self._timeout = timeout
        self._timer: Optional[None | threading.Timer] = None

    def _connect(self):
        """Establish TCP connection to RTSP server."""
        if self.sock:
            logger.debug("Closing existing socket connection")
            self.sock.close()
        
        logger.debug(f"Attempting TCP connection to {self.ip}:{self.port}")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((self.ip, self.port))
            logger.info(f"Successfully connected to RTSP server {self.ip}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to RTSP server {self.ip}:{self.port}: {e}")
            raise

    def _send_request(self, request):
        """Send RTSP request and receive response."""
        logger.debug("----- Sending Request -----\n%s", request)
        self.sock.send(request.encode())
        response = self.sock.recv(4096).decode()
        logger.debug("----- Received Response -----\n%s", response)
        return response

    def _build_request(self, method, url, extra_headers="", auth=None):
        """Build RTSP request with headers."""
        headers = [
            f"{method} {url} RTSP/1.0",
            f"CSeq: {self.cseq}",
            "User-Agent: ax-devil-RTSPClient/1.0"
        ]
        if self.session_id:
            headers.append(f"Session: {self.session_id}")
        if extra_headers:
            headers.append(extra_headers.strip())
        if auth:
            headers.append(f"Authorization: {auth}")
        return "\r\n".join(headers) + "\r\n\r\n"

    def _compute_digest_auth(self, www_auth, method, uri):
        """Compute digest authentication response."""
        realm = re.search(r'realm="([^"]+)"', www_auth).group(1)
        nonce = re.search(r'nonce="([^"]+)"', www_auth).group(1)
        qop_match = re.search(r'qop="([^"]+)"', www_auth)
        qop = qop_match.group(1) if qop_match else None

        ha1 = hashlib.md5(
            f"{self.username}:{realm}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()

        if qop:
            nc = "00000001"
            cnonce = os.urandom(8).hex()
            response_hash = hashlib.md5(
                f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
            return (f'Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
                    f'response="{response_hash}", algorithm="MD5", qop={qop}, nc={nc}, cnonce="{cnonce}"')
        else:
            response_hash = hashlib.md5(
                f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
            return (f'Digest username="{self.username}", realm="{realm}", nonce="{nonce}", uri="{uri}", '
                    f'response="{response_hash}", algorithm="MD5"')

    def _handle_401(self, response, method, uri):
        """Handle 401 Unauthorized response."""
        match = re.search(r'WWW-Authenticate:\s*(Digest.*)',
                          response, re.IGNORECASE)
        if match:
            return self._compute_digest_auth(match.group(1).strip(), method, uri)
        raise Exception(
            "Missing WWW-Authenticate header with digest in 401 response.")

    def _send_rtsp(self, method, url, extra_headers=""):
        """Send RTSP request with authentication handling."""
        if not self.sock:
            self._connect()

        req = self._build_request(method, url, extra_headers)
        response = self._send_request(req)
        if "401 Unauthorized" in response:
            auth = self._handle_401(response, method, url)
            req = self._build_request(method, url, extra_headers, auth)
            response = self._send_request(req)
        self.cseq += 1
        return response

    def _handle_metadata_packet(self, packet):
        """Handle RTP packet containing metadata."""
        if len(packet) < 12:
            return

        marker = (packet[1] >> 7) & 0x01
        rtp_payload = packet[12:]
        self.xml_buffer += rtp_payload

        if marker == 1:
            try:
                xml_text = self.xml_buffer.decode('utf-8')
            except UnicodeDecodeError:
                xml_text = self.xml_buffer.decode('utf-8', errors='ignore')

            if xml_text and self.raw_data_callback:
                try:
                    self.raw_data_callback(xml_text)
                except Exception as e:
                    logger.error("Error in raw data callback: %s", e)
            self.xml_buffer = b""

    def _timeout_handler(self) -> None:
        """Handle timeout by stopping client."""
        logger.warning(f"Timeout reached ({self._timeout}s), stopping client")
        self.stop()

    def start(self):
        """Start the metadata client and begin receiving data."""
        logger.info("Starting SceneMetadataRawClient")
        try:
            if self._timeout:
                self._timer = threading.Timer(
                    self._timeout, self._timeout_handler)
                self._timer.start()

            self._connect()

            # DESCRIBE
            resp = self._send_rtsp(
                "DESCRIBE", self.rtsp_url, "Accept: application/sdp")
            if "200 OK" not in resp:
                raise Exception("DESCRIBE failed")

            # Parse SDP for metadata track
            sdp_start = resp.find("v=")
            if sdp_start == -1:
                raise Exception("SDP not found in response")
            sdp = resp[sdp_start:]

            # Find metadata track control URL
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
                raise Exception("Metadata track control URL not found in SDP")

            # Resolve track URL
            track_url = track_control if track_control.startswith(
                "rtsp://") else f"{self.rtsp_url.rstrip('/')}/{track_control}"

            # SETUP
            resp = self._send_rtsp(
                "SETUP", track_url, "Transport: RTP/AVP/TCP;unicast;interleaved=0-1")
            if "200 OK" not in resp:
                raise Exception("SETUP failed")

            session_match = re.search(r"Session: ([^;\r\n]+)", resp)
            if not session_match:
                raise Exception("Session ID not found in SETUP response")
            self.session_id = session_match.group(1)

            # PLAY
            resp = self._send_rtsp("PLAY", self.rtsp_url)
            if "200 OK" not in resp:
                raise Exception("PLAY failed")

            if self._timer is not None:
                self._timer.cancel()

            # Receive data
            self._receive_data()

        except Exception as e:
            logger.error("Error in metadata client: %s", e)
            raise
        finally:
            self.stop()

    def stop(self):
        """Stop the metadata client and clean up resources."""
        logger.info("Stopping SceneMetadataRawClient")
        
        # Cancel timeout timer if it exists
        if self._timer and self._timer.is_alive():
            logger.debug("Canceling raw socket timeout timer")
            self._timer.cancel()
            logger.debug("Raw socket timeout timer canceled")
        elif self._timer:
            logger.debug("Raw socket timeout timer exists but is not alive")
        else:
            logger.debug("No raw socket timeout timer to cancel")
            
        if self.sock:
            try:
                if self.session_id:
                    self._send_rtsp("TEARDOWN", self.rtsp_url)
            except Exception as e:
                logger.error("Error during TEARDOWN: %s", e)
            finally:
                self.sock.close()
                self.sock = None
        logger.debug("Client stopped")

    def _receive_data(self):
        """Receive and process RTP/RTCP data."""
        logger.info("Starting data stream...")
        self.sock.settimeout(4.0)
        buffer = b""

        try:
            while True:
                try:
                    data = self.sock.recv(4096)
                    if not data:
                        logger.warning("Server closed connection")
                        break
                    buffer += data
                except socket.timeout:
                    continue
                except (socket.error, OSError) as e:
                    logger.error("Socket error: %s", e)
                    break

                while len(buffer) >= 4:
                    if buffer[0] == 0x24:  # '$' indicating interleaved RTP/RTCP
                        header = buffer[:4]
                        _, channel, length = struct.unpack("!BBH", header)

                        if len(buffer) < 4 + length:
                            break

                        packet = buffer[4:4+length]
                        buffer = buffer[4+length:]

                        if channel == 0:  # RTP data channel
                            self._handle_metadata_packet(packet)
                    else:
                        # Handle RTSP message
                        end_idx = buffer.find(b"\r\n\r\n")
                        if end_idx != -1:
                            buffer = buffer[end_idx+4:]
                        else:
                            break

        except KeyboardInterrupt:
            logger.info("Stream interrupted")
