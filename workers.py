import os
import subprocess
import tempfile
import shutil
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal

# ==========================================
# WORKER: ZIP (Prepares files)
# ==========================================
class ZipWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, str)

    def __init__(self, source_path, _7z_path):
        super().__init__()
        self.source_path = source_path
        self._7z_path = _7z_path

    def run(self):
        try:
            self.log_signal.emit("🗜️ Preparing files for transfer (Zipping)...")
            temp_base_dir = tempfile.mkdtemp(prefix="croc_send_")
            is_dir = os.path.isdir(self.source_path)

            startupinfo = self._get_startup_info()

            if is_dir:
                folder_name = os.path.basename(os.path.normpath(self.source_path))
                staged_path = os.path.join(temp_base_dir, folder_name)
                os.makedirs(staged_path)

                for item in os.listdir(self.source_path):
                    item_full = os.path.join(self.source_path, item)
                    out_7z = os.path.join(staged_path, item + ".7z")
                    self.log_signal.emit(f"  -> Zipping: {item}")
                    subprocess.run([self._7z_path, "a", "-mx=3", out_7z, item_full],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
            else:
                out_7z = os.path.join(temp_base_dir, os.path.basename(self.source_path) + ".7z")
                staged_path = out_7z
                self.log_signal.emit(f"  -> Zipping file...")
                subprocess.run([self._7z_path, "a", "-mx=3", out_7z, self.source_path],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)

            self.log_signal.emit("✅ Zipping complete.")
            self.finished_signal.emit(True, staged_path, temp_base_dir)

        except Exception as e:
            self.log_signal.emit(f"❌ Zip Error: {e}")
            logging.error(f"Zip Error: {e}")
            self.finished_signal.emit(False, "", "")

    def _get_startup_info(self):
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return startupinfo
        return None

# ==========================================
# WORKER: LIVE UNZIP (Manual Receive)
# ==========================================
class LiveUnzipWorker(QThread):
    log_signal = pyqtSignal(str)
    file_extracted_signal = pyqtSignal()

    def __init__(self, download_dir, _7z_path):
        super().__init__()
        self.download_dir = download_dir
        self._7z_path = _7z_path
        self.is_running = True

    def run(self):
        startupinfo = self._get_startup_info()
        while self.is_running:
            self.process_files(startupinfo)
            time.sleep(1.5)
        self.process_files(startupinfo)

    def process_files(self, startupinfo):
        for root, dirs, files in os.walk(self.download_dir):
            for f in files:
                if f.endswith(".7z"):
                    filepath = os.path.join(root, f)
                    if self._is_file_ready(filepath):
                        test_res = subprocess.run([self._7z_path, "t", filepath],
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                  startupinfo=startupinfo)
                        if test_res.returncode == 0:
                            ext_res = subprocess.run([self._7z_path, "x", "-y", filepath, f"-o{root}"],
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                     startupinfo=startupinfo)
                            if ext_res.returncode == 0:
                                try:
                                    os.remove(filepath)
                                    self.log_signal.emit(f"📦 Extracted & Ready: {f[:-3]}")
                                    self.file_extracted_signal.emit()
                                except OSError:
                                    pass

    def _is_file_ready(self, filepath):
        if os.name != 'nt': return True
        try:
            with open(filepath, 'a'):
                pass
            return True
        except IOError:
            return False

    def _get_startup_info(self):
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return startupinfo
        return None

    def stop(self):
        self.is_running = False

# ==========================================
# WORKER: CROC (Manual Send/Recv)
# ==========================================
class CrocWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, bool)

    def __init__(self, command_args):
        super().__init__()
        self.command_args = command_args
        self.process = None
        self.is_killed = False

    def run(self):
        startupinfo = self._get_startup_info()
        try:
            self.process = subprocess.Popen(
                self.command_args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', bufsize=1, startupinfo=startupinfo
            )
            for line in self.process.stdout:
                clean_line = line.strip()
                if clean_line: self.log_signal.emit(clean_line)

            self.process.wait()
            is_success = (self.process.returncode == 0)

            if self.is_killed:
                self.log_signal.emit("\n⏸️ Transfer Paused manually.")
            elif is_success:
                self.log_signal.emit("\n✅ Transfer Completed Successfully!")
            else:
                self.log_signal.emit(f"\n⚠️ Connection dropped. (Code {self.process.returncode})")

            self.finished_signal.emit(self.is_killed, is_success)
        except Exception as e:
            self.log_signal.emit(f"❌ System Error: {str(e)}")
            self.finished_signal.emit(False, False)

    def _get_startup_info(self):
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return startupinfo
        return None

    def stop(self):
        self.is_killed = True
        if self.process: self.process.terminate()


import os
import subprocess
import tempfile
import shutil
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal


# ... [Keep ZipWorker, LiveUnzipWorker, and CrocWorker exactly as they were] ...
# ... [Assuming you have the previous file, I will only paste the CHANGED Auto Workers below] ...

class AutoSendWorker(QThread):
    """
    CLIENT SIDE: Auto-Sender (Watcher Mode)
    1. Monitors a LIST of folders.
    2. Keeps track of files sent (using modification time).
    3. If a NEW file appears or an OLD file is MODIFIED:
       - Zips ONLY that file/folder.
       - Pushes it to the Receiver.
       - Updates the tracker.
    """
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, folders, code, _7z_path):
        super().__init__()
        self.folders = folders  # List of folder paths
        self.code = code
        self._7z_path = _7z_path
        self.is_running = True
        self.temp_dir = None

        # Tracking Dictionary: { 'full_file_path': last_modification_time }
        self.file_tracker = {}

    def run(self):
        self.log_signal.emit(f"\n[Watcher] 👀 Monitoring {len(self.folders)} folders for changes...")
        self.temp_dir = tempfile.mkdtemp(prefix="croc_watch_")

        # Initial Scan (Populate tracker so we don't re-send unchanged files if restarted,
        # or optionally send everything found at start.
        # Strategy: Send everything found at start to ensure sync, then watch.)

        startupinfo = self._get_startup_info()

        while self.is_running:
            files_to_send = []

            # 1. SCAN PHASE
            for folder in self.folders:
                if not os.path.exists(folder): continue

                for root, dirs, files in os.walk(folder):
                    for file in files:
                        full_path = os.path.join(root, file)
                        try:
                            mtime = os.path.getmtime(full_path)
                            # If file is new OR modification time is newer than what we recorded
                            if full_path not in self.file_tracker or mtime > self.file_tracker[full_path]:
                                files_to_send.append(full_path)
                        except OSError:
                            pass  # File might be locked or deleted during scan

            # 2. PROCESS PHASE
            if files_to_send:
                self.log_signal.emit(f"[Watcher] 🔎 Detected {len(files_to_send)} new/modified files.")

                for file_path in files_to_send:
                    if not self.is_running: break

                    # Prepare Zip
                    filename = os.path.basename(file_path)
                    zip_path = os.path.join(self.temp_dir, filename + ".7z")

                    self.log_signal.emit(f"[Watcher]   -> Zipping: {filename}")
                    subprocess.run([self._7z_path, "a", "-mx=3", zip_path, file_path],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)

                    # SEND (Blocking until receiver takes it)
                    self.send_file(zip_path, filename, startupinfo)

                    # Update Tracker (Only if send didn't fail/crash loop)
                    try:
                        self.file_tracker[file_path] = os.path.getmtime(file_path)
                    except:
                        pass

                    # Cleanup zip
                    try:
                        os.remove(zip_path)
                    except:
                        pass

            # 3. WAIT PHASE
            # Check every 3 seconds for new files
            for _ in range(30):
                if not self.is_running: break
                time.sleep(0.1)

        self.cleanup()
        self.finished_signal.emit()

    def send_file(self, zip_path, original_name, startupinfo):
        """
        Loops trying to send a specific file until the receiver accepts it.
        """
        cmd = ["croc", "send", "--code", self.code, zip_path]
        self.log_signal.emit(f"[Watcher] 📡 Sending '{original_name}' on code '{self.code}'...")

        while self.is_running:
            process = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', startupinfo=startupinfo
            )

            # We don't spam logs here, just wait for result
            process.wait()

            if process.returncode == 0:
                self.log_signal.emit(f"[Watcher] ✅ Sent: {original_name}")
                return  # Success, go back to main loop
            else:
                self.log_signal.emit(f"[Watcher] ⏳ Receiver busy or missing. Retrying '{original_name}' in 5s...")
                time.sleep(5)

    def _get_startup_info(self):
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return startupinfo
        return None

    def cleanup(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except:
                pass

    def stop(self):
        self.is_running = False


class AutoRecvWorker(QThread):
    """
    SERVER SIDE: Auto-Receiver
    Continuously loops. If a sender connects, it downloads.
    """
    log_signal = pyqtSignal(str)
    extracted_signal = pyqtSignal()

    def __init__(self, code, base_download_dir, subfolder_name, _7z_path):
        super().__init__()
        self.code = code
        self.target_dir = os.path.join(base_download_dir, subfolder_name)
        self.subfolder_name = subfolder_name
        self._7z_path = _7z_path
        self.is_running = True
        self.process = None

        if not os.path.exists(self.target_dir):
            os.makedirs(self.target_dir)

    def run(self):
        startupinfo = self._get_startup_info()
        tag = f"[Server: {self.subfolder_name}]"

        self.log_signal.emit(f"\n{tag} 🟢 Listening for incoming files on code: '{self.code}'")

        while self.is_running:
            # We add --overwrite to ensure updates to files are saved
            cmd = ["croc", "--yes", "--overwrite", "--out", self.target_dir, self.code]

            self.process = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', startupinfo=startupinfo
            )

            for line in self.process.stdout:
                if not self.is_running: break
                ln = line.strip()
                if ln and any(k in ln.lower() for k in ["%", "receiving", "download", "mb", "kb", "speed"]):
                    self.log_signal.emit(f"{tag} {ln}")

            self.process.wait()
            if not self.is_running: break

            if self.process.returncode == 0:
                self.log_signal.emit(f"{tag} 📥 File Received. Unpacking...")
                self.extract_files(startupinfo, tag)
                # Immediately loop back to catch the next file in the sender's queue
            else:
                # Receiver disconnects or timeout, short sleep before retry
                time.sleep(1)

    def extract_files(self, startupinfo, tag):
        for root, dirs, files in os.walk(self.target_dir):
            for f in files:
                if f.endswith(".7z"):
                    filepath = os.path.join(root, f)
                    subprocess.run([self._7z_path, "x", "-y", filepath, f"-o{root}"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
                    try:
                        os.remove(filepath)
                        self.log_signal.emit(f"{tag} 📦 Processed: {f[:-3]}")
                        self.extracted_signal.emit()
                    except OSError:
                        pass

    def _get_startup_info(self):
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return startupinfo
        return None

    def stop(self):
        self.is_running = False
        if self.process: self.process.terminate()