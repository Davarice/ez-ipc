import json


end = b"END\n"
end_ack = b"END_ACK\n"

head_json = b"JSON::"


JSON_OPTS = {
    "separators": (",", ":")
}


def decode(dat: bytes):
    return json.loads(dat[len(head_json):-1].decode("utf-8"), **JSON_OPTS)


def encode(obj):
    return head_json + json.dumps(obj, **JSON_OPTS).encode("utf-8") + b"\n"


def is_json(dat: bytes):
    return dat[:len(head_json)] == head_json
