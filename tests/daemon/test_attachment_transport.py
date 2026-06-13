"""daemon 附件传输:base64 编解码往返。"""
from argos.daemon.attachments_wire import encode_attachments, decode_attachments
from argos.input.attachments import ImageAttachment

_ATT = ImageAttachment(data=b"\x89PNG\r\n\x1a\nABC", media_type="image/png",
                       source_label="clipboard", width=10, height=10)


def test_encode_decode_roundtrip():
    wire = encode_attachments([_ATT])
    assert isinstance(wire, list)
    assert wire[0]["media_type"] == "image/png"
    assert "data_b64" in wire[0]
    back = decode_attachments(wire)
    assert back[0].data == _ATT.data
    assert back[0].media_type == "image/png"
    assert back[0].width == 10 and back[0].height == 10
    assert back[0].source_label == "clipboard"


def test_encode_empty_is_empty():
    assert encode_attachments([]) == []
    assert encode_attachments(None) == []


def test_decode_empty_is_empty():
    assert decode_attachments(None) == []
    assert decode_attachments([]) == []


def test_decode_skips_malformed():
    """畸形条目(缺 data_b64)跳过,不崩。"""
    good = encode_attachments([_ATT])[0]
    assert decode_attachments([{"media_type": "image/png"}, good]) == decode_attachments([good])
