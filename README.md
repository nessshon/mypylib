# mypylib

A Python library for writing background services and daemons.

- **Logging** — colored console output and log file with automatic size control
- **Persistent state** — JSON database with file locking and three-way merge on concurrent access
- **Process management** — single-instance enforcement via PID file, daemon fork, cron `@reboot` registration
- **Health monitoring** — per-process memory usage tracking with configurable warning threshold, thread count
- **Lifecycle** — clean shutdown on `SIGINT` / `SIGTERM`, cyclic worker threads with automatic error isolation
- **systemd integration** — start/stop services, query status/PID/uptime, generate and enable unit files
- **Git helpers** — compare local vs remote HEAD, detect available updates via GitHub API
- **Utilities** — networking (`ping`, `get_own_ip`, interface name), filesystem search, time formatting, ANSI colours

---

### Quick start

```python
import json
from mypylib import MyPyClass, INFO, DEBUG

local = MyPyClass(__file__)


def configure() -> None:
    local.db.config.isStartOnlyOneProcess = False  # default: True
    local.db.config.isLimitLogFile = False         # default: True
    local.db.config.isDeleteOldLogFile = True      # default: False
    local.db.config.isIgnorLogWarning = True       # default: False
    local.db.config.memoryUsinglimit = 20          # MB, default: 50
    local.db.config.isLocaldbSaving = True         # default: False
    local.db.config.isWritingLogFile = False       # default: True
    local.db.config.logLevel = DEBUG               # default: INFO


def general(args: str) -> None:
    local.add_log(f"start general with args: {args}")
    # some code...

    # example:
    print(json.dumps(local.db, indent=4))
    local.print_self_testing_result()


if __name__ == "__main__":
    configure()
    local.run()
    local.cycle(general, sec=3, args=("test args",))
```

---

### Configuration reference

| Key                     | Type   | Default  | Description                                       |
|-------------------------|--------|----------|---------------------------------------------------|
| `isStartOnlyOneProcess` | `bool` | `True`   | Prevent running multiple instances                |
| `isLimitLogFile`        | `bool` | `True`   | Trim log file when it exceeds `logFileSizeLines`  |
| `logFileSizeLines`      | `int`  | `16384`  | Maximum lines kept in the log file                |
| `isDeleteOldLogFile`    | `bool` | `False`  | Delete log file on startup                        |
| `isIgnorLogWarning`     | `bool` | `False`  | Suppress `WARNING`-level log entries              |
| `isWritingLogFile`      | `bool` | `True`   | Write log entries to a file                       |
| `isLocaldbSaving`       | `bool` | `False`  | Persist `local.db` to disk automatically          |
| `memoryUsinglimit`      | `int`  | `50`     | Memory threshold in MB before a warning is logged |
| `logLevel`              | `str`  | `"info"` | Minimum log level: `"info"` or `"debug"`          |

---

### API reference

#### `MyPyClass(file)`

```python
local = MyPyClass(__file__)
```

#### Logging

```python
local.add_log("message")                           # INFO level
local.add_log("message", WARNING)                  # WARNING level
local.add_log("message", ERROR)                    # ERROR level
local.add_log("message", DEBUG)                    # DEBUG level (printed only if logLevel = "debug")
```

#### Lifecycle

```python
local.run()                                        # parse CLI args, start background threads
local.start_cycle(func, sec=5)                     # call func() every 5 seconds in a thread
local.start_cycle(func, sec=5, args=("x",))        # with positional arguments
local.start_thread(func)                           # run func() once in a daemon thread
local.exit()                                       # flush state and exit cleanly
```

#### Persistent storage

```python
local.db.mykey = "value"                           # stored in memory; persisted to disk if isLocaldbSaving = True
local.save_db()                                    # force write to disk immediately
local.load_db()                                    # reload from disk
```

#### System services

```python
local.start_service("nginx")                       # systemctl restart + wait 1 s (default)
local.start_service("nginx", sleep=3)              # systemctl restart + wait 3 s
local.stop_service("nginx")                        # systemctl stop
```

---

### Utility functions

```python
b2mb(bytes)                                        # int -> float MB
get_timestamp()                                    # current Unix timestamp
get_username()                                     # $USER
get_load_avg()                                     # [1m, 5m, 15m] load averages
get_internet_interface_name()                      # primary network interface name
get_own_ip()                                       # public IPv4 address
ping(hostname)                                     # bool

get_service_status(name)                           # bool - is systemd service active
get_service_uptime(name)                           # int seconds or None
get_service_pid(name)                              # int PID or None

get_git_hash(path)                                 # local HEAD commit SHA
get_git_branch(path)                               # current branch name
check_git_update(path)                             # True if remote has newer commits
get_git_last_remote_commit(path)                   # remote HEAD SHA (via GitHub API)

color_text("{red}error{endc}")                     # replace color placeholders with ANSI codes
color_print("{blue}info{endc}")                    # print with color placeholders expanded
timeago(timestamp)                                 # "3 minutes ago"
time2human(seconds)                                # "5 hours"
timestamp2datetime(timestamp)                      # "01.01.2024 12:00:00"

add2systemd(
    name="myapp",                                  # create and enable a systemd unit
    start="/usr/bin/python3 /opt/myapp/main.py",
    user="myapp"
)
```
