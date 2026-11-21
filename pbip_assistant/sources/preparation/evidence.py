"""Bounded authenticated native package evidence; grants no workbook write authority."""
import base64
from copy import deepcopy
import hashlib
import json
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from pbip_assistant.errors import InputError
from .model import require_hash, require_identifier
from .packages import image_fingerprint
from .image_model import image_full_fingerprint
from .package_preservation import inspect_package, verify_package_image


def _fail(code, message):
    return InputError(code, 'preservation', message)


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError) as exc:
        raise _fail('DP_BACKUP_FAILED', 'Invalid bounded preservation evidence') from exc


class PhysicalBudget:
    """Atomic aggregate leases. No callbacks into another state owner's lock."""
    def __init__(self, max_bytes=256 * 1024 * 1024):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError('Budget must be a positive integer')
        self._max_bytes, self._leases, self._lock = max_bytes, {}, RLock()

    def replace_usage(self, owner_key, new_bytes):
        if not isinstance(owner_key, str) or not owner_key or type(new_bytes) is not int or new_bytes < 0:
            raise ValueError('Invalid physical budget lease')
        with self._lock:
            if sum(self._leases.values()) - self._leases.get(owner_key, 0) + new_bytes > self._max_bytes:
                raise _fail('DP_BACKUP_LIMIT', 'Combined physical recovery budget is exhausted')
            if new_bytes:
                self._leases[owner_key] = new_bytes
            else:
                self._leases.pop(owner_key, None)

    def can_replace(self, owner_key, new_bytes):
        if not isinstance(owner_key, str) or not owner_key or type(new_bytes) is not int or new_bytes < 0:
            raise ValueError("Invalid physical budget lease")
        with self._lock:
            return sum(self._leases.values()) - self._leases.get(owner_key, 0) + new_bytes <= self._max_bytes

    @property
    def usage(self):
        with self._lock:
            return sum(self._leases.values())


class PreservationEvidenceStore:
    def __init__(self, *, clock=time.time, budget=None, max_bytes=64 * 1024 * 1024,
                 total_bytes=256 * 1024 * 1024, start_janitor=False):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError('Evidence budget must be positive')
        self._clock, self._max_bytes = clock, max_bytes
        self._budget = budget or PhysicalBudget(total_bytes)
        self._total_bytes = total_bytes
        self._lease_key = 'evidence_' + uuid4().hex
        self._uploads, self._completed, self._owners = {}, {}, {}
        self._bytes, self._closed = 0, False
        self._lock, self._stop = RLock(), Event()
        self._janitor = None
        if start_janitor:
            self._janitor = Thread(target=self._cleanup_loop, name='preservation-cleanup', daemon=True)
            self._janitor.start()

    def _cleanup_loop(self):
        while not self._stop.wait(30):
            self.expire()

    @property
    def usage(self):
        with self._lock:
            return self._bytes

    def _resize(self, value):
        if value > self._max_bytes:
            raise _fail('DP_BACKUP_LIMIT', 'Native evidence exceeds physical recovery budget')
        self._budget.replace_usage(self._lease_key, value)
        self._bytes = value

    def _reserve_capacity(self, growth, *, slots=0):
        # Completed captures are a volatile read cache. Durable journal images
        # embed their own evidence and remain independently retained.
        while True:
            over_count = len(self._uploads) + len(self._completed) + slots > 64
            try:
                if over_count:
                    raise _fail('DP_BACKUP_LIMIT', 'Native capture cache is full')
                self._resize(self._bytes + growth)
                return
            except InputError:
                if not self._completed:
                    raise
                oldest = next(iter(self._completed))
                item = self._completed.pop(oldest)
                self._resize(self._bytes - len(item['payload']))

    def _drop_upload(self, upload_id):
        upload = self._uploads.pop(upload_id, None)
        if upload:
            self._resize(self._bytes - upload['reserved'])

    def _retire(self, transport):
        for key, value in list(self._uploads.items()):
            if value['transport'] == transport:
                self._drop_upload(key)
        for key, value in list(self._completed.items()):
            if value['transport'] == transport:
                self._resize(self._bytes - len(value['payload']))
                del self._completed[key]
        self._owners.pop(transport, None)

    def expire(self):
        with self._lock:
            now = self._clock()
            for transport, owner in list(self._owners.items()):
                if now >= owner['issued'] + 28800 or now >= owner['touched'] + 1800:
                    self._retire(transport)

    def _owner(self, transport, *, create=False):
        require_identifier(transport)
        self.expire()
        if self._closed:
            raise _fail('DP_POINT_EXPIRED', 'Native evidence service is closed')
        owner = self._owners.get(transport)
        if owner is None:
            if not create:
                raise _fail('DP_POINT_EXPIRED', 'Native evidence expired or belongs to another transport')
            owner = self._owners[transport] = {'issued':self._clock(), 'touched':self._clock()}
        return owner

    def begin(self, transport, byte_length, package_hash):
        with self._lock:
            owner = self._owner(transport, create=True)
            require_hash(package_hash)
            if type(byte_length) is not int or not 0 < byte_length <= 64 * 1024 * 1024:
                raise _fail('DP_BACKUP_LIMIT', 'Native package exceeds compressed evidence bound')
            self._reserve_capacity(byte_length, slots=1)
            upload_id = uuid4().hex
            self._uploads[upload_id] = {'transport':transport, 'reserved':byte_length, 'hash':package_hash,
                'bytes':bytearray(), 'chunks':[], 'next':0}
            owner['touched'] = self._clock()
            return {'uploadId':upload_id, 'maxChunkBytes':1048576}

    def _upload(self, transport, upload_id):
        self._owner(transport)
        require_identifier(upload_id)
        upload = self._uploads.get(upload_id)
        if upload is None or upload['transport'] != transport:
            raise _fail('DP_BINDING_REQUIRED', 'Native upload is not bound to this transport')
        return upload

    def chunk(self, transport, upload_id, index, offset, chunk_hash, data_base64):
        with self._lock:
            upload = self._upload(transport, upload_id)
            try:
                require_hash(chunk_hash)
                if type(index) is not int or index < 0 or type(offset) is not int or offset < 0 or not isinstance(data_base64, str) or len(data_base64) > 1398104:
                    raise ValueError()
                data = base64.b64decode(data_base64, validate=True)
                if not 0 < len(data) <= 1048576 or 'sha256:' + hashlib.sha256(data).hexdigest() != chunk_hash:
                    raise ValueError()
                if index < len(upload['chunks']):
                    old_offset, old_length, old_hash = upload['chunks'][index]
                    if (offset, len(data), chunk_hash) != (old_offset, old_length, old_hash) or bytes(upload['bytes'][offset:offset+len(data)]) != data:
                        raise ValueError()
                else:
                    if index != len(upload['chunks']) or offset != len(upload['bytes']) or offset + len(data) > upload['reserved']:
                        raise ValueError()
                    upload['bytes'].extend(data)
                    upload['chunks'].append((offset,len(data),chunk_hash))
                self._owners[transport]['touched'] = self._clock()
                return {'status':'accepted','nextOffset':len(upload['bytes'])}
            except (ValueError, TypeError, InputError) as exc:
                self._drop_upload(upload_id)
                raise _fail('DP_BACKUP_FAILED', 'Native upload chunk failed integrity or sequence validation') from exc

    def finish(self, transport, upload_id, semantic_image):
        with self._lock:
            upload = self._upload(transport, upload_id)
            try:
                if len(upload['bytes']) != upload['reserved'] or 'sha256:' + hashlib.sha256(upload['bytes']).hexdigest() != upload['hash']:
                    raise _fail('DP_BACKUP_FAILED', 'Native package upload is incomplete or corrupt')
                if len(_json(semantic_image)) > 8 * 1024 * 1024:
                    raise _fail('DP_BACKUP_LIMIT', 'Semantic image exceeds 8 MiB bound')
                semantic = image_fingerprint(semantic_image)
                if semantic_image.get('fingerprint',semantic) != semantic:
                    raise _fail('DP_BACKUP_FAILED', 'Semantic image fingerprint is invalid')
                evidence = inspect_package(bytes(upload['bytes']))
                verify_package_image(evidence, semantic_image)
                evidence_id = uuid4().hex
                full = image_full_fingerprint(semantic_image, evidence['fingerprint'])
                result = {'evidenceId':evidence_id,'preservation':{'version':1,'packageFingerprint':evidence['fingerprint'],'evidenceId':evidence_id},'fullFingerprint':full}
                payload = _json({'evidence':evidence,'packageFingerprint':evidence['fingerprint'], 'semanticFingerprint':semantic,
                    'fullFingerprint':full, 'nativeSheetIds':[s['sheetId'] for s in semantic_image['sheets']]})
                self._reserve_capacity(len(payload) - upload['reserved'])
                del self._uploads[upload_id]
                self._completed[evidence_id] = {'transport':transport,'payload':payload}
                self._owners[transport]['touched'] = self._clock()
                return result
            except Exception:
                self._drop_upload(upload_id)
                raise

    def resolve(self, transport, evidence_id):
        with self._lock:
            self._owner(transport)
            require_identifier(evidence_id)
            value = self._completed.get(evidence_id)
            if value is None or value['transport'] != transport:
                raise _fail('DP_BINDING_REQUIRED', 'Native evidence is not bound to this transport')
            # Resolution is an internal read and cannot refresh either TTL.
            return json.loads(value['payload'])

    def transport_closed(self, transport, _reason=None):
        with self._lock:
            self._retire(transport)

    def close(self):
        self._stop.set()
        if self._janitor:
            self._janitor.join(timeout=1)
        with self._lock:
            self._uploads.clear();self._completed.clear();self._owners.clear()
            self._resize(0);self._closed = True
