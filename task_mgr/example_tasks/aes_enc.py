import os
import secrets
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

def generate(task_dir):
    input_data = secrets.token_bytes(1024 * 1024)
    key = get_random_bytes(32)  # 256-bit
    iv = get_random_bytes(16)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    pad_len = 16 - len(input_data) % 16
    padded_data = input_data + bytes([pad_len] * pad_len)
    encrypted = cipher.encrypt(padded_data)

    with open(os.path.join(task_dir, "input", "data.bin"), "wb") as f:
        f.write(input_data)
    with open(os.path.join(task_dir, "input", "key.bin"), "wb") as f:
        f.write(key)
    with open(os.path.join(task_dir, "input", "enc_data.bin"), "wb") as f:
        f.write(iv + encrypted)

    with open(os.path.join(task_dir, "main.py"), "w") as f:
        f.write("""\
import os

from Crypto.Cipher import AES

def pad(data):
    pad_len = 16 - len(data) % 16
    return data + bytes([pad_len] * pad_len)

with open("input/data.bin", "rb") as f:
    data = f.read()
with open("input/key.bin", "rb") as f:
    key = f.read()

iv = os.urandom(16)
cipher = AES.new(key, AES.MODE_CBC, iv)
enc_data = cipher.encrypt(pad(data))

os.makedirs("output", exist_ok=True)
with open("output/enc_data.bin", "wb") as f:
    f.write(iv + enc_data)
with open("output/key.bin", "wb") as f:
    f.write(key)
""")
