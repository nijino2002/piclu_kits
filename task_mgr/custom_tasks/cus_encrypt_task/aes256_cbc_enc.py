#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess

# 自动安装 pycryptodome
def ensure_dependencies():
    try:
        import Crypto
    except ImportError:
        print("[INFO] Installing required package 'pycryptodome'...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pycryptodome"])

ensure_dependencies()

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad

def derive_key(password, salt, key_len=32):
    return PBKDF2(password, salt, dkLen=key_len, count=100_000)

def encrypt_file(password, input_path, output_path):
    salt = get_random_bytes(16)
    key = derive_key(password.encode(), salt)
    iv = get_random_bytes(16)

    with open(input_path, 'rb') as f:
        plaintext = f.read()
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext, AES.block_size))

    with open(output_path, 'wb') as f:
        f.write(salt + iv + ciphertext)

    key_info_path = os.path.join(os.path.dirname(output_path), os.path.splitext(os.path.basename(output_path))[0] + ".keyinfo")
    with open(key_info_path, 'w') as f:
        f.write(f"Salt (hex): {salt.hex()}\n")
        f.write(f"IV   (hex): {iv.hex()}\n")
        f.write(f"Key  (hex): {key.hex()}\n")
        f.write(f"PBKDF2 Iterations: 100000\n")
        f.write(f"Key Length: 256 bits\n")
    print(f"[OK] Encrypted '{input_path}' to '{output_path}'")
    print(f"[OK] Key info saved to '{key_info_path}'")

def main():
    parser = argparse.ArgumentParser(description='AES-256-CBC encryption for files using password-derived key.')
    parser.add_argument('-p', '--password', required=True, help='Password to derive the encryption key')
    parser.add_argument('-i', '--input', required=True, help='Input file to encrypt')
    parser.add_argument('-o', '--output', required=True, help='Output encrypted file (binary)')

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"[ERROR] Input file '{args.input}' not found.")
        sys.exit(1)

    encrypt_file(args.password, args.input, args.output)

if __name__ == '__main__':
    main()
