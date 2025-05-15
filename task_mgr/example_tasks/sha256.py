import os
import secrets

def generate(task_dir):
    input_path = os.path.join(task_dir, "input", "data.bin")
    with open(input_path, "wb") as f:
        f.write(secrets.token_bytes(1024 * 1024))  # 1MB random data

    with open(os.path.join(task_dir, "main.py"), "w") as f:
        f.write("""\
import hashlib
import os

input_file = "input/data.bin"
output_file = "output/sha256.txt"

with open(input_file, "rb") as f:
    data = f.read()

digest = hashlib.sha256(data).hexdigest()

os.makedirs("output", exist_ok=True)
with open(output_file, "w") as f:
    f.write(digest)
""")
