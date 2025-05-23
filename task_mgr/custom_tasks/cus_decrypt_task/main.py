#!/usr/bin/env python3
import os
import subprocess
import sys
import zipfile

# === 配置 ===
PASSWORD = "123456"
INPUT_DIR = "./input"
OUTPUT_DIR = "./output"
DECRYPT_SCRIPT = os.path.abspath("aes256_cbc_dec.py")
ZIP_NAME = "decrypted_files.zip"

def ensure_dirs():
    if not os.path.isdir(INPUT_DIR):
        print(f"[ERROR] Input directory '{INPUT_DIR}' does not exist.")
        sys.exit(1)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def decrypt_all_files():
    decrypted_files = []
    for filename in os.listdir(INPUT_DIR):
        input_path = os.path.join(INPUT_DIR, filename)
        if not os.path.isfile(input_path):
            continue

        # 去掉扩展名，例如 myfile.dat.enc → myfile.dat
        if '.' in filename:
            base_name = filename.rsplit('.', 1)[0]
        else:
            base_name = filename

        output_path = os.path.join(OUTPUT_DIR, base_name)

        cmd = [
            sys.executable, DECRYPT_SCRIPT,
            "-p", PASSWORD,
            "-i", input_path,
            "-o", output_path
        ]

        print(f"[INFO] Decrypting '{input_path}' → '{output_path}'...")
        result = subprocess.run(cmd)
        if result.returncode == 0:
            decrypted_files.append(output_path)
        else:
            print(f"[ERROR] Failed to decrypt '{input_path}'")

    return decrypted_files

def zip_files(files, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in files:
            arcname = os.path.basename(file_path)
            zipf.write(file_path, arcname)
    print(f"[OK] Created zip archive: {zip_path}")

def main():
    ensure_dirs()
    decrypted_files = decrypt_all_files()

    if len(decrypted_files) > 1:
        zip_path = os.path.join(OUTPUT_DIR, ZIP_NAME)
        zip_files(decrypted_files, zip_path)

if __name__ == "__main__":
    main()
