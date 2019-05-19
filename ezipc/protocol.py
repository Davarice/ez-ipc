import json


end = b"END\n"
end_ack = b"END_ACK\n"

head_json = b"JSON::"


def serialize(obj):
    return head_json + json.dumps(obj).encode("utf-8") + b"\n"


def is_json(dat: bytes):
    return dat[:len(head_json)] == head_json


def deserialize(dat: bytes):
    return json.loads(dat[len(head_json):-1].decode("utf-8"))
