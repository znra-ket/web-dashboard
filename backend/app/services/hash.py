from hashlib import sha256


def calculate_script_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()
