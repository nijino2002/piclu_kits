import argparse
import os
import shutil
import tempfile
import zipfile
from example_tasks import sha256, aes_enc, aes_dec

EXAMPLE_REQUIREMENTS = {
    "sha256": [],
    "aes_enc": ["pycryptodome"],
    "aes_dec": ["pycryptodome"]
}

DOCKERFILE_TEMPLATE = """\
FROM dockerproxy.net/library/python:3.11-slim-bookworm

RUN apt-get update \\
    && apt-get install -y --no-install-recommends python3 python3-pip \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /task
COPY . /task
RUN pip3 install --no-cache-dir -r requirements.txt || true

CMD ["python3", "main.py"]
"""

def write_requirements(task_dir, packages):
    req_path = os.path.join(task_dir, "requirements.txt")
    with open(req_path, "w") as f:
        f.write("\n".join(packages) + "\n") if packages else f.write("")

def write_dockerfile(task_dir):
    with open(os.path.join(task_dir, "Dockerfile"), "w") as f:
        f.write(DOCKERFILE_TEMPLATE)

def make_task_zip(task_dir, output_path):
    shutil.make_archive(output_path.replace(".zip", ""), "zip", root_dir=task_dir)

def print_usage():
    print("""
Usage:
  python build_task.py -e TASK_NAME [-d DEP_ZIP] -o OUTPUT_ZIP

Options:
  -e, --example   示例任务名 (sha256, aes_enc, aes_dec)
  -d, --deps      依赖的加密任务 zip 包路径（仅 aes_dec 需要）
  -o, --output    输出任务包 zip 路径

Examples:
  python build_task.py -e sha256 -o sha256_task.zip
  python build_task.py -e aes_enc -o aes_enc_task.zip
  python build_task.py -e aes_dec -d aes_enc_task.zip -o aes_dec_task.zip
""")

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-e", "--example", help="Example task name (sha256, aes_enc, aes_dec)")
    parser.add_argument("-d", "--deps", help="Dependency zip file (for aes_dec)")
    parser.add_argument("-o", "--output", required=True, help="Output zip file path")
    args = parser.parse_args()

    if not args.example:
        print("Error: Missing required -e/--example argument.\n")
        print_usage()
        return

    if args.example not in EXAMPLE_REQUIREMENTS:
        print(f"Error: Unsupported example task '{args.example}'\n")
        print_usage()
        return

    if args.example == "aes_dec" and not args.deps:
        print("Error: aes_dec requires -d <enc_task.zip> dependency.\n")
        print_usage()
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        task_dir = os.path.join(temp_dir, "example_task")
        os.makedirs(os.path.join(task_dir, "input"), exist_ok=True)
        os.makedirs(os.path.join(task_dir, "output"), exist_ok=True)

        # 生成代码和数据
        if args.example == "sha256":
            sha256.generate(task_dir)
        elif args.example == "aes_enc":
            aes_enc.generate(task_dir)
        elif args.example == "aes_dec":
            aes_dec.generate(task_dir, args.deps)

        # 写入 requirements.txt 和 Dockerfile
        reqs = EXAMPLE_REQUIREMENTS[args.example]
        write_requirements(task_dir, reqs)
        write_dockerfile(task_dir)

        # 打包
        make_task_zip(task_dir, args.output)
        print(f"Task package created: {args.output}")

if __name__ == "__main__":
    main()
