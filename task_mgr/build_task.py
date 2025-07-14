import argparse
import os
import shutil
import tempfile
import zipfile
import json
import textwrap
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
  示例任务模式:
    python build_task.py -e TASK_NAME [-d DEP_ZIP] -o OUTPUT_ZIP

  自定义任务模式:
    python build_task.py -i CODE_DIR [-d INPUT_DIR] -o OUTPUT_ZIP [--no-docker]

Options:
  -e, --example      示例任务名 (sha256, aes_enc, aes_dec)
  -d, --deps / --input-data  示例任务依赖zip包或自定义任务的输入目录
  -i, --input-code   自定义任务的代码目录（必须包含 main.py）
  -o, --output       输出任务包 zip 路径
  --no-docker        不使用 Docker 运行任务（默认使用 Docker）

Examples:
  示例任务：
    python build_task.py -e sha256 -o sha256_task.zip
    python build_task.py -e aes_enc -o aes_enc_task.zip
    python build_task.py -e aes_dec -d aes_enc_task.zip -o aes_dec_task.zip

  自定义任务：
    python build_task.py -i ./mytask -d ./mytask/input -o mytask.zip --no-docker
""")

def build_custom_task(code_dir, input_dir, output_path, use_docker):
    if not os.path.isdir(code_dir):
        raise ValueError(f"Invalid task code directory: {code_dir}")

    if not os.path.isfile(os.path.join(code_dir, "main.py")):
        raise FileNotFoundError("Your custom task must contain a 'main.py' in the root directory.")

    with tempfile.TemporaryDirectory() as temp_dir:
        task_dir = os.path.join(temp_dir, "custom_task")
        os.makedirs(task_dir)

        # 拷贝代码
        for filename in os.listdir(code_dir):
            src = os.path.join(code_dir, filename)
            dst = os.path.join(task_dir, filename)
            if os.path.isfile(src):
                shutil.copy(src, dst)
            elif os.path.isdir(src):
                shutil.copytree(src, dst)

        # 创建 input/output 目录
        os.makedirs(os.path.join(task_dir, "input"), exist_ok=True)
        os.makedirs(os.path.join(task_dir, "output"), exist_ok=True)

        # 拷贝输入数据（如果有）
        if input_dir:
            for filename in os.listdir(input_dir):
                shutil.copy(os.path.join(input_dir, filename), os.path.join(task_dir, "input", filename))

        # 写 requirements.txt（用户手动修改或默认为空）
        write_requirements(task_dir, [])

        # 写 Dockerfile（默认）
        write_dockerfile(task_dir)

        # 写 task_config.json
        config = {
            "use_docker": use_docker,
            "requires_input": bool(input_dir)
        }
        with open(os.path.join(task_dir, "task_config.json"), "w") as f:
            json.dump(config, f, indent=2)

        # 打包
        make_task_zip(task_dir, output_path)
        print(f"[✓] Custom task package created: {output_path}")

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-e", "--example", help="Example task name (sha256, aes_enc, aes_dec)")
    parser.add_argument("-d", "--deps", help="Dependency zip (for aes_dec) or input directory (for custom)")
    parser.add_argument("-i", "--input-code", help="Custom task code directory (must include main.py)")
    parser.add_argument("-o", "--output", required=True, help="Output zip file path")
    parser.add_argument("--no-docker", action="store_true", help="Do not use Docker to run this task")
    args = parser.parse_args()

    if not args.example and not args.input_code:
        print("Error: Must specify either -e for example task or -i for custom task.\n")
        print_usage()
        return

    if args.example:
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

            # 生成任务代码和数据
            if args.example == "sha256":
                sha256.generate(task_dir)
            elif args.example == "aes_enc":
                aes_enc.generate(task_dir)
            elif args.example == "aes_dec":
                aes_dec.generate(task_dir, args.deps)

            write_requirements(task_dir, EXAMPLE_REQUIREMENTS[args.example])
            write_dockerfile(task_dir)

            config = {
                "use_docker": not args.no_docker,
                "requires_input": True
            }
            with open(os.path.join(task_dir, "task_config.json"), "w") as f:
                json.dump(config, f, indent=2)

            make_task_zip(task_dir, args.output)
            print(f"[✓] Example task package created: {args.output}")

    elif args.input_code:
        build_custom_task(args.input_code, args.deps, args.output, not args.no_docker)

if __name__ == "__main__":
    main()
