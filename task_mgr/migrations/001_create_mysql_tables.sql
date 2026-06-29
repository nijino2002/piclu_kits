CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR(32) PRIMARY KEY,
    task_type VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    phase VARCHAR(64) NULL,
    progress INT NOT NULL DEFAULT 0,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    dependency_id VARCHAR(32) NULL,
    worker_id VARCHAR(255) NULL,
    task_package_path VARCHAR(255) NOT NULL,
    result_package_path VARCHAR(255) NULL,
    use_docker BOOLEAN NULL,
    error_message TEXT NULL,
    submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME NULL,
    completed_at DATETIME NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_tasks_dependency FOREIGN KEY (dependency_id) REFERENCES tasks(id) ON DELETE SET NULL,
    INDEX idx_tasks_status_submitted (status, submitted_at),
    INDEX idx_tasks_dependency (dependency_id),
    INDEX ix_tasks_worker_id (worker_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS task_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_id VARCHAR(32) NOT NULL,
    status VARCHAR(20) NOT NULL,
    phase VARCHAR(64) NULL,
    progress INT NULL,
    message TEXT NULL,
    worker_id VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_task_events_task FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    INDEX idx_task_events_task_time (task_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workers (
    id VARCHAR(255) PRIMARY KEY,
    hostname VARCHAR(255) NULL,
    ip_address VARCHAR(45) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'online',
    current_task_id VARCHAR(32) NULL,
    last_heartbeat_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_workers_current_task_id (current_task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
