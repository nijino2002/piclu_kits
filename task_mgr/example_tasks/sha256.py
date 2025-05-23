import os
import secrets
import json
import textwrap

def generate(task_dir):
    # 写入随机输入数据
    input_path = os.path.join(task_dir, "input", "data.bin")
    with open(input_path, "wb") as f:
        f.write(secrets.token_bytes(1024 * 1024))  # 1MB random data

    # 写入 main.py，统一风格
    main_code = textwrap.dedent("""\
        import hashlib
        import os

        def main():
            input_file = os.path.join("input", "data.bin")
            output_file = os.path.join("output", "sha256.txt")

            if not os.path.exists(input_file):
                raise FileNotFoundError(f"Input file not found: {input_file}")

            with open(input_file, "rb") as f:
                data = f.read()

            digest = hashlib.sha256(data).hexdigest()

            os.makedirs("output", exist_ok=True)
            with open(output_file, "w") as f:
                f.write(digest)

        if __name__ == "__main__":
            try:
                main()
            except Exception as e:
                print(f"[ERROR] Task failed: {e}")
    """)

    with open(os.path.join(task_dir, "main.py"), "w") as f:
        f.write(main_code)

    # 写入任务配置
    config = {
        "use_docker": True,
        "requires_input": True
    }
    with open(os.path.join(task_dir, "task_config.json"), "w") as f:
        json.dump(config, f, indent=2)
