import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
import winreg
from ctypes import wintypes
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = '1.0.0'
APP = 'Aion2Helper'
PROTOCOL = 'aion2helper'
REPO = 'Vanya-ID/aion2-helper'
SITE = 'https://vanya-id.github.io/aion2-helper/'
EXE_URL = f'https://github.com/{REPO}/releases/latest/download/aion2-helper.exe'
PORT = 47123
LOCAL_URL = f'http://127.0.0.1:{PORT}/'
ALLOWED_ORIGINS = {f'http://127.0.0.1:{PORT}', 'https://vanya-id.github.io'}
SHOW_SECONDS = 10
TOP_OFFSET = 40
NEXT_COUNT = 3

FROZEN = getattr(sys, 'frozen', False)
HOME = Path(os.environ['LOCALAPPDATA']) / APP if FROZEN else Path(__file__).resolve().parent
INSTALLED_EXE = HOME / 'aion2-helper.exe'
SETTINGS_FILE = HOME / 'overlay-settings.json'
HOME.mkdir(parents=True, exist_ok=True)

if sys.stderr is None:
    sys.stderr = open(HOME / 'overlay.log', 'a', encoding='utf-8')
    sys.stdout = sys.stderr

user32 = ctypes.windll.user32
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_TOOLWINDOW = 0x80
WS_EX_LAYERED = 0x80000
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE = 0x1
SWP_NOMOVE = 0x2
SWP_NOACTIVATE = 0x10
SWP_SHOWWINDOW = 0x40
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
MOD_ALT = 0x1
MOD_CONTROL = 0x2
MOD_SHIFT = 0x4
MOD_NOREPEAT = 0x4000
VK_Q = 0x51
WM_HOTKEY = 0x0312
WM_APP = 0x8000
MB_ICONINFORMATION = 0x40
MB_ICONERROR = 0x10
CREATE_NO_WINDOW = 0x08000000
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
PROTOCOL_KEY = rf'Software\Classes\{PROTOCOL}'

messages = queue.Queue()
schedule = {'events': [], 'seconds': SHOW_SECONDS}
hotkey = {'mods': MOD_CONTROL | MOD_ALT, 'vk': VK_Q, 'label': 'Ctrl+Alt+Q', 'ok': False}
hotkey_requests = queue.Queue()
hotkey_results = queue.Queue()
hotkey_thread = {'id': None}
update_state = {'running': False, 'error': ''}


def desktop_dir():
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
    return Path(buf.value)


def desktop_link():
    return desktop_dir() / 'Aion 2 трекер.url'


def message_box(text, error=False):
    user32.MessageBoxW(None, text, 'Aion 2 — помощник', MB_ICONERROR if error else MB_ICONINFORMATION)


def register():
    exe = str(INSTALLED_EXE)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, APP, 0, winreg.REG_SZ, f'"{exe}"')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PROTOCOL_KEY) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, 'URL:Aion 2 helper')
        winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PROTOCOL_KEY + r'\shell\open\command') as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f'"{exe}" "%1"')
    link = f'[InternetShortcut]\r\nURL={SITE}\r\nIconFile={exe}\r\nIconIndex=0\r\n'
    desktop_link().write_text(link, encoding='utf-16')


def unregister():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, APP)
        except FileNotFoundError:
            pass
    for sub in (r'\shell\open\command', r'\shell\open', r'\shell', ''):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, PROTOCOL_KEY + sub)
        except FileNotFoundError:
            pass
    desktop_link().unlink(missing_ok=True)


def quit_running_instance():
    request = urllib.request.Request(f'{LOCAL_URL}quit', method='POST')
    try:
        urllib.request.urlopen(request, timeout=2)
    except OSError:
        return
    for _ in range(20):
        time.sleep(0.25)
        try:
            urllib.request.urlopen(f'{LOCAL_URL}ping', timeout=1)
        except OSError:
            return


def retry(action, attempts=20):
    for attempt in range(attempts):
        try:
            return action()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25)


def install():
    quit_running_instance()
    data = Path(sys.executable).read_bytes()
    retry(lambda: INSTALLED_EXE.write_bytes(data))
    register()
    subprocess.Popen([str(INSTALLED_EXE), '--restart'])
    if '--silent' in sys.argv:
        return
    webbrowser.open(SITE)
    message_box('Плашка установлена и будет запускаться вместе с Windows.\n\n'
                'Трекер открыт в браузере, на рабочем столе ярлык «Aion 2 трекер».\n'
                'Если браузер спросит про доступ к устройствам в локальной сети — нажми «Разрешить».')


def self_update():
    new_exe = HOME / 'aion2-helper.new.exe'
    old_exe = HOME / 'aion2-helper.old.exe'
    try:
        urllib.request.urlretrieve(EXE_URL, new_exe)
        old_exe.unlink(missing_ok=True)
        os.replace(INSTALLED_EXE, old_exe)
        os.replace(new_exe, INSTALLED_EXE)
    except OSError as error:
        print(f'update failed: {error!r}', file=sys.stderr, flush=True)
        update_state.update(running=False, error=str(error))
        return
    messages.put('restart')


def uninstall():
    unregister()
    script = f'for /l %i in (1,1,20) do if exist "{HOME}" (ping -n 2 127.0.0.1 >nul & rmdir /s /q "{HOME}")'
    subprocess.Popen(f'cmd /c {script}', cwd=os.environ['TEMP'], creationflags=CREATE_NO_WINDOW)
    messages.put(None)


class Server(ThreadingHTTPServer):
    allow_reuse_address = False


class Handler(SimpleHTTPRequestHandler):
    def origin_allowed(self):
        origin = self.headers.get('Origin')
        return origin is None or origin in ALLOWED_ORIGINS

    def do_OPTIONS(self):
        if not self.origin_allowed():
            self.reply(403, b'forbidden')
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if not self.origin_allowed():
            self.reply(403, b'forbidden')
            return
        if self.path == '/ping':
            self.reply_json({'version': VERSION, 'frozen': FROZEN, 'updating': update_state['running'], 'updateError': update_state['error']})
            return
        if self.path == '/hotkey':
            self.reply_json({'label': hotkey['label'], 'ok': hotkey['ok']})
            return
        if FROZEN:
            self.send_response(302)
            self.send_header('Location', SITE)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self):
        if not self.origin_allowed():
            self.reply(403, b'forbidden')
            return
        if self.path == '/quit':
            messages.put(None)
            self.reply(204, b'')
            return
        if self.path in ('/update', '/uninstall'):
            if not FROZEN:
                self.reply_json({'error': 'only the installed program can do this'}, 409)
                return
            if self.path == '/update':
                if not update_state['running']:
                    update_state.update(running=True, error='')
                    threading.Thread(target=self_update, daemon=True).start()
            else:
                uninstall()
            self.reply(202, b'')
            return
        if self.path not in ('/notify', '/schedule', '/hotkey'):
            self.reply(404, b'not found')
            return
        length = int(self.headers.get('Content-Length', 0))
        data = json.loads(self.rfile.read(length) or b'{}')
        if self.path == '/hotkey':
            hotkey_requests.put({'mods': int(data['mods']) & (MOD_ALT | MOD_CONTROL | MOD_SHIFT), 'vk': int(data['vk']), 'label': str(data['label'])[:40]})
            user32.PostThreadMessageW(hotkey_thread['id'], WM_APP, 0, 0)
            try:
                changed = hotkey_results.get(timeout=3)
            except queue.Empty:
                changed = False
            self.reply_json({'changed': changed, 'label': hotkey['label'], 'ok': hotkey['ok']})
            return
        seconds = min(60, max(3, int(data.get('seconds', SHOW_SECONDS))))
        if self.path == '/schedule':
            schedule['events'] = data.get('events', [])
            schedule['seconds'] = seconds
        else:
            messages.put((str(data.get('title', '')), str(data.get('body', '')), seconds))
        self.reply(204, b'')

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        origin = self.headers.get('Origin')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        super().end_headers()

    def reply_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def reply(self, code, body):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def fmt_left(ms):
    minutes = int(ms // 60000)
    if minutes < 1:
        return '<1м'
    days, hours, mins = minutes // 1440, minutes % 1440 // 60, minutes % 60
    if days:
        return f'{days}д {hours}ч'
    if hours:
        return f'{hours}ч {mins:02d}м'
    return f'{mins}м'


def upcoming_text():
    now = time.time() * 1000
    items = []
    for ev in schedule['events']:
        occ = next(((start, end) for start, end in ev['occ'] if end > now), None)
        if occ is None:
            continue
        start, end = occ
        if start <= now:
            items.append((0, end, f'идёт · {ev["name"]} · ещё {fmt_left(end - now)}'))
        else:
            items.append((1, start, f'{fmt_left(start - now)} · {ev["name"]}'))
    if not items:
        return 'Нет расписания — открой трекер в браузере'
    items.sort(key=lambda item: item[:2])
    return '\n'.join(text for _, _, text in items[:NEXT_COUNT])


def load_hotkey():
    if SETTINGS_FILE.exists():
        saved = json.loads(SETTINGS_FILE.read_text(encoding='utf-8')).get('hotkey')
        if saved:
            hotkey.update(mods=saved['mods'], vk=saved['vk'], label=saved['label'])


def save_hotkey():
    data = {'hotkey': {'mods': hotkey['mods'], 'vk': hotkey['vk'], 'label': hotkey['label']}}
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def register_hotkey(mods, vk):
    return bool(user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))


def hotkey_loop():
    hotkey_thread['id'] = threading.get_native_id()
    msg = wintypes.MSG()
    user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
    hotkey['ok'] = register_hotkey(hotkey['mods'], hotkey['vk'])
    if not hotkey['ok']:
        print(f'RegisterHotKey {hotkey["label"]} failed: taken by another program', file=sys.stderr, flush=True)
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            messages.put('next')
        elif msg.message == WM_APP:
            new = hotkey_requests.get()
            if hotkey['ok']:
                user32.UnregisterHotKey(None, 1)
            if register_hotkey(new['mods'], new['vk']):
                hotkey.update(new, ok=True)
                save_hotkey()
                hotkey_results.put(True)
            else:
                hotkey['ok'] = register_hotkey(hotkey['mods'], hotkey['vk'])
                hotkey_results.put(False)


class Overlay:
    def __init__(self, root, server):
        self.root = root
        self.server = server
        self.active = []
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg='#f2b84b')
        self.win.attributes('-alpha', 0.94)
        self.body = tk.Frame(self.win, bg='#161920', padx=22, pady=14)
        self.body.pack(padx=(5, 0), fill='both', expand=True)
        self.win.update_idletasks()
        self.hwnd = int(self.win.wm_frame(), 16)
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        user32.ShowWindow(self.hwnd, SW_HIDE)
        root.after(200, self.poll)

    def poll(self):
        changed = False
        while not messages.empty():
            message = messages.get()
            if message is None:
                self.root.destroy()
                return
            if message == 'restart':
                self.server.shutdown()
                self.server.server_close()
                subprocess.Popen([str(INSTALLED_EXE), '--restart'])
                self.root.destroy()
                return
            if message == 'next':
                self.active = [m for m in self.active if m[3] != 'next']
                self.active.append((time.monotonic() + schedule['seconds'], 'Что дальше', upcoming_text(), 'next'))
            else:
                title, body, seconds = message
                self.active.append((time.monotonic() + seconds, title, body, 'notify'))
            changed = True
        now = time.monotonic()
        alive = [m for m in self.active if m[0] > now]
        if len(alive) != len(self.active):
            changed = True
        self.active = alive
        if changed:
            self.render()
        self.root.after(200, self.poll)

    def render(self):
        for child in self.body.winfo_children():
            child.destroy()
        if not self.active:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            return
        for _, title, body, _ in self.active:
            tk.Label(self.body, text=title, fg='#e7e9ef', bg='#161920', font=('Segoe UI', 26, 'bold'), anchor='w', justify='left').pack(fill='x')
            if body:
                tk.Label(self.body, text=body, fg='#8d94a5', bg='#161920', font=('Segoe UI', 16), anchor='w', justify='left').pack(fill='x', pady=(0, 6))
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = (self.win.winfo_screenwidth() - w) // 2
        self.win.geometry(f'{w}x{h}+{x}+{TOP_OFFSET}')
        self.win.update_idletasks()
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)


def start_server(retry):
    handler = partial(Handler, directory=str(HOME))
    for attempt in range(40 if retry else 1):
        try:
            return Server(('127.0.0.1', PORT), handler)
        except OSError:
            if attempt < 39 and retry:
                time.sleep(0.25)
    return None


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    if FROZEN and Path(sys.executable).resolve() != INSTALLED_EXE.resolve():
        try:
            install()
        except OSError as error:
            print(f'install failed: {error!r}', file=sys.stderr, flush=True)
            message_box(f'Не удалось установить плашку:\n{error}', error=True)
        return
    page = SITE if FROZEN else LOCAL_URL
    if FROZEN:
        retry(lambda: (HOME / 'aion2-helper.old.exe').unlink(missing_ok=True))
    server = start_server(retry='--restart' in sys.argv)
    if server is None:
        if '--open' in sys.argv:
            webbrowser.open(page)
        return
    load_hotkey()
    threading.Thread(target=hotkey_loop, daemon=True).start()
    threading.Thread(target=server.serve_forever, daemon=True).start()

    root = tk.Tk()
    root.withdraw()
    Overlay(root, server)
    if '--open' in sys.argv:
        webbrowser.open(page)
    root.mainloop()
    server.shutdown()


main()
