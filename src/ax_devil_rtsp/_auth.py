"""Shared Basic and Digest authentication for RTSP and HTTP."""

import base64
import hashlib
import re
import secrets


def _md5(text: str) -> str:
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def digest_response(
    username: str,
    password: str,
    realm: str,
    nonce: str,
    method: str,
    uri: str,
    *,
    qop: str = "",
    nc: str = "",
    cnonce: str = "",
) -> str:
    """Return the RFC 2617 MD5 digest response."""
    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    if qop:
        return _md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    return _md5(f"{ha1}:{nonce}:{ha2}")


def _parse_challenge(header: str) -> tuple[str, dict[str, str]]:
    scheme, _, rest = header.strip().partition(" ")
    params = {key.lower(): value.strip('"') for key, value in re.findall(r'(\w+)=("[^"]*"|[^\s,]*)', rest)}
    return scheme.lower(), params


def _pick_challenge(headers: list[str]) -> tuple[str, dict[str, str]] | None:
    challenges = [_parse_challenge(header) for header in headers]
    for scheme, params in challenges:
        if scheme == "digest" and params.get("algorithm", "MD5").upper() == "MD5":
            return scheme, params
    return next((challenge for challenge in challenges if challenge[0] == "basic"), None)


def _authorization(
    username: str, password: str, challenge: tuple[str, dict[str, str]], method: str, uri: str, nc: int
) -> str:
    """Return the Authorization header value answering `challenge`; `nc` counts the uses of its nonce."""
    scheme, params = challenge
    if scheme == "basic":
        return f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
    realm, nonce = params.get("realm", ""), params.get("nonce", "")
    fields = [f'username="{username}"', f'realm="{realm}"', f'nonce="{nonce}"', f'uri="{uri}"']
    if "auth" in (qop.strip() for qop in params.get("qop", "").split(",")):
        nc_value, cnonce = f"{nc:08x}", secrets.token_hex(8)
        response = digest_response(
            username, password, realm, nonce, method, uri, qop="auth", nc=nc_value, cnonce=cnonce
        )
        fields += [f'response="{response}"', "qop=auth", f"nc={nc_value}", f'cnonce="{cnonce}"']
    else:
        fields.append(f'response="{digest_response(username, password, realm, nonce, method, uri)}"')
    if "opaque" in params:
        fields.append(f'opaque="{params["opaque"]}"')
    if "algorithm" in params:
        fields.append(f"algorithm={params['algorithm']}")
    return f"Digest {', '.join(fields)}"
