#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess

# 自动安装依赖
def ensure_dependencies():
    try:
        import Crypto
    except ImportError:
        print("[INFO] Installing required package 'pycryptodome'...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pycryptodome"])

ensure_dependencies()

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Util.Padding import unpad

def derive_key(password, salt, key_len=32):
    return PBKDF2(password.encode(), salt, dkLen=key_len, count=100_000)

def decrypt_file(password, input_path, output_path):
    with open(input_path, 'rb') as f:
        content = f.read()

    if len(content) < 32:
        print("[ERROR] File too short to contain salt + IV.")
        sys.exit(1)

    salt = content[:16]
    iv = content[16:32]
    ciphertext = content[32:]

    key = derive_key(password, salt)

    try:
        cipher = AES.new(key, AES.MODE_CBC, iv)
        plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
    except ValueError as e:
        print(f"[ERROR] Decryption failed: {e}")
        sys.exit(1)

    with open(output_path, 'wb') as f:
        f.write(plaintext)

    print(f"[OK] Decrypted '{input_path}' to '{output_path}'")

def main():
    parser = argparse.ArgumentParser(description='AES-256-CBC decryption for files using password-derived key.')
    parser.add_argument('-p', '--password', required=True, help='Password to derive the decryption key')
    parser.add_argument('-i', '--input', required=True, help='Input encrypted file (binary)')
    parser.add_argument('-o', '--output', required=True, help='Output decrypted file')

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"[ERROR] Input file '{args.input}' not found.")
        sys.exit(1)

    decrypt_file(args.password, args.input, args.output)

if __name__ == '__main__':
    main()
