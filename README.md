# piclu_kits

本项目是一套用于树莓派集群管理的工具集合，主要提供任务管理、状态记录、Worker管理等能力。

## MySQL 初始化

`init_db.py` 只负责创建表，运行前必须先创建 `piclu` 数据库。

### 1. 登录 MySQL

```powershell
mysql -u root -p
```

### 2. 创建数据库和项目账号

```sql
CREATE DATABASE IF NOT EXISTS piclu
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'piclu'@'localhost'
    IDENTIFIED BY '<your-password>';

GRANT ALL PRIVILEGES ON piclu.* TO 'piclu'@'localhost';

FLUSH PRIVILEGES;
```

请将 `<your-password>` 替换为本地密码。

### 3. 配置当前 PowerShell 环境变量

```powershell
$env:DATABASE_URL="mysql+pymysql://piclu:<your-password>@127.0.0.1:3306/piclu?charset=utf8mb4"
$env:STORAGE_ROOT="E:\piclu_kits\.runtime\storage"
```

### 4. 安装依赖并创建表

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\task_mgr\requirements.txt
python .\task_mgr\init_db.py
```

`init_db.py` 会在 `piclu` 数据库中创建以下表：

```text
tasks
task_events
workers
```
