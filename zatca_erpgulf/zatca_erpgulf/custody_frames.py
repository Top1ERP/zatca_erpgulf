"""Shared exact bounded binary framing, not authentication or public export.

Domain magic and frame bounds are fixed internal format constants. No repair,
pickle, XML normalization, I/O or interpretation of framed bytes occurs here.
"""


def encode_frames(magic, bounds, parts):
    if len(parts) != len(bounds) or any(type(part) is not bytes or len(part) > bound
                                      for part, bound in zip(parts, bounds)):
        raise ValueError("custody_frame_payload")
    return magic + b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def decode_frames(magic, bounds, content):
    if (type(content) is not bytes or not len(magic) < len(content) <= len(magic) + 4 * len(bounds) + sum(bounds)
        or not content.startswith(magic)):
        raise ValueError("custody_frame_payload")
    offset, parts = len(magic), []
    for bound in bounds:
        if len(content) - offset < 4:
            raise ValueError("custody_frame_payload")
        size = int.from_bytes(content[offset:offset + 4], "big")
        offset += 4
        if size > bound or len(content) - offset < size:
            raise ValueError("custody_frame_payload")
        parts.append(content[offset:offset + size])
        offset += size
    if offset != len(content):
        raise ValueError("custody_frame_payload")
    return tuple(parts)
