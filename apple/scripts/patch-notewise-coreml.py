#!/usr/bin/env python3
"""Reproducible, byte-preserving repair of upstream TF divide_no_nan semantics.

Uses the public CoreML protobuf field numbers and locked operation payloads.
No CoreML/protobuf runtime, learned weights, epsilon or detector threshold is used.
"""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "NoteWiseModels"
MODEL = "NoteWiseBasicPitch.mlpackage/Data/com.apple.CoreML/model.mlmodel"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def fields(data):
    position = 0
    def integer():
        nonlocal position
        value = shift = 0
        while position < len(data) and shift < 70:
            byte = data[position]
            position += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
            shift += 7
        raise ValueError("Invalid protobuf varint")
    while position < len(data):
        start = position
        tag = integer()
        number, wire = tag >> 3, tag & 7
        if number < 1:
            raise ValueError("Invalid protobuf field")
        if wire == 2:
            length = integer()
            value = data[position:position + length]
            position += length
        elif wire == 0:
            value = integer()
        elif wire in (1, 5):
            length = 8 if wire == 1 else 4
            value = data[position:position + length]
            position += length
        else:
            raise ValueError("Unsupported protobuf wire type")
        if position > len(data):
            raise ValueError("Truncated protobuf field")
        yield number, wire, value, data[start:position]


def message(number, payload):
    return varint((number << 3) | 2) + varint(len(payload)) + payload


def replace_message(data, number, operation):
    count = 0
    output = bytearray()
    for key, wire, value, raw in fields(data):
        if key == number and wire == 2:
            replacement = operation(value)
            if replacement is not None:
                output.extend(message(key, replacement))
                count += 1
                continue
        output.extend(raw)
    if count != 1:
        raise ValueError("Expected exactly one locked graph path")
    return bytes(output)


def map_value(data, name, operation):
    keys = [v for n, w, v, _ in fields(data) if n == 1 and w == 2]
    if keys != [name.encode()]:
        return None
    return replace_message(data, 2, operation)


def graph(data, operation):
    return replace_message(data, 502, lambda program:
        replace_message(program, 2, lambda function:
            map_value(function, "main", lambda body:
                replace_message(body, 3, lambda block:
                    map_value(block, "CoreML5", operation)))))


def transform(data, patch, restore=False):
    expected = patch["patchedModelSha256" if restore else "upstreamModelSha256"]
    if digest(data) != expected:
        raise ValueError("Model is not the locked input snapshot")
    original = base64.b64decode(patch["originalOperation"], validate=True)
    additions = [base64.b64decode(x, validate=True) for x in patch["replacementOperations"]]
    def rewrite(block):
        entries = list(fields(block))
        operations = [(index, value) for index, (n, w, value, _) in enumerate(entries) if n == 3 and w == 2]
        needle = additions if restore else [original]
        matches = [position for position in range(len(operations) - len(needle) + 1)
                   if [value for _, value in operations[position:position + len(needle)]] == needle]
        if len(matches) != 1:
            raise ValueError("Locked operation sequence is missing or ambiguous")
        offset = matches[0]
        indexes = [index for index, _ in operations[offset:offset + len(needle)]]
        replacement = [original] if restore else additions
        result = bytearray()
        for index, (_, _, _, raw) in enumerate(entries):
            if index == indexes[0]:
                for value in replacement:
                    result.extend(message(3, value))
            if index not in indexes:
                result.extend(raw)
        return bytes(result)
    output = graph(data, rewrite)
    wanted = patch["upstreamModelSha256" if restore else "patchedModelSha256"]
    # During initial payload generation only, the output digest is not populated.
    if wanted and digest(output) != wanted:
        raise ValueError("Repaired model checksum mismatch")
    return output


def load_patch(root=ROOT):
    patch = json.loads((root / "DIVIDE-NO-NAN-PATCH.json").read_text(encoding="utf-8"))
    if patch["patchId"] != "tf-divide-no-nan-coreml5-v1":
        raise ValueError("Unsupported local graph patch")
    return patch


def apply(root=ROOT):
    patch = load_patch(root)
    path = root / MODEL
    data = path.read_bytes()
    if digest(data) == patch["patchedModelSha256"]:
        transform(data, patch, restore=True)  # Verify exact inverse too.
        return
    path.write_bytes(transform(data, patch))


if __name__ == "__main__":
    apply()
    print(json.dumps({"status": "passed", "patchId": "tf-divide-no-nan-coreml5-v1", "nativeInferenceTested": False}))
