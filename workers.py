import os
import subprocess
import tempfile
import shutil
import time
import logging
from PyQt5.QtCore import QThread, pyqtSignal


# ==========================================
# WORKER: ZIP (Prepares manual files)
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


# ==========================================
# WORKER: WATCHER (Auto-Sender)
# ==========================================
class AutoSendWorker(QThread):
    """
    CLIENT SIDE: Auto-Sender (Watcher Mode)
    Monitors folders. If a file is added/modified, it zips it and pushes it.
    Can also delete the original file upon success.
    """
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, folders, code, _7z_path, remove_sent_files):
        super().__init__()
        self.folders = folders
        self.code = code
        self._7z_path = _7z_path
        self.remove_sent_files = remove_sent_files
        self.is_running = True
        self.temp_dir = None
        self.file_tracker = {}

    def run(self):
        self.log_signal.emit(f"\n[Watcher] 👀 Monitoring {len(self.folders)} folders for changes...")
        if self.remove_sent_files:
            self.log_signal.emit("[Watcher] ℹ️ Auto-Delete is ENABLED. Originals will be deleted after sending.")

        self.temp_dir = tempfile.mkdtemp(prefix="croc_watch_")
        startupinfo = self._get_startup_info()

        while self.is_running:
            files_to_send = []

            # 1. SCAN FOLDERS
            for folder in self.folders:
                if not os.path.exists(folder): continue

                for root, dirs, files in os.walk(folder):
                    for file in files:
                        full_path = os.path.join(root, file)
                        try:
                            mtime = os.path.getmtime(full_path)
                            if full_path not in self.file_tracker or mtime > self.file_tracker[full_path]:
                                files_to_send.append(full_path)
                        except OSError:
                            pass

                            # 2. ZIP AND PUSH NEW FILES
            if files_to_send:
                self.log_signal.emit(f"[Watcher] 🔎 Detected {len(files_to_send)} new/modified items.")

                for file_path in files_to_send:
                    if not self.is_running: break

                    filename = os.path.basename(file_path)
                    zip_path = os.path.join(self.temp_dir, filename + ".7z")

                    self.log_signal.emit(f"[Watcher]   -> Zipping: {filename}")
                    subprocess.run([self._7z_path, "a", "-mx=3", zip_path, file_path],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)

                    # BLOCKING SEND
                    is_success = self.send_file(zip_path, filename, startupinfo)

                    # CLEANUP / DELETE ORIGINALS
                    if is_success:
                        try:
                            self.file_tracker[file_path] = os.path.getmtime(file_path)
                        except:
                            pass

                        # Remove the temporary zip
                        try:
                            os.remove(zip_path)
                        except:
                            pass

                        # Remove original if setting enabled
                        if self.remove_sent_files:
                            try:
                                os.remove(file_path)
                                self.log_signal.emit(f"[Watcher] 🗑️ Removed original: {filename}")
                            except Exception as e:
                                self.log_signal.emit(f"[Watcher] ⚠️ Could not remove original {filename}: {e}")

            # 3. IDLE (Check every 3 seconds)
            for _ in range(30):
                if not self.is_running: break
                time.sleep(0.1)

        self.cleanup()
        self.finished_signal.emit()

    def send_file(self, zip_path, original_name, startupinfo):
        cmd = ["croc", "send", "--code", self.code, zip_path]
        self.log_signal.emit(f"[Watcher] 📡 Hosting '{original_name}' on code '{self.code}'. Waiting for Server...")

        while self.is_running:
            process = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', startupinfo=startupinfo
            )

            for line in process.stdout:
                ln = line.strip()
                if ln and any(k in ln.lower() for k in ["error", "failed", "flag"]):
                    self.log_signal.emit(f"[Watcher] ⚠️ Croc warning: {ln}")

            process.wait()

            if process.returncode == 0:
                self.log_signal.emit(f"[Watcher] ✅ Sent: {original_name}")
                return True
            else:
                self.log_signal.emit(f"[Watcher] 🔄 Server busy/offline. Retrying '{original_name}' in 3s...")
                time.sleep(3)

        return False

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


# ==========================================
# WORKER: SERVER (Auto-Receiver)
# ==========================================
class AutoRecvWorker(QThread):
    """
    SERVER SIDE: Auto-Receiver
    Continuously polls for connection. As soon as Sender pushes a file, it downloads.
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

        poll_count = 0
        while self.is_running:
            # We ONLY use --yes.
            cmd = ["croc", "--yes", "--out", self.target_dir, self.code]

            self.process = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', startupinfo=startupinfo
            )

            for line in self.process.stdout:
                if not self.is_running: break
                ln = line.strip()
                if not ln: continue

                lower_ln = ln.lower()
                # Print real transfer data
                if any(k in lower_ln for k in ["%", "receiving", "download", "mb", "kb", "speed"]):
                    self.log_signal.emit(f"{tag} {ln}")
                # Print IF CROC CRASHES so we actually see the bug
                elif any(k in lower_ln for k in ["error", "flag", "failed", "command not found"]):
                    self.log_signal.emit(f"{tag} ❌ Croc Error: {ln}")

            self.process.wait()
            if not self.is_running: break

            if self.process.returncode == 0:
                self.log_signal.emit(f"{tag} 📥 File Received! Unpacking...")
                self.extract_files(startupinfo, tag)
                poll_count = 0
            else:
                poll_count += 1
                if poll_count >= 10:  # Heartbeat every ~30 seconds
                    self.log_signal.emit(f"{tag} ⏳ Still polling for sender data on '{self.code}'...")
                    poll_count = 0
                time.sleep(3)  # Wait 3s before polling again to prevent relay ban

    def extract_files(self, startupinfo, tag):
        for root, dirs, files in os.walk(self.target_dir):
            for f in files:
                if f.endswith(".7z"):
                    filepath = os.path.join(root, f)
                    subprocess.run([self._7z_path, "x", "-y", filepath, f"-o{root}"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
                    try:
                        os.remove(filepath)
                        self.log_signal.emit(f"{tag} 📦 Unzipped: {f[:-3]}")
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