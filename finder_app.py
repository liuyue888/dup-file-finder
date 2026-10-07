# -*- coding: utf-8 -*-
"""
重复文件查找器（本地工具，纯 Python 标准库，无第三方依赖）
- 扫描指定磁盘/目录，把「不同路径下文件名相同或相近」的文件分组列出
- 相近判定：自动剥掉日期前缀、@标记、(1)/(1)(2)/副本/copy 等后缀后，核心名相同
- 网页界面：搜索、分页、按大小/名称/数量排序、打开所在位置、删除（移入回收站）
- 首次扫描结果缓存为 index.json，重开秒开，可随时重新扫描
启动：双击同目录 启动重复文件查找器.bat（或 python finder_app.py）
"""

import os
import re
import gc
import json
import time
import ctypes
import threading
import webbrowser
import subprocess
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _data_dir():
    """数据（索引/设置/隐藏记录/日志）存放目录：优先程序目录，不可写时退回 %LOCALAPPDATA%"""
    try:
        with open(os.path.join(APP_DIR, ".wtest"), "a") as f:
            f.write("")            # 只探测可写，不做删除（删除可能被网盘同步占用而误判为不可写）
        return APP_DIR
    except Exception:
        pass
    try:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "DupFinder")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, ".wtest"), "a") as f:
            f.write("")
        return d
    except Exception:
        return APP_DIR


DATA_DIR = _data_dir()
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
INDEX_PATH = os.path.join(DATA_DIR, "index.json")
DELETIONS_PATH = os.path.join(DATA_DIR, "deletions.json")
LOG_PATH = os.path.join(DATA_DIR, "log.txt")

HOST = "127.0.0.1"
PORT_CANDIDATES = [8777, 8778, 8779, 8780, 8781]

# 默认扫描 C、D 两个盘；默认跳过纯系统/程序目录（AppData 默认跳过，可在界面里去掉）
DEFAULT_SKIP = [
    "$recycle.bin", "system volume information", "windows", "perflogs",
    "program files", "program files (x86)", "programdata", "recovery",
    "$windows.~bt", "msocache", "appdata", "node_modules", ".git",
    "__pycache__", ".venv", "venv",
]

# 默认只统计 5MB 及以上的文件：几 KB / 几 MB 以下的系统文件、缓存、缩略图全是噪音，
# 删它们既省不了空间又会把列表撑爆；界面顶部下拉可切到 ≥1MB（索引里含更小文件时即时生效）
DEFAULT_MIN_SIZE = 5 * 1024 * 1024

INDEX_MIN_SIZE = DEFAULT_MIN_SIZE   # 当前索引实际采用的阈值（写入 index.json）

STATE = {
    "running": False,
    "scanned": 0,
    "kept": 0,
    "current": "",
    "done": True,
    "error": None,
    "started_at": None,
    "finished_at": None,
    "groups": [],
}

_LOCK = threading.Lock()

# 已删除的路径 / 已处理过的组 key：删除后立即从列表隐藏，无需重新扫描（重启和重扫也不丢/自动重置）
DELETIONS = {"paths": [], "keys": []}


def load_deletions():
    if os.path.isfile(DELETIONS_PATH):
        try:
            with open(DELETIONS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            DELETIONS["paths"] = list(data.get("paths", []))
            DELETIONS["keys"] = list(data.get("keys", []))
        except Exception:
            pass


def save_deletions():
    try:
        with open(DELETIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(DELETIONS, f, ensure_ascii=False)
    except Exception:
        pass


def record_deletions(paths):
    """把实际已删除的路径记下来，并把包含它们的组标记为「已处理」"""
    pset = set(os.path.normpath(p) for p in DELETIONS["paths"])
    for p in paths:
        pset.add(os.path.normpath(p))
    kset = set(DELETIONS["keys"])
    for g in STATE["groups"]:
        if g["key"] in kset:
            continue
        for f in g["files"]:
            if os.path.normpath(f["path"]) in pset:
                kset.add(g["key"])
                break
    DELETIONS["paths"] = list(pset)
    DELETIONS["keys"] = list(kset)
    save_deletions()


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(msg) + "\n")
    except Exception:
        pass


# ---------------- 名称归一化（核心名提取） ----------------

# 日期时间类前缀/内嵌 token：2026-09-14、2026.9.14、2026年9月14日、2026-09-14-16-28-32、20260914162832 等
RE_DATE = re.compile(
    r"(20\d{2}[.\-_/年]\d{1,2}(?:[.\-_/月]\d{1,2})?日?月?)"      # 2026-09-14 / 2026.9.14 / 2026年3月 / 2026年9月14日 / 2026-06
    r"([ T_\-时]*\d{1,2}[.:\-时]\d{2}([.:\-分]\d{1,2}秒?)?)?"   # 可选时间 16.28 / 16:28:05 / 16-28-32
)
RE_DATETIME2 = re.compile(r"20\d{12,14}")                       # 20260914162832
RE_TIME = re.compile(r"(?<![0-9])\d{1,2}[-.:]\d{2}[-.:]\d{2}(?![0-9])")  # 残余的 16-28-32 之类
RE_AT = re.compile(r"@[^\s,，;\u3002]+")                          # @netsdrive、@netsdrive-2026-...
RE_TAIL_COUNTER = re.compile(r"[\s\-_·]*\(\d+\)$")               # 结尾 (1) （2）
RE_TAIL_COPY = re.compile(r"[\s\-_·]*(副本|复件|copy|backup)$", re.I)
RE_WAVE = re.compile(r"[\s\-_·]*~+\d*$")                        # 结尾 ~ / ~2


def normalize_core(stem: str) -> str:
    """提取文件名核心：去掉日期/时间前缀、@标记、结尾 (1)/(1)(2)/副本/copy 等，只留字母数字汉字"""
    s = stem.replace("（", "(").replace("）", ")")
    # 反复剥结尾计数/副本后缀，直到稳定（覆盖 (1)(1)、- 副本 之类）
    for _ in range(12):
        s2 = RE_TAIL_COUNTER.sub("", s)
        s2 = RE_WAVE.sub("", s2)
        s2 = RE_TAIL_COPY.sub("", s2)
        if s2 == s:
            break
        s = s2
    s = RE_DATETIME2.sub(" ", s)
    s = RE_DATE.sub(" ", s)
    s = RE_TIME.sub(" ", s)
    s = RE_AT.sub(" ", s)
    # 只保留 汉字/字母/数字，再转小写，使「汇报材料-初稿」「汇报材料_初稿」等同判
    s = "".join(ch for ch in s if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    return s.lower()


def fmt_group(files):
    return {
        "key": "",
        "core": "",
        "count": len(files),
        "total_size": sum(f["size"] for f in files),
        "files": files,
    }


def build_groups(file_list, include_same_dir):
    """按 (核心名, 扩展名) 分组，只保留 2 个及以上文件的组"""
    buckets = {}
    for f in file_list:
        stem, ext = os.path.splitext(f["name"])
        core = normalize_core(stem)
        if not core:
            continue
        key = core + "\x00" + ext.lower()
        buckets.setdefault(key, []).append(f)

    groups = []
    for key, files in buckets.items():
        if len(files) < 2:
            continue
        if not include_same_dir and len({os.path.dirname(f["path"]) for f in files}) < 2:
            continue
        g = fmt_group(files)
        g["key"] = key
        g["core"] = files[0]["name"]
        groups.append(g)
    return groups


# ---------------- 扫描 ----------------

def scan_worker(roots, skip_names, include_same_dir, min_size=DEFAULT_MIN_SIZE):
    global STATE
    try:
        skip = {s.lower() for s in skip_names}
        files = []
        checked = 0
        t0 = time.time()
        with _LOCK:
            STATE.update(running=True, scanned=0, current="", done=False,
                         error=None, started_at=time.time(), finished_at=None)
        for root in roots:
            root = os.path.normpath(root)
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
                dirnames[:] = [d for d in dirnames if d.lower() not in skip]
                with _LOCK:
                    STATE["current"] = dirpath
                for fn in filenames:
                    p = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(p)
                        checked += 1
                        # 默认忽略小于阈值的小文件（系统文件、缓存、缩略图等噪音）
                        if st.st_size >= min_size:
                            files.append({
                                "name": fn,
                                "path": p,
                                "size": st.st_size,
                                "mtime": int(st.st_mtime),
                            })
                        if checked % 200 == 0:
                            with _LOCK:
                                STATE["scanned"] = checked
                                STATE["kept"] = len(files)
                            time.sleep(0.002)   # 主动让出 CPU，扫描时不拖慢整机
                    except OSError:
                        pass
        kept = len(files)
        groups = build_groups(files, include_same_dir)
        del files                       # 尽快释放原始列表，避免峰值内存叠加
        gc.collect()
        groups.sort(key=lambda g: -g["total_size"])
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump({"built_at": time.time(),
                       "roots": roots,
                       "include_same_dir": include_same_dir,
                       "min_size": min_size,
                       "total_files": kept,
                       "groups": groups}, f, ensure_ascii=False)
        with _LOCK:
            global INDEX_MIN_SIZE
            INDEX_MIN_SIZE = min_size
            STATE["groups"] = groups
            STATE.update(running=False, done=True, scanned=checked, kept=kept, error=None,
                         finished_at=time.time(), current="")
        # 注意：扫描完成后【不清空】隐藏/忽略记录。
        # 若清空，扫描期间或扫描开始前的删除会在扫描结束的一瞬间"复活"已处理的组，
        # 让用户以为没删掉而重复操作（已踩坑）。需要重置时用界面上的「清空隐藏记录」按钮。
        log("扫描完成: 检查 %d 个文件，其中 ≥%s 的有 %d 个，成组 %d 组，用时 %.1fs"
            % (checked, human_size(min_size), kept, len(groups), time.time() - t0))
    except Exception as e:
        log("扫描出错: %r" % e)
        with _LOCK:
            STATE.update(running=False, done=True, error=str(e), current="")


def human_size(n):
    if n >= 1073741824:
        return "%.2f GB" % (n / 1073741824)
    if n >= 1048576:
        return "%.0f MB" % (n / 1048576)
    if n >= 1024:
        return "%.0f KB" % (n / 1024)
    return "%d B" % n


# ---------------- 文件性质识别（能不能删？） ----------------

# 软件安装目录：里面的文件删除会导致软件损坏
PROG_DIR_HINTS = [
    "\\program files\\", "\\program files (x86)\\", "\\programdata\\",
    "\\appdata\\local\\programs\\", "\\windowsapps\\", "\\windows\\",
    "\\steamapps\\", "\\android\\sdk\\", "\\nodejs\\node_modules\\",
]
# 缓存 / 临时 / 日志：程序自动重建，删了不影响功能
CACHE_HINTS = [
    "\\cache", "cachestorage", "code cache", "gpucache", "blob_storage",
    "deliveryoptimization", "\\temp\\", "\\tmp\\", "crashpad", "\\logs\\",
    "\\log\\", "shadercache", "dawncache", "graphitecache", "thumbnails",
]
# 下载 / 接收目录
DOWNLOAD_HINTS = [
    "\\downloads\\", "\\baidunetdiskdownload\\", "\\thunder", "\\qqdownload",
    "\\baidunetdisk\\", "\\下载\\", "\\迅雷下载\\",
]
# 备份 / 副本
BACKUP_HINTS = [
    ".local-backup-", "\\backup", "\\bak\\", "\\副本", "-backup", "_backup",
]
# 你的工作 / 同步目录
WORK_HINTS = [
    "\\baidusyncdisk\\", "\\workspaces\\", "\\workbuddy\\", "\\documents\\",
    "\\desktop\\", "\\onedrive\\",
]
# 通讯 / 会议软件
IM_HINTS = [
    "\\xwechat_files\\", "\\wechat files\\", "\\tencent files\\",
    "\\tencentmeeting\\", "\\qq\\", "\\weixin\\",
]
# 程序二进制 / 资源：一般不要删
PROG_EXTS = {".dll", ".sys", ".exe", ".pyd", ".node", ".so", ".dylib", ".ocx",
             ".pak", ".asar", ".bin", ".dat", ".wem", ".pyc", ".jar", ".nupkg"}
# 临时 / 日志：可以删
TEMP_EXTS = {".tmp", ".temp", ".log", ".old", ".bak", ".crdownload", ".part",
             ".!ut", ".ds_store", ".etag"}
# 你的文档 / 媒体
DOC_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".txt",
            ".md", ".dwg", ".skp", ".psd", ".jpg", ".jpeg", ".png", ".gif",
            ".mp4", ".avi", ".mov", ".mp3", ".wav", ".zip", ".rar", ".7z"}

LEVEL_META = {
    "no": ("程序必要文件", "不建议删除"),
    "safe": ("缓存/临时文件", "可以删除"),
    "warn": ("安装包/备份", "谨慎判断"),
    "user": ("你的文件", "自行判断"),
    "unknown": ("未识别", "先确认来源"),
}


def classify_file(path):
    """判断文件性质：能不能删、为什么。返回 (level, tag, 说明)"""
    p = path.lower().replace("/", "\\")
    name = os.path.basename(path)
    lname = name.lower()
    ext = os.path.splitext(name)[1].lower()

    # 1) Office / 大型软件的离线安装包数据源（如 office/data/16.0.4266.1003/stream.*.dat）
    if lname.startswith("stream.") and ext == ".dat" and re.search(r"\\[0-9]+(\.[0-9]+)+\\", p):
        return ("warn", "软件离线安装源",
                "这是 Office/大型软件的离线安装包数据文件，删掉后无法再用它修复或重装该软件；"
                "软件已装好且你另有安装包备份时可删，否则建议保留。")
    # 2) 软件安装目录
    if any(h in p for h in PROG_DIR_HINTS):
        return ("no", "程序必要文件",
                "位于软件安装目录内，是程序运行必需的组件，删除会导致软件无法启动或功能异常。")
    # 3) 缓存 / 临时 / 日志
    if any(h in p for h in CACHE_HINTS):
        return ("safe", "缓存/临时文件",
                "程序自动生成并会自动重建的缓存，删除不影响软件功能，可放心清理以释放空间。")
    # 4) 备份副本
    if any(h in p for h in BACKUP_HINTS):
        return ("warn", "备份副本",
                "看起来是目录级备份或历史副本。先在正常目录里确认已有同名最新版，再删这个副本。")
    # 5) Office 临时锁文件
    if lname.startswith("~$"):
        return ("safe", "Office 临时文件", "Office 打开文档时产生的临时锁文件，可删。")
    # 6) 通讯软件接收（优先于下载目录判定，因为微信目录常在 Downloads 下）
    if any(h in p for h in IM_HINTS):
        return ("user", "通讯软件文件",
                "微信/QQ/腾讯会议接收或产生的文件。重复转发、重复录制的可以删，原件建议保留。")
    # 7) 下载目录
    if any(h in p for h in DOWNLOAD_HINTS):
        return ("user", "下载目录文件",
                "位于下载/网盘下载目录，通常是安装包或素材。确认不再需要安装或使用时可删。")
    # 8) 你的工作目录
    if any(h in p for h in WORK_HINTS):
        return ("user", "你的工作文件",
                "位于你的项目/同步/文档目录，是你自己的资料。确认是重复副本后可删，注意核对版本。")
    # 9) 按扩展名兜底
    if ext in TEMP_EXTS:
        return ("safe", "临时/日志文件", "临时文件或日志，删除无副作用。")
    if ext in PROG_EXTS:
        return ("no", "程序组件",
                "程序二进制或资源文件，删除可能导致相关软件异常，不建议手工删除。")
    if ext in DOC_EXTS:
        return ("user", "你的文档/媒体", "文档、图片或音视频，需你自己判断哪一份是最新版。")
    return ("unknown", "未识别类型", "无法判定来源，建议先点路径打开所在位置确认后再决定。")


def pick_keeper(files):
    """在一组重复文件里挑一个「建议保留」的：优先不在备份/缓存/下载目录、且较新的那个"""
    def score(f):
        p = f["path"].lower().replace("/", "\\")
        s = 0
        if any(h in p for h in BACKUP_HINTS):
            s -= 3
        if any(h in p for h in CACHE_HINTS):
            s -= 2
        if any(h in p for h in DOWNLOAD_HINTS):
            s -= 1
        if os.path.basename(p).startswith("~$"):
            s -= 5
        return s
    return max(files, key=lambda f: (score(f), f["mtime"]))


def annotate(files):
    """给每个文件加上性质判定 + 是否建议保留 + 是否与其他路径指向同一份实际文件"""
    real = {}
    for f in files:
        try:
            real[f["path"]] = os.path.realpath(f["path"]).lower()
        except OSError:
            real[f["path"]] = f["path"].lower()
    cnt = {}
    for v in real.values():
        cnt[v] = cnt.get(v, 0) + 1
    keeper = pick_keeper(files)
    out = []
    for f in files:
        nf = dict(f)
        lv, tag, note = classify_file(f["path"])
        same = cnt[real[f["path"]]] > 1
        if same:
            note = ("这份与同组另一条路径其实是同一个文件（目录联接/快捷方式指向同一份数据），"
                    "删掉一处另一处也会消失，不要重复删。") + note
        nf["lv"] = lv
        nf["tag"] = tag
        nf["note"] = note
        nf["same"] = same
        nf["keep"] = (f["path"] == keeper["path"])
        out.append(nf)
    return out


def start_scan(roots, skip_names, include_same_dir, min_size=DEFAULT_MIN_SIZE):
    if STATE["running"]:
        return False
    t = threading.Thread(target=scan_worker,
                         args=(roots, skip_names, include_same_dir, min_size), daemon=True)
    t.start()
    return True


def load_index():
    global INDEX_MIN_SIZE
    if os.path.isfile(INDEX_PATH):
        try:
            with open(INDEX_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            STATE["groups"] = data.get("groups", [])
            INDEX_MIN_SIZE = data.get("min_size", DEFAULT_MIN_SIZE)
            return data
        except Exception:
            return None
    return None


def load_settings():
    defaults = {
        "roots": ["C:\\", "D:\\"],
        "skip": DEFAULT_SKIP,
        "include_same_dir": False,
        "min_size": DEFAULT_MIN_SIZE,
    }
    if os.path.isfile(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            defaults.update({k: data[k] for k in defaults if k in data})
        except Exception:
            pass
    return defaults


def save_settings(s):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


# ---------------- Windows 操作：打开位置 / 移入回收站 ----------------

def open_location(path):
    try:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return True
    except Exception as e:
        log("open_location 失败: %r" % e)
        return False


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


SH_ERR_MAP = {
    2: "找不到文件或路径无效（可能已被移动/删除，或路径过长）",
    3: "找不到路径",
    5: "拒绝访问（权限不足，可尝试以管理员运行）",
    32: "文件被其他程序占用，请先关闭相关程序",
    145: "目录非空",
}


def recycle_via_powershell(paths):
    """备用方案：用 .NET VisualBasic.FileIO 逐个移入回收站（对 SHFileOperation 失败的顽固文件有效）。
    返回 (成功列表, 失败列表)"""
    os.makedirs(os.path.join(APP_DIR, "tmp"), exist_ok=True)
    tag = int(time.time() * 1000)
    in_path = os.path.join(APP_DIR, "tmp", "del_in_%d.txt" % tag)
    out_path = os.path.join(APP_DIR, "tmp", "del_out_%d.txt" % tag)
    with open(in_path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(paths))
    script = (
        "$ErrorActionPreference='Continue'\n"
        "Add-Type -AssemblyName Microsoft.VisualBasic\n"
        "$paths = Get-Content -LiteralPath '%s' -Encoding UTF8\n"
        "$ok=New-Object System.Collections.Generic.List[string]\n"
        "$fail=New-Object System.Collections.Generic.List[string]\n"
        "foreach($p in $paths){\n"
        "  try{ if(Test-Path -LiteralPath $p){ "
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p,'OnlyErrorDialogs','SendToRecycleBin'); "
        "$ok.Add($p) } }\n"
        "  catch{ $fail.Add($p) }\n"
        "}\n"
        "@{ok=$ok;fail=$fail}|ConvertTo-Json|Set-Content -LiteralPath '%s' -Encoding UTF8\n"
    ) % (in_path.replace("'", "''"), out_path.replace("'", "''"))
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       timeout=180, capture_output=True)
        with open(out_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        ok = data.get("ok", [])
        fail = data.get("fail", [])
        if isinstance(ok, str): ok = [ok]
        if isinstance(fail, str): fail = [fail]
        return ok, fail
    except Exception as e:
        log("PowerShell 回收站备用方案异常: %r" % e)
        return [], list(paths)
    finally:
        for p in (in_path, out_path):
            try: os.remove(p)
            except OSError: pass


def recycle_files(paths):
    """移入回收站（FOF_ALLOWUNDO），可从回收站还原。
    以「文件是否仍存在」为准判断成败，不依赖 SHFileOperationW 的返回码（它对成功也可能返回非 0）。"""
    paths = [os.path.normpath(p) for p in paths if p]
    if not paths:
        return False, "没有选择文件"

    missing = [p for p in paths if not os.path.exists(p)]
    todo = [p for p in paths if os.path.exists(p)]
    failed = {}   # path -> 原因（真正删除失败的）

    if todo:
        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x40
        FOF_NOCONFIRMATION = 0x10
        FOF_SILENT = 0x4
        FOF_NOERRORUI = 0x400
        # 关键：用 create_unicode_buffer 保证「路径\0路径\0\0」的双 null 结尾不被截断
        # （此前用 c_wchar_p 直接赋值，第一个 \0 后的内容会被截断，
        #  导致批量删除只删第一个、且成功也返回错误码 2）
        pfrom = "\0".join(todo) + "\0"
        buf = ctypes.create_unicode_buffer(pfrom)
        op = SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = FO_DELETE
        op.pFrom = ctypes.cast(buf, ctypes.c_wchar_p)
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        op.fAnyOperationsAborted = False
        op.hNameMappings = None
        op.lpszProgressTitle = None
        r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        log("SHFileOperationW 返回 %s, 提交 %d 个, 未删除 %d 个" % (r, len(todo), len([p for p in todo if os.path.exists(p)])))

        remaining = [p for p in todo if os.path.exists(p)]
        if remaining:
            # 备用方案：.NET FileIO 逐个移入回收站
            ok2, fail2 = recycle_via_powershell(remaining)
            for p in fail2:
                failed[p] = "文件被占用或权限不足（已尝试两种方式）"
            remaining = fail2

    recycled = [p for p in todo if p not in failed]
    if not failed and not missing:
        log("已移入回收站 %d 个文件" % len(recycled))
        return True, "已移入回收站 %d 个文件（可在回收站还原）" % len(recycled)

    parts = []
    if recycled:
        parts.append("已移入回收站 %d 个" % len(recycled))
    if missing:
        # 之前已经删过的文件再次提交时不再报"失败"，避免误导用户重复整理
        parts.append("%d 个此前已删除（无需重复操作）" % len(missing))
    if failed:
        detail = "；".join("%s（%s）" % (os.path.basename(p), reason) for p, reason in list(failed.items())[:3])
        if len(failed) > 3:
            detail += " 等 %d 个" % len(failed)
        parts.append("%d 个删除失败: %s" % (len(failed), detail))
    return not failed, "，".join(parts)


# ---------------- HTTP 服务 ----------------

def filter_groups(q, min_size=DEFAULT_MIN_SIZE, include_same_dir=False, risk="all",
                  show_processed=False):
    """按关键字 + 大小阈值 + 性质过滤；已删除的文件与已处理过的组不再显示"""
    q = (q or "").strip().lower()
    delpaths = set(os.path.normpath(p) for p in DELETIONS["paths"])
    delkeys = set(DELETIONS["keys"])
    out = []
    for g in STATE["groups"]:
        if g["key"] in delkeys and not show_processed:
            continue
        files = [f for f in g["files"]
                 if f["size"] >= min_size and os.path.normpath(f["path"]) not in delpaths]
        if len(files) < 2:
            continue
        if not include_same_dir and len({os.path.dirname(f["path"]) for f in files}) < 2:
            continue
        files = annotate(files)          # 加性质判定 + 建议保留标记
        levels = [f["lv"] for f in files]
        if risk == "safe" and "safe" not in levels:      # 只看含「可清理」的组
            continue
        if risk == "user" and "user" not in levels:      # 只看含「你的文件」的组
            continue
        if risk == "hide_no" and all(lv == "no" for lv in levels):   # 隐藏全是程序必要文件的组
            continue
        if q and not (q in g["core"].lower() or any(q in f["path"].lower() for f in files)):
            continue
        ng = dict(g)
        ng["files"] = files
        ng["count"] = len(files)
        ng["total_size"] = sum(f["size"] for f in files)
        out.append(ng)
    return out


def sort_groups(groups, sort):
    if sort == "name":
        return sorted(groups, key=lambda g: g["core"])
    if sort == "count":
        return sorted(groups, key=lambda g: (-g["count"], -g["total_size"]))
    return sorted(groups, key=lambda g: -g["total_size"])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, "application/json; charset=utf-8", body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            with open(os.path.join(APP_DIR, "app.html"), "rb") as f:
                self._send(200, "text/html; charset=utf-8", f.read())
        elif u.path == "/api/status":
            st = {k: v for k, v in STATE.items() if k != "groups"}   # 不回传全量分组，避免轮询卡顿
            st["groups_count"] = len(STATE["groups"])
            st["current"] = st["current"][-120:] if st["current"] else ""
            st["index_min_size"] = INDEX_MIN_SIZE
            self._json(st)
        elif u.path == "/api/groups":
            qs = parse_qs(u.query)
            q = qs.get("q", [""])[0]
            sort = qs.get("sort", ["size"])[0]
            risk = qs.get("risk", ["all"])[0]
            s = load_settings()
            try:
                min_size = int(qs.get("min_size", [s["min_size"]])[0])
            except (ValueError, TypeError):
                min_size = s["min_size"]
            try:
                page = max(1, int(qs.get("page", ["1"])[0]))
            except ValueError:
                page = 1
            try:
                per = int(qs.get("per", ["40"])[0])     # 每页组数：默认 40，降低单次渲染压力
            except ValueError:
                per = 40
            per = max(10, min(per, 200))
            show_done = qs.get("show_processed", ["0"])[0] == "1"
            groups = sort_groups(filter_groups(q, min_size, s["include_same_dir"], risk,
                                               show_done), sort)
            pages = max(1, (len(groups) + per - 1) // per)
            page = min(page, pages)
            chunk = groups[(page - 1) * per: page * per]
            self._json({"total": len(groups), "page": page, "pages": pages,
                        "min_size": min_size,
                        "need_rescan": min_size < INDEX_MIN_SIZE,
                        "index_min_size": INDEX_MIN_SIZE,
                        "groups": chunk})
        elif u.path == "/api/settings":
            self._json(load_settings())
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        u = urlparse(self.path)
        data = self._body()
        if u.path == "/api/start":
            s = load_settings()
            roots = data.get("roots") or s["roots"]
            skip = data.get("skip") if isinstance(data.get("skip"), list) else s["skip"]
            inc = bool(data.get("include_same_dir", s["include_same_dir"]))
            try:
                min_size = int(data.get("min_size", s["min_size"]))
            except (ValueError, TypeError):
                min_size = s["min_size"]
            save_settings({"roots": roots, "skip": skip, "include_same_dir": inc,
                           "min_size": min_size})
            ok = start_scan(roots, skip, inc, min_size)
            self._json({"ok": ok, "msg": "" if ok else "扫描正在进行中"})
        elif u.path == "/api/open":
            ok = open_location(data.get("path", ""))
            self._json({"ok": ok})
        elif u.path == "/api/delete":
            req_paths = [p for p in (data.get("paths") or []) if p]
            ok, msg = recycle_files(req_paths)
            # 记录实际已删除的路径 → 前端立即隐藏对应重复组（无需重新扫描）
            gone = [p for p in req_paths if not os.path.exists(p)]
            if gone:
                record_deletions(gone)
            self._json({"ok": ok, "msg": msg})
        elif u.path == "/api/reset_hidden":
            # 清空「已删除/已忽略」的隐藏记录：之前删过但被隐藏的组会重新显示（文件不会恢复）
            DELETIONS["paths"] = []
            DELETIONS["keys"] = []
            save_deletions()
            log("已清空隐藏/忽略记录")
            self._json({"ok": True, "msg": "已清空隐藏记录，之前隐藏的组会重新显示"})
        elif u.path == "/api/ignore":
            # 忽略本组：不删除任何文件，只是不再在列表里显示（可在「显示已处理过的组」里找回）
            key = data.get("key", "")
            if key and key not in DELETIONS["keys"]:
                DELETIONS["keys"].append(key)
                save_deletions()
            self._json({"ok": True})
        else:
            self._send(404, "text/plain", b"not found")


def main():
    # 把自己的优先级降到「低于正常」，扫描/轮询都不会跟前台程序抢 CPU
    try:
        BELOW_NORMAL_PRIORITY_CLASS = 0x4000
        ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    data = load_index()
    load_deletions()
    if data:
        log("已加载缓存索引: %d 组 (构建于 %s)" % (len(data.get("groups", [])),
            time.strftime("%Y-%m-%d %H:%M", time.localtime(data.get("built_at", 0)))))
    port = None
    srv = None
    for p in PORT_CANDIDATES:
        try:
            srv = ThreadingHTTPServer((HOST, p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        log("端口全部被占用，退出")
        return
    url = "http://%s:%d" % (HOST, port)
    log("服务已启动: %s" % url)
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
