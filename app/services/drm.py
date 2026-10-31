# -*- coding: utf-8 -*-
"""Read Widevine initialization metadata, without requesting or decrypting keys.
Derived from waladir/plugin.video.ivysilani.cz (drake127 & brozikcz).
"""
import re
import struct
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
import urllib.request

DASH = {'d': 'urn:mpeg:dash:schema:mpd:2011'}
WIDEVINE_ID = bytes.fromhex('edef8ba979d64acea3c827dcd51d21ed')
WIDEVINE_SCHEME = 'urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed'
MANIFEST_LIMIT = 1024 * 1024
SEGMENT_PREFIX_LIMIT = 128 * 1024
NETWORK_TIMEOUT = 10

def is_drm_stream(url: str) -> bool:
    """ČT marks the selected stream explicitly; do not guess from its title."""
    return any(value.lower() == 'true' for value in
               parse_qs(urlsplit(url).query).get('drmOnly', []))

def download_segment(url: str, user_agent: str, prefix: bool = False, prefix_bytes: int = SEGMENT_PREFIX_LIMIT):
    headers = {'User-Agent': user_agent}
    limit = min(prefix_bytes, SEGMENT_PREFIX_LIMIT) if prefix else MANIFEST_LIMIT
    if prefix:
        headers['Range'] = f'bytes=0-{limit - 1}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as response:
        data = response.read(limit if prefix else limit + 1)
        if not prefix and len(data) > limit:
            raise ValueError('DASH manifest exceeds size limit')
        return data, response.geturl(), response.headers.get('Date')

def find_widevine_pssh(data: bytes):
    """Find a complete Widevine PSSH in moov/moof; never scan encrypted mdat."""
    def boxes(start, end, depth=0):
        if depth > 8:
            return None
        pos = start
        while pos + 8 <= end:
            size, kind = struct.unpack_from('>I4s', data, pos)
            header = 8
            if size == 1:
                if pos + 16 > end:
                    return None
                size = struct.unpack_from('>Q', data, pos + 8)[0]
                header = 16
            elif size == 0:
                size = end - pos
            if size < header:
                return None
            box_end = pos + size
            if kind in (b'moov', b'moof'):
                found = boxes(pos + header, min(box_end, end), depth + 1)
                if found:
                    return found
            elif (kind == b'pssh' and box_end <= end and size >= header + 24
                  and data[pos + header + 4:pos + header + 20] == WIDEVINE_ID):
                version = data[pos + header]
                offset = pos + header + 20
                if version == 1:
                    if offset + 4 > box_end:
                        return None
                    count = struct.unpack_from('>I', data, offset)[0]
                    offset += 4 + 16 * count
                elif version != 0:
                    return None
                if offset + 4 <= box_end:
                    payload_size = struct.unpack_from('>I', data, offset)[0]
                    if offset + 4 + payload_size == box_end:
                        return data[pos:box_end]
            if box_end > end:
                return None
            pos = box_end
        return None
    return boxes(0, len(data))

def parse_duration(value: str) -> float:
    match = re.fullmatch(r'P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?'
                         r'(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?', value)
    if not match:
        raise ValueError('Unsupported DASH duration')
    return sum(float(part or 0) * scale for part, scale in
               zip(match.groups(), (86400, 3600, 60, 1)))

def parse_timestamp(value: str) -> float:
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()

def media_name(template: str, representation: dict, number: int, segment_time: int) -> str:
    values = {'RepresentationID': representation.get('id', ''),
              'Bandwidth': representation.get('bandwidth', '0'),
              'Number': str(number),
              'Time': str(segment_time)}
    def replace(match):
        spec = match.group(1)
        name = next(k for k in values if spec.startswith(k))
        format_spec = spec[len(name):]
        value = int(values[name]) if format_spec else values[name]
        return format(value, format_spec.lstrip('%') or 's')
    return re.sub(r'\$([^\$]+)\$', replace, template)
