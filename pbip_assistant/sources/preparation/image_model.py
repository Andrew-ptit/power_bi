"""Bind approved semantic images to independently retained complete OOXML evidence."""
import re
from pbip_assistant.errors import InputError
from pbip_assistant.sources.assistant_ingest import canonical_hash


def image_full_fingerprint(image, package_fingerprint):
    from .packages import image_fingerprint
    if not isinstance(package_fingerprint, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", package_fingerprint):
        raise InputError("DP_UNSUPPORTED_PRESERVATION", "image", "Invalid native package evidence reference")
    return canonical_hash({"version": 1, "semanticFingerprint": image_fingerprint(image),
                           "packageFingerprint": package_fingerprint})


def preservation_fingerprint(image):
    evidence = image.get("preservation")
    if (not isinstance(evidence, dict) or set(evidence) != {"version", "packageFingerprint", "evidenceId"}
            or evidence["version"] != 1 or not isinstance(evidence["evidenceId"], str)
            or not 0 < len(evidence["evidenceId"]) <= 128):
        raise InputError("DP_UNSUPPORTED_PRESERVATION", "image", "Complete native package evidence is required")
    result = image_full_fingerprint(image, evidence["packageFingerprint"])
    if image.get("fullFingerprint", result) != result:
        raise InputError("DP_BACKUP_FAILED", "image", "Preservation fingerprint does not match native package evidence")
    return result
