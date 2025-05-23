#!/usr/bin/env python3
import os
import subprocess
import sys
import zipfile

# 可配置参数
PASSWORD = "123456"
INPUT_DIR = "./input"
OUTPUT_DIR = "./output"
ENCRYPT_SCRIPT = os.path.abspath("aes256_cbc_enc.py")
ZIP_NAME = "encrypted_files.zip"

def ensure_dirs():
    if not os.path.isdir(INPUT_DIR):
        print(f"[ERROR] Input directory '{INPUT_DIR}' does not exist.")
        sys.exit(1)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def encrypt_all_files():
    encrypted_files = []
    for filename in os.listdir(INPUT_DIR):
        input_path = os.path.join(INPUT_DIR, filename)
        if not os.path.isfile(input_path):
            continue

        output_filename = filename + ".enc"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        cmd = [
            sys.executable, ENCRYPT_SCRIPT,
            "-p", PASSWORD,
            "-i", input_path,
            "-o", output_path
        ]

        print(f"[INFO] Encrypting '{input_path}' → '{output_path}'...")
        result = subprocess.run(cmd)
        if result.returncode == 0:
            encrypted_files.append(output_path)
        else:
            print(f"[ERROR] Failed to encrypt '{input_path}'")

    return encrypted_files

def zip_files(files, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in files:
            arcname = os.path.basename(file_path)
            zipf.write(file_path, arcname)
    print(f"[OK] Created zip archive: {zip_path}")

def main():
    ensure_dirs()
    encrypted_files = encrypt_all_files()

    if len(encrypted_files) > 1:
        zip_path = os.path.join(OUTPUT_DIR, ZIP_NAME)
        zip_files(encrypted_files, zip_path)

if __name__ == "__main__":
    main()
