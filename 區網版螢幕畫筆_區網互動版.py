"""
螢幕畫筆 V7.0 - 區網互動版
- 不需要 Firebase / 網際網路：程式啟動時在本機建立 HTTP 伺服器
- 學生以 iPad（Safari）連到同一個區域網路即可掃 QR Code 加入
- 主機端介面以觸控大屏操作為主，採馬卡龍淡色系設計
"""
import sys, os, io, csv, json, time, uuid, html, random, socket, zipfile, base64, logging, datetime, threading, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from PyQt5.QtCore import Qt, QPoint, QPointF, QRect, QRectF, QElapsedTimer, QTimer, QObject, pyqtSignal, QBuffer, QIODevice, QByteArray, QSettings, QSize
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QPixmap, QIcon, QImage, QFont, QKeySequence, QPainterPath
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QButtonGroup,
    QLabel, QComboBox, QGraphicsDropShadowEffect, QShortcut, QMessageBox, QDialog, QScrollArea, QFrame,
    QTabWidget, QTextBrowser, QSizePolicy, QSlider, QFileDialog, QLineEdit, QStackedWidget, QCheckBox, QLayout
)

try:
    import qrcode
except ImportError:
    qrcode = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

APP_TITLE = "螢幕畫筆 V7.0 · 區網互動版"
SETTINGS_KEY = ("PyLanPen", "Config")
DEFAULT_PORT = 8000
ONLINE_TIMEOUT = 6  # 秒：超過此時間沒有輪詢即視為離線
MAX_BODY = 40 * 1024 * 1024
MAX_CALC_PAGES = 20


def app_dir():
    """可寫入資料的程式資料夾（打包成 exe 時為 exe 所在位置）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class MissionType:
    NONE = "none"
    DRAW = "draw"
    CHOICE = "choice"
    TEXT = "text"
    CALC = "calc"


MISSION_LABELS = {
    MissionType.NONE: "尚未出題",
    MissionType.DRAW: "🎨 塗鴉題",
    MissionType.CALC: "🧮 計算題",
    MissionType.CHOICE: "🔤 選擇題",
    MissionType.TEXT: "📝 簡答題",
}

##########################################
# 馬卡龍配色主題
##########################################
class C:
    BG = "#FBF7F4"
    SURFACE = "#FFFFFF"
    SURFACE_2 = "#F6F1F8"
    LINE = "#ECE4EF"
    INK = "#4A4358"
    MUTED = "#8F879C"
    PINK, PINK_D = "#F9D3DF", "#E88AAB"
    MINT, MINT_D = "#CDEFE2", "#5FBF9C"
    LAV, LAV_D = "#E2D8F6", "#9C84DB"
    LEMON, LEMON_D = "#FFF1BF", "#E3BD45"
    PEACH, PEACH_D = "#FFDCCB", "#EF9A77"
    SKY, SKY_D = "#D3E8F8", "#6FAEDD"


TONES = {
    "lav": (C.LAV, C.LAV_D), "mint": (C.MINT, C.MINT_D), "pink": (C.PINK, C.PINK_D),
    "peach": (C.PEACH, C.PEACH_D), "lemon": (C.LEMON, C.LEMON_D), "sky": (C.SKY, C.SKY_D),
}

PEN_COLORS = [
    ("紅", "#E5484D"), ("橙", "#F08C2E"), ("黃", "#F5C518"), ("綠", "#2FA37A"), ("青", "#1BA3B8"),
    ("藍", "#3E7BFA"), ("紫", "#8E5CD9"), ("粉", "#EC6FA5"), ("黑", "#2B2B2B"), ("白", "#FFFFFF"),
]
PEN_SIZES = [3, 6, 12, 24, 48]


class UI:
    scale = 1.0


def px(v):
    return int(round(v * UI.scale))


def build_qss():
    p = px
    tone_rules = ""
    for name, (bg, deep) in TONES.items():
        hover = QColor(bg).darker(104).name()
        press = QColor(bg).darker(110).name()
        tone_rules += f"""
        QPushButton[tone="{name}"] {{ background: {bg}; border: 1px solid {bg}; }}
        QPushButton[tone="{name}"]:hover {{ background: {hover}; }}
        QPushButton[tone="{name}"]:pressed, QPushButton[tone="{name}"]:checked {{ background: {press}; border: 2px solid {deep}; }}
        """
    return f"""
    * {{ font-family: "Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC", sans-serif; }}
    QWidget {{ color: {C.INK}; font-size: {p(15)}px; }}
    QMainWindow, QDialog {{ background: {C.BG}; }}
    QToolTip {{ background: {C.SURFACE}; color: {C.INK}; border: 1px solid {C.LINE}; padding: {p(6)}px; }}

    QPushButton {{
        background: {C.SURFACE}; border: 1px solid {C.LINE}; border-radius: {p(16)}px;
        padding: {p(8)}px {p(18)}px; font-weight: 700;
    }}
    QPushButton:hover {{ background: {C.SURFACE_2}; }}
    QPushButton:pressed {{ background: {C.LINE}; }}
    QPushButton:disabled {{ color: #C4BDCB; background: #F4F1F5; border-color: #F4F1F5; }}
    QPushButton[tool="true"]:checked {{ background: {C.LAV}; border: 2px solid {C.LAV_D}; }}
    QPushButton[ghost="true"] {{ background: transparent; border: none; }}
    QPushButton[ghost="true"]:pressed {{ background: {C.SURFACE_2}; }}
    QPushButton[tile="true"] {{ background: {C.SURFACE}; border: 2px solid {C.LINE}; border-radius: {p(24)}px; }}
    QPushButton[tile="true"]:checked {{ background: {C.LAV}; border: 3px solid {C.LAV_D}; }}
    QPushButton[seg="true"] {{ border-radius: {p(14)}px; padding: {p(8)}px {p(18)}px; }}
    QPushButton[seg="true"]:checked {{ background: {C.LAV}; border: 2px solid {C.LAV_D}; }}
    {tone_rules}

    QLineEdit, QComboBox {{
        background: {C.SURFACE}; border: 2px solid {C.LINE}; border-radius: {p(14)}px;
        padding: {p(8)}px {p(14)}px; min-height: {p(30)}px;
    }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {C.LAV_D}; }}
    QComboBox::drop-down {{ border: none; width: {p(34)}px; }}
    QComboBox QAbstractItemView {{
        background: {C.SURFACE}; border: 1px solid {C.LINE}; outline: 0; padding: {p(6)}px;
        selection-background-color: {C.LAV}; selection-color: {C.INK};
    }}
    QComboBox QAbstractItemView::item {{ min-height: {p(40)}px; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: {p(14)}px; margin: {p(4)}px; }}
    QScrollBar::handle:vertical {{ background: #DCD3E3; border-radius: {p(3)}px; min-height: {p(48)}px; }}
    QScrollBar:horizontal {{ background: transparent; height: {p(14)}px; margin: {p(4)}px; }}
    QScrollBar::handle:horizontal {{ background: #DCD3E3; border-radius: {p(3)}px; min-width: {p(48)}px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    QTabWidget::pane {{ border: none; }}
    QTabBar {{ font-weight: 800; font-size: {p(17)}px; }}
    QTabBar::tab {{
        background: transparent; color: {C.MUTED}; padding: {p(12)}px {p(26)}px; margin-right: {p(8)}px;
        border-radius: {p(16)}px;
    }}
    QTabBar::tab:selected {{ background: {C.SURFACE}; color: {C.INK}; }}

    QFrame#card {{ background: {C.SURFACE}; border: 1px solid {C.LINE}; border-radius: {p(22)}px; }}
    QFrame#soft {{ background: {C.SURFACE_2}; border: none; border-radius: {p(16)}px; }}
    QLabel {{ background: transparent; }}
    QLabel#h1 {{ font-size: {p(28)}px; font-weight: 800; }}
    QLabel#h2 {{ font-size: {p(19)}px; font-weight: 800; }}
    QLabel#muted {{ color: {C.MUTED}; }}
    QLabel#section {{ color: {C.MUTED}; font-size: {p(13)}px; font-weight: 700; }}
    QLabel#chip {{
        background: {C.SURFACE}; border: 1px solid {C.LINE}; border-radius: {p(18)}px;
        padding: {p(8)}px {p(16)}px; font-weight: 800;
    }}

    QSlider::groove:horizontal {{ height: {p(10)}px; background: {C.SURFACE_2}; border-radius: {p(5)}px; }}
    QSlider::sub-page:horizontal {{ background: {C.LAV_D}; border-radius: {p(5)}px; }}
    QSlider::handle:horizontal {{
        background: white; border: {p(3)}px solid {C.LAV_D}; width: {p(26)}px; height: {p(26)}px;
        margin: -{p(10)}px 0; border-radius: {p(16)}px;
    }}
    QTextBrowser {{ background: {C.SURFACE}; border: 1px solid {C.LINE}; border-radius: {p(22)}px; padding: {p(16)}px; }}
    QMessageBox QLabel {{ font-size: {p(17)}px; }}
    QMessageBox QPushButton {{ min-width: {p(100)}px; }}
    QCheckBox {{ spacing: {p(10)}px; font-weight: 700; }}
    QCheckBox::indicator {{ width: {p(24)}px; height: {p(24)}px; border-radius: {p(8)}px; border: 2px solid {C.LINE}; background: {C.SURFACE}; }}
    QCheckBox::indicator:checked {{ background: {C.LAV_D}; border-color: {C.LAV_D}; }}
    """


def make_button(text, tone=None, height=None, checkable=False, tool=False, font_px=None):
    b = QPushButton(text)
    if tone:
        b.setProperty("tone", tone)
    if tool:
        b.setProperty("tool", True)
    b.setCheckable(checkable)
    b.setMinimumHeight(px(height or 44))
    if font_px:
        b.setStyleSheet(f"font-size: {px(font_px)}px;")
    b.setCursor(Qt.PointingHandCursor)
    b.setFocusPolicy(Qt.NoFocus)
    return b


def make_label(text="", obj=None, wrap=False, align=None):
    lbl = QLabel(text)
    if obj:
        lbl.setObjectName(obj)
    lbl.setWordWrap(wrap)
    if align is not None:
        lbl.setAlignment(align)
    return lbl


def make_card(obj="card"):
    f = QFrame()
    f.setObjectName(obj)
    return f


def soft_shadow(widget, blur=36, dy=8, alpha=34):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(px(blur))
    eff.setOffset(0, px(dy))
    eff.setColor(QColor(120, 100, 150, alpha))
    widget.setGraphicsEffect(eff)


def fit_resize(widget, w, h):
    """依介面比例設定視窗大小，但不超出螢幕可用範圍。"""
    avail = QApplication.primaryScreen().availableGeometry()
    parent = widget.parentWidget()
    if parent is not None and parent.windowHandle() is not None:
        avail = parent.windowHandle().screen().availableGeometry()
    widget.resize(min(w, int(avail.width() * 0.94)), min(h, int(avail.height() * 0.92)))


def app_icon():
    path = resource_path("app_icon.ico")
    return QIcon(path) if os.path.exists(path) else QIcon()


##########################################
# 工具函式
##########################################
def get_lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # 不會真的送出封包，只用來找出預設網卡
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    ips = [ip for ip in ips if not ip.startswith("127.")]
    # 將 APIPA (169.254.x.x) 排在最後
    ips.sort(key=lambda ip: ip.startswith("169.254."))
    return ips or ["127.0.0.1"]


def make_qr_pixmap(text, size):
    if qrcode is None:
        return None
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    cell = max(1, size // n)
    img = QImage(cell * n, cell * n, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2E2838"))
    for y, row in enumerate(matrix):
        for x, v in enumerate(row):
            if v:
                p.drawRect(x * cell, y * cell, cell, cell)
    p.end()
    return QPixmap.fromImage(img)


def pixmap_to_jpeg(pm, max_side=1400, quality=90):
    if pm.width() > max_side or pm.height() > max_side:
        pm = pm.scaled(max_side, max_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pm.save(buf, "JPG", quality)
    buf.close()
    return bytes(ba)


def decode_data_uri(uri):
    """回傳 (bytes, 副檔名)"""
    try:
        head, b64 = uri.split(",", 1)
        ext = "png" if "png" in head else "jpg"
        return base64.b64decode(b64), ext
    except Exception:
        return None, None


def pixmap_from_data_uri(uri):
    data, _ = decode_data_uri(uri or "")
    if not data:
        return None
    pm = QPixmap()
    pm.loadFromData(data)
    return None if pm.isNull() else pm


def safe_filename(name):
    s = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    return s or "student"


##########################################
# 區網伺服器（取代 Firebase）
##########################################
class _LanHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False  # Windows 上避免與其他程式共用同一個 port
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    server_version = "ClassroomLAN/7.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    @property
    def app(self):
        return self.server.app

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        path = url.path
        try:
            if path in ("/", "/index.html"):
                self._send(200, self.app.student_page(), "text/html; charset=utf-8")
            elif path == "/api/poll":
                self._json(self.app.poll(q.get("sid", [""])[0]))
            elif path == "/api/mission_image":
                img = self.app.mission_image()
                if img:
                    self._send(200, img, "image/jpeg")
                else:
                    self._json({"error": "no image"}, 404)
            elif path == "/favicon.ico":
                icon = resource_path("app_icon.ico")
                if os.path.exists(icon):
                    with open(icon, "rb") as f:
                        self._send(200, f.read(), "image/x-icon")
                else:
                    self._send(404, b"", "text/plain")
            else:
                self._json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_HEAD = do_GET

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                self._json({"error": "資料太大"}, 413)
                return
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("bad payload")
        except Exception:
            self._json({"error": "格式錯誤"}, 400)
            return
        path = urlparse(self.path).path
        if path == "/api/join":
            code, obj = self.app.join(data)
        elif path == "/api/answer":
            code, obj = self.app.submit(data)
        else:
            code, obj = 404, {"error": "not found"}
        self._json(obj, code)


class ClassroomServer(QObject):
    """在本機提供學生網頁與 API，並以 Qt 訊號通知主程式。"""
    answer_received = pyqtSignal(dict)
    student_joined = pyqtSignal(dict)
    mission_changed = pyqtSignal(dict)
    paused_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.session = uuid.uuid4().hex[:10]
        self.version = 0
        self.mission_type = MissionType.NONE
        self.mission_jpeg = None
        self.paused = False      # 暫停作答
        self.retry = False       # 目前題目是否為「重新作答」
        self.students = {}
        self.answers = {}
        self.httpd = None
        self.port = None

    # ----- 生命週期 -----
    def start(self, port=DEFAULT_PORT):
        last_err = None
        for p in range(port, port + 20):
            try:
                self.httpd = _LanHTTPServer(("0.0.0.0", p), _Handler)
                self.httpd.app = self
                self.port = p
                threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
                logging.info(f"LAN server started on port {p}")
                return True, p
            except OSError as e:
                last_err = e
        return False, str(last_err)

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None

    @property
    def running(self):
        return self.httpd is not None

    def urls(self):
        return [f"http://{ip}:{self.port}/" for ip in get_lan_ips()]

    # ----- 給 HTTP 執行緒呼叫 -----
    def student_page(self):
        path = resource_path(os.path.join("templates", "index_lan.html"))
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return "<h1>找不到學生端網頁 templates/index_lan.html</h1>".encode("utf-8")

    def mission_image(self):
        with self.lock:
            return self.mission_jpeg

    def poll(self, sid):
        with self.lock:
            st = self.students.get(sid)
            if st:
                st["last_seen"] = time.time()
            return {
                "session": self.session,
                "version": self.version,
                "type": self.mission_type,
                "has_image": self.mission_jpeg is not None,
                "known": st is not None,
                "paused": self.paused,
                "retry": self.retry,
            }

    def join(self, data):
        sid = str(data.get("sid", ""))[:64]
        name = str(data.get("name", "")).strip()[:20]
        if not sid or not name:
            return 400, {"error": "缺少姓名"}
        now = time.time()
        with self.lock:
            st = self.students.setdefault(sid, {"sid": sid, "joined": now})
            st.update(name=name, last_seen=now)
            info = dict(st)
        self.student_joined.emit(info)
        return 200, {"ok": True, "session": self.session}

    def submit(self, data):
        sid = str(data.get("sid", ""))[:64]
        name = str(data.get("name", "")).strip()[:20] or "匿名"
        atype = data.get("type")
        content = data.get("content")
        with self.lock:
            if data.get("version") != self.version or atype != self.mission_type:
                return 409, {"error": "題目已更新"}
            if self.paused:
                return 423, {"error": "老師已暫停作答"}
            if not isinstance(content, str) or not content:
                return 400, {"error": "沒有內容"}
            if atype in (MissionType.DRAW, MissionType.CALC) and not content.startswith("data:image/"):
                return 400, {"error": "圖片格式錯誤"}
            pages = data.get("pages")
            if atype == MissionType.CALC:
                if not (isinstance(pages, list) and 1 <= len(pages) <= MAX_CALC_PAGES
                        and all(isinstance(pg, str) and pg.startswith("data:image/") for pg in pages)):
                    return 400, {"error": "計算紙資料不完整"}
            if atype == MissionType.CHOICE and content not in ("A", "B", "C", "D"):
                return 400, {"error": "選項錯誤"}
            if atype == MissionType.TEXT:
                content = content.strip()[:300]
            ans = {
                "key": sid, "sid": sid, "name": name, "type": atype, "content": content,
                "timestamp": int(time.time() * 1000), "version": self.version,
            }
            replay = data.get("replay")
            if atype == MissionType.DRAW and isinstance(replay, dict) and isinstance(replay.get("strokes"), list):
                ans["replay"] = replay  # 繪圖重播用的筆畫路徑
            if atype == MissionType.CALC:
                ans["pages"] = pages  # 每一頁計算紙（各自完整解析度）
                empty = data.get("empty")
                n = len(pages)
                ans["empty"] = [bool(x) for x in empty] if isinstance(empty, list) and len(empty) == n else [False] * n
            self.answers[sid] = ans
            if sid in self.students:
                self.students[sid]["name"] = name
                self.students[sid]["last_seen"] = time.time()
        self.answer_received.emit(dict(ans))
        return 200, {"ok": True}

    # ----- 給主程式呼叫 -----
    def send_mission(self, m_type, jpeg_bytes, retry=False):
        with self.lock:
            self.version += 1
            self.mission_type = m_type
            self.mission_jpeg = jpeg_bytes
            self.paused = False
            self.retry = retry
            self.answers.clear()
            info = {"version": self.version, "type": m_type, "retry": retry}
        logging.info(f"Mission {m_type} v{info['version']} sent" + (" (retry)" if retry else ""))
        self.mission_changed.emit(info)
        self.paused_changed.emit(False)

    def restart_mission(self):
        """同一張截圖、同一題型重新作答，清空原作答紀錄。"""
        with self.lock:
            m_type, jpeg = self.mission_type, self.mission_jpeg
        if m_type == MissionType.NONE:
            return False
        self.send_mission(m_type, jpeg, retry=True)
        return True

    def set_paused(self, paused):
        with self.lock:
            if self.mission_type == MissionType.NONE:
                paused = False
            changed = self.paused != paused
            self.paused = paused
        if changed:
            logging.info("Answers paused" if paused else "Answers resumed")
            self.paused_changed.emit(paused)

    def clear_mission(self):
        self.send_mission(MissionType.NONE, None)

    def snapshot_students(self):
        now = time.time()
        with self.lock:
            out = []
            for st in self.students.values():
                d = dict(st)
                d["online"] = now - st.get("last_seen", 0) < ONLINE_TIMEOUT
                d["answered"] = st["sid"] in self.answers
                out.append(d)
        out.sort(key=lambda d: d.get("joined", 0))
        return out

    def snapshot_answers(self):
        with self.lock:
            return sorted((dict(a) for a in self.answers.values()), key=lambda a: a["timestamp"])

    def online_count(self):
        return sum(1 for s in self.snapshot_students() if s["online"])

    def remove_offline_students(self):
        now = time.time()
        with self.lock:
            for sid in [s for s, st in self.students.items() if now - st.get("last_seen", 0) >= ONLINE_TIMEOUT]:
                del self.students[sid]


##########################################
# 共用小元件
##########################################
class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ScaledPixmapLabel(QLabel):
    """隨大小自動縮放的圖片。"""

    def __init__(self, pixmap=None):
        super().__init__()
        self._pm = pixmap
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMinimumSize(px(80), px(80))

    def set_source(self, pm):
        self._pm = pm
        self._refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self):
        if self._pm and not self._pm.isNull():
            self.setPixmap(self._pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class DragHandle(QLabel):
    """拖曳視窗用的把手（支援觸控）。"""

    def __init__(self, text=""):
        super().__init__(text)
        self._off = None
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._off = e.globalPos() - self.window().frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._off is not None and e.buttons() & Qt.LeftButton:
            self.window().move(e.globalPos() - self._off)

    def mouseReleaseEvent(self, e):
        self._off = None
        cb = getattr(self.window(), "on_drag_finished", None)
        if cb:
            QTimer.singleShot(0, cb)


class ResponsiveGrid(QScrollArea):
    """依寬度自動調整欄數的卡片格線。"""

    def __init__(self, item_width, empty_text=""):
        super().__init__()
        self.item_width = item_width
        self.spacing = px(18)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.inner = QWidget()
        self.grid = QGridLayout(self.inner)
        self.grid.setSpacing(self.spacing)
        self.grid.setContentsMargins(px(4), px(4), px(4), px(4))
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setWidget(self.inner)
        self.items = []
        self._cols = 0
        self.empty = make_label(empty_text, "muted", True, Qt.AlignCenter)
        self.empty.setStyleSheet(f"font-size: {px(20)}px; padding: {px(60)}px;")
        self.grid.addWidget(self.empty, 0, 0)

    def add(self, w):
        self.items.append(w)
        self._relayout(force=True)

    def clear(self):
        for w in self.items:
            self.grid.removeWidget(w)
            w.deleteLater()
        self.items = []
        self._relayout(force=True)

    def _relayout(self, force=False):
        cols = max(1, (self.viewport().width() + self.spacing) // (self.item_width + self.spacing))
        if not force and cols == self._cols:
            return
        self._cols = cols
        for w in self.items:
            self.grid.removeWidget(w)
        self.empty.setVisible(not self.items)
        for i, w in enumerate(self.items):
            self.grid.addWidget(w, i // cols, i % cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()


##########################################
# 學生連線對話框（QR Code）
##########################################
class ConnectionDialog(QDialog):
    def __init__(self, server, parent=None):
        super().__init__(parent)
        self.server = server
        self.setWindowTitle("學生連線")
        self.setWindowIcon(app_icon())
        root = QVBoxLayout(self)
        root.setContentsMargins(px(32), px(28), px(32), px(28))
        root.setSpacing(px(18))

        root.addWidget(make_label("📱 學生連線", "h1"))
        root.addWidget(make_label("請學生用 iPad 相機掃描 QR Code，或在 Safari 輸入下方網址", "muted", True))

        body = QHBoxLayout()
        body.setSpacing(px(24))
        qr_card = make_card()
        qv = QVBoxLayout(qr_card)
        qv.setContentsMargins(px(20), px(20), px(20), px(20))
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(px(340), px(340))
        self.qr_label.setAlignment(Qt.AlignCenter)
        qv.addWidget(self.qr_label)
        body.addWidget(qr_card)

        info = QVBoxLayout()
        info.setSpacing(px(12))
        info.addWidget(make_label("連線網址", "section"))
        self.url_label = make_label("", wrap=True)
        self.url_label.setStyleSheet(f"font-size: {px(30)}px; font-weight: 800; color: {C.LAV_D};")
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.addWidget(self.url_label)

        self.ips = server.urls() if server.running else []
        if len(self.ips) > 1:
            info.addWidget(make_label("網路介面（若學生連不上，請試試其他選項）", "section", True))
            self.ip_combo = QComboBox()
            for u in self.ips:
                self.ip_combo.addItem(u)
            self.ip_combo.currentIndexChanged.connect(self.refresh)
            info.addWidget(self.ip_combo)
        else:
            self.ip_combo = None

        btn_row = QHBoxLayout()
        btn_copy = make_button("📋 複製網址", "mint", 56)
        btn_copy.clicked.connect(self.copy_url)
        btn_open = make_button("🌐 本機預覽", "sky", 56)
        btn_open.clicked.connect(lambda: webbrowser.open(self.current_url()))
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_open)
        info.addLayout(btn_row)

        tips = make_card("soft")
        tv = QVBoxLayout(tips)
        tv.setContentsMargins(px(18), px(14), px(18), px(14))
        tip = make_label(
            "💡 小提醒\n"
            "• iPad 與這台電腦必須連在同一個 Wi-Fi／區域網路\n"
            "• 第一次執行若跳出 Windows 防火牆，請允許「私人網路」存取\n"
            "• 若學校 Wi-Fi 會隔離裝置，可改用同一台分享器",
            wrap=True)
        tip.setStyleSheet(f"font-size: {px(14)}px; line-height: 150%;")
        tv.addWidget(tip)
        info.addWidget(tips)
        info.addStretch()
        body.addLayout(info, 1)
        root.addLayout(body)

        bottom = QHBoxLayout()
        self.count_label = make_label("", "chip")
        bottom.addWidget(self.count_label)
        bottom.addStretch()
        btn_close = make_button("關閉", "lav", 56)
        btn_close.setMinimumWidth(px(160))
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        root.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_count)
        self.timer.start(1500)
        self.refresh()
        self.update_count()
        fit_resize(self, px(980), px(560))

    def current_url(self):
        if not self.ips:
            return ""
        return self.ip_combo.currentText() if self.ip_combo else self.ips[0]

    def refresh(self):
        url = self.current_url()
        if not url:
            self.url_label.setText("伺服器未啟動")
            self.qr_label.setText("無法產生 QR Code")
            return
        self.url_label.setText(url.rstrip("/"))
        pm = make_qr_pixmap(url, px(340))
        if pm:
            self.qr_label.setPixmap(pm.scaled(px(340), px(340), Qt.KeepAspectRatio, Qt.FastTransformation))
        else:
            self.qr_label.setText("未安裝 qrcode 套件\npip install qrcode")

    def update_count(self):
        self.count_label.setText(f"👥 已連線 {self.server.online_count()} 位學生")

    def copy_url(self):
        QApplication.clipboard().setText(self.current_url())
        self.count_label.setText("✅ 已複製網址")


##########################################
# 使用說明
##########################################
class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("使用說明")
        self.setWindowIcon(app_icon())
        fit_resize(self, px(820), px(680))
        v = QVBoxLayout(self)
        v.setContentsMargins(px(28), px(24), px(28), px(24))
        v.setSpacing(px(16))
        v.addWidget(make_label("📖 使用說明", "h1"))
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(f"""
        <div style="font-size:{px(17)}px; line-height:170%; color:{C.INK}">
        <h3 style="color:{C.LAV_D}">① 讓學生連線</h3>
        <p>程式開啟時會自動在這台電腦建立課堂伺服器（不需要網際網路、不需要 Firebase）。
        按「📱 學生連線」顯示 QR Code，學生用 iPad 相機掃描即可在 Safari 開啟並輸入名字加入。</p>
        <h3 style="color:{C.MINT_D}">② 畫記與出題</h3>
        <p>按「開始繪圖」後，畫面會凍結為截圖，可用觸控直接畫記。
        需要出題時按「✂️ 截圖出題」，在畫面上拖曳框選題目範圍，再選擇
        <b>塗鴉題／選擇題／簡答題／計算題</b>後發送，學生 iPad 會立即收到。</p>
        <p><b>🧮 計算題</b>：學生使用計算紙作答（預設 4 頁、可自行新增到 20 頁；點一格放大書寫、左右滑頁、兩指捏合回全覽），
        儀表板可看每位學生所有頁的總覽，並點任一頁單獨放大。</p>
        <p>不需要畫記時，也可以直接在主面板按「✂️ 截圖出題」框選畫面出題（按上方「✕ 取消框選」或右鍵可取消）。</p>
        <p><b>📚 題庫</b>：出題視窗按「💾 存入題庫」可先存起來，上課時在題庫按「🚀 派送」即可；題庫可匯出／匯入 ZIP（含截圖原檔）。</p>
        <h3 style="color:{C.PEACH_D}">③ 查看作答</h3>
        <p>「📊 儀表板」會即時顯示學生回答（不需手動更新）。塗鴉與簡答可點卡片放大投影，
        塗鴉可選取最多 4 張並排比較，也可一鍵下載全部作答。
        另有「🎲 抽人」「⏸ 暫停作答」「🔁 重新作答」（同一張截圖重新作答並清空紀錄）。
        塗鴉題可按「🎬 繪圖重播」在截圖上重播學生的作畫過程，可切換 1X／2X／3X 速度。</p>
        <h3 style="color:{C.SKY_D}">連不上怎麼辦？</h3>
        <ul>
        <li>確認 iPad 與電腦在同一個 Wi-Fi／網段。</li>
        <li>第一次執行時 Windows 會詢問防火牆，請允許「私人網路」。若曾按下拒絕，可到
        「Windows 安全性 → 防火牆 → 允許應用程式通過防火牆」中勾選 Python 或本程式。</li>
        <li>電腦有多張網卡時，在「學生連線」視窗切換其他網址試試。</li>
        <li>部分校園 Wi-Fi 會隔離用戶端，請改用同一台無線分享器。</li>
        </ul>
        <p>介面大小會依螢幕解析度自動調整（4K 螢幕自動放大），也可在主面板用「A－／A＋」微調。</p>
        <p style="color:{C.MUTED}">小技巧：學生可在 Safari「分享 → 加入主畫面」，下次一點就能開啟。</p>
        </div>""")
        v.addWidget(tb)
        btn = make_button("我知道了", "lav", 56)
        btn.clicked.connect(self.accept)
        v.addWidget(btn, alignment=Qt.AlignRight)


##########################################
# 出題對話框
##########################################
class TileButton(QPushButton):
    def __init__(self, emoji, title, sub):
        super().__init__()
        self.setProperty("tile", True)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumHeight(px(150))
        v = QVBoxLayout(self)
        v.setContentsMargins(px(12), px(16), px(12), px(16))
        v.setSpacing(px(4))
        for text, style in ((emoji, f"font-size:{px(40)}px;"),
                            (title, f"font-size:{px(20)}px; font-weight:800;"),
                            (sub, f"font-size:{px(13)}px; color:{C.MUTED};")):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(style + "background: transparent;")
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            v.addWidget(lbl)


class MissionConfigDialog(QDialog):
    def __init__(self, parent, screenshot_pixmap, server, control_panel):
        super().__init__(parent)
        self.screenshot = screenshot_pixmap
        self.server = server
        self.control_panel = control_panel
        self.settings = QSettings(*SETTINGS_KEY)
        self.setWindowTitle("發送互動任務")
        self.setWindowIcon(app_icon())

        v = QVBoxLayout(self)
        v.setContentsMargins(px(32), px(28), px(32), px(28))
        v.setSpacing(px(16))
        v.addWidget(make_label("🚀 發送互動任務", "h1"))
        v.addWidget(make_label("學生會在 iPad 上看到這張截圖", "muted"))

        prev_card = make_card("soft")
        pv = QVBoxLayout(prev_card)
        pv.setContentsMargins(px(12), px(12), px(12), px(12))
        preview = ScaledPixmapLabel(self.screenshot)
        preview.setMinimumHeight(px(240))
        pv.addWidget(preview)
        v.addWidget(prev_card, 1)

        v.addWidget(make_label("選擇題型", "h2"))
        tiles = QHBoxLayout()
        tiles.setSpacing(px(16))
        self.tiles = build_type_tiles(self, tiles, self.settings.value("last_mission", MissionType.DRAW))
        v.addLayout(tiles)

        opt = QHBoxLayout()
        opt.setSpacing(px(12))
        opt.addWidget(make_label("題目名稱", "section"))
        self.title_edit = QLineEdit(f"題目 {len(control_panel.presets.items) + 1}")
        self.title_edit.setMaxLength(40)
        self.title_edit.setPlaceholderText("存入題庫時使用的名稱")
        opt.addWidget(self.title_edit, 1)
        self.chk_dash = QCheckBox("發送後開啟儀表板")
        self.chk_dash.setChecked(self.settings.value("open_dash", "true") == "true")
        opt.addWidget(self.chk_dash)
        v.addLayout(opt)

        bottom = QHBoxLayout()
        bottom.addWidget(make_label(f"👥 目前在線 {server.online_count()} 位學生", "chip"))
        bottom.addStretch()
        btn_cancel = make_button("取消", height=60)
        btn_cancel.setMinimumWidth(px(140))
        btn_cancel.clicked.connect(self.reject)
        btn_save = make_button("💾 存入題庫", "mint", 60, font_px=18)
        btn_save.setToolTip("先存起來，之後在「📚 題庫」一鍵派送")
        btn_save.clicked.connect(self.save_preset)
        btn_send = make_button("🚀 發送任務", "lav", 60, font_px=19)
        btn_send.setMinimumWidth(px(220))
        btn_send.clicked.connect(self.send_mission)
        bottom.addWidget(btn_cancel)
        bottom.addWidget(btn_save)
        bottom.addWidget(btn_send)
        v.addLayout(bottom)
        fit_resize(self, px(820), px(720))

    def save_preset(self):
        m_type = checked_type(self.tiles)
        try:
            self.control_panel.presets.add(self.screenshot, m_type, self.title_edit.text())
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"存入題庫失敗：{e}")
            return
        self.settings.setValue("last_mission", m_type)
        self.done(2)  # 2 = 已存入題庫

    def send_mission(self):
        m_type = checked_type(self.tiles)
        try:
            jpeg = pixmap_to_jpeg(self.screenshot) if self.screenshot else None
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"圖片壓縮失敗：{e}")
            return
        self.settings.setValue("last_mission", m_type)
        self.settings.setValue("open_dash", "true" if self.chk_dash.isChecked() else "false")
        self.control_panel.live_preset_id = None
        self.server.send_mission(m_type, jpeg)
        if self.chk_dash.isChecked():
            QTimer.singleShot(0, self.control_panel.show_dashboard)
        self.accept()


##########################################
# 放大檢視 / 比較
##########################################
class ShowcaseDialog(QDialog):
    """全螢幕逐一瀏覽學生作答（圖片或文字）。"""

    def __init__(self, parent, items, index=0):
        super().__init__(parent)
        self.items = items  # [{'name', 'pixmap' | 'text'}]
        self.index = index
        self.setWindowTitle("作答展示")
        self.setWindowIcon(app_icon())
        v = QVBoxLayout(self)
        v.setContentsMargins(px(28), px(20), px(28), px(20))
        v.setSpacing(px(14))

        top = QHBoxLayout()
        self.name_label = make_label("", "h1")
        self.counter = make_label("", "chip")
        btn_close = make_button("✕ 關閉", "pink", 56)
        btn_close.setMinimumWidth(px(140))
        btn_close.clicked.connect(self.accept)
        top.addWidget(self.name_label)
        top.addSpacing(px(12))
        top.addWidget(self.counter)
        top.addStretch()
        top.addWidget(btn_close)
        v.addLayout(top)

        card = make_card()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(px(20), px(20), px(20), px(20))
        self.stack = QStackedWidget()
        self.image = ScaledPixmapLabel()
        self.text = make_label("", wrap=True, align=Qt.AlignCenter)
        self.text.setStyleSheet(f"font-size: {px(46)}px; font-weight: 700; padding: {px(40)}px;")
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stack.addWidget(self.image)
        self.stack.addWidget(self.text)
        cv.addWidget(self.stack)
        v.addWidget(card, 1)

        nav = QHBoxLayout()
        self.btn_prev = make_button("◀  上一位", "sky", 64, font_px=19)
        self.btn_next = make_button("下一位  ▶", "sky", 64, font_px=19)
        self.btn_prev.setMinimumWidth(px(220))
        self.btn_next.setMinimumWidth(px(220))
        self.btn_prev.clicked.connect(lambda: self.go(-1))
        self.btn_next.clicked.connect(lambda: self.go(1))
        nav.addWidget(self.btn_prev)
        nav.addStretch()
        nav.addWidget(self.btn_next)
        v.addLayout(nav)
        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self.go(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self.go(1))
        self.render_item()
        self.setWindowState(Qt.WindowMaximized)

    def go(self, d):
        self.index = (self.index + d) % len(self.items)
        self.render_item()

    def render_item(self):
        it = self.items[self.index]
        self.name_label.setText(it["name"])
        self.counter.setText(f"{self.index + 1} / {len(self.items)}")
        if it.get("pixmap") is not None:
            self.image.set_source(it["pixmap"])
            self.stack.setCurrentWidget(self.image)
        else:
            self.text.setText(it.get("text", ""))
            self.stack.setCurrentWidget(self.text)
        multi = len(self.items) > 1
        self.btn_prev.setVisible(multi)
        self.btn_next.setVisible(multi)


class CompareDialog(QDialog):
    def __init__(self, parent, selected):
        super().__init__(parent)
        self.setWindowTitle("並排比較")
        self.setWindowIcon(app_icon())
        v = QVBoxLayout(self)
        v.setContentsMargins(px(24), px(18), px(24), px(18))
        v.setSpacing(px(14))
        top = QHBoxLayout()
        top.addWidget(make_label(f"🔍 並排比較 {len(selected)} 份作答", "h1"))
        top.addStretch()
        btn_close = make_button("✕ 關閉", "pink", 56)
        btn_close.setMinimumWidth(px(140))
        btn_close.clicked.connect(self.accept)
        top.addWidget(btn_close)
        v.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(px(16))
        cols = 1 if len(selected) == 1 else 2
        tones = [C.PINK, C.MINT, C.SKY, C.LEMON]
        for i, (name, pm) in enumerate(selected):
            card = make_card()
            cv = QVBoxLayout(card)
            cv.setContentsMargins(px(14), px(12), px(14), px(14))
            tag = make_label(name, align=Qt.AlignCenter)
            tag.setStyleSheet(f"background:{tones[i % 4]}; border-radius:{px(14)}px; padding:{px(8)}px;"
                              f"font-size:{px(20)}px; font-weight:800;")
            cv.addWidget(tag)
            cv.addWidget(ScaledPixmapLabel(pm), 1)
            grid.addWidget(card, i // cols, i % cols)
        v.addLayout(grid, 1)
        self.setWindowState(Qt.WindowMaximized)


##########################################
# 儀表板元件
##########################################
class AnswerCard(QFrame):
    open_requested = pyqtSignal(str)
    select_toggled = pyqtSignal(str, bool)
    replay_requested = pyqtSignal(str)

    def __init__(self, key, kind, width, height):
        super().__init__()
        self.key = key
        self.kind = kind
        self.setObjectName("card")
        self.setFixedSize(width, height)
        soft_shadow(self, 24, 4, 22)
        v = QVBoxLayout(self)
        m = px(12)
        v.setContentsMargins(m, m, m, m)
        v.setSpacing(px(8))
        footer_h = px(44)
        self.body_size = QSize(width - 2 * m, height - 2 * m - px(8) - footer_h)
        self.body = ClickableLabel()
        self.body.setFixedSize(self.body_size)
        self.body.setCursor(Qt.PointingHandCursor)
        self.body.clicked.connect(lambda: self.open_requested.emit(self.key))
        if kind in ("draw", "calc"):
            self.body.setAlignment(Qt.AlignCenter)
            self.body.setStyleSheet(f"background: {C.SURFACE_2}; border-radius: {px(14)}px;")
        else:
            self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            self.body.setWordWrap(True)
            self.body.setStyleSheet(f"background: {C.SURFACE_2}; border-radius: {px(14)}px;"
                                    f"padding: {px(14)}px; font-size: {px(20)}px; font-weight: 600;")
        v.addWidget(self.body)

        foot = QHBoxLayout()
        foot.setSpacing(px(8))
        self.name = make_label("")
        self.name.setStyleSheet(f"font-size: {px(17)}px; font-weight: 800;")
        self.time = make_label("", "muted")
        self.time.setStyleSheet(f"font-size: {px(13)}px;")
        foot.addWidget(self.name)
        foot.addWidget(self.time)
        foot.addStretch()
        self.btn_sel = None
        self.btn_replay = None
        if kind in ("draw", "calc"):
            self.btn_replay = make_button("🎬", "sky")
            self.btn_replay.setToolTip("繪圖重播")
            self.btn_replay.setFixedSize(px(48), footer_h)
            self.btn_replay.setStyleSheet(f"padding:0; border-radius:{px(12)}px; font-size:{px(18)}px;")
            self.btn_replay.clicked.connect(lambda: self.replay_requested.emit(self.key))
            if kind == "draw":
                foot.addWidget(self.btn_replay)
            else:  # 計算題沒有重播
                self.btn_replay.deleteLater()
                self.btn_replay = None
            self.btn_sel = make_button("☆ 選取", checkable=True, tool=True)
            self.btn_sel.setFixedHeight(footer_h)
            self.btn_sel.setStyleSheet(f"padding: 0 {px(12)}px; border-radius: {px(12)}px; font-size: {px(14)}px;")
            self.btn_sel.toggled.connect(self._on_toggle)
            foot.addWidget(self.btn_sel)
        v.addLayout(foot)

    def _on_toggle(self, on):
        self.btn_sel.setText("★ 已選" if on else "☆ 選取")
        self.select_toggled.emit(self.key, on)

    def set_selected(self, on):
        if self.btn_sel:
            self.btn_sel.blockSignals(True)
            self.btn_sel.setChecked(on)
            self.btn_sel.setText("★ 已選" if on else "☆ 選取")
            self.btn_sel.blockSignals(False)

    def set_data(self, name, timestamp, pixmap=None, text=None, has_replay=False):
        self.name.setText(name)
        if self.btn_replay:
            self.btn_replay.setEnabled(has_replay)
        self.time.setText(datetime.datetime.fromtimestamp(timestamp / 1000).strftime("%H:%M:%S"))
        if self.kind in ("draw", "calc"):
            if pixmap:
                self.body.setPixmap(pixmap.scaled(self.body_size - QSize(px(8), px(8)),
                                                  Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.body.setText("圖片載入失敗")
        else:
            self.body.setText(text or "")


class BarWidget(QWidget):
    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.value = 0.0
        self.setFixedHeight(px(34))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, v):
        self.value = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C.SURFACE_2))
        p.drawRoundedRect(r, rad, rad)
        if self.value > 0:
            w = max(r.height(), r.width() * self.value)
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(r.x(), r.y(), w, r.height()), rad, rad)
        p.end()


class ChoiceStatsWidget(QWidget):
    OPTS = [("A", C.PINK, C.PINK_D), ("B", C.MINT, C.MINT_D), ("C", C.SKY, C.SKY_D), ("D", C.LEMON, C.LEMON_D)]

    def __init__(self):
        super().__init__()
        self.show_names = True
        self.stats = {o: [] for o, _, _ in self.OPTS}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(px(14))
        self.rows = {}
        for opt, bg, deep in self.OPTS:
            card = make_card()
            h = QHBoxLayout(card)
            h.setContentsMargins(px(18), px(14), px(22), px(14))
            h.setSpacing(px(20))
            badge = make_label(opt, align=Qt.AlignCenter)
            badge.setFixedSize(px(72), px(72))
            badge.setStyleSheet(f"background:{bg}; border-radius:{px(24)}px; font-size:{px(34)}px; font-weight:800;")
            h.addWidget(badge)
            mid = QVBoxLayout()
            mid.setSpacing(px(8))
            bar = BarWidget(deep)
            names = make_label("", "muted", True)
            names.setStyleSheet(f"font-size:{px(15)}px;")
            mid.addStretch()
            mid.addWidget(bar)
            mid.addWidget(names)
            mid.addStretch()
            h.addLayout(mid, 1)
            count = make_label("0", align=Qt.AlignRight | Qt.AlignVCenter)
            count.setMinimumWidth(px(110))
            count.setStyleSheet(f"font-size:{px(34)}px; font-weight:800;")
            h.addWidget(count)
            v.addWidget(card)
            self.rows[opt] = (bar, names, count)
        v.addStretch()

    def reset_stats(self):
        self.stats = {o: [] for o in self.stats}
        self.refresh()

    def set_answer(self, key, option, name):
        for lst in self.stats.values():
            lst[:] = [x for x in lst if x[0] != key]
        if option in self.stats:
            self.stats[option].append((key, name))
        self.refresh()

    def set_show_names(self, on):
        self.show_names = on
        self.refresh()

    def refresh(self):
        total = sum(len(v) for v in self.stats.values())
        for opt, (bar, names, count) in self.rows.items():
            n = len(self.stats[opt])
            bar.set_value(n / total if total else 0)
            pct = f"<span style='font-size:{px(15)}px; color:{C.MUTED}'> {round(n * 100 / total) if total else 0}%</span>"
            count.setText(f"{n}{pct}")
            names.setText("、".join(nm for _, nm in self.stats[opt]) if self.show_names else "")
            names.setVisible(self.show_names and n > 0)


class CloudViewWidget(QTextBrowser):
    COLORS = [C.PINK_D, C.MINT_D, C.LAV_D, C.PEACH_D, C.SKY_D, C.LEMON_D]

    def __init__(self):
        super().__init__()
        self.answers = {}

    def reset_cloud(self):
        self.answers = {}
        self.render_cloud()

    def set_answer(self, key, text):
        self.answers[key] = text
        self.render_cloud()

    def render_cloud(self):
        counts = {}
        for t in self.answers.values():
            k = t.strip()
            counts[k] = counts.get(k, 0) + 1
        if not counts:
            self.setHtml(f"<p style='color:{C.MUTED}; font-size:{px(20)}px' align='center'><br><br>等待學生作答…</p>")
            return
        parts = []
        for i, (text, n) in enumerate(sorted(counts.items(), key=lambda kv: -kv[1])):
            size = px(min(22 + (n - 1) * 12, 72))
            color = self.COLORS[i % len(self.COLORS)]
            badge = f"<sup style='font-size:{px(14)}px; color:{C.MUTED}'> ×{n}</sup>" if n > 1 else ""
            parts.append(f"<span style='font-size:{size}px; color:{color}; font-weight:800'>"
                         f"{html.escape(text)}</span>{badge}")
        self.setHtml(f"<p align='center' style='line-height:180%'>{' &nbsp;&nbsp;&nbsp; '.join(parts)}</p>")


class StudentChip(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setFixedSize(px(230), px(72))
        h = QHBoxLayout(self)
        h.setContentsMargins(px(16), px(8), px(14), px(8))
        h.setSpacing(px(10))
        self.dot = QLabel("●")
        self.name = QLabel()
        self.name.setStyleSheet(f"font-size:{px(17)}px; font-weight:800;")
        self.state = QLabel()
        h.addWidget(self.dot)
        h.addWidget(self.name, 1)
        h.addWidget(self.state)

    def set_info(self, st):
        self.name.setText(st.get("name", ""))
        self.dot.setStyleSheet(f"color:{C.MINT_D if st['online'] else '#D5CEDA'}; font-size:{px(16)}px;")
        if st["answered"]:
            self.state.setText("✓ 已作答")
            self.state.setStyleSheet(f"background:{C.MINT}; border-radius:{px(10)}px; padding:{px(4)}px {px(10)}px;"
                                     f"font-size:{px(13)}px; font-weight:800;")
        else:
            self.state.setText("作答中" if st["online"] else "離線")
            self.state.setStyleSheet(f"color:{C.MUTED}; font-size:{px(13)}px;")


##########################################
# 題庫：預先截圖並設定題型，可即時派送、匯出/匯入 ZIP
##########################################
PRESET_ZIP_FORMAT = "screen-pen-lan-presets"
VALID_TYPES = (MissionType.DRAW, MissionType.CHOICE, MissionType.TEXT, MissionType.CALC)


class PresetStore:
    """題庫資料：題庫/presets.json + 題庫/images/*.png（截圖原檔）。"""

    def __init__(self, root):
        self.root = root
        self.img_dir = os.path.join(root, "images")
        self.index_path = os.path.join(root, "presets.json")
        self.items = []
        self.load()

    def load(self):
        self.items = []
        try:
            with open(self.index_path, encoding="utf-8") as f:
                data = json.load(f)
            for it in data.get("items", []):
                if it.get("type") in VALID_TYPES and os.path.exists(self.image_path(it)):
                    self.items.append(it)
        except (OSError, ValueError):
            pass

    def save(self):
        os.makedirs(self.root, exist_ok=True)
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"format": PRESET_ZIP_FORMAT, "version": 1, "items": self.items}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.index_path)

    def image_path(self, item):
        return os.path.join(self.img_dir, item["image"])

    def pixmap(self, item):
        pm = QPixmap(self.image_path(item))
        return None if pm.isNull() else pm

    def get(self, pid):
        return next((it for it in self.items if it["id"] == pid), None)

    def _new_item(self, title, m_type, ext="png"):
        pid = uuid.uuid4().hex[:12]
        return {"id": pid, "title": title.strip()[:40] or "未命名題目", "type": m_type,
                "image": f"{pid}.{ext}", "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}

    def add(self, pixmap, m_type, title):
        os.makedirs(self.img_dir, exist_ok=True)
        item = self._new_item(title, m_type)
        if not pixmap.save(self.image_path(item), "PNG"):
            raise OSError("截圖存檔失敗")
        self.items.append(item)
        self.save()
        return item

    def update(self, pid, **fields):
        it = self.get(pid)
        if it:
            if "title" in fields:
                fields["title"] = fields["title"].strip()[:40] or "未命名題目"
            it.update(fields)
            self.save()

    def delete(self, pid):
        it = self.get(pid)
        if it:
            try:
                os.remove(self.image_path(it))
            except OSError:
                pass
            self.items.remove(it)
            self.save()

    def move(self, pid, delta):
        it = self.get(pid)
        if not it:
            return
        i = self.items.index(it)
        j = max(0, min(len(self.items) - 1, i + delta))
        if i != j:
            self.items.insert(j, self.items.pop(i))
            self.save()

    def export_zip(self, path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("presets.json", json.dumps(
                {"format": PRESET_ZIP_FORMAT, "version": 1, "items": self.items}, ensure_ascii=False, indent=2))
            for it in self.items:
                zf.write(self.image_path(it), f"images/{it['image']}")
        return len(self.items)

    def import_zip(self, path):
        """匯入 ZIP，回傳 (成功筆數, 略過筆數)。每筆給新的 id，不會覆蓋既有題目。"""
        added = skipped = 0
        os.makedirs(self.img_dir, exist_ok=True)
        with zipfile.ZipFile(path) as zf:
            try:
                meta = json.loads(zf.read("presets.json").decode("utf-8"))
            except KeyError:
                raise ValueError("ZIP 內找不到 presets.json，這不是題庫匯出檔。")
            for src in meta.get("items", []):
                try:
                    if src.get("type") not in VALID_TYPES:
                        raise ValueError("bad type")
                    data = zf.read(f"images/{src['image']}")
                    img = QImage.fromData(data)
                    if img.isNull():
                        raise ValueError("bad image")
                    item = self._new_item(str(src.get("title", "")), src["type"])
                    if not img.save(self.image_path(item), "PNG"):
                        raise OSError("save failed")
                    if src.get("created"):
                        item["created"] = str(src["created"])[:16]
                    self.items.append(item)
                    added += 1
                except Exception:
                    skipped += 1
        self.save()
        return added, skipped


def build_type_tiles(parent, layout, checked):
    """建立三個題型大卡片，回傳 {type: TileButton}。"""
    group = QButtonGroup(parent)
    tiles = {
        MissionType.DRAW: TileButton("🎨", "塗鴉題", "在圖上畫畫作答"),
        MissionType.CHOICE: TileButton("🔤", "選擇題", "A / B / C / D"),
        MissionType.TEXT: TileButton("📝", "簡答題", "輸入文字回答"),
        MissionType.CALC: TileButton("🧮", "計算題", "多頁計算紙"),
    }
    for t in tiles.values():
        group.addButton(t)
        layout.addWidget(t)
    tiles.get(checked, tiles[MissionType.DRAW]).setChecked(True)
    return tiles


def checked_type(tiles):
    return next(k for k, t in tiles.items() if t.isChecked())


class PresetEditDialog(QDialog):
    def __init__(self, parent, pixmap, title, m_type):
        super().__init__(parent)
        self.setWindowTitle("編輯題目")
        self.setWindowIcon(app_icon())
        v = QVBoxLayout(self)
        v.setContentsMargins(px(32), px(28), px(32), px(28))
        v.setSpacing(px(14))
        v.addWidget(make_label("✏️ 編輯題目", "h1"))
        card = make_card("soft")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(px(12), px(12), px(12), px(12))
        prev = ScaledPixmapLabel(pixmap)
        prev.setMinimumHeight(px(220))
        cv.addWidget(prev)
        v.addWidget(card, 1)
        v.addWidget(make_label("題目名稱", "h2"))
        self.title_edit = QLineEdit(title)
        self.title_edit.setMaxLength(40)
        v.addWidget(self.title_edit)
        v.addWidget(make_label("題型", "h2"))
        row = QHBoxLayout()
        row.setSpacing(px(16))
        self.tiles = build_type_tiles(self, row, m_type)
        v.addLayout(row)
        bottom = QHBoxLayout()
        bottom.addStretch()
        b_cancel = make_button("取消", height=60)
        b_cancel.setMinimumWidth(px(140))
        b_cancel.clicked.connect(self.reject)
        b_ok = make_button("💾 儲存", "lav", 60, font_px=19)
        b_ok.setMinimumWidth(px(200))
        b_ok.clicked.connect(self.accept)
        bottom.addWidget(b_cancel)
        bottom.addWidget(b_ok)
        v.addLayout(bottom)
        fit_resize(self, px(820), px(740))

    def values(self):
        return self.title_edit.text(), checked_type(self.tiles)


class PresetCard(QFrame):
    def __init__(self, library, item, index):
        super().__init__()
        self.library = library
        self.item = item
        self.setObjectName("card")
        self.setFixedSize(px(340), px(330))
        soft_shadow(self, 24, 4, 22)
        v = QVBoxLayout(self)
        v.setContentsMargins(px(12), px(12), px(12), px(12))
        v.setSpacing(px(8))

        thumb = ClickableLabel()
        thumb.setFixedSize(px(316), px(170))
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setCursor(Qt.PointingHandCursor)
        thumb.setStyleSheet(f"background:{C.SURFACE_2}; border-radius:{px(14)}px;")
        pm = library.store.pixmap(item)
        if pm:
            thumb.setPixmap(pm.scaled(px(308), px(162), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        thumb.clicked.connect(lambda: library.edit_item(item["id"]))
        v.addWidget(thumb)

        row = QHBoxLayout()
        row.setSpacing(px(8))
        num = make_label(str(index + 1), align=Qt.AlignCenter)
        num.setFixedSize(px(30), px(30))
        num.setStyleSheet(f"background:{C.LAV}; border-radius:{px(10)}px; font-weight:800; font-size:{px(14)}px;")
        row.addWidget(num)
        title = make_label(item["title"])
        title.setStyleSheet(f"font-size:{px(17)}px; font-weight:800;")
        title.setToolTip(item["title"])
        title.setMinimumWidth(1)
        row.addWidget(title, 1)
        tone = {MissionType.DRAW: C.LAV, MissionType.CHOICE: C.SKY, MissionType.TEXT: C.PEACH,
                MissionType.CALC: C.MINT}[item["type"]]
        chip = make_label(MISSION_LABELS[item["type"]])
        chip.setStyleSheet(f"background:{tone}; border-radius:{px(12)}px; padding:0 {px(10)}px;"
                           f"font-size:{px(13)}px; font-weight:800;")
        chip.setFixedHeight(px(30))
        chip.setAlignment(Qt.AlignCenter)
        row.addWidget(chip, 0, Qt.AlignVCenter)
        v.addLayout(row)

        live = library.control_panel.live_preset_id == item["id"] and \
            library.control_panel.server.mission_type != MissionType.NONE
        btns = QHBoxLayout()
        btns.setSpacing(px(6))
        b_send = make_button("📡 派送中" if live else "🚀 派送", "mint" if live else "lav", 52, font_px=17)
        b_send.clicked.connect(lambda: library.send_item(item["id"]))
        btns.addWidget(b_send, 1)
        for text, tip, slot in (("◀", "往前移", lambda: library.move_item(item["id"], -1)),
                                ("▶", "往後移", lambda: library.move_item(item["id"], 1)),
                                ("✏️", "編輯", lambda: library.edit_item(item["id"])),
                                ("🗑", "刪除", lambda: library.delete_item(item["id"]))):
            b = make_button(text, height=52)
            b.setToolTip(tip)
            b.setFixedWidth(px(46))
            b.setStyleSheet("padding:0;")
            b.clicked.connect(slot)
            btns.addWidget(b)
        v.addLayout(btns)


class PresetLibraryDialog(QDialog):
    def __init__(self, control_panel):
        super().__init__(None)
        self.control_panel = control_panel
        self.store = control_panel.presets
        self.setWindowTitle("題庫")
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)

        v = QVBoxLayout(self)
        v.setContentsMargins(px(32), px(24), px(32), px(24))
        v.setSpacing(px(16))
        head = QHBoxLayout()
        head.setSpacing(px(10))
        tcol = QVBoxLayout()
        tcol.setSpacing(px(2))
        tcol.addWidget(make_label("📚 題庫", "h1"))
        self.summary = make_label("", "muted")
        self.summary.setStyleSheet(f"font-size:{px(16)}px;")
        tcol.addWidget(self.summary)
        head.addLayout(tcol)
        head.addStretch()
        for text, tone, slot in (("＋ 截圖新增", "lav", self.capture_new),
                                 ("⬆ 匯入 ZIP", "sky", self.import_zip),
                                 ("⬇ 匯出 ZIP", "mint", self.export_zip),
                                 ("📂 資料夾", None, self.open_folder)):
            b = make_button(text, tone, 56)
            b.clicked.connect(slot)
            head.addWidget(b)
        v.addLayout(head)

        self.grid = ResponsiveGrid(px(340), "題庫是空的\n\n按「＋ 截圖新增」，或在截圖出題視窗按「💾 存入題庫」即可新增題目")
        v.addWidget(self.grid, 1)
        control_panel.server.mission_changed.connect(lambda _: self.refresh() if self.isVisible() else None)
        self.refresh()
        fit_resize(self, px(1200), px(820))

    def refresh(self):
        self.grid.clear()
        for i, it in enumerate(self.store.items):
            self.grid.add(PresetCard(self, it, i))
        counts = {t: sum(1 for it in self.store.items if it["type"] == t) for t in VALID_TYPES}
        self.summary.setText(f"共 {len(self.store.items)} 題　·　塗鴉 {counts['draw']}　選擇 {counts['choice']}"
                             f"　簡答 {counts['text']}　計算 {counts['calc']}　·　點「🚀 派送」即時發送給學生")

    def send_item(self, pid):
        if self.control_panel.send_preset(pid):
            self.refresh()

    def edit_item(self, pid):
        it = self.store.get(pid)
        if not it:
            return
        dlg = PresetEditDialog(self, self.store.pixmap(it), it["title"], it["type"])
        if dlg.exec_():
            title, m_type = dlg.values()
            self.store.update(pid, title=title, type=m_type)
            self.refresh()

    def move_item(self, pid, delta):
        self.store.move(pid, delta)
        self.refresh()

    def delete_item(self, pid):
        it = self.store.get(pid)
        if it and QMessageBox.question(self, "刪除題目", f"確定要刪除「{it['title']}」嗎？") == QMessageBox.Yes:
            self.store.delete(pid)
            self.refresh()

    def capture_new(self):
        self.hide()
        self.control_panel.on_quick_mission_clicked(after=self.control_panel.show_library)

    def export_zip(self):
        if not self.store.items:
            QMessageBox.information(self, "匯出", "題庫是空的，沒有可以匯出的題目。")
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        path, _ = QFileDialog.getSaveFileName(self, "匯出題庫", f"題庫_{stamp}.zip", "Zip (*.zip)")
        if not path:
            return
        try:
            n = self.store.export_zip(path)
            QMessageBox.information(self, "匯出完成", f"已匯出 {n} 題（含截圖原檔）：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "匯出失敗", str(e))

    def import_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入題庫", "", "Zip (*.zip)")
        if not path:
            return
        try:
            added, skipped = self.store.import_zip(path)
        except (zipfile.BadZipFile, ValueError) as e:
            QMessageBox.warning(self, "匯入失敗", str(e) if isinstance(e, ValueError) else "檔案不是有效的 ZIP。")
            return
        except Exception as e:
            QMessageBox.critical(self, "匯入失敗", str(e))
            return
        self.refresh()
        msg = f"已匯入 {added} 題。"
        if skipped:
            msg += f"\n有 {skipped} 題資料不完整，已略過。"
        QMessageBox.information(self, "匯入完成", msg)

    def open_folder(self):
        os.makedirs(self.store.root, exist_ok=True)
        os.startfile(self.store.root)


##########################################
# 抽人
##########################################
class LuckyDrawDialog(QDialog):
    TONES = {"A": C.PINK, "B": C.MINT, "C": C.SKY, "D": C.LEMON}

    def __init__(self, dashboard):
        super().__init__(dashboard)
        self.dash = dashboard
        self.final = None
        self.ticks = []
        self.setWindowTitle("抽人")
        self.setWindowIcon(app_icon())
        v = QVBoxLayout(self)
        v.setContentsMargins(px(32), px(24), px(32), px(24))
        v.setSpacing(px(14))

        head = QHBoxLayout()
        head.addWidget(make_label("🎲 從回應中抽一位", "h1"))
        head.addStretch()
        self.count = make_label("", "chip")
        head.addWidget(self.count)
        v.addLayout(head)

        card = make_card()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(px(24), px(18), px(24), px(24))
        cv.setSpacing(px(12))
        self.name = make_label("", align=Qt.AlignCenter)
        self.name.setMinimumHeight(px(130))
        cv.addWidget(self.name)
        self.stack = QStackedWidget()
        self.blank = QWidget()
        self.image = ScaledPixmapLabel()
        self.text = make_label("", wrap=True, align=Qt.AlignCenter)
        self.text.setStyleSheet(f"font-size:{px(34)}px; font-weight:700; padding:{px(20)}px;")
        self.choice = make_label("", align=Qt.AlignCenter)
        for w in (self.blank, self.image, self.text, self.choice):
            self.stack.addWidget(w)
        cv.addWidget(self.stack, 1)
        v.addWidget(card, 1)

        self.chk_norepeat = QCheckBox("不重複抽（已抽過的同學不會再被抽到）")
        self.chk_norepeat.setChecked(True)
        v.addWidget(self.chk_norepeat)

        bottom = QHBoxLayout()
        bottom.setSpacing(px(10))
        self.btn_reset = make_button("↺ 重設已抽名單", height=60)
        self.btn_reset.clicked.connect(self.reset_drawn)
        bottom.addWidget(self.btn_reset)
        bottom.addStretch()
        self.btn_zoom = make_button("🔍 放大作答", "sky", 64, font_px=18)
        self.btn_zoom.clicked.connect(self.zoom_answer)
        self.btn_again = make_button("🎲 再抽一次", "lav", 64, font_px=20)
        self.btn_again.setMinimumWidth(px(220))
        self.btn_again.clicked.connect(self.start)
        btn_close = make_button("✕ 關閉", "pink", 64, font_px=18)
        btn_close.clicked.connect(self.accept)
        for b in (self.btn_zoom, self.btn_again, btn_close):
            bottom.addWidget(b)
        v.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._tick)
        fit_resize(self, px(1000), px(760))
        QTimer.singleShot(250, self.start)

    def _set_name(self, text, final=False):
        color = C.LAV_D if final else C.MUTED
        size = px(88) if final else px(72)
        self.name.setStyleSheet(f"font-size:{size}px; font-weight:800; color:{color};")
        self.name.setText(text)

    def update_count(self):
        n = len(self.dash.answers)
        drawn = len(self.dash.drawn & set(self.dash.answers))
        self.count.setText(f"👥 回應 {n} 人　·　已抽 {drawn} 人")

    def reset_drawn(self):
        self.dash.drawn.clear()
        self.update_count()

    def start(self):
        if self.timer.isActive():
            return
        keys = list(self.dash.answers)
        if not keys:
            self._set_name("目前還沒有學生回應")
            self.stack.setCurrentWidget(self.blank)
            self.update_count()
            return
        pool = [k for k in keys if not (self.chk_norepeat.isChecked() and k in self.dash.drawn)]
        if not pool:
            self.dash.drawn.clear()
            pool = keys
        self.final = random.choice(pool)
        names = [self.dash.answers[k]["name"] for k in keys]
        # 由快到慢的滾動動畫
        self.ticks = [int(40 + (i ** 2) * 1.1) for i in range(18)]  # 約 2.7 秒
        self.roll_names = names
        self.stack.setCurrentWidget(self.blank)
        for b in (self.btn_again, self.btn_zoom, self.btn_reset):
            b.setEnabled(False)
        self.update_count()
        self._tick()

    def _tick(self):
        if self.ticks:
            self._set_name(random.choice(self.roll_names))
            self.timer.start(self.ticks.pop(0))
            return
        a = self.dash.answers.get(self.final)
        if not a:
            self.start()
            return
        self.dash.drawn.add(self.final)
        self._set_name(f"🎉 {a['name']}", final=True)
        t = a["type"]
        if t in (MissionType.DRAW, MissionType.CALC) and self.dash.pixmaps.get(self.final):
            self.image.set_source(self.dash.pixmaps[self.final])
            self.stack.setCurrentWidget(self.image)
        elif t == MissionType.TEXT:
            self.text.setText(a["content"])
            self.stack.setCurrentWidget(self.text)
        elif t == MissionType.CHOICE:
            opt = a["content"]
            self.choice.setText(opt)
            self.choice.setStyleSheet(f"background:{self.TONES.get(opt, C.LAV)}; border-radius:{px(40)}px;"
                                      f"font-size:{px(120)}px; font-weight:800; margin:0 {px(260)}px;")
            self.stack.setCurrentWidget(self.choice)
        for b in (self.btn_again, self.btn_zoom, self.btn_reset):
            b.setEnabled(True)
        self.btn_zoom.setVisible(t != MissionType.CHOICE)
        self.update_count()

    def zoom_answer(self):
        a = self.dash.answers.get(self.final)
        if not a:
            return
        if a["type"] == MissionType.CALC:
            self.dash.open_calc(self.final)
            return
        if a["type"] == MissionType.DRAW:
            item = {"name": a["name"], "pixmap": self.dash.pixmaps.get(self.final)}
        else:
            item = {"name": a["name"], "text": a["content"]}
        ShowcaseDialog(self, [item]).exec_()


##########################################
# 繪圖重播：依學生回傳的筆畫路徑，在截圖背景上重現作畫過程
##########################################
REPLAY_GAP_IN_STROKE = 250   # 筆畫內兩點最長間隔（ms），避免停頓太久
REPLAY_GAP_BETWEEN = 600     # 筆畫之間最長間隔（ms）
REPLAY_SPEEDS = (1, 2, 3)


def parse_replay(replay):
    """把學生端的筆畫資料整理成 (strokes, events, duration)。events = [(時間ms, 筆畫序, 點序)]"""
    strokes = []
    for s in (replay or {}).get("strokes", [])[:5000]:
        try:
            pts = [(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0)
                   for p in s.get("pts", []) if len(p) >= 2]
        except (TypeError, ValueError):
            continue
        if not pts:
            continue
        tool = s.get("tool", "pen")
        strokes.append({
            "tool": tool if tool in ("pen", "marker", "eraser") else "pen",
            "color": QColor(str(s.get("color", "#2B2B2B"))),
            "w": max(0.5, float(s.get("w", 4) or 4)),
            "pts": pts,
        })
    strokes.sort(key=lambda s: s["pts"][0][2])
    has_time = any(p[2] for s in strokes for p in s["pts"])
    events, T, last = [], 0.0, None
    for si, s in enumerate(strokes):
        for j, (_x, _y, t) in enumerate(s["pts"]):
            if last is not None:
                if has_time:
                    cap = REPLAY_GAP_BETWEEN if j == 0 else REPLAY_GAP_IN_STROKE
                    T += min(max(t - last, 0.0), cap)
                else:  # 舊資料沒有時間：每點 8ms
                    T += 8.0 if j else 200.0
            last = t
            events.append((T, si, j))
    return strokes, events, T


class ReplayCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.bg = None
        self.strokes, self.events, self.duration = [], [], 0.0
        self.ink = self.layer = None
        self.idx = 0
        self.cur_t = 0.0
        self.active = None

    def load(self, bg, replay):
        self.bg = bg
        self.strokes, self.events, self.duration = parse_replay(replay)
        w = int(replay.get("w") or (bg.width() if bg else 1200))
        h = int(replay.get("h") or (bg.height() if bg else 900))
        self.W, self.H = max(1, w), max(1, h)
        self.ink = QImage(self.W, self.H, QImage.Format_ARGB32_Premultiplied)
        self.layer = QImage(self.W, self.H, QImage.Format_ARGB32_Premultiplied)
        self.reset()

    def reset(self):
        self.ink.fill(Qt.transparent)
        self.layer.fill(Qt.transparent)
        self.idx, self.cur_t, self.active = 0, 0.0, None
        self.update()

    @staticmethod
    def _opacity(stroke):
        return 0.38 if stroke["tool"] == "marker" else 1.0

    def _pen(self, stroke):
        return QPen(stroke["color"], stroke["w"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def _process(self, si, j):
        s = self.strokes[si]
        x, y, _ = s["pts"][j]
        eraser = s["tool"] == "eraser"
        target = self.ink if eraser else self.layer
        if j == 0 and not eraser:
            self.layer.fill(Qt.transparent)
            self.active = si
        p = QPainter(target)
        p.setRenderHint(QPainter.Antialiasing)
        if eraser:
            p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.setPen(self._pen(s))
        if j == 0:
            p.drawPoint(QPointF(x, y))
        else:
            px0, py0, _ = s["pts"][j - 1]
            p.drawLine(QPointF(px0, py0), QPointF(x, y))
        p.end()
        if j == len(s["pts"]) - 1 and not eraser:  # 筆畫結束：合併到墨水層
            p = QPainter(self.ink)
            p.setOpacity(self._opacity(s))
            p.drawImage(0, 0, self.layer)
            p.end()
            self.layer.fill(Qt.transparent)
            self.active = None

    def advance_to(self, t):
        if t < self.cur_t:
            self.reset()
        while self.idx < len(self.events) and self.events[self.idx][0] <= t:
            _, si, j = self.events[self.idx]
            self._process(si, j)
            self.idx += 1
        self.cur_t = t
        self.update()

    def target_rect(self):
        r = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        s = min(r.width() / self.W, r.height() / self.H)
        w, h = self.W * s, self.H * s
        return QRectF(r.x() + (r.width() - w) / 2, r.y() + (r.height() - h) / 2, w, h)

    def paintEvent(self, e):
        if self.ink is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        tr = self.target_rect()
        p.fillRect(tr, QColor("white"))
        if self.bg:
            p.drawPixmap(tr, self.bg, QRectF(self.bg.rect()))
        p.drawImage(tr, self.ink)
        if self.active is not None:
            p.setOpacity(self._opacity(self.strokes[self.active]))
            p.drawImage(tr, self.layer)
        p.end()


class ReplayDialog(QDialog):
    """全螢幕重播學生作畫過程，可 1X / 2X / 3X，並可切換上一位 / 下一位。"""

    def __init__(self, parent, bg, entries, index=0):
        super().__init__(parent)
        self.bg = bg
        self.entries = entries  # [(name, replay)]
        self.index = index
        self.settings = QSettings(*SETTINGS_KEY)
        try:
            self.speed = int(self.settings.value("replay_speed", 1))
        except (TypeError, ValueError):
            self.speed = 1
        if self.speed not in REPLAY_SPEEDS:
            self.speed = 1
        self.playing = False
        self.setWindowTitle("繪圖重播")
        self.setWindowIcon(app_icon())

        v = QVBoxLayout(self)
        v.setContentsMargins(px(28), px(20), px(28), px(20))
        v.setSpacing(px(14))
        top = QHBoxLayout()
        top.addWidget(make_label("🎬", "h1"))
        self.name_label = make_label("", "h1")
        top.addWidget(self.name_label)
        top.addSpacing(px(12))
        self.counter = make_label("", "chip")
        top.addWidget(self.counter)
        top.addStretch()
        btn_close = make_button("✕ 關閉", "pink", 56)
        btn_close.setMinimumWidth(px(140))
        btn_close.clicked.connect(self.accept)
        top.addWidget(btn_close)
        v.addLayout(top)

        card = make_card()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(px(12), px(12), px(12), px(12))
        self.canvas = ReplayCanvas()
        cv.addWidget(self.canvas)
        v.addWidget(card, 1)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(px(10))
        self.btn_prev = make_button("◀ 上一位", "sky", 60)
        self.btn_prev.clicked.connect(lambda: self.go(-1))
        self.btn_restart = make_button("↺", height=60, font_px=22)
        self.btn_restart.setToolTip("從頭重播")
        self.btn_restart.setFixedWidth(px(64))
        self.btn_restart.clicked.connect(self.restart)
        self.btn_play = make_button("⏸", "lav", 60, font_px=22)
        self.btn_play.setFixedWidth(px(80))
        self.btn_play.clicked.connect(self.toggle_play)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimumHeight(px(44))
        self.slider.setMinimumWidth(px(260))
        self.slider.sliderPressed.connect(self.pause)
        self.slider.valueChanged.connect(self.on_seek)
        self.time_label = make_label("", "muted")
        self.time_label.setMinimumWidth(px(130))
        self.time_label.setStyleSheet(f"font-size:{px(16)}px;")
        ctrl.addWidget(self.btn_prev)
        ctrl.addWidget(self.btn_restart)
        ctrl.addWidget(self.btn_play)
        ctrl.addWidget(self.slider, 1)
        ctrl.addWidget(self.time_label)
        self.speed_buttons = {}
        group = QButtonGroup(self)
        for sp in REPLAY_SPEEDS:
            b = make_button(f"{sp}X", checkable=True, height=60, font_px=18)
            b.setProperty("seg", True)
            b.setFixedWidth(px(70))
            b.clicked.connect(lambda _, s=sp: self.set_speed(s))
            group.addButton(b)
            ctrl.addWidget(b)
            self.speed_buttons[sp] = b
        self.speed_buttons[self.speed].setChecked(True)
        self.btn_next = make_button("下一位 ▶", "sky", 60)
        self.btn_next.clicked.connect(lambda: self.go(1))
        ctrl.addWidget(self.btn_next)
        v.addLayout(ctrl)

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        QShortcut(QKeySequence(Qt.Key_Space), self, self.toggle_play)
        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self.go(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self.go(1))
        self.load_entry()
        self.setWindowState(Qt.WindowMaximized)

    def load_entry(self):
        name, replay = self.entries[self.index]
        self.name_label.setText(f"{name} 的作畫過程")
        self.counter.setText(f"{self.index + 1} / {len(self.entries)}")
        multi = len(self.entries) > 1
        self.btn_prev.setVisible(multi)
        self.btn_next.setVisible(multi)
        self.canvas.load(self.bg, replay)
        self.slider.blockSignals(True)
        self.slider.setRange(0, int(self.canvas.duration))
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self._update_time()
        QTimer.singleShot(300, self.play)

    def go(self, d):
        if len(self.entries) > 1:
            self.pause()
            self.index = (self.index + d) % len(self.entries)
            self.load_entry()

    def set_speed(self, sp):
        self.speed = sp
        self.settings.setValue("replay_speed", sp)

    def play(self):
        if self.canvas.cur_t >= self.canvas.duration:
            self.canvas.reset()
        self.playing = True
        self.btn_play.setText("⏸")
        self.clock.start()
        self.timer.start()

    def pause(self):
        self.playing = False
        self.btn_play.setText("▶")
        self.timer.stop()

    def toggle_play(self):
        self.pause() if self.playing else self.play()

    def restart(self):
        self.canvas.reset()
        self.slider.blockSignals(True)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.play()

    def _tick(self):
        dt = self.clock.restart() * self.speed
        t = min(self.canvas.cur_t + dt, self.canvas.duration)
        self.canvas.advance_to(t)
        self.slider.blockSignals(True)
        self.slider.setValue(int(t))
        self.slider.blockSignals(False)
        self._update_time()
        if t >= self.canvas.duration:
            self.pause()

    def on_seek(self, value):
        self.canvas.advance_to(float(value))
        self._update_time()

    def _update_time(self):
        self.time_label.setText(f"{self.canvas.cur_t / 1000:.1f} / {self.canvas.duration / 1000:.1f} 秒")

    def done(self, r):
        self.timer.stop()
        super().done(r)


##########################################
# 計算題檢視：每位學生的四分割計算紙，可逐頁放大
##########################################
class CalcPageTile(QFrame):
    clicked = pyqtSignal(int)

    def __init__(self, index):
        super().__init__()
        self.index = index
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        g = QGridLayout(self)
        g.setContentsMargins(px(8), px(8), px(8), px(8))
        self.image = ScaledPixmapLabel()
        g.addWidget(self.image, 0, 0)
        self.badge = make_label(str(index + 1), align=Qt.AlignCenter)
        self.badge.setFixedSize(px(34), px(34))
        self.badge.setStyleSheet(f"background: rgba(143,135,156,150); color: white; border-radius: {px(15)}px;"
                                 f"font-size: {px(16)}px; font-weight: 800;")
        g.addWidget(self.badge, 0, 0, Qt.AlignTop | Qt.AlignLeft)
        self.empty = make_label("（空白）", "muted", align=Qt.AlignCenter)
        g.addWidget(self.empty, 0, 0)

    def set_page(self, pm, empty):
        self.image.set_source(pm)
        if pm is None:
            self.image.clear()
        self.empty.setVisible(empty)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.pos()):
            self.clicked.emit(self.index)


class CalcViewerDialog(QDialog):
    """entries = [(姓名, [每頁 QPixmap], [是否空白])]；頁數不限"""

    def __init__(self, parent, entries, index=0, page=None):
        super().__init__(parent)
        self.entries = entries
        self.index = index
        self.page = page  # None = 全部頁總覽；0~N-1 = 單頁放大
        self.setWindowTitle("計算過程")
        self.setWindowIcon(app_icon())
        v = QVBoxLayout(self)
        v.setContentsMargins(px(28), px(20), px(28), px(20))
        v.setSpacing(px(14))

        top = QHBoxLayout()
        top.setSpacing(px(10))
        self.name_label = make_label("", "h1")
        top.addWidget(self.name_label)
        self.counter = make_label("", "chip")
        top.addWidget(self.counter)
        top.addStretch()
        self.btn_grid = make_button("⊞ 回總覽", "lav", 56)
        self.btn_grid.clicked.connect(lambda: self.show_page(None))
        top.addWidget(self.btn_grid)
        btn_close = make_button("✕ 關閉", "pink", 56)
        btn_close.setMinimumWidth(px(140))
        btn_close.clicked.connect(self.accept)
        top.addWidget(btn_close)
        v.addLayout(top)

        self.stack = QStackedWidget()
        # 總覽：4 頁以內 2 欄填滿；超過 4 頁改 3 欄並可捲動
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_w = QWidget()
        self.grid = QGridLayout(self.grid_w)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(px(10))
        self.grid_scroll.setWidget(self.grid_w)
        self.tiles = []
        self.stack.addWidget(self.grid_scroll)

        single = make_card()
        sg = QGridLayout(single)
        sg.setContentsMargins(px(12), px(12), px(12), px(12))
        self.single = ScaledPixmapLabel()
        sg.addWidget(self.single, 0, 0)
        self.single_badge = make_label("", align=Qt.AlignCenter)
        self.single_badge.setStyleSheet(f"background: rgba(143,135,156,160); color: white; border-radius: {px(18)}px;"
                                        f"font-size: {px(18)}px; font-weight: 800; padding: {px(6)}px {px(16)}px;")
        sg.addWidget(self.single_badge, 0, 0, Qt.AlignTop | Qt.AlignLeft)
        self.single_empty = make_label("（空白頁）", "muted", align=Qt.AlignCenter)
        self.single_empty.setStyleSheet(f"font-size:{px(24)}px;")
        sg.addWidget(self.single_empty, 0, 0)
        self.stack.addWidget(single)
        self.single_card = single
        v.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        nav.setSpacing(px(10))
        self.btn_prev_stu = make_button("◀ 上一位", "sky", 60)
        self.btn_prev_stu.clicked.connect(lambda: self.go_student(-1))
        self.btn_prev_page = make_button("◀ 上一頁", height=60, font_px=18)
        self.btn_prev_page.clicked.connect(lambda: self.go_page(-1))
        self.page_label = make_label("", "chip")
        self.btn_next_page = make_button("下一頁 ▶", height=60, font_px=18)
        self.btn_next_page.clicked.connect(lambda: self.go_page(1))
        self.btn_next_stu = make_button("下一位 ▶", "sky", 60)
        self.btn_next_stu.clicked.connect(lambda: self.go_student(1))
        nav.addWidget(self.btn_prev_stu)
        nav.addStretch()
        nav.addWidget(self.btn_prev_page)
        nav.addWidget(self.page_label)
        nav.addWidget(self.btn_next_page)
        nav.addStretch()
        nav.addWidget(self.btn_next_stu)
        v.addLayout(nav)

        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self.go_page(-1) if self.page is not None else self.go_student(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self.go_page(1) if self.page is not None else self.go_student(1))
        QShortcut(QKeySequence(Qt.Key_Escape), self, lambda: self.show_page(None) if self.page is not None else self.accept())
        self.render()
        self.setWindowState(Qt.WindowMaximized)

    def go_student(self, d):
        if len(self.entries) > 1:
            self.index = (self.index + d) % len(self.entries)
            self.render()

    def go_page(self, d):
        if self.page is not None:
            self.page = (self.page + d) % len(self.entries[self.index][1])
            self.render()

    def show_page(self, page):
        self.page = page
        self.render()

    def render(self):
        name, pages, empty = self.entries[self.index]
        n = len(pages)
        if self.page is not None and self.page >= n:
            self.page = n - 1
        self.name_label.setText(f"🧮 {name} 的計算過程（共 {n} 頁）")
        self.counter.setText(f"{self.index + 1} / {len(self.entries)}")
        multi = len(self.entries) > 1
        self.btn_prev_stu.setVisible(multi)
        self.btn_next_stu.setVisible(multi)
        single = self.page is not None
        for w in (self.btn_prev_page, self.btn_next_page, self.page_label, self.btn_grid):
            w.setVisible(single)
        if single:
            self.single.set_source(pages[self.page])
            if pages[self.page] is None:
                self.single.clear()
            self.single_badge.setText(f"第 {self.page + 1} 頁")
            self.single_empty.setVisible(empty[self.page])
            self.page_label.setText(f"第 {self.page + 1} / {n} 頁")
            self.stack.setCurrentWidget(self.single_card)
        else:
            self.build_tiles(n)
            for i, t in enumerate(self.tiles):
                t.set_page(pages[i], empty[i] if i < len(empty) else False)
            self.stack.setCurrentIndex(0)

    def build_tiles(self, n):
        if len(self.tiles) == n:
            return
        for t in self.tiles:
            self.grid.removeWidget(t)
            t.deleteLater()
        self.tiles = []
        cols = 2 if n <= 4 else 3
        for i in range(n):
            t = CalcPageTile(i)
            t.clicked.connect(self.show_page)
            if n > 4:  # 頁數多時固定高度、可捲動
                t.setMinimumHeight(px(280))
            self.grid.addWidget(t, i // cols, i % cols)
            self.tiles.append(t)
        for c in range(3):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)


##########################################
# 儀表板
##########################################
class DashboardWindow(QMainWindow):
    def __init__(self, server, control_panel):
        super().__init__()
        self.server = server
        self.control_panel = control_panel
        self.setWindowTitle("課堂互動儀表板")
        self.setWindowIcon(app_icon())
        self.mission_type = MissionType.NONE
        self.mission_no = 0
        self.answers = {}
        self.pixmaps = {}
        self.cards = {}
        self.selected = []
        self.chips = {}
        self.drawn = set()  # 本題已抽過的學生
        self.calc_pages = {}  # 計算題：key -> ([每頁 QPixmap], [是否空白])

        self.init_ui()
        server.answer_received.connect(self.on_answer)
        server.mission_changed.connect(self.on_mission)
        server.paused_changed.connect(self.on_paused)
        server.student_joined.connect(lambda _: self.refresh_students())

        self.on_mission({"version": server.version, "type": server.mission_type})
        for ans in server.snapshot_answers():
            self.on_answer(ans)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_students)
        self.timer.start(1500)
        self.refresh_students()

    # ---------- 介面 ----------
    def init_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(px(32), px(24), px(32), px(24))
        v.setSpacing(px(18))

        header = QHBoxLayout()
        header.setSpacing(px(12))
        title_col = QVBoxLayout()
        title_col.setSpacing(px(2))
        title_col.addWidget(make_label("📊 課堂互動儀表板", "h1"))
        self.subtitle = make_label("", "muted")
        self.subtitle.setStyleSheet(f"font-size:{px(16)}px;")
        title_col.addWidget(self.subtitle)
        header.addLayout(title_col)
        header.addStretch()
        self.chip_paused = make_label("⏸ 已暫停作答", "chip")
        self.chip_paused.setStyleSheet(f"background:{C.PINK}; border-color:{C.PINK};")
        self.chip_paused.hide()
        self.chip_online = make_label("", "chip")
        self.chip_answered = make_label("", "chip")
        self.chip_answered.setStyleSheet(f"background:{C.MINT}; border-color:{C.MINT};")
        header.addWidget(self.chip_paused)
        header.addWidget(self.chip_online)
        header.addWidget(self.chip_answered)
        header.addSpacing(px(8))
        self.btn_pause = make_button("⏸ 暫停作答", checkable=True, tool=True, height=56)
        self.btn_pause.setToolTip("暫停後學生無法送出答案，再按一次繼續")
        self.btn_pause.toggled.connect(self.toggle_pause)
        self.btn_retry = make_button("🔁 重新作答", "peach", 56)
        self.btn_retry.setToolTip("同一張截圖讓學生重新作答，並清空目前的作答紀錄")
        self.btn_retry.clicked.connect(self.retry_mission)
        btn_lib = make_button("📚 題庫", "lemon", 56)
        btn_lib.clicked.connect(self.control_panel.show_library)
        btn_conn = make_button("📱 學生連線", "sky", 56)
        btn_conn.clicked.connect(self.control_panel.show_connection)
        for b in (self.btn_pause, self.btn_retry, btn_lib, btn_conn):
            header.addWidget(b)
        v.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setCursor(Qt.PointingHandCursor)
        v.addWidget(self.tabs, 1)

        # --- 作答結果頁 ---
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, px(14), 0, 0)
        pv.setSpacing(px(14))

        bar = QHBoxLayout()
        bar.setSpacing(px(10))
        self.btn_draw_lot = make_button("🎲 抽人", "lemon", 52, font_px=17)
        self.btn_draw_lot.setToolTip("從已回應的學生中隨機抽出一位")
        self.btn_draw_lot.clicked.connect(self.lucky_draw)
        bar.addWidget(self.btn_draw_lot)
        self.seg_card = make_button("🗂 卡片", checkable=True)
        self.seg_cloud = make_button("☁️ 文字雲", checkable=True)
        for b in (self.seg_card, self.seg_cloud):
            b.setProperty("seg", True)
            b.setMinimumHeight(px(52))
        seg_group = QButtonGroup(self)
        seg_group.addButton(self.seg_card)
        seg_group.addButton(self.seg_cloud)
        self.seg_card.setChecked(True)
        self.seg_card.clicked.connect(lambda: self.stack.setCurrentWidget(self.text_grid))
        self.seg_cloud.clicked.connect(lambda: self.stack.setCurrentWidget(self.cloud))

        self.btn_names = make_button("👁 顯示姓名", checkable=True, tool=True, height=52)
        self.btn_names.setChecked(True)
        self.btn_names.toggled.connect(lambda on: self.choice.set_show_names(on))

        self.btn_compare = make_button("🔍 比較已選 (0/4)", "peach", 52)
        self.btn_compare.clicked.connect(self.compare_selected)
        self.btn_clear_sel = make_button("取消選取", height=52)
        self.btn_clear_sel.clicked.connect(self.clear_selection)
        self.btn_replay_all = make_button("🎬 繪圖重播", "sky", 52)
        self.btn_replay_all.setToolTip("在截圖背景上重播學生的作畫過程（可 1X / 2X / 3X）")
        self.btn_replay_all.clicked.connect(lambda: self.open_replay(None))
        self.btn_show_all = make_button("▶ 逐一展示", "lav", 52)
        self.btn_show_all.clicked.connect(lambda: self.open_showcase(None))
        self.btn_download = make_button("⬇ 下載作答", "mint", 52)
        self.btn_download.clicked.connect(self.download_answers)
        for w in (self.seg_card, self.seg_cloud, self.btn_names, self.btn_compare, self.btn_clear_sel):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.btn_replay_all)
        bar.addWidget(self.btn_show_all)
        bar.addWidget(self.btn_download)
        pv.addLayout(bar)

        self.stack = QStackedWidget()
        self.empty = make_label("還沒有題目\n\n在畫筆工具列按「✂️ 截圖出題」發送給學生", "muted", True, Qt.AlignCenter)
        self.empty.setStyleSheet(f"font-size:{px(22)}px;")
        self.draw_grid = ResponsiveGrid(px(320), "等待學生作答…")
        self.text_grid = ResponsiveGrid(px(320), "等待學生作答…")
        self.choice = ChoiceStatsWidget()
        choice_scroll = QScrollArea()
        choice_scroll.setWidgetResizable(True)
        choice_scroll.setWidget(self.choice)
        self.choice_scroll = choice_scroll
        self.cloud = CloudViewWidget()
        for w in (self.empty, self.draw_grid, self.text_grid, choice_scroll, self.cloud):
            self.stack.addWidget(w)
        pv.addWidget(self.stack, 1)
        self.tabs.addTab(page, "作答結果")

        # --- 學生名單頁 ---
        spage = QWidget()
        sv = QVBoxLayout(spage)
        sv.setContentsMargins(0, px(14), 0, 0)
        sv.setSpacing(px(14))
        srow = QHBoxLayout()
        self.student_summary = make_label("", "muted")
        self.student_summary.setStyleSheet(f"font-size:{px(16)}px;")
        srow.addWidget(self.student_summary)
        srow.addStretch()
        btn_prune = make_button("🧹 移除離線學生", height=52)
        btn_prune.clicked.connect(self.prune_students)
        srow.addWidget(btn_prune)
        sv.addLayout(srow)
        self.student_grid = ResponsiveGrid(px(230), "尚無學生加入\n請按「📱 學生連線」顯示 QR Code")
        sv.addWidget(self.student_grid, 1)
        self.tabs.addTab(spage, "學生名單")

        fit_resize(self, px(1280), px(820))

    # ---------- 題目 / 作答 ----------
    def on_mission(self, info):
        self.mission_type = info["type"]
        retry = info.get("retry", False)
        if self.mission_type != MissionType.NONE and not (retry and self.mission_no):
            self.mission_no += 1
        self.drawn = set()
        self.answers.clear()
        self.pixmaps.clear()
        self.cards.clear()
        self.selected = []
        self.draw_grid.clear()
        self.text_grid.clear()
        self.choice.reset_stats()
        self.cloud.reset_cloud()

        t = self.mission_type
        self.seg_card.setVisible(t == MissionType.TEXT)
        self.seg_cloud.setVisible(t == MissionType.TEXT)
        self.btn_names.setVisible(t == MissionType.CHOICE)
        self.btn_compare.setVisible(t in (MissionType.DRAW, MissionType.CALC))
        self.btn_clear_sel.setVisible(t in (MissionType.DRAW, MissionType.CALC))
        self.btn_show_all.setVisible(t in (MissionType.DRAW, MissionType.TEXT, MissionType.CALC))
        self.calc_pages.clear()
        self.btn_replay_all.setVisible(t == MissionType.DRAW)
        jpeg = self.server.mission_image()
        self.mission_bg = None
        if jpeg:
            bg = QPixmap()
            if bg.loadFromData(jpeg):
                self.mission_bg = bg
        self.btn_download.setVisible(t != MissionType.NONE)
        self.btn_draw_lot.setVisible(t != MissionType.NONE)
        self.btn_pause.setEnabled(t != MissionType.NONE)
        self.btn_retry.setEnabled(t != MissionType.NONE)

        if t in (MissionType.DRAW, MissionType.CALC):
            self.stack.setCurrentWidget(self.draw_grid)
        elif t == MissionType.CHOICE:
            self.stack.setCurrentWidget(self.choice_scroll)
        elif t == MissionType.TEXT:
            self.seg_card.setChecked(True)
            self.stack.setCurrentWidget(self.text_grid)
        else:
            self.stack.setCurrentWidget(self.empty)
        self.subtitle.setText(f"目前任務：{MISSION_LABELS.get(t, t)}"
                              + (f"　·　第 {self.mission_no} 題" if t != MissionType.NONE else "")
                              + ("（重新作答）" if retry and t != MissionType.NONE else ""))
        self.update_selection_ui()
        self.refresh_students()
        self.tabs.setCurrentIndex(0)

    def on_answer(self, data):
        if data.get("type") != self.mission_type:
            return
        key = data["key"]
        self.answers[key] = data
        name, ts, content = data.get("name", ""), data.get("timestamp", 0), data.get("content", "")
        t = self.mission_type
        if t == MissionType.CHOICE:
            self.choice.set_answer(key, content, name)
        elif t == MissionType.TEXT:
            self.cloud.set_answer(key, content)
            card = self._get_card(key, "text", self.text_grid)
            card.set_data(name, ts, text=content)
        elif t == MissionType.DRAW:
            pm = pixmap_from_data_uri(content)
            self.pixmaps[key] = pm
            card = self._get_card(key, "draw", self.draw_grid)
            card.set_data(name, ts, pixmap=pm, has_replay=bool(data.get("replay")))
        elif t == MissionType.CALC:
            pm = pixmap_from_data_uri(content)
            self.pixmaps[key] = pm
            pages = [pixmap_from_data_uri(pg) for pg in data.get("pages", [])]
            empty = data.get("empty", [])
            empty = empty + [False] * (len(pages) - len(empty))
            self.calc_pages[key] = (pages, empty)
            card = self._get_card(key, "calc", self.draw_grid)
            card.set_data(name, ts, pixmap=pm)
        self.refresh_students()

    def _get_card(self, key, kind, grid):
        card = self.cards.get(key)
        if card is None:
            card = AnswerCard(key, kind, px(320), px(270) if kind in ("draw", "calc") else px(220))
            card.open_requested.connect(self.open_showcase)
            card.replay_requested.connect(self.open_replay)
            card.select_toggled.connect(self.on_select)
            self.cards[key] = card
            grid.add(card)
        return card

    # ---------- 暫停 / 重新作答 / 抽人 ----------
    def toggle_pause(self, on):
        self.server.set_paused(on)

    def on_paused(self, paused):
        self.btn_pause.blockSignals(True)
        self.btn_pause.setChecked(paused)
        self.btn_pause.blockSignals(False)
        self.btn_pause.setText("▶ 繼續作答" if paused else "⏸ 暫停作答")
        self.chip_paused.setVisible(paused)

    def retry_mission(self):
        n = len(self.answers)
        msg = "讓學生針對同一張截圖重新作答？"
        if n:
            msg += f"\n\n目前的 {n} 份作答紀錄將會清空（需要的話請先按「⬇ 下載作答」）。"
        if QMessageBox.question(self, "重新作答", msg) == QMessageBox.Yes:
            self.server.restart_mission()

    def lucky_draw(self):
        LuckyDrawDialog(self).exec_()

    def ordered_keys(self):
        return sorted(self.answers, key=lambda k: self.answers[k]["timestamp"])

    def open_replay(self, key):
        keys = [k for k in self.ordered_keys() if self.answers[k].get("replay")]
        if not keys:
            QMessageBox.information(self, "繪圖重播", "目前還沒有可以重播的塗鴉作答。")
            return
        entries = [(self.answers[k]["name"], self.answers[k]["replay"]) for k in keys]
        idx = keys.index(key) if key in keys else 0
        ReplayDialog(self, self.mission_bg, entries, idx).exec_()

    def open_calc(self, key, page=None):
        keys = [k for k in self.ordered_keys() if k in self.calc_pages]
        if not keys:
            QMessageBox.information(self, "計算過程", "目前還沒有學生作答。")
            return
        entries = [(self.answers[k]["name"], *self.calc_pages[k]) for k in keys]
        idx = keys.index(key) if key in keys else 0
        CalcViewerDialog(self, entries, idx, page).exec_()

    def open_showcase(self, key):
        if self.mission_type == MissionType.CALC:
            self.open_calc(key)
            return
        keys = [k for k in self.ordered_keys() if self.mission_type == MissionType.TEXT or self.pixmaps.get(k)]
        if not keys:
            QMessageBox.information(self, "展示", "目前還沒有學生作答。")
            return
        items = []
        for k in keys:
            a = self.answers[k]
            if self.mission_type == MissionType.DRAW:
                items.append({"name": a["name"], "pixmap": self.pixmaps[k]})
            else:
                items.append({"name": a["name"], "text": a["content"]})
        idx = keys.index(key) if key in keys else 0
        ShowcaseDialog(self, items, idx).exec_()

    # ---------- 比較 ----------
    def on_select(self, key, on):
        if on:
            if len(self.selected) >= 4:
                self.cards[key].set_selected(False)
                QMessageBox.information(self, "最多 4 份", "一次最多選取 4 份作答進行比較。")
                return
            self.selected.append(key)
        elif key in self.selected:
            self.selected.remove(key)
        self.update_selection_ui()

    def clear_selection(self):
        for k in self.selected:
            if k in self.cards:
                self.cards[k].set_selected(False)
        self.selected = []
        self.update_selection_ui()

    def update_selection_ui(self):
        n = len(self.selected)
        self.btn_compare.setText(f"🔍 比較已選 ({n}/4)")
        self.btn_compare.setEnabled(n > 0)
        self.btn_clear_sel.setEnabled(n > 0)

    def compare_selected(self):
        items = [(self.answers[k]["name"], self.pixmaps[k]) for k in self.selected if self.pixmaps.get(k)]
        if items:
            CompareDialog(self, items).exec_()

    # ---------- 學生 ----------
    def refresh_students(self):
        students = self.server.snapshot_students()
        online = sum(1 for s in students if s["online"])
        answered = len(self.answers)
        self.chip_online.setText(f"👥 在線 {online}")
        self.chip_answered.setText(f"✅ 已作答 {answered}" + (f" / {online}" if online else ""))
        self.student_summary.setText(f"共 {len(students)} 位學生加入，{online} 位在線")
        current = set()
        for st in students:
            current.add(st["sid"])
            chip = self.chips.get(st["sid"])
            if chip is None:
                chip = StudentChip()
                self.chips[st["sid"]] = chip
                self.student_grid.add(chip)
            chip.set_info(st)
        removed = [sid for sid in self.chips if sid not in current]
        if removed:
            for sid in removed:
                self.chips.pop(sid)
            self.student_grid.clear()
            self.chips.clear()
            self.refresh_students()

    def prune_students(self):
        self.server.remove_offline_students()
        self.refresh_students()

    # ---------- 下載 ----------
    def download_answers(self):
        if not self.answers:
            QMessageBox.information(self, "下載", "目前沒有作答資料。")
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        rows = [(a["name"], datetime.datetime.fromtimestamp(a["timestamp"] / 1000).strftime("%H:%M:%S"), a)
                for a in (self.answers[k] for k in self.ordered_keys())]
        try:
            if self.mission_type == MissionType.DRAW:
                path, _ = QFileDialog.getSaveFileName(self, "儲存塗鴉作答", f"塗鴉作答_{stamp}.zip", "Zip (*.zip)")
                if not path:
                    return
                used = set()
                with zipfile.ZipFile(path, "w") as zf:
                    for name, _, a in rows:
                        data, ext = decode_data_uri(a["content"])
                        if not data:
                            continue
                        base = safe_filename(name)
                        fn, i = f"{base}.{ext}", 2
                        while fn in used:
                            fn, i = f"{base}_{i}.{ext}", i + 1
                        used.add(fn)
                        zf.writestr(fn, data)
            elif self.mission_type == MissionType.CALC:
                path, _ = QFileDialog.getSaveFileName(self, "儲存計算題作答", f"計算題作答_{stamp}.zip", "Zip (*.zip)")
                if not path:
                    return
                used = set()
                with zipfile.ZipFile(path, "w") as zf:
                    for name, _, a in rows:
                        base, i = safe_filename(name), 2
                        folder = base
                        while folder in used:
                            folder, i = f"{base}_{i}", i + 1
                        used.add(folder)
                        data, ext = decode_data_uri(a["content"])
                        if data:
                            zf.writestr(f"{folder}/總覽.{ext}", data)
                        for n, pg in enumerate(a.get("pages", []), 1):
                            data, ext = decode_data_uri(pg)
                            if data:
                                zf.writestr(f"{folder}/第{n}頁.{ext}", data)
            else:
                label = "選擇題" if self.mission_type == MissionType.CHOICE else "簡答題"
                path, _ = QFileDialog.getSaveFileName(self, "儲存作答", f"{label}作答_{stamp}.csv", "CSV (*.csv)")
                if not path:
                    return
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(["姓名", "送出時間", "答案"])
                    for name, t, a in rows:
                        w.writerow([name, t, a["content"]])
            QMessageBox.information(self, "完成", f"已儲存：\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", str(e))


##########################################
# 全螢幕畫記層
##########################################
class FullScreenOverlay(QWidget):
    def __init__(self, control_panel=None):
        super().__init__()
        self.control_panel = control_panel
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.current_tool = 'pen'
        self.current_color = QColor(PEN_COLORS[0][1])
        self.current_thickness = 6
        self.last_point = None
        self.drawing_layer = None
        self.background = None
        self.original_background = None
        self.current_board_color = None
        self.undo_stack = []

        self.shape_active = False
        self.shape_start = None
        self.shape_end = None
        self.eraser_pos = None

        self.save_label = QLabel("", self)
        self.save_label.hide()
        # 框選出題時顯示的「取消」按鈕（觸控大屏沒有 Esc 鍵）
        self.btn_cancel_region = make_button("✕ 取消框選", "pink")
        self.btn_cancel_region.setParent(self)
        self.btn_cancel_region.clicked.connect(self.cancel_region)
        self.btn_cancel_region.hide()
        QShortcut(QKeySequence.Undo, self, self.undo)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.cancel_region)

    def capture_screenshot(self, screen):
        screenshot = screen.grabWindow(0)
        self.setGeometry(screen.geometry())
        self.background = QPixmap(screenshot)
        self.original_background = QPixmap(screenshot)
        self.current_board_color = None
        self.drawing_layer = QPixmap(self.background.size())
        self.drawing_layer.fill(Qt.transparent)
        self.undo_stack = []

    def set_tool(self, tool_name):
        self.current_tool = tool_name
        self.eraser_pos = None
        self.shape_active = False
        region = tool_name == "region_screenshot"
        self.setCursor(Qt.CrossCursor if region else Qt.ArrowCursor)
        if region:
            b = self.btn_cancel_region
            b.setStyleSheet(f"font-size:{px(20)}px; padding:0 {px(28)}px; border-radius:{px(24)}px;")
            b.setFixedHeight(px(64))
            b.adjustSize()
            b.move((self.width() - b.width()) // 2, px(28))
            b.show()
            b.raise_()
        else:
            self.btn_cancel_region.hide()
        self.update()

    def cancel_region(self):
        if self.current_tool == "region_screenshot":
            self.shape_active = False
            self.show_save_message("已取消框選")
            self.control_panel.region_finished()

    def set_color(self, color):
        self.current_color = color

    def set_thickness(self, t):
        self.current_thickness = t

    def push_undo(self):
        if self.drawing_layer:
            self.undo_stack.append(QPixmap(self.drawing_layer))
            del self.undo_stack[:-30]

    def undo(self):
        if self.undo_stack:
            self.drawing_layer = self.undo_stack.pop()
            self.update()
        else:
            self.show_save_message("沒有可以復原的步驟")

    def clear_all(self):
        if self.drawing_layer:
            self.push_undo()
            self.drawing_layer.fill(Qt.transparent)
            self.update()

    def set_board(self, board_color):
        """切換白板/黑板；再按一次回到截圖。回傳目前板色（None 表示截圖）。"""
        if self.current_board_color == board_color:
            if self.original_background:
                self.background = QPixmap(self.original_background)
            self.current_board_color = None
        else:
            self.background = QPixmap(self.size())
            self.background.fill(board_color)
            self.current_board_color = board_color
        self.update()
        return self.current_board_color

    def composite(self):
        out = QPixmap(self.background.size())
        out.fill(Qt.white)
        p = QPainter(out)
        p.drawPixmap(0, 0, self.background)
        p.drawPixmap(0, 0, self.drawing_layer)
        p.end()
        return out

    def _pen(self, width=None):
        return QPen(self.current_color, width or self.current_thickness, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def _draw_shape(self, p, start, end):
        rect = QRect(start, end).normalized()
        p.setRenderHint(QPainter.Antialiasing)
        if self.current_tool == 'rect':
            p.setPen(QPen(self.current_color, 1))
            p.setBrush(QBrush(self.current_color))
            p.drawRect(rect)
        elif self.current_tool == 'line':
            p.setPen(self._pen())
            p.drawLine(start, end)
        elif self.current_tool in ('solid_circle', 'hollow_circle'):
            p.setPen(self._pen())
            p.setBrush(QBrush(self.current_color) if self.current_tool == 'solid_circle' else Qt.NoBrush)
            p.drawEllipse(rect)

    # ----- 滑鼠 / 觸控 -----
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton and self.current_tool == "region_screenshot":
            self.cancel_region()
            return
        if event.button() == Qt.LeftButton and self.drawing_layer:
            pos = event.pos()
            if self.current_tool == "region_screenshot":
                self.btn_cancel_region.hide()
                self.shape_active, self.shape_start, self.shape_end = True, pos, pos
            elif self.current_tool in ('pen', 'eraser'):
                self.push_undo()
                self.last_point = pos
                if self.current_tool == 'eraser':
                    self.eraser_pos = pos
                else:  # 點一下也留下一個點
                    p = QPainter(self.drawing_layer)
                    p.setRenderHint(QPainter.Antialiasing)
                    p.setPen(self._pen())
                    p.drawPoint(pos)
                    p.end()
                self.update()
            else:
                self.push_undo()
                self.shape_active, self.shape_start, self.shape_end = True, pos, pos
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self.drawing_layer:
            pos = event.pos()
            if self.current_tool in ('pen', 'eraser') and self.last_point is not None:
                p = QPainter(self.drawing_layer)
                p.setRenderHint(QPainter.Antialiasing)
                if self.current_tool == 'pen':
                    p.setPen(self._pen())
                else:
                    p.setCompositionMode(QPainter.CompositionMode_Clear)
                    p.setPen(QPen(Qt.transparent, self.current_thickness + 16, Qt.SolidLine, Qt.RoundCap))
                    self.eraser_pos = pos
                p.drawLine(self.last_point, pos)
                p.end()
                self.last_point = pos
                self.update()
            elif self.shape_active:
                self.shape_end = pos
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drawing_layer:
            pos = event.pos()
            if self.current_tool == "region_screenshot" and self.shape_active:
                self.shape_active = False
                rect = QRect(self.shape_start, pos).normalized()
                self.update()
                if rect.width() > 10 and rect.height() > 10:
                    self.open_mission_dialog(self.composite().copy(rect))
                else:
                    self.show_save_message("範圍太小，請重新拖曳框選")
                    self.set_tool("region_screenshot")
                    return
                self.control_panel.region_finished()
            elif self.shape_active:
                self.shape_active = False
                p = QPainter(self.drawing_layer)
                self._draw_shape(p, self.shape_start, pos)
                p.end()
                self.update()
            self.last_point = None
            if self.current_tool == 'eraser':
                self.eraser_pos = None
                self.update()
        super().mouseReleaseEvent(event)

    def open_mission_dialog(self, region):
        cp = self.control_panel
        try:
            dlg = MissionConfigDialog(self, region, cp.server, cp)
            QApplication.setOverrideCursor(Qt.ArrowCursor)
            result = dlg.exec_()
            QApplication.restoreOverrideCursor()
            if result == 1:
                self.show_save_message("🚀 已發送題目給學生")
            elif result == 2:
                self.show_save_message("💾 已存入題庫")
        except Exception as e:
            logging.exception("MissionConfigDialog error")
            QMessageBox.critical(self, "錯誤", f"無法開啟出題視窗：{e}")

    def paintEvent(self, event):
        if not self.background or not self.drawing_layer:
            return
        p = QPainter(self)
        p.drawPixmap(0, 0, self.background)
        p.drawPixmap(0, 0, self.drawing_layer)
        if self.shape_active and self.current_tool == 'region_screenshot':
            sel = QRect(self.shape_start, self.shape_end).normalized()
            path = QPainterPath()
            path.addRect(QRectF(self.rect()))
            path.addRoundedRect(QRectF(sel), px(8), px(8))
            p.setRenderHint(QPainter.Antialiasing)
            p.fillPath(path, QColor(74, 67, 88, 110))
            p.setPen(QPen(QColor(C.LAV_D), px(3), Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(sel, px(8), px(8))
        elif self.shape_active:
            self._draw_shape(p, self.shape_start, self.shape_end)
        elif self.current_tool == 'eraser' and self.eraser_pos:
            r = (self.current_thickness + 16) / 2
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(C.MUTED), 2))
            p.setBrush(QColor(255, 255, 255, 90))
            p.drawEllipse(self.eraser_pos, r, r)
        p.end()

    def show_save_message(self, msg, ms=2000):
        self.save_label.setStyleSheet(f"""
            color: white; font-weight: 700; font-size: {px(20)}px; background: rgba(74, 67, 88, 225);
            padding: {px(14)}px {px(28)}px; border-radius: {px(24)}px;
        """)
        self.save_label.setText(msg)
        self.save_label.adjustSize()
        self.save_label.move((self.width() - self.save_label.width()) // 2,
                             self.height() - self.save_label.height() - px(60))
        self.save_label.show()
        self.save_label.raise_()
        QTimer.singleShot(ms, self.save_label.hide)


class SwatchButton(QPushButton):
    """圓形顏色按鈕（自行繪製，避免 QSS 圓角限制）。"""

    def __init__(self, color, size, ring):
        super().__init__()
        self.color = QColor(color)
        self.ring = ring
        self.setCheckable(True)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self.isChecked():
            p.setPen(QPen(QColor(C.INK), self.ring))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(self.ring / 2, self.ring / 2, -self.ring / 2, -self.ring / 2))
        pad = self.ring * 2
        inner = r.adjusted(pad, pad, -pad, -pad)
        p.setPen(QPen(QColor("#DDD5E3"), 1) if self.color.lightness() > 240 else Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(inner)
        p.end()


##########################################
# 主控面板：開始畫面與畫筆工具整合為同一個浮動面板
##########################################
def screen_factor(screen):
    """以 1080p 為基準的螢幕比例；4K（實體高度 ≥ 2000）再放大，觸控大屏較易閱讀與點選。"""
    geo = screen.geometry()
    dpr = screen.devicePixelRatio() or 1.0
    f = max(1.0, geo.height() / 1080.0, screen.logicalDotsPerInch() / 96.0)
    if geo.height() * dpr >= 2000:
        f *= 1.25
    return f


class ControlPanel(QWidget):
    BASE_WIDTH = 240  # 與原雲端版相同：寬度 = 240 × 0.75（1080p）
    ZOOMS = [0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6]
    TOOLS = [("pen", "✏️", "畫筆"), ("eraser", "🧽", "橡皮擦"), ("line", "／", "直線"),
             ("rect", "■", "方塊"), ("solid_circle", "●", "實心圓"), ("hollow_circle", "○", "空心圓")]

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.settings = QSettings(*SETTINGS_KEY)
        try:
            self.zoom = float(self.settings.value("ui_zoom", 1.0))
        except (TypeError, ValueError):
            self.zoom = 1.0

        self.server = ClassroomServer()
        ok, info = self.server.start(int(self.settings.value("port", DEFAULT_PORT)))
        if not ok:
            QMessageBox.critical(None, "伺服器啟動失敗", f"無法建立區網伺服器：\n{info}")

        self.presets = PresetStore(os.path.join(app_dir(), "題庫"))
        self.live_preset_id = None
        self.library = None
        self.after_region = None  # 框選結束後要執行的動作（例如回到題庫）

        self.overlay = FullScreenOverlay(self)
        self.overlay.hide()
        self.dashboard = None
        self.screens = QApplication.screens()
        self.screen_index = 0
        self.drawing = False
        self.quick_mode = False
        self.collapsed = False
        self.frame = None
        self.k = 0
        self.scale_screen = QApplication.primaryScreen()

        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSizeConstraint(QLayout.SetFixedSize)
        self.apply_scale(self.scale_screen, force=True)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1500)

    def q(self, v):
        return max(1, int(round(v * self.k)))

    # ---------- 縮放 ----------
    def apply_scale(self, screen, force=False):
        """依所在螢幕重新計算介面比例（4K 自動放大），必要時重建面板。"""
        f = screen_factor(screen) * self.zoom
        k = 0.75 * f
        self.scale_screen = screen
        if not force and abs(k - self.k) < 0.01:
            return
        self.k = k
        self.W = int(self.BASE_WIDTH * k)
        UI.scale = f
        QApplication.instance().setStyleSheet(build_qss())
        if self.dashboard is not None and not self.dashboard.isVisible():
            self.dashboard.deleteLater()  # 下次開啟時以新比例重建
            self.dashboard = None
        self.build_ui()

    def current_panel_screen(self):
        handle = self.windowHandle()
        return handle.screen() if handle else QApplication.primaryScreen()

    def on_drag_finished(self):
        scr = QApplication.screenAt(self.frameGeometry().center()) or self.current_panel_screen()
        if scr is not self.scale_screen:
            self.apply_scale(scr)

    def change_zoom(self, step):
        idx = min(range(len(self.ZOOMS)), key=lambda i: abs(self.ZOOMS[i] - self.zoom))
        idx = max(0, min(len(self.ZOOMS) - 1, idx + step))
        if self.ZOOMS[idx] == self.zoom:
            return
        self.zoom = self.ZOOMS[idx]
        self.settings.setValue("ui_zoom", self.zoom)
        self.apply_scale(self.scale_screen, force=True)

    # ---------- 介面 ----------
    def build_ui(self):
        q = self.q
        if self.frame is not None:
            self.outer.removeWidget(self.frame)
            self.frame.deleteLater()
        self.setStyleSheet(f"""
            QFrame#panel {{ background: rgba(255,255,255,250); border: 1px solid {C.LINE}; border-radius: {q(20)}px; }}
            QPushButton {{ font-size: {q(16)}px; padding: 0 {q(6)}px; border-radius: {q(12)}px; }}
            QLabel {{ font-size: {q(14)}px; }}
            QLabel#section {{ font-size: {q(13)}px; }}
            QComboBox {{ font-size: {q(15)}px; padding: 0 {q(10)}px; min-height: {q(40)}px; border-radius: {q(12)}px; }}
            QComboBox QAbstractItemView::item {{ min-height: {q(40)}px; }}
        """)
        frame = QFrame()
        frame.setObjectName("panel")
        frame.setFixedWidth(self.W)
        self.frame = frame
        self.outer.addWidget(frame)

        v = QVBoxLayout(frame)
        v.setContentsMargins(q(10), q(6), q(10), q(12))
        v.setSpacing(q(8))

        head = QHBoxLayout()
        head.setSpacing(q(2))
        handle = DragHandle("⠿ 螢幕畫筆")
        handle.setStyleSheet(f"font-size:{q(15)}px; font-weight:800; color:{C.MUTED};")
        handle.setMinimumHeight(q(36))
        head.addWidget(handle, 1)
        self.btn_min = self._head_button("—", self.on_min_clicked)
        self.btn_close = self._head_button("✕", self.close)
        head.addWidget(self.btn_min)
        head.addWidget(self.btn_close)
        v.addLayout(head)

        self.start_page = self.build_start_page()
        self.draw_page = self.build_draw_page()
        v.addWidget(self.start_page)
        v.addWidget(self.draw_page)

        # 重建後同步畫筆狀態
        self.overlay.set_color(QColor(PEN_COLORS[0][1]))
        self.overlay.set_thickness(6)
        self.set_mode(self.drawing)
        if self.drawing and self.overlay.current_tool != "region_screenshot":
            self.select_tool("pen")
        self.adjustSize()

    def _head_button(self, text, slot):
        b = make_button(text)
        b.setProperty("ghost", True)
        b.setFixedSize(self.q(36), self.q(36))
        b.setMinimumHeight(self.q(36))
        b.clicked.connect(slot)
        return b

    def _btn(self, text, tone=None, h=44, fs=None, checkable=False, tool=False):
        b = make_button(text, tone, checkable=checkable, tool=tool)
        b.setMinimumHeight(self.q(h))
        if fs:
            b.setStyleSheet(f"font-size:{self.q(fs)}px;")
        return b

    def _section(self, text):
        return make_label(text, "section")

    def build_start_page(self):
        q = self.q
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(q(8))

        card = make_card("soft")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(q(10), q(8), q(10), q(8))
        cv.setSpacing(q(2))
        self.status_title = make_label("", wrap=True)
        self.status_title.setStyleSheet(f"font-size:{q(13)}px; font-weight:700;")
        self.status_url = make_label("", wrap=True)
        self.status_url.setStyleSheet(f"font-size:{q(15)}px; font-weight:800; color:{C.LAV_D};")
        self.status_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cv.addWidget(self.status_title)
        cv.addWidget(self.status_url)
        v.addWidget(card)

        start_btn = self._btn("🖊️ 開始繪圖", "lav", 60, 19)
        start_btn.clicked.connect(self.on_start_clicked)
        v.addWidget(start_btn)

        quick_btn = self._btn("✂️ 截圖出題", "pink", 54, 18)
        quick_btn.setToolTip("不進入繪圖，直接框選螢幕畫面出題")
        quick_btn.clicked.connect(lambda: self.on_quick_mission_clicked())
        v.addWidget(quick_btn)

        lib_btn = self._btn("📚 題庫", "lemon", 46)
        lib_btn.setToolTip("預先存好的截圖題目，一鍵派送")
        lib_btn.clicked.connect(self.show_library)
        v.addWidget(lib_btn)

        row = QHBoxLayout()
        row.setSpacing(q(6))
        b_conn = self._btn("📱 連線", "mint", 46)
        b_conn.clicked.connect(self.show_connection)
        b_dash = self._btn("📊 儀表板", "peach", 46)
        b_dash.clicked.connect(self.show_dashboard)
        row.addWidget(b_conn)
        row.addWidget(b_dash)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(q(6))
        b_help = self._btn("📖 說明", "sky", 42)
        b_help.clicked.connect(self.show_help)
        b_small = self._btn("A－", h=42)
        b_small.setToolTip("縮小介面")
        b_small.setFixedWidth(q(46))
        b_small.clicked.connect(lambda: self.change_zoom(-1))
        b_big = self._btn("A＋", h=42)
        b_big.setToolTip("放大介面")
        b_big.setFixedWidth(q(46))
        b_big.clicked.connect(lambda: self.change_zoom(1))
        row2.addWidget(b_help, 1)
        row2.addWidget(b_small)
        row2.addWidget(b_big)
        v.addLayout(row2)

        self.screens = QApplication.screens()
        self.screen_combo = QComboBox()
        self.screen_combo.setCursor(Qt.PointingHandCursor)
        for i, _s in enumerate(self.screens):
            self.screen_combo.addItem(f"🖥 螢幕 {i + 1}", i)
        self.screen_combo.setCurrentIndex(min(self.screen_index, len(self.screens) - 1))
        self.screen_combo.currentIndexChanged.connect(lambda i: setattr(self, "screen_index", i))
        self.screen_combo.setVisible(len(self.screens) > 1)
        v.addWidget(self.screen_combo)

        credit = make_label("Made by 阿剛老師 (LAN Ver)", "muted", align=Qt.AlignCenter)
        credit.setStyleSheet(f"font-size:{q(12)}px;")
        v.addWidget(credit)
        return w

    def build_draw_page(self):
        q = self.q
        w = QWidget()
        b = QVBoxLayout(w)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(q(6))
        inner = self.W - 2 * q(10)

        b.addWidget(self._section("畫布"))
        row = QHBoxLayout()
        row.setSpacing(q(6))
        self.btn_white = self._btn("⬜ 白板", h=44, checkable=True, tool=True)
        self.btn_black = self._btn("⬛ 黑板", h=44, checkable=True, tool=True)
        self.btn_white.clicked.connect(lambda: self.toggle_board(QColor("white")))
        self.btn_black.clicked.connect(lambda: self.toggle_board(QColor("#23463C")))
        row.addWidget(self.btn_white)
        row.addWidget(self.btn_black)
        b.addLayout(row)
        board = self.overlay.current_board_color
        self.btn_white.setChecked(board is not None and board == QColor("white"))
        self.btn_black.setChecked(board is not None and board != QColor("white"))

        b.addWidget(self._section("工具"))
        grid = QGridLayout()
        grid.setSpacing(q(6))
        tw = (inner - 2 * q(6)) // 3
        self.tool_group = QButtonGroup(w)
        self.tool_buttons = {}
        for i, (key, icon, name) in enumerate(self.TOOLS):
            btn = make_button(f"{icon}\n{name}", checkable=True, tool=True)
            btn.setFixedSize(tw, q(56))
            btn.setStyleSheet(f"font-size:{q(14)}px; padding:0;")
            btn.clicked.connect(lambda _, k=key: self.select_tool(k))
            self.tool_group.addButton(btn)
            self.tool_buttons[key] = btn
            grid.addWidget(btn, i // 3, i % 3)
        b.addLayout(grid)

        b.addWidget(self._section("顏色"))
        cgrid = QGridLayout()
        cgrid.setSpacing(q(6))
        sw = (inner - 4 * q(6)) // 5
        color_group = QButtonGroup(w)
        for i, (cname, cval) in enumerate(PEN_COLORS):
            btn = SwatchButton(cval, sw, max(2, q(3)))
            btn.setToolTip(cname)
            btn.clicked.connect(lambda _, c=cval: self.overlay.set_color(QColor(c)))
            color_group.addButton(btn)
            cgrid.addWidget(btn, i // 5, i % 5)
            if i == 0:
                btn.setChecked(True)
        b.addLayout(cgrid)

        b.addWidget(self._section("粗細"))
        srow = QHBoxLayout()
        srow.setSpacing(q(4))
        bw = (inner - 4 * q(4)) // 5
        size_group = QButtonGroup(w)
        for size in PEN_SIZES:
            btn = make_button("", checkable=True, tool=True)
            btn.setFixedSize(bw, q(40))
            btn.setStyleSheet("padding:0;")
            btn.setIcon(self._dot_icon(size))
            btn.setIconSize(QSize(q(28), q(28)))
            btn.setToolTip(f"{size} px")
            btn.clicked.connect(lambda _, s=size: self.overlay.set_thickness(s))
            size_group.addButton(btn)
            srow.addWidget(btn)
            if size == 6:
                btn.setChecked(True)
        b.addLayout(srow)

        arow = QHBoxLayout()
        arow.setSpacing(q(6))
        for text, slot in (("↶ 復原", self.overlay.undo), ("🗑 清除", self.overlay.clear_all), ("💾 存檔", self.on_save_clicked)):
            btn = self._btn(text, h=42, fs=14)
            btn.clicked.connect(slot)
            arow.addWidget(btn)
        b.addLayout(arow)

        b.addWidget(self._section("課堂互動"))
        self.btn_region = self._btn("✂️ 截圖出題", "lav", 54, 18)
        self.btn_region.clicked.connect(lambda: self.on_region_clicked())
        b.addWidget(self.btn_region)
        lib_btn = self._btn("📚 題庫", "lemon", 44)
        lib_btn.clicked.connect(self.show_library)
        b.addWidget(lib_btn)
        irow = QHBoxLayout()
        irow.setSpacing(q(6))
        btn_dash = self._btn("📊 儀表板", "peach", 46)
        btn_dash.clicked.connect(self.show_dashboard)
        btn_qr = self._btn("📱 連線", "mint", 46)
        btn_qr.clicked.connect(self.show_connection)
        irow.addWidget(btn_dash)
        irow.addWidget(btn_qr)
        b.addLayout(irow)
        self.draw_status = make_label("", "muted", align=Qt.AlignCenter)
        self.draw_status.setStyleSheet(f"font-size:{q(12)}px;")
        b.addWidget(self.draw_status)

        btn_stop = self._btn("❌ 結束繪圖", "pink", 50, 17)
        btn_stop.clicked.connect(self.on_stop_drawing)
        b.addWidget(btn_stop)
        return w

    def _dot_icon(self, size):
        d = self.q(28)
        pm = QPixmap(d, d)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C.INK))
        r = max(1.5, min(d / 2 - 1, (2 + size * 0.3) * self.k))
        p.drawEllipse(QRectF(d / 2 - r, d / 2 - r, 2 * r, 2 * r))
        p.end()
        return QIcon(pm)

    # ---------- 模式切換 ----------
    def set_mode(self, drawing):
        self.drawing = drawing
        self.collapsed = False
        self.start_page.setVisible(not drawing)
        self.draw_page.setVisible(drawing)
        self.btn_close.setVisible(not drawing)
        self.btn_min.setText("—")
        self.btn_min.setToolTip("收合" if drawing else "最小化")
        self.update_status()

    def on_min_clicked(self):
        if not self.drawing:
            self.showMinimized()
            return
        self.collapsed = not self.collapsed
        self.draw_page.setVisible(not self.collapsed)
        self.btn_min.setText("＋" if self.collapsed else "—")

    def update_status(self):
        n = self.server.online_count() if self.server.running else 0
        if self.server.running:
            self.status_title.setText(f"🟢 伺服器運行中 · {n} 人在線")
            self.status_url.setText(self.server.urls()[0].rstrip("/").replace("http://", ""))
        else:
            self.status_title.setText("🔴 伺服器未啟動")
            self.status_url.setText("請確認連接埠未被占用")
        self.draw_status.setText(f"👥 在線 {n} 位學生")

    # ---------- 工具 ----------
    def select_tool(self, key):
        self.tool_buttons[key].setChecked(True)
        self.overlay.set_tool(key)

    def toggle_board(self, color):
        board = self.overlay.set_board(color)
        self.btn_white.setChecked(board is not None and board == QColor("white"))
        self.btn_black.setChecked(board is not None and board != QColor("white"))

    # ----- 對話框 -----
    def show_connection(self):
        if not self.server.running:
            QMessageBox.warning(self, "伺服器未啟動", "區網伺服器沒有成功啟動，學生無法連線。")
            return
        parent = self.dashboard if self.dashboard and self.dashboard.isVisible() else self
        ConnectionDialog(self.server, parent).exec_()

    def show_help(self):
        HelpDialog(self).exec_()

    def current_screen(self):
        self.screens = QApplication.screens()
        return self.screens[min(self.screen_index, len(self.screens) - 1)]

    def show_dashboard(self):
        if not self.dashboard:
            self.dashboard = DashboardWindow(self.server, self)
            geo = self.current_screen().availableGeometry()
            self.dashboard.move(geo.x() + (geo.width() - self.dashboard.width()) // 2,
                                geo.y() + (geo.height() - self.dashboard.height()) // 2)
        # 以最大化開啟（先移到所選螢幕，再最大化於該螢幕）
        self.dashboard.setWindowState((self.dashboard.windowState() & ~Qt.WindowMinimized) | Qt.WindowMaximized)
        self.dashboard.showMaximized()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    # ----- 題庫 -----
    def show_library(self):
        if self.library is None:
            self.library = PresetLibraryDialog(self)
        self.library.refresh()
        self.library.show()
        self.library.setWindowState(self.library.windowState() & ~Qt.WindowMinimized)
        self.library.raise_()
        self.library.activateWindow()

    def send_preset(self, pid):
        it = self.presets.get(pid)
        pm = self.presets.pixmap(it) if it else None
        if pm is None:
            QMessageBox.warning(self.library or self, "無法派送", "找不到這題的截圖檔案。")
            return False
        if not self.server.running:
            QMessageBox.warning(self.library or self, "伺服器未啟動", "區網伺服器沒有成功啟動，無法派送。")
            return False
        self.live_preset_id = pid
        self.server.send_mission(it["type"], pixmap_to_jpeg(pm))
        if self.settings.value("open_dash", "true") == "true":
            QTimer.singleShot(0, self.show_dashboard)
        return True

    # ----- 繪圖模式 -----
    def on_start_clicked(self):
        self.server.clear_mission()
        screen = self.current_screen()
        self.hide()
        QTimer.singleShot(400, lambda: self.enter_drawing_mode(screen))

    def enter_drawing_mode(self, screen):
        self.overlay.capture_screenshot(screen)
        self.overlay.setGeometry(screen.geometry())
        self.overlay.show()
        self.overlay.activateWindow()
        self.drawing = True
        self.apply_scale(screen)
        self.btn_white.setChecked(False)
        self.btn_black.setChecked(False)
        self.select_tool("pen")
        self.set_mode(True)
        self.adjustSize()
        geo = screen.availableGeometry()
        if not geo.contains(self.frameGeometry().center()):
            self.move(geo.right() - self.width() - self.q(20), geo.top() + max(0, (geo.height() - self.height()) // 2))
        self.show()
        self.raise_()

    # ----- 直接截圖出題（不進入繪圖） -----
    def on_quick_mission_clicked(self, after=None):
        if not self.server.running:
            QMessageBox.warning(self, "伺服器未啟動", "區網伺服器沒有成功啟動，無法出題。")
            return
        if self.drawing:  # 繪圖中：直接在目前畫面上框選
            self.on_region_clicked(after)
            return
        self.after_region = after
        screen = self.current_screen()
        self.hide()
        QTimer.singleShot(400, lambda: self.enter_quick_mission(screen))

    def enter_quick_mission(self, screen):
        self.quick_mode = True
        self.apply_scale(screen)
        self.overlay.capture_screenshot(screen)
        self.overlay.setGeometry(screen.geometry())
        self.overlay.show()
        self.overlay.activateWindow()
        self.overlay.set_tool("region_screenshot")
        self.overlay.show_save_message("✂️ 請拖曳框選出題範圍", 2600)

    def region_finished(self):
        """框選出題結束（已發送或取消）。"""
        if self.quick_mode:
            self.quick_mode = False
            self.overlay.set_tool("pen")
            self.overlay.hide()
            self.set_mode(False)
            self.adjustSize()
            self.show()
            self.raise_()
        else:
            self.select_tool("pen")
        after, self.after_region = self.after_region, None
        if after:
            QTimer.singleShot(0, after)

    def on_region_clicked(self, after=None):
        self.after_region = after
        if not self.server.running:
            QMessageBox.warning(self, "伺服器未啟動", "區網伺服器沒有成功啟動，無法出題。")
            return
        self.tool_group.setExclusive(False)
        for b in self.tool_buttons.values():
            b.setChecked(False)
        self.tool_group.setExclusive(True)
        self.overlay.set_tool("region_screenshot")
        self.overlay.show_save_message("✂️ 請在畫面上拖曳框選出題範圍", 2600)

    def on_save_clicked(self):
        directory = os.path.join(os.getcwd(), "畫記存檔")
        os.makedirs(directory, exist_ok=True)
        now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(directory, f"畫記存檔_{now}.jpg")
        self.overlay.composite().save(filename, "JPG", 92)
        self.overlay.show_save_message(f"💾 已存檔：{os.path.basename(filename)}")

    def on_stop_drawing(self):
        self.server.clear_mission()
        self.overlay.hide()
        self.set_mode(False)
        self.adjustSize()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.server.stop()
        for w in (self.dashboard, self.overlay):
            if w:
                w.close()
        event.accept()
        QApplication.quit()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft JhengHei UI"))
    window = ControlPanel()  # 依螢幕解析度自動設定介面比例與樣式
    window.show()
    sys.exit(app.exec_())
