#!/usr/bin/env python3
"""Global X11 dictation through an isolated official Claude Code PTY."""
import argparse, codecs, ctypes as C, fcntl, hashlib, json, os, pathlib, pty, re
import select, shlex, shutil, signal, socket, struct, subprocess, sys, termios, time
BASE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'vendor'))
import pyte
STATE = BASE / 'state'
RUNTIME = pathlib.Path('/tmp') / ('claude-dictation-' + str(os.getuid()) + '-' + hashlib.sha256(str(BASE).encode()).hexdigest()[:12])
ENDPOINT = RUNTIME / 'bridge.sock'


def hook():
    # Emit a stop decision even if delivery to the bridge fails.
    try:
        data = json.load(sys.stdin)
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(2)
            s.connect(os.environ['CLAUDE_DICTATION_SOCKET'])
            s.sendall(json.dumps({'final': data.get('prompt', ''),
                                  'session': data.get('session_id')}).encode())
    finally:
        print('{"continue":false,"stopReason":"Dictation captured; no model response requested."}')


class X11:
    class Key(C.Structure):
        _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
                    ('display', C.c_void_p), ('window', C.c_ulong), ('root', C.c_ulong),
                    ('subwindow', C.c_ulong), ('time', C.c_ulong), ('x', C.c_int),
                    ('y', C.c_int), ('x_root', C.c_int), ('y_root', C.c_int),
                    ('state', C.c_uint), ('keycode', C.c_uint), ('same_screen', C.c_int)]
    class Event(C.Union):
        _fields_ = [('type', C.c_int), ('pad', C.c_long * 24)]

    def __init__(self):
        self.x = C.CDLL('libX11.so.6'); self.xt = C.CDLL('libXtst.so.6')
        signatures = {
            'XOpenDisplay': (C.c_void_p, [C.c_char_p]),
            'XDefaultRootWindow': (C.c_ulong, [C.c_void_p]),
            'XKeysymToKeycode': (C.c_ubyte, [C.c_void_p, C.c_ulong]),
            'XStringToKeysym': (C.c_ulong, [C.c_char_p]),
            'XPending': (C.c_int, [C.c_void_p]),
            'XNextEvent': (C.c_int, [C.c_void_p, C.c_void_p]),
            'XGrabKey': (C.c_int, [C.c_void_p, C.c_int, C.c_uint, C.c_ulong, C.c_int, C.c_int, C.c_int]),
            'XUngrabKey': (C.c_int, [C.c_void_p, C.c_int, C.c_uint, C.c_ulong]),
            'XGetInputFocus': (C.c_int, [C.c_void_p, C.POINTER(C.c_ulong), C.POINTER(C.c_int)]),
            'XFlush': (C.c_int, [C.c_void_p]), 'XSync': (C.c_int, [C.c_void_p, C.c_int]),
            'XCloseDisplay': (C.c_int, [C.c_void_p]),
        }
        for name, (restype, args) in signatures.items():
            f = getattr(self.x, name); f.restype = restype; f.argtypes = args
        self.xt.XTestFakeKeyEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
        self.d = self.x.XOpenDisplay(None)
        if not self.d: raise RuntimeError('No se puede abrir DISPLAY; requiere GNOME X11.')
        self.root = self.x.XDefaultRootWindow(self.d)
        self.errors = []
        self.error_cb = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)(lambda d,e: self.errors.append(True) or 0)
        self.x.XSetErrorHandler.argtypes = [C.c_void_p]; self.x.XSetErrorHandler(self.error_cb)

    def code(self, name):
        c = self.x.XKeysymToKeycode(self.d, self.x.XStringToKeysym(name.encode()))
        if not c: raise RuntimeError('Tecla desconocida: ' + name)
        return c

    def grab(self, key, modifiers, enable=True):
        self.errors.clear()
        for lock in (0, 2, 16, 18):
            if enable: self.x.XGrabKey(self.d, key, modifiers | lock, self.root, 0, 1, 1)
            else: self.x.XUngrabKey(self.d, key, modifiers | lock, self.root)
        self.x.XSync(self.d, 0)
        if self.errors and enable: raise RuntimeError('Atajo ocupado; elige otra tecla con --key.')

    def events(self):
        while self.x.XPending(self.d):
            e = self.Event(); self.x.XNextEvent(self.d, C.byref(e))
            if e.type in (2, 3):
                k = C.cast(C.byref(e), C.POINTER(self.Key)).contents
                yield e.type, k.keycode, k.time

    def focus(self):
        w = C.c_ulong(); r = C.c_int()
        self.x.XGetInputFocus(self.d, C.byref(w), C.byref(r)); return w.value

    def key(self, name, down):
        self.xt.XTestFakeKeyEvent(self.d, self.code(name), int(down), 0)
        self.x.XFlush(self.d)

    def paste(self, text, erase, terminal):
        # Never synthesize Enter. Flatten dictation to keep shell input unsubmitted.
        held = []
        keys = C.create_string_buffer(32)
        self.x.XQueryKeymap.argtypes = [C.c_void_p, C.c_void_p]
        self.x.XQueryKeymap(self.d, keys)
        for name in ('Control_L','Control_R','Alt_L','Alt_R','Shift_L','Shift_R','Super_L','Super_R'):
            # Layouts using AltGr often have no Alt_R (or Super_R) keycode.
            c = self.x.XKeysymToKeycode(self.d, self.x.XStringToKeysym(name.encode()))
            if not c:
                continue
            if keys.raw[c//8] & (1 << (c%8)):
                held.append(name); self.key(name,False)
        try:
            self._paste(text, erase, terminal)
        finally:
            for name in held: self.key(name,True)

    def _paste(self, text, erase, terminal):
        if erase:
            raise RuntimeError('El puente no permite borrar texto del editor.')
        if not text: return
        old = subprocess.run(['xclip','-selection','clipboard','-o'], capture_output=True, timeout=1)
        self.clip(text.encode())
        self.key('Control_L', True)
        if terminal: self.key('Shift_L', True)
        self.key('v', True); self.key('v', False)
        if terminal: self.key('Shift_L', False)
        self.key('Control_L', False)
        time.sleep(.15)
        # Restore plain text only, and only if the user did not change it meanwhile.
        now = subprocess.run(['xclip','-selection','clipboard','-o'], capture_output=True, timeout=1)
        if old.returncode == 0 and now.stdout == text.encode(): self.clip(old.stdout)

    @staticmethod
    def clip(text):
        p = subprocess.Popen(['xclip','-selection','clipboard','-in'], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.communicate(text, timeout=2)

    @staticmethod
    def terminal():
        try:
            root = subprocess.check_output(['xprop','-root','_NET_ACTIVE_WINDOW'], timeout=1).decode()
            window = re.search(r'0x[0-9a-fA-F]+', root).group()
            cls = subprocess.check_output(['xprop','-id',window,'WM_CLASS'], timeout=1).decode().lower()
            return any(n in cls for n in ('terminal','terminator','alacritty','kitty','konsole','xterm','wezterm','tilix'))
        except Exception:
            return False


class Preview:
    """Non-focusable status in both modes, with optional live transcript."""
    def __init__(self, enabled):
        self.live = enabled
        self.dismiss_at = None
        self.phase = 'idle'
        import tkinter as tk
        root = self.root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.wm_attributes('-type', 'notification')
        root.wm_attributes('-topmost', True)
        root.configure(background='#202124', takefocus=False)
        self.title = tk.Label(root, text='Dictado · Esc cancela', foreground='#a8c7fa',
                              background='#202124', font=('Sans', 11), anchor='w')
        self.title.pack(fill='x', padx=16, pady=(12,4))
        self.text = tk.Label(root, foreground='#f1f3f4', background='#202124',
                             font=('Sans', 14), wraplength=560, justify='left',
                             anchor='w', takefocus=False)
        self.text.pack(fill='both', padx=16, pady=(0,16))
        self.last = None
        self.transcript = ''

    def set_phase(self, phase, message=None):
        self.phase = phase
        self.dismiss_at = None
        titles = {'listening':'● Escuchando…', 'processing':'◌ Procesando…',
                  'done':'✓ Texto pegado', 'cancelled':'Dictado cancelado',
                  'error':'No se pudo pegar', 'empty':'No se detectó voz'}
        self.title.configure(text=titles[phase], foreground={
            'listening':'#a8c7fa','processing':'#fdd663','done':'#81c995',
            'error':'#f28b82'}.get(phase,'#dadce0'))
        if phase == 'listening':
            self.transcript = ''
        hints = {'listening':'Suelta el atajo para terminar · Esc cancela',
                 'processing':'Esperando la transcripción final · Esc cancela',
                 'done':'Puedes seguir escribiendo', 'cancelled':'No se ha pegado texto',
                 'error':'Resultado conservado en state/last.txt', 'empty':'Vuelve a intentarlo'}
        self.show(message or hints[phase])
        if phase in ('done','cancelled','empty','error'):
            self.dismiss_at = time.monotonic() + (5 if phase == 'error' else 1.8)

    def show(self, text):
        if self.root is None:
            return
        text = text[-1000:] or 'Escuchando…'
        if (text, self.phase) != self.last:
            self.text.configure(text=text)
            self.root.update_idletasks()
            w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
            self.root.geometry('+%d+%d' % (max(0,self.root.winfo_screenwidth()-w-32),
                                         max(0,self.root.winfo_screenheight()-h-64)))
            self.last = (text, self.phase)
        self.root.deiconify()
        self.root.update()

    def update_transcript(self, text):
        if self.live and text:
            self.transcript = text
            self.show(text)

    def pump(self):
        if self.dismiss_at is not None and time.monotonic() >= self.dismiss_at:
            self.dismiss_at = None
            self.hide()
        self.root.update()

    def hide(self):
        if self.root is not None:
            self.root.withdraw()
            self.root.update()

    def close(self):
        if self.root is not None:
            self.root.destroy()


def prepare(language, source_profile):
    STATE.mkdir(mode=0o700, exist_ok=True); os.chmod(STATE, 0o700)
    source_profile = pathlib.Path(source_profile).expanduser().resolve()
    profile_key = hashlib.sha256(str(source_profile).encode()).hexdigest()[:12]
    profiles = STATE / 'profiles'; profiles.mkdir(mode=0o700, exist_ok=True)
    profile = profiles / profile_key; profile.mkdir(mode=0o700, exist_ok=True)
    credential = source_profile / '.credentials.json'
    if not credential.is_file():
        raise RuntimeError('No se encontraron credenciales de Claude. Inicia sesión con claude y comprueba --claude-config.')
    link = profile / '.credentials.json'
    if not link.exists(): link.symlink_to(credential)
    config = profile / '.claude.json'
    if not config.exists():
        source_config = source_profile / '.claude.json'
        if source_profile == (pathlib.Path.home() / '.claude').resolve():
            source_config = pathlib.Path.home() / '.claude.json'
        original = json.loads(source_config.read_text()) if source_config.is_file() else {}
        config.write_text(json.dumps({k: original[k] for k in
            ('hasCompletedOnboarding','lastOnboardingVersion','oauthAccount') if k in original}))
        config.chmod(0o600)
    settings = {'language':language, 'model':'haiku','tui':'default',
        'voice':{'enabled':True,'mode':'tap'}, 'disableAllHooks':False,
        'prefersReducedMotion':True, 'permissions':{'defaultMode':'dontAsk'},
        'hooks':{'UserPromptSubmit':[{'hooks':[{'type':'command',
            'command':shlex.join([sys.executable, str(BASE/'dictate.py'), 'hook']),
            'onFailure':'block'}]}]}}
    (STATE/'settings.json').write_text(json.dumps(settings))
    return profile


def prompt_text(screen):
    rows = screen.display
    starts = [i for i,row in enumerate(rows) if row.startswith('❯')]
    if not starts: return None
    i = starts[-1]; out = [rows[i][2:].rstrip()]
    for row in rows[i+1:]:
        if row.startswith('─'): break
        out.append(row[2:].rstrip())
    # Audio cursor is a block glyph; it is not part of the transcript.
    return re.sub(r'[▁▂▃▄▅▆▇█▏▎▍▌▋▊▉▮▯]', '', ' '.join(out)).strip()


def run(args):
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland': raise RuntimeError('Este puente requiere X11.')
    executable = shutil.which(args.claude)
    if executable is None:
        raise RuntimeError('Claude no está en PATH. Instálalo o indica --claude con su ejecutable.')
    executable = str(pathlib.Path(executable).resolve())
    missing = [name for name in ('xclip','xprop') if shutil.which(name) is None]
    if missing:
        raise RuntimeError('Faltan dependencias: '+', '.join(missing)+'. Consulta los requisitos del README.')
    try:
        import tkinter
    except ImportError as error:
        raise RuntimeError('Falta Tkinter para este Python. Instala python3-tk o selecciona otro intérprete con PYTHON.') from error
    profile = prepare(args.language, args.claude_config)
    lock = open(STATE/'bridge.lock','w')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('El puente ya está abierto.')
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    if RUNTIME.is_symlink() or RUNTIME.stat().st_uid != os.getuid():
        raise RuntimeError('Directorio temporal no seguro.')
    os.chmod(RUNTIME,0o700)
    endpoint = ENDPOINT
    endpoint.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX); server.bind(str(endpoint)); server.listen(4)
    os.chmod(endpoint, 0o600); server.setblocking(False)
    x = X11(); key = x.code(args.key); x.grab(key, 12)
    esc = x.code('Escape')
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH',60,240,0,0))
    env = os.environ.copy()
    for k in ('ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','ANTHROPIC_BASE_URL','CLAUDECODE',
              'CLAUDE_CODE_USE_BEDROCK','CLAUDE_CODE_USE_VERTEX','CLAUDE_CODE_USE_FOUNDRY',
              'CLAUDE_CODE_OAUTH_TOKEN'):
        env.pop(k, None)
    env.update(CLAUDE_CONFIG_DIR=str(profile), CLAUDE_DICTATION_SOCKET=str(endpoint),
        DISABLE_AUTOUPDATER='1', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', TERM='xterm-256color')
    command = [executable, '--settings',str(STATE/'settings.json'),
        '--setting-sources','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}',
        '--tools','','--disable-slash-commands']
    proc = subprocess.Popen(command, cwd=STATE, env=env, stdin=slave, stdout=slave,
                            stderr=slave, start_new_session=True)
    os.close(slave); os.set_blocking(master, False)
    screen = pyte.Screen(240,60); stream = pyte.Stream(screen)
    decoder = codecs.getincrementaldecoder('utf8')('replace')
    recording = False; processing = False; ready = False; target = None
    inserted = ''; pending = None; last_update = 0; started = 0; trust_sent = False
    terminal_target = False; rec_seen = False; stable_text = None; stable_since = 0
    preview = Preview(args.live)
    state = {'status':'starting','language':args.language,'live':args.live}
    def status(value):
        state['status'] = value; (STATE/'status.json').write_text(json.dumps(state))
        print(value, flush=True)
    def write(b): os.write(master,b)
    def deliver(text):
        nonlocal inserted
        text = ' '.join(text.split())
        if x.focus() != target:
            preview.set_phase('error', 'El foco cambió. Resultado conservado en state/last.txt')
            status('Foco cambiado: no se insertó más texto. Resultado en last.txt.'); return False
        if text == inserted: return True
        try:
            x.paste(text,0,terminal_target)
        except Exception as error:
            preview.set_phase('error')
            status('Error al pegar: '+str(error)+'. Resultado conservado en state/last.txt.')
            return False
        inserted = text; return True
    def cancel():
        nonlocal recording,processing,pending
        write(b'\x1b'); recording = processing = False; pending = None
        x.grab(esc,0,False)
        preview.set_phase('cancelled')
        status('Cancelado; no se ha insertado texto provisional.')
    stop = False
    def finish(signum, frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, finish); signal.signal(signal.SIGINT, finish)
    status('Iniciando Claude aislado…')
    try:
        while not stop and proc.poll() is None:
            readable,_,_ = select.select([master,server],[],[],.025)
            if master in readable:
                try: chunk = os.read(master,262144)
                except OSError: break
                if not chunk: break
                stream.feed(decoder.decode(chunk))
                display = '\n'.join(screen.display)
                # Reply to terminal queries, but never send prompts to a model.
                if b'\x1b[c' in chunk: write(b'\x1b[?1;2c')
                if b'\x1b[6n' in chunk: write(b'\x1b[1;1R')
                if not trust_sent and 'Yes, I trust this folder' in display:
                    write(b'\x1b[B\r'); trust_sent = True
                if not ready and prompt_text(screen) == '' and 'Claude Code v' in display:
                    ready = True; status('Listo: mantén Ctrl+Alt+'+args.key+'; Esc cancela.')
                if 'requires a Claude.ai account' in display or 'Please run /login' in display:
                    status('Error de autenticación: ejecuta claude /login en tu terminal habitual.'); break
            for kind,code,timestamp in x.events():
                if code == esc and kind == 2 and (recording or processing): cancel()
                if code != key: continue
                if kind == 2:
                    pending = None
                    if ready and not recording and not processing:
                        target = x.focus(); inserted = ''; started = time.monotonic()
                        terminal_target = args.terminal or x.terminal()
                        rec_seen = False; stable_text = None; stable_since = started
                        x.grab(esc,0); write(b'\x15 '); recording = True
                        preview.set_phase('listening')
                        status('Grabando…')
                elif recording: pending = time.monotonic()+.065
            now = time.monotonic()
            display = '\n'.join(screen.display)
            if recording and 'REC' in display: rec_seen = True
            if recording and rec_seen and 'REC' not in display:
                recording = False; processing = True; pending = None
                preview.set_phase('processing')
            if pending and now >= pending:
                write(b' '); pending = None; recording = False; processing = True
                status('Finalizando…')
                preview.set_phase('processing')
            if server in readable:
                with server.accept()[0] as client:
                    client.settimeout(2); chunks=[]
                    while True:
                        b=client.recv(65536)
                        if not b: break
                        chunks.append(b)
                    data=json.loads(b''.join(chunks))
                if 'final' in data and (recording or processing):
                    text=data['final']; (STATE/'last.txt').write_text(text)
                    preview.hide()
                    delivered = deliver(text); recording = processing = False; pending = None
                    x.grab(esc,0,False)
                    if delivered:
                        preview.set_phase('done' if text.strip() else 'empty')
                        status('Listo. Dictado finalizado.')
                elif data.get('command') == 'cancel': cancel()
                elif data.get('command') == 'stop': stop = True
            if args.live and (recording or processing) and now-last_update > .15:
                current=prompt_text(screen)
                if current is not None: preview.update_transcript(current)
                last_update=now
            # Tap mode does not auto-submit transcripts shorter than three words.
            if processing and now-started > .8:
                display='\n'.join(screen.display)
                if 'REC' not in display and 'listening' not in display and 'processing' not in display.lower():
                    current=prompt_text(screen)
                    if current != stable_text:
                        stable_text = current; stable_since = now
                    if current and now-stable_since > 2:
                        write(b'\r'); stable_since=now+3
            if (recording or processing) and now-started > 135:
                cancel(); status('Sin resultado después de 135 s; revisa micrófono/conexión.')
            if not ready and now-last_update > 25:
                (STATE/'screen.txt').write_text('\n'.join(screen.display)); last_update=now
            preview.pump()
    finally:
        preview.close()
        x.x.XCloseDisplay(x.d)
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL)
        os.close(master); server.close(); endpoint.unlink(missing_ok=True)
        status('Detenido.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run','status','stop','cancel','hook'],nargs='?',default='run')
    parser.add_argument('--language',choices=['spanish','english'],default='spanish')
    parser.add_argument('--key',default='j',help='Ctrl+Alt+esta tecla (predeterminado J)')
    parser.add_argument('--live',action='store_true',help='Vista previa flotante en directo; pega solo el resultado final')
    parser.add_argument('--terminal',action='store_true',help='Usa Ctrl+Shift+V en vez de Ctrl+V')
    parser.add_argument('--claude',default=os.environ.get('CLAUDE_BIN','claude'),help='Ejecutable de Claude (por defecto: claude en PATH)')
    parser.add_argument('--claude-config',default=os.environ.get('CLAUDE_CONFIG_DIR',str(pathlib.Path.home()/'.claude')),help='Perfil existente con credenciales de Claude.ai (por defecto: CLAUDE_CONFIG_DIR o ~/.claude)')
    args=parser.parse_args()
    if args.command == 'run' and re.fullmatch(r'F(?:[1-9]|1[0-2])', args.key, re.I):
        parser.error('Ctrl+Alt+F1…F12 cambia de consola en Linux; usa una letra, por ejemplo --key j.')
    if args.command=='hook': hook()
    elif args.command=='status': print((STATE/'status.json').read_text() if (STATE/'status.json').exists() else 'No iniciado')
    elif args.command in ('stop','cancel'):
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(str(ENDPOINT)); s.sendall(json.dumps({'command':args.command}).encode())
    else: run(args)

if __name__=='__main__':
    try: main()
    except Exception as e: print('Error:',e,file=sys.stderr); sys.exit(1)
