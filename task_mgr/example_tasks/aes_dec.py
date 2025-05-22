import os
import shutil
import tempfile
import zipfile
import textwrap

def generate(task_dir, dep_zip_path):
    # 解压依赖 zip
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(dep_zip_path, "r") as zip_ref:
            zip_ref.extractall(tmpdir)
        
        key_path = os.path.join(tmpdir, "input", "key.bin")
        enc_data_path = os.path.join(tmpdir, "input", "enc_data.bin")

        if not os.path.exists(key_path) or not os.path.exists(enc_data_path):
            raise FileNotFoundError("Missing key.bin or enc_data.bin in dependency zip")

        os.makedirs(os.path.join(task_dir, "input"), exist_ok=True)
        os.makedirs(os.path.join(task_dir, "output"), exist_ok=True)

        shutil.copy(key_path, os.path.join(task_dir, "input", "key.bin"))
        shutil.copy(enc_data_path, os.path.join(task_dir, "input", "enc_data.bin"))

    # 写 main.py
    with open(os.path.join(task_dir, "main.py"), "w") as f:
    f.write(textwrap.dedent("""\
        import os
        from Crypto.Cipher import AES

        def unpad(data):
            return data[:-data[-1]]

        def main():
            with open("input/key.bin", "rb") as f:
                key = f.read()
            with open("input/enc_data.bin", "rb") as f:
                raw = f.read()

            iv = raw[:16]
            ciphertext = raw[16:]

            cipher = AES.new(key, AES.MODE_CBC, iv)
            plaintext = unpad(cipher.decrypt(ciphertext))

            os.makedirs("output", exist_ok=True)
            with open("output/dec_data.bin", "wb") as f:
                f.write(plaintext)

        if __name__ == "__main__":
            try:
                main()
            except Exception as e:
                print(f"[ERROR] Task failed: {e}")
    """))
