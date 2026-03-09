"""Generate a temporary JWT keypair for test isolation and print the file path.

Called by tox before pytest starts.  Each invocation produces a unique temp
file so concurrent tox runs never share keys.  All xdist workers within a
single pytest session receive the same path via --jwt-keypair-file.
"""

import json
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
data = {
    "private": key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode(),
    "public": key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode(),
}

f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="gateway_jwt_", delete=False)
json.dump(data, f)
f.close()
print(f.name)
