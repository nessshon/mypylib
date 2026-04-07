from __future__ import annotations

import base64
import fcntl
import json
import os
import platform
import shlex
import signal
import subprocess
import sys
import threading
import time
import zlib
from collections import deque
from datetime import datetime, timezone
from typing import IO, TYPE_CHECKING, Any, Final, NoReturn

import psutil

from ._colors import Colors, color_text
from ._types import ByteUnit, Dict
from ._utils import (
    convert_bytes,
    ensure_dir_slash,
    get_full_name_from_path,
    get_username,
    read_config_from_file,
)

if TYPE_CHECKING:
    import types
    from collections.abc import Callable

INFO = "info"
WARNING = "warning"
ERROR = "error"
DEBUG = "debug"

_MODE_COLORS: Final[dict[str, str]] = {
    INFO: Colors.INFO,
    WARNING: Colors.WARNING,
    ERROR: Colors.ERROR,
    DEBUG: Colors.DEBUG,
}

_DEFAULT_CONFIG: Final[dict[str, Any]] = {
    "logLevel": INFO,
    "isLimitLogFile": True,
    "isDeleteOldLogFile": False,
    "isIgnorLogWarning": False,
    "isStartOnlyOneProcess": True,
    "memoryUsinglimit": 50,
    "isLocaldbSaving": False,
    "isWritingLogFile": True,
    "logFileSizeLines": 16384,
}


class MyPyClass:
    """Application framework for background services and daemons.

    Manages process lifecycle (PID file, signals), a JSON database
    with three-way merge, colored logging, and background thread cycles.

    :param file: Path to the main script file (typically ``__file__``).
    :param name: Override for the application name.  When set,
        :meth:`get_my_name` returns this value instead of deriving
        it from *file*.
    :param work_dir: Override for the working directory.  When set,
        :meth:`get_my_work_dir` returns this value instead of
        computing it from the user/root convention.
    """

    def __init__(
        self,
        file: str,
        name: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        self.working = True

        self.file = file
        self.name = name
        self.work_dir = work_dir

        self.db = Dict()
        self.db.config = Dict()

        self.buffer = Dict()
        self.buffer.old_db = Dict()
        self.buffer.log_list = deque()
        self.buffer.thread_count = None
        self.buffer.memory_using = None
        self.buffer.free_space_memory = None

        self._file_locks: dict[str, IO[str]] = {}
        self._write_lock = threading.Lock()

        self.refresh()

        signal.signal(signal.SIGINT, self.exit)
        signal.signal(signal.SIGTERM, self.exit)

    def start_service(self, service_name: str, sleep: int = 1) -> None:
        """Restart a systemd service and wait.

        :param service_name: Name of the service unit.
        :param sleep: Seconds to wait after restart.
        """
        self.add_log(f"Start/restart {service_name} service", "debug")
        result = subprocess.run(
            ["systemctl", "restart", service_name],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8").strip()
            self.add_log(f"systemctl restart {service_name} failed: {stderr}", ERROR)
        self.add_log(f"sleep {sleep} sec", "debug")
        time.sleep(sleep)

    def stop_service(self, service_name: str) -> None:
        """Stop a systemd service.

        :param service_name: Name of the service unit.
        """
        self.add_log(f"Stop {service_name} service", "debug")
        result = subprocess.run(
            ["systemctl", "stop", service_name],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8").strip()
            self.add_log(f"systemctl stop {service_name} failed: {stderr}", ERROR)

    def refresh(self) -> None:
        """Recalculate paths, create directories, and reload the database."""
        user = get_username()
        my_name = self.get_my_name()
        my_work_dir = self.get_my_work_dir()
        self.buffer.my_name = my_name
        self.buffer.my_dir = self.get_my_dir()
        self.buffer.my_full_name = self.get_my_full_name()
        self.buffer.my_path = self.get_my_path()
        self.buffer.my_work_dir = my_work_dir
        self.buffer.my_temp_dir = self.get_my_temp_dir()
        self.buffer.log_file_name = my_work_dir + my_name + ".log"
        self.buffer.db_path = my_work_dir + my_name + ".db"
        self.buffer.pid_file_path = my_work_dir + my_name + ".pid"
        self.buffer.venvs_dir = f"/home/{user}/.local/venv"

        os.makedirs(self.buffer.my_work_dir, exist_ok=True)
        os.makedirs(self.buffer.my_temp_dir, exist_ok=True)

        self.load_db()
        self.set_default_config()

        if self.db.config.isDeleteOldLogFile and os.path.isfile(self.buffer.log_file_name):
            os.remove(self.buffer.log_file_name)

    def run(self) -> None:
        """Parse CLI arguments and start background service threads.

        Supported flags:

        - ``-ef`` -- suppress stdout/stderr
        - ``-d`` -- fork as daemon
        - ``-s <path>`` -- load settings from file
        - ``--add2cron`` -- register in crontab
        """
        if "-ef" in sys.argv:
            file = open(os.devnull, "w")  # noqa: SIM115
            sys.stdout = file
            sys.stderr = file
        if "-d" in sys.argv:
            self.fork_daemon()
        if "-s" in sys.argv:
            x = sys.argv.index("-s")
            file_path = sys.argv[x + 1]
            self.get_settings(file_path)
        if "--add2cron" in sys.argv:
            self.add_to_crone()

        if self.db.config.isStartOnlyOneProcess:
            self.start_only_one_process()

        self.start_cycle(self.self_test, sec=1)
        if self.db.config.isWritingLogFile is True:
            self.start_cycle(self.write_log, sec=1)
        if self.db.config.isLocaldbSaving is True:
            self.start_cycle(self.save_db, sec=1)
        self.buffer.thread_count_old = threading.active_count()

        self.add_log(f"Start program `{self.buffer.my_path}`", DEBUG)

    def set_default_config(self) -> None:
        """Populate missing config keys with default values."""
        for key, value in _DEFAULT_CONFIG.items():
            if self.db.config.get(key) is None:
                self.db.config[key] = value

    def start_only_one_process(self) -> None:
        """Ensure only one instance is running; exit if a duplicate exists."""
        pid_file_path = self.buffer.pid_file_path
        if os.path.isfile(pid_file_path) and self._is_duplicate_running(pid_file_path):
            self.add_log("The process is already running", ERROR)
            sys.exit(1)
        self.write_pid()

    def _is_duplicate_running(self, pid_file_path: str) -> bool:
        """Check whether the PID file points to an already-running instance.

        :param pid_file_path: Path to the PID file.
        :return: ``True`` if a matching process is currently running.
        """
        try:
            with open(pid_file_path) as file:
                pid = int(file.read())
            cmdline = " ".join(psutil.Process(pid).cmdline())
        except (ValueError, psutil.Error, OSError):
            return False
        return self.buffer.my_full_name in cmdline

    def write_pid(self) -> None:
        """Write the current process PID to the PID file."""
        pid = os.getpid()
        pid_str = str(pid)
        pid_file_path = self.buffer.pid_file_path
        with open(pid_file_path, "w") as file:
            file.write(pid_str)

    def self_test(self) -> None:
        """Collect memory and thread metrics; warn on high usage."""
        memory_using = convert_bytes(psutil.Process().memory_info().rss, ByteUnit.MB)
        free_space_memory = convert_bytes(psutil.virtual_memory().available, ByteUnit.MB)
        thread_count = threading.active_count()
        self.buffer.memory_using = memory_using
        self.buffer.free_space_memory = free_space_memory
        self.buffer.thread_count = thread_count
        if memory_using > self.db.config.memoryUsinglimit:
            self.db.config.memoryUsinglimit += 50
            self.add_log(
                f"Memory using: {memory_using}Mb, free: {free_space_memory}Mb",
                WARNING,
            )

    def print_self_testing_result(self) -> None:
        """Log current thread count and memory usage."""
        self.add_log(color_text("{blue}Self testing information:{endc}"))
        self.add_log(f"Threads: {self.buffer.thread_count} -> {self.buffer.thread_count_old}")
        self.add_log(f"Memory using: {self.buffer.memory_using}Mb, free: {self.buffer.free_space_memory}Mb")

    @staticmethod
    def get_thread_name() -> str:
        """Return the name of the current thread.

        :return: Thread name string.
        """
        return threading.current_thread().name

    def get_my_full_name(self) -> str:
        """Return the script file name with extension (e.g. ``test.py``).

        :return: File name, or ``"empty"`` if unresolvable.
        """
        my_path = self.get_my_path()
        my_full_name = get_full_name_from_path(my_path)
        if len(my_full_name) == 0:
            my_full_name = "empty"
        return my_full_name

    def get_my_name(self) -> str:
        """Return the script name without extension (e.g. ``test``).

        :return: Base name string.
        """
        if self.name is not None:
            return self.name
        my_full_name = self.get_my_full_name()
        return my_full_name[: my_full_name.rfind(".")]

    def get_my_path(self) -> str:
        """Return the absolute path to the script file.

        :return: Absolute path string.
        """
        return os.path.abspath(self.file)

    def get_my_dir(self) -> str:
        """Return the directory containing the script file.

        :return: Directory path with trailing slash.
        """
        my_path = self.get_my_path()
        my_dir = os.path.dirname(my_path)
        return ensure_dir_slash(my_dir)

    def get_my_work_dir(self) -> str:
        """Return the working directory for runtime files.

        Root: ``/usr/local/bin/<name>/``,
        non-root: ``~/.local/share/<name>/``.

        :return: Directory path with trailing slash.
        """
        if self.work_dir is not None:
            return ensure_dir_slash(os.path.abspath(self.work_dir))
        if self.check_root_permission():
            program_files_dir = "/usr/local/bin/"
        else:
            user_home_dir = ensure_dir_slash(os.getenv("HOME", ""))
            program_files_dir = ensure_dir_slash(os.getenv("XDG_DATA_HOME", user_home_dir + ".local/share/"))
        my_name = self.get_my_name()
        return ensure_dir_slash(program_files_dir + my_name)

    def get_my_temp_dir(self) -> str:
        """Return the temporary directory (``/tmp/<name>/``).

        :return: Directory path with trailing slash.
        """
        temp_files_dir = "/tmp/"  # noqa: S108
        my_name = self.get_my_name()
        return ensure_dir_slash(temp_files_dir + my_name)

    @staticmethod
    def get_lang() -> str:
        """Detect UI language from the ``LANG`` environment variable.

        :return: ``"ru"`` or ``"en"``.
        """
        lang = os.getenv("LANG", "en")
        return "ru" if "ru" in lang else "en"

    @staticmethod
    def check_root_permission() -> bool:
        """Check whether the process is running as root.

        :return: ``True`` if effective UID is 0.
        """
        # Check effective UID instead of touching the filesystem
        return os.geteuid() == 0

    def add_log(self, input_text: object, mode: str = INFO) -> None:
        """Append a log entry to the buffer and print it.

        :param input_text: Message to log.
        :param mode: Log level (``info``, ``warning``, ``error``,
            ``debug``).
        """
        input_text = f"{input_text}"
        utc_now = datetime.now(timezone.utc)
        time_text = utc_now.strftime("%d.%m.%Y, %H:%M:%S.%f")[:-3]
        time_text = f"{time_text} (UTC)".ljust(32, " ")

        if (self.db.config.logLevel != DEBUG and mode == DEBUG) or (
            self.db.config.isIgnorLogWarning and mode == WARNING
        ):
            return

        mode_color = _MODE_COLORS.get(mode, Colors.UNDERLINE) + Colors.BOLD
        mode_text = f"{mode_color}{f'[{mode}]'.ljust(10, ' ')}{Colors.ENDC}"

        thread_color = (Colors.ERROR if mode == ERROR else Colors.OKGREEN) + Colors.BOLD
        thread_name = f"<{self.get_thread_name()}>".ljust(14, " ")
        thread_text = f"{thread_color}{thread_name}{Colors.ENDC}"
        log_text = mode_text + time_text + thread_text + input_text

        self.buffer.log_list.append(log_text)
        print(log_text)

    def write_log(self) -> None:
        """Flush the log buffer to the log file and trim if needed."""
        log_file_name = self.buffer.log_file_name

        with open(log_file_name, "a") as file:
            while self.buffer.log_list:
                file.write(self.buffer.log_list.popleft() + "\n")

        if self.db.config.isLimitLogFile is False:
            return
        log_size = self.db.config.logFileSizeLines or 16384
        line_count = self.count_lines(log_file_name)
        if line_count <= log_size + 256:
            return

        skip = line_count - log_size
        with open(log_file_name) as file:
            lines = file.readlines()
        with open(log_file_name, "w") as file:
            file.writelines(lines[skip:])

    @staticmethod
    def count_lines(filename: str, chunk_size: int = 1 << 13) -> int:
        """Count the number of lines in a file.

        :param filename: Path to the file.
        :param chunk_size: Read buffer size in bytes.
        :return: Line count, or ``0`` if the file does not exist.
        """
        if not os.path.isfile(filename):
            return 0
        with open(filename) as file:
            return sum(chunk.count("\n") for chunk in iter(lambda: file.read(chunk_size), ""))

    @staticmethod
    def dict_to_base64_with_compress(item: Any) -> str:
        """Serialize, compress, and base64-encode a JSON-compatible object.

        :param item: JSON-serializable value.
        :return: Base64 string.
        """
        string = json.dumps(item)
        original = string.encode("utf-8")
        compressed = zlib.compress(original)
        b64 = base64.b64encode(compressed)
        return b64.decode("utf-8")

    @staticmethod
    def base64_to_dict_with_decompress(item: str) -> Any:
        """Decode and decompress a base64 string back to a Python object.

        :param item: Base64-encoded compressed JSON string.
        :return: Deserialized Python object.
        """
        data = item.encode("utf-8")
        b64 = base64.b64decode(data)
        decompress = zlib.decompress(b64)
        original = decompress.decode("utf-8")
        data_dict: Any = json.loads(original)
        return data_dict

    def exit(
        self,
        _signum: int | None = None,
        _frame: types.FrameType | None = None,
    ) -> NoReturn:
        """Gracefully shut down: remove PID file, save state, and exit."""
        self.working = False
        if os.path.isfile(self.buffer.pid_file_path):
            os.remove(self.buffer.pid_file_path)
        self.save()
        sys.exit(0)

    @staticmethod
    def read_file(path: str) -> str:
        """Read and return the entire contents of a text file.

        :param path: File path.
        :return: File contents as a string.
        """
        with open(path) as file:
            return file.read()

    @staticmethod
    def write_file(path: str, text: str = "") -> None:
        """Write text to a file, overwriting any existing content.

        :param path: File path.
        :param text: Content to write.
        """
        with open(path, "w") as file:
            file.write(text)

    def read_db(self, db_path: str) -> Dict:
        """Read the JSON database with retries on failure.

        :param db_path: Path to the database file.
        :return: Parsed database contents.
        :raises RuntimeError: After 10 consecutive failures.
        """
        err: Exception | None = None
        for _ in range(10):
            try:
                return self.read_db_process(db_path)
            except Exception as ex:  # noqa: PERF203
                err = ex
                time.sleep(0.1)
        raise RuntimeError(f"read_db error: {err}") from err

    def read_db_process(self, db_path: str) -> Dict:
        """Parse a single read of the JSON database file.

        :param db_path: Path to the database file.
        :return: Parsed :class:`Dict`.
        """
        text = self.read_file(db_path)
        data = json.loads(text)
        return Dict(data)

    def write_db(self, data: Dict) -> None:
        """Write the database to disk with thread and process locking.

        :param data: Database contents to persist.
        """
        db_path = self.buffer.db_path
        text = json.dumps(data, indent=4)
        # _write_lock: inter-thread safety (save_db cycle thread vs signal handler)
        with self._write_lock:
            # flock: inter-process safety (multiple app instances sharing the same db)
            self.lock_file(db_path)
            try:
                self.write_file(db_path, text)
            finally:
                # Always release flock even if write_file raises
                self.unlock_file(db_path)

    def lock_file(self, path: str) -> None:
        """Acquire an exclusive kernel-level file lock.

        :param path: Path to the file to lock (a ``.lock`` suffix
            is appended).
        """
        lock_path = path + ".lock"
        # Atomic kernel-level lock; blocks until acquired
        fd = open(lock_path, "w")  # noqa: SIM115
        fcntl.flock(fd, fcntl.LOCK_EX)
        self._file_locks[lock_path] = fd

    def unlock_file(self, path: str) -> None:
        """Release a previously acquired file lock.

        :param path: Same path that was passed to :meth:`lock_file`.
        """
        lock_path = path + ".lock"
        fd = self._file_locks.pop(lock_path, None)
        if fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

    def merge_three_dicts(self, local_data: Dict, file_data: Dict, old_file_data: Dict) -> bool:
        """Three-way merge of local, on-disk, and snapshot dictionaries.

        Modifies *local_data* and *file_data* in place.

        :param local_data: Current in-memory state.
        :param file_data: Latest state read from disk.
        :param old_file_data: Snapshot of last known disk state.
        :return: ``True`` if *local_data* was modified and needs writing.
        :raises Exception: If any two arguments are the same object.
        """
        if id(local_data) == id(file_data) or id(file_data) == id(old_file_data) or id(local_data) == id(old_file_data):
            print(local_data.keys())
            print(file_data.keys())
            raise Exception("merge_three_dicts error: merge the same object")

        need_write_local_data = False
        if local_data == file_data and file_data == old_file_data:
            return need_write_local_data

        dict_keys: list[str] = []
        dict_keys += [key for key in local_data if key not in dict_keys]
        dict_keys += [key for key in file_data if key not in dict_keys]
        for key in dict_keys:
            buff = self.merge_three_dicts_process(key, local_data, file_data, old_file_data)
            if buff:
                need_write_local_data = True
        return need_write_local_data

    def merge_three_dicts_process(self, key: str, local_data: Dict, file_data: Dict, old_file_data: Dict) -> bool:
        """Process a single key during three-way merge.

        :param key: Dictionary key to merge.
        :param local_data: Current in-memory state.
        :param file_data: Latest state read from disk.
        :param old_file_data: Snapshot of last known disk state.
        :return: ``True`` if local data was modified.
        """
        need_write_local_data = False
        tmp = self.mtdp_get_tmp(key, local_data, file_data, old_file_data)
        if tmp.local_item != tmp.file_item and tmp.file_item == tmp.old_file_item:
            self.mtdp_flc(key, local_data, file_data, old_file_data)
            need_write_local_data = True
        elif tmp.file_item != tmp.old_file_item:
            self.mtdp_fcfc(key, local_data, file_data, old_file_data)
        return need_write_local_data

    @staticmethod
    def mtdp_get_tmp(key: str, local_data: Dict, file_data: Dict, old_file_data: Dict) -> Dict:
        """Gather values and types for a key across all three dicts.

        :param key: Dictionary key.
        :param local_data: Current in-memory state.
        :param file_data: Latest state read from disk.
        :param old_file_data: Snapshot of last known disk state.
        :return: :class:`Dict` with ``local_item``, ``file_item``,
            ``old_file_item`` and their types.
        """
        tmp = Dict()
        tmp.local_item = local_data.get(key)
        tmp.file_item = file_data.get(key)
        tmp.old_file_item = old_file_data.get(key)
        tmp.local_item_type = type(tmp.local_item)
        tmp.file_item_type = type(tmp.file_item)
        tmp.old_file_item_type = type(tmp.old_file_item)
        return tmp

    def mtdp_flc(self, key: str, local_data: Dict, file_data: Dict, old_file_data: Dict) -> None:
        """Handle merge case: file unchanged, local changed.

        :param key: Dictionary key.
        :param local_data: Current in-memory state.
        :param file_data: Latest state read from disk.
        :param old_file_data: Snapshot of last known disk state.
        """
        dict_types = [dict, Dict]
        tmp = self.mtdp_get_tmp(key, local_data, file_data, old_file_data)
        if (
            tmp.local_item_type in dict_types
            and tmp.file_item_type in dict_types
            and tmp.old_file_item_type in dict_types
        ):
            self.merge_three_dicts(tmp.local_item, tmp.file_item, tmp.old_file_item)

    def mtdp_fcfc(self, key: str, local_data: Dict, file_data: Dict, old_file_data: Dict) -> None:
        """Handle merge case: file changed since last snapshot.

        :param key: Dictionary key.
        :param local_data: Current in-memory state.
        :param file_data: Latest state read from disk.
        :param old_file_data: Snapshot of last known disk state.
        """
        dict_types = [dict, Dict]
        tmp = self.mtdp_get_tmp(key, local_data, file_data, old_file_data)
        if (
            tmp.local_item_type in dict_types
            and tmp.file_item_type in dict_types
            and tmp.old_file_item_type in dict_types
        ):
            self.merge_three_dicts(tmp.local_item, tmp.file_item, tmp.old_file_item)
        elif tmp.file_item is None:
            local_data.pop(key)
        elif tmp.file_item_type not in dict_types:
            local_data[key] = tmp.file_item
        elif tmp.file_item_type in dict_types:
            local_data[key] = Dict(tmp.file_item)
        else:
            raise Exception(
                f"mtdp_fcfc error: {key} -> {tmp.local_item_type}, {tmp.file_item_type}, {tmp.old_file_item_type}"
            )

    def save_db(self) -> None:
        """Read, merge, and write the database atomically.

        Holds both a thread lock and a file lock for the entire
        read-merge-write cycle to prevent lost updates.
        """
        with self._write_lock:
            self.lock_file(self.buffer.db_path)
            try:
                file_data = self.read_db(self.buffer.db_path)
                need_write_local_data = self.merge_three_dicts(self.db, file_data, self.buffer.old_db)
                self.buffer.old_db = Dict(self.db)
                if need_write_local_data:
                    text = json.dumps(self.db, indent=4)
                    self.write_file(self.buffer.db_path, text)
            finally:
                self.unlock_file(self.buffer.db_path)

    def save(self) -> None:
        """Persist the database and flush the log buffer."""
        self.save_db()
        self.write_log()

    def load_db(self, db_path: str = "") -> bool:
        """Load the database from disk into :attr:`db`.

        Creates the file if it does not exist.

        :param db_path: Override path; defaults to the working-dir DB.
        :return: ``True`` on success, ``False`` on error.
        """
        if not db_path:
            db_path = self.buffer.db_path
        if not os.path.isfile(db_path):
            self.write_db(self.db)
        try:
            file_data = self.read_db(db_path)
        except Exception as err:
            self.add_log(f"load_db error: {err}", ERROR)
            return False
        self.db = Dict(file_data)
        self.buffer.old_db = Dict(file_data)
        self.set_default_config()
        return True

    def get_settings(self, file_path: str) -> None:
        """Load settings from a JSON file, save to DB, and exit.

        :param file_path: Path to the settings JSON file.
        """
        try:
            self.db = read_config_from_file(file_path)
            self.save_db()
        except Exception as err:
            self.add_log(f"get_settings error: {err}", ERROR)
            return
        self.add_log(f"get setting successful: {file_path}")
        self.exit()

    @staticmethod
    def get_python3_path() -> str:
        """Return the platform-appropriate Python 3 interpreter path.

        :return: Absolute path to ``python3``.
        """
        python3_path = "/usr/bin/python3"
        if platform.system() == "OpenBSD":
            python3_path = "/usr/local/bin/python3"
        return python3_path

    def fork_daemon(self) -> NoReturn:
        """Fork the current script as a background daemon and exit."""
        my_path = self.buffer.my_path
        python3_path = self.get_python3_path()
        # Use Popen with list args to avoid shell injection
        subprocess.Popen(
            [python3_path, my_path, "-ef"],
            start_new_session=True,
        )
        self.add_log(f"daemon start: {my_path}")
        self.exit()

    def add_to_crone(self) -> NoReturn:
        """Add a ``@reboot`` crontab entry for this script and exit."""
        python3_path = self.get_python3_path()
        cron_text = f"@reboot {python3_path} {shlex.quote(self.buffer.my_path)} -d\n"
        # Read existing crontab and append via stdin
        # to avoid shell injection and temp files
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            check=False,
        )
        existing = result.stdout if result.returncode == 0 else ""
        write = subprocess.run(
            ["crontab", "-"],
            input=existing + cron_text,
            capture_output=True,
            text=True,
            check=False,
        )
        if write.returncode != 0:
            self.add_log(f"crontab update failed: {write.stderr.strip()}", ERROR)
            self.exit()
        self.add_log(f"add to cron successful: {cron_text.strip()}")
        self.exit()

    def try_function(self, func: Callable[..., Any], **kwargs: Any) -> Any:
        """Call *func*, logging any exception instead of propagating it.

        :param func: Callable to invoke.
        :param kwargs: Optional ``args`` tuple to unpack.
        :return: Return value of *func*, or ``None`` on error.
        """
        args = kwargs.get("args")
        try:
            return func(*args) if args is not None else func()
        except Exception as err:
            self.add_log(f"{func.__name__} error: {err}", ERROR)
            return None

    def start_thread(self, func: Callable[..., Any], **kwargs: Any) -> None:
        """Start a daemon thread running *func*.

        :param func: Callable to run in the thread.
        :param kwargs: Optional ``name`` and ``args``.
        """
        name = kwargs.get("name", func.__name__)
        args = kwargs.get("args") or ()
        threading.Thread(target=func, name=name, args=args, daemon=True).start()
        self.add_log(f"Thread {name} started", "debug")

    def cycle(self, func: Callable[..., Any], sec: int, args: tuple[Any, ...] | None) -> None:
        """Repeatedly call *func* every *sec* seconds while running.

        :param func: Callable to invoke each iteration.
        :param sec: Sleep interval between calls.
        :param args: Optional positional arguments for *func*.
        """
        while self.working:
            self.try_function(func, args=args)
            time.sleep(sec)

    def start_cycle(self, func: Callable[..., Any], **kwargs: Any) -> None:
        """Start a background daemon thread that calls *func* in a loop.

        :param func: Callable to invoke repeatedly.
        :param kwargs: Optional ``name``, ``args``, and ``sec`` (interval).
        """
        name = kwargs.get("name", func.__name__)
        args = kwargs.get("args")
        sec = kwargs.get("sec", 1)
        self.start_thread(self.cycle, name=name, args=(func, sec, args))

    def init_translator(self, file_path: str | None = None) -> None:
        """Load a translation dictionary from a JSON file.

        :param file_path: Path to the translations file; defaults to
            ``self.db.translate_file_path``.
        """
        if file_path is None:
            file_path = self.db.translate_file_path
        with open(file_path, encoding="utf-8") as file:
            text = file.read()
        self.buffer.translate = json.loads(text)

    def translate(self, text: str) -> str:
        """Replace known tokens in *text* with their translations.

        :param text: Input string with space-separated tokens.
        :return: String with translated tokens substituted.
        """
        lang = self.get_lang()
        text_list = text.split(" ")
        for item in text_list:
            sitem = self.buffer.translate.get(item)
            if sitem is None:
                continue
            ritem = sitem.get(lang)
            if ritem is not None:
                text = text.replace(item, ritem)
        return text
