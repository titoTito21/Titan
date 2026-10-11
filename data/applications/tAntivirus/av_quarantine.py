# -*- coding: utf-8 -*-
"""Quarantine: a threat taken out of the way, and put back if it was wrong.

A quarantined file is not merely moved. Its bytes are written through a
repeating XOR key into ``antivirus/quarantine/<id>.qar`` and the original is
removed, so what sits in the folder is not an executable Windows will run,
not a document an editor will open and not something another antivirus
will flag again on every scan - while restoring it gives back exactly the
bytes that were there, checked against the SHA-256 taken before.

Beside each ``.qar`` is ``<id>.json``: where it came from, what it was
called, the threat, which engine, when, and the digest.
"""

import hashlib
import json
import os
import time
import uuid

import av_store

KEY = b'TitanAntivirusQuarantine\x5a\xa5\x3c\xc3'
CHUNK = 64 * 1024


def _transform(source, target):
    """Copy ``source`` to ``target`` through the key; answer the SHA-256 of
    what was READ (the original on the way in, the stored form on the way
    out)."""
    digest = hashlib.sha256()
    offset = 0
    key_length = len(KEY)
    with open(source, 'rb') as reader, open(target, 'wb') as writer:
        while True:
            block = reader.read(CHUNK)
            if not block:
                break
            digest.update(block)
            shifted = KEY[offset % key_length:] + KEY[:offset % key_length]
            repeated = (shifted * (len(block) // key_length + 1))[:len(block)]
            # One big-integer XOR per block: a byte-at-a-time loop is
            # minutes for a two-hundred-megabyte installer.
            mixed = int.from_bytes(block, 'little') ^ \
                int.from_bytes(repeated, 'little')
            writer.write(mixed.to_bytes(len(block), 'little'))
            offset += len(block)
    return digest.hexdigest()


def _folder():
    return av_store.folder('quarantine')


def put(path, threat='', engine='clamav'):
    """Quarantine ``path``; answer the record. Raises OSError when the file
    cannot be read or removed - a file Windows holds open is one of those,
    and the caller says so rather than pretending."""
    identifier = uuid.uuid4().hex
    stored = os.path.join(_folder(), identifier + '.qar')
    digest = _transform(path, stored)
    try:
        os.remove(path)
    except OSError:
        os.remove(stored)
        raise
    record = {'id': identifier, 'path': os.path.abspath(path),
              'name': os.path.basename(path), 'threat': threat,
              'engine': engine, 'time': time.time(), 'sha256': digest,
              'size': os.path.getsize(stored)}
    with open(os.path.join(_folder(), identifier + '.json'), 'w',
              encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
    return record


def items():
    """Everything in quarantine, newest first."""
    records = []
    try:
        names = os.listdir(_folder())
    except OSError:
        return []
    for name in names:
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(_folder(), name), 'r',
                      encoding='utf-8') as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and os.path.exists(
                os.path.join(_folder(), str(record.get('id')) + '.qar')):
            records.append(record)
    records.sort(key=lambda record: record.get('time', 0), reverse=True)
    return records


def restore(identifier, target=None):
    """Write the file back (to where it was, unless ``target`` says
    otherwise); answer the path. A file already at the target is not
    overwritten - a new name is chosen beside it."""
    record = _record(identifier)
    destination = target or record['path']
    folder = os.path.dirname(destination)
    os.makedirs(folder, exist_ok=True)
    stem, extension = os.path.splitext(destination)
    counter = 1
    while os.path.exists(destination):
        destination = f'{stem} ({counter}){extension}'
        counter += 1
    stored = os.path.join(_folder(), identifier + '.qar')
    _transform(stored, destination)
    if record.get('sha256'):
        digest = hashlib.sha256()
        with open(destination, 'rb') as handle:
            for block in iter(lambda: handle.read(CHUNK), b''):
                digest.update(block)
        # Removed only once it is closed: Windows refuses to delete a file
        # this process still holds open.
        if digest.hexdigest() != record['sha256']:
            os.remove(destination)
            raise ValueError('damaged')
    _forget(identifier)
    return destination


def delete(identifier):
    _record(identifier)
    _forget(identifier)


def _record(identifier):
    path = os.path.join(_folder(), f'{identifier}.json')
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def _forget(identifier):
    for extension in ('.qar', '.json'):
        try:
            os.remove(os.path.join(_folder(), identifier + extension))
        except OSError:
            pass
