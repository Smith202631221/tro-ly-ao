# -*- coding: utf-8 -*-
"""
Trợ lý ảo – App Android (Kivy)  |  Personal Assistant – Android app (Kivy)

AI:
  - Offline miễn phí: Ollama chạy trong Termux (ollama serve)
      gõ trong app:  model qwen2.5:1.5b
  - Online: Claude API
      gõ trong app:  key sk-ant-...
"""

import json
import os
import ssl
import threading
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from html import unescape

API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_TURNS = 6          # số tin nhắn gần nhất gửi cho Claude (tiết kiệm token)
# giá USD cho 1 triệu token (vào, ra)
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0),
          "claude-opus-5-5": (4.0, 20.0)}
CLAUDE_TOOLS = [
    {"name": "web_search",
     "description": "Search the internet (free). Use for current events, news, prices, weather "
                    "or facts you are not sure about. Not for simple chat.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                      "required": ["query"]}},
    {"name": "fetch_page",
     "description": "Read the text of a web page URL found by web_search.",
     "input_schema": {"type": "object", "properties": {"url": {"type": "string"}},
                      "required": ["url"]}}]
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


TOOL_CMDS = ("plot", "bar", "pie", "flow", "cycle", "chem", "pdf", "word", "excel", "image")

TOOL_HINT = """

The app can draw and create files. If the user asks to draw/plot a graph, chart,
diagram, process, cycle or molecule, or to create/export a PDF, Word or Excel file,
reply with ONLY one line in exactly one of these forms and nothing else:
plot <expr>; <expr> from <a> to <b>      (variable x, e.g. plot sin(x); x^2 from -5 to 5)
bar <title>: <label>=<number>, <label>=<number>
pie <title>: <label>=<number>, <label>=<number>
flow <title>: <step> -> <step> -> <step>
cycle <title>: <stage> -> <stage> -> <stage>
chem <chemical name in English>
image <detailed English description of the picture>   (for drawing a picture, photo, art or illustration; not for charts)
pdf <topic>
word <topic>
excel <topic>
Use real data you know for charts. For every other request answer normally."""


def _nice(path):
    return path.replace("/storage/emulated/0/Download", "Tải về (Download)")


def is_tool_line(text):
    """AI trả lời bằng đúng một dòng lệnh (vd 'plot sin(x)') chứ không phải câu văn."""
    lines = [l for l in text.strip().split("\n") if l.strip()]
    if not lines or len(lines) > 2 or len(lines[0]) > 300:
        return False
    first = lines[0].strip().strip("`").strip()
    word, _, rest = first.partition(" ")
    word = word.lower()
    if word not in TOOL_CMDS or not rest.strip():
        return False
    if word == "plot":
        return "x" in rest.lower()
    if word in ("bar", "pie"):
        return "=" in rest
    if word == "image":
        return len(rest.split()) <= 80
    if word in ("flow", "cycle"):
        return "->" in rest or "→" in rest
    return len(rest.split()) <= 25 and not rest.rstrip().endswith((".", "?", "!"))


def _strip(html):
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


_SUB = str.maketrans({**{c: str(i) for i, c in enumerate("₀₁₂₃₄₅₆₇₈₉")},
                      **{c: "^" + str(i) for i, c in enumerate("⁰¹²³⁴⁵⁶⁷⁸⁹")}})


def _plain(text):
    """Bỏ ký hiệu Markdown/LaTeX để hiển thị và đọc to cho gọn."""
    text = re.sub(r"^\s*```.*$", "", text, flags=re.M)          # ``` code
    text = re.sub(r"\\[\(\)\[\]]", "", text)                  # \( \) \[ \]
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)                 # **đậm**
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.M)          # # tiêu đề
    text = text.replace("`", "").translate(_SUB)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


T = {
    "vi": {
        "welcome": "Xin chào {name}! Gõ 'help' để xem lệnh.",
        "ask_name": "Chào bạn! Bạn muốn mình gọi bạn là gì? (gõ tên rồi bấm Gửi)",
        "help": (
            "LỆNH:\n"
            "time – giờ & ngày\n"
            "note <nội dung> – lưu ghi chú\n"
            "notes – xem ghi chú\n"
            "delnote <số> – xóa ghi chú\n"
            "todo <việc> – thêm việc\n"
            "todos – xem việc\n"
            "done <số> – đánh dấu xong\n"
            "remind <phút> <nội dung> – nhắc (khi app đang mở)\n"
            "calc <biểu thức> – máy tính\n"
            "remember <khóa>=<giá trị> – ghi nhớ về bạn\n"
            "profile – xem thông tin\n"
            "forget <khóa> – xóa thông tin\n"
            "name <tên> – đổi tên\n"
            "lang vi/en – đổi ngôn ngữ\n\n"
            "CÀI AI:\n"
            "model <tên> – dùng Ollama offline (vd: model qwen2.5:1.5b)\n"
            "ollama <url> – đổi địa chỉ Ollama\n"
            "key <sk-ant-...> – dùng Claude API\n"
            "ai ollama / ai claude / ai off – chọn AI\n"
            "status – xem cài đặt AI\n"
            "clear – xóa lịch sử chat AI\n\n"
            "GIỌNG NÓI & WEB:\n"
            "Nút 'Nói' – hỏi bằng giọng nói\n"
            "voice on/off – bật/tắt đọc to câu trả lời\n"
            "web on/off – bật/tắt tìm kiếm online\n"
            "lock <mật khẩu> – chỉ nhận lệnh giọng nói bắt đầu bằng mật khẩu\n"
            "unlock – tắt khóa giọng nói\n\n"
            "VẼ & XUẤT FILE (hoặc nói tự nhiên, vd 'vẽ đồ thị sin x'):\n"
            "plot sin(x); x^2 từ -5 đến 5 – đồ thị hàm số\n"
            "bar Tên: A=3, B=5 – biểu đồ cột\n"
            "pie Tên: A=60, B=40 – biểu đồ tròn\n"
            "flow Tên: bước 1 -> bước 2 – sơ đồ quy trình\n"
            "cycle Tên: giai đoạn 1 -> giai đoạn 2 – sơ đồ chu trình\n"
            "chem caffeine – cấu trúc phân tử (tên tiếng Anh, cần mạng)\n"
            "pdf <chủ đề> – infographic PDF\n"
            "word <chủ đề> – file Word\n"
            "excel <chủ đề> – bảng Excel\n"
            "image <mô tả> – vẽ tranh/ảnh (Stable Diffusion trên máy tính)\n"
            "server <IP máy tính> – địa chỉ máy tính, vd server 192.168.1.20\n"
            "ollama pc / ollama phone – dùng Ollama trên máy tính / điện thoại\n"
            "(File lưu trong thư mục Tải về/TroLyAo)\n\n"
            "NÂNG CAO:\n"
            "Nút 'Ảnh' – gửi ảnh rồi hỏi về ảnh (model nhìn ảnh)\n"
            "Nút 'Tệp' – mở PDF/Word/TXT/Excel rồi hỏi về tài liệu\n"
            "doc clear – bỏ tài liệu đang mở\n"
            "vision <model> – model nhìn ảnh (mặc định gemma3:4b)\n"
            "think on/off – bật/tắt chế độ suy nghĩ kỹ (qwen3)\n"
            "usage – xem chi phí Claude tháng này\n"
            "budget <USD> – ngân sách Claude mỗi tháng (mặc định 1)\n"
            "claude haiku/sonnet/opus – chọn model Claude (haiku rẻ nhất)\n"
            "Nút 'Dừng' – dừng câu trả lời đang chạy\n\n"
            "Câu khác sẽ gửi tới AI."
        ),
        "saved": "Đã lưu.", "deleted": "Đã xóa.", "empty": "(trống)",
        "bad_num": "Số không hợp lệ.",
        "remind_set": "Sẽ nhắc bạn lúc {t} (nhớ để app mở).",
        "remind_fire": "NHẮC NHỞ: {msg}",
        "no_ai": "Chưa cài AI. Gõ 'help' xem phần CÀI AI.",
        "ai_err": "Lỗi AI: {e}\n(Nếu dùng Ollama: đã chạy 'ollama serve' trong Termux chưa?)",
        "thinking": "Đang suy nghĩ...",
        "time": "Bây giờ là {t}.",
        "cleared": "Đã xóa lịch sử chat.",
        "calc_err": "Biểu thức không hợp lệ.",
        "send": "Gửi", "hint": "Nhập tin nhắn...", "mic": "Nói",
        "mic_prompt": "Hãy nói câu hỏi...",
        "mic_err": "Không mở được nhận giọng nói. Hãy cài/bật ứng dụng Google.",
        "searching": "Đang tìm trên mạng...",
        "working": "Đang tạo...",
        "file_saved": "Đã lưu file: {p}\nMở bằng ứng dụng Tệp của tôi (My Files).",
        "img_saved": "Đã lưu ảnh: {p}",
        "tool_err": "Không tạo được: {e}",
        "no_server": "Chưa có địa chỉ máy tính. Gõ: server <IP máy tính>, vd server 192.168.1.20",
        "pc_err": "Không kết nối được máy tính ({e}). Máy tính đã bật Stable Diffusion/Ollama và cùng wifi chưa?",
        "drawing": "Đang vẽ trên máy tính...",
        "locked": "Đã bật khóa giọng nói. Lệnh bằng giọng phải bắt đầu bằng: \"{p}\"",
        "unlocked": "Đã tắt khóa giọng nói.",
        "voice_ignored": "Bỏ qua: câu nói không bắt đầu bằng mật khẩu.",
        "stop": "Dừng", "photo": "Ảnh", "file": "Tệp", "notes_btn": "Ghi chú",
        "todos_btn": "Việc", "help_btn": "Lệnh",
        "img_attached": "Đã đính kèm ảnh. Giờ hãy hỏi về ảnh (vd: đây là gì?).",
        "doc_loading": "Đang đọc tài liệu...",
        "doc_loaded": "Đã đọc \"{n}\" ({c} ký tự). Cứ hỏi về tài liệu này. Gõ 'doc clear' để bỏ.",
        "doc_cleared": "Đã bỏ tài liệu.",
        "doc_err": "Không đọc được tài liệu: {e}",
        "pick_err": "Không mở được trình chọn file.",
        "web_q": "Đang tìm trên mạng: {q}",
        "web_read": "Đang đọc trang: {q}",
        "fallback_phone": "(Máy tính không phản hồi – đang dùng Ollama trên điện thoại)",
        "fallback_claude": "(Máy tính không phản hồi – đang dùng Claude)",
        "stopped": " …(đã dừng)",
        "budget_hit": "Đã dùng hết ngân sách Claude tháng này ({b} USD). Dùng Ollama, hoặc gõ: budget <số USD>",
        "refused": "(Claude từ chối trả lời câu này)",
        "usage": "Claude tháng {m}: {c} lần gọi, {i} token vào, {o} token ra\nChi phí ước tính: {usd:.4f} / {b} USD\nCòn khoảng {n} câu hỏi nữa.",
    },
    "en": {
        "welcome": "Hi {name}! Type 'help' for commands.",
        "ask_name": "Hi! What should I call you? (type your name and tap Send)",
        "help": (
            "COMMANDS:\n"
            "time – time & date\n"
            "note <text> – save note\n"
            "notes – list notes\n"
            "delnote <n> – delete note\n"
            "todo <task> – add task\n"
            "todos – list tasks\n"
            "done <n> – mark done\n"
            "remind <min> <text> – reminder (while app is open)\n"
            "calc <expr> – calculator\n"
            "remember <key>=<value> – remember a fact\n"
            "profile – show facts\n"
            "forget <key> – remove fact\n"
            "name <name> – change name\n"
            "lang vi/en – switch language\n\n"
            "AI SETUP:\n"
            "model <name> – use offline Ollama (e.g. model qwen2.5:1.5b)\n"
            "ollama <url> – change Ollama address\n"
            "key <sk-ant-...> – use Claude API\n"
            "ai ollama / ai claude / ai off – choose AI\n"
            "status – show AI settings\n"
            "clear – clear AI chat history\n\n"
            "VOICE & WEB:\n"
            "'Talk' button – ask by voice\n"
            "voice on/off – read answers aloud\n"
            "web on/off – online search\n"
            "lock <passphrase> – only accept voice commands starting with it\n"
            "unlock – turn voice lock off\n\n"
            "DRAW & EXPORT (or just say e.g. 'plot sin x'):\n"
            "plot sin(x); x^2 from -5 to 5 – function graph\n"
            "bar Title: A=3, B=5 – bar chart\n"
            "pie Title: A=60, B=40 – pie chart\n"
            "flow Title: step 1 -> step 2 – process diagram\n"
            "cycle Title: stage 1 -> stage 2 – cycle diagram\n"
            "chem caffeine – molecule structure (needs internet)\n"
            "pdf <topic> – PDF infographic\n"
            "word <topic> – Word file\n"
            "excel <topic> – Excel table\n"
            "image <description> – draw a picture (Stable Diffusion on your PC)\n"
            "server <PC IP> – PC address, e.g. server 192.168.1.20\n"
            "ollama pc / ollama phone – use Ollama on the PC / the phone\n"
            "(Files are saved in Download/TroLyAo)\n\n"
            "ADVANCED:\n"
            "'Photo' button – attach a photo and ask about it (vision model)\n"
            "'File' button – open PDF/Word/TXT/Excel and ask about it\n"
            "doc clear – close the open document\n"
            "vision <model> – vision model (default gemma3:4b)\n"
            "think on/off – deep thinking mode (qwen3)\n"
            "usage – Claude cost this month\n"
            "budget <USD> – monthly Claude budget (default 1)\n"
            "claude haiku/sonnet/opus – Claude model (haiku is cheapest)\n"
            "'Stop' button – stop the answer being written\n\n"
            "Anything else goes to the AI."
        ),
        "saved": "Saved.", "deleted": "Deleted.", "empty": "(empty)",
        "bad_num": "Invalid number.",
        "remind_set": "I'll remind you at {t} (keep the app open).",
        "remind_fire": "REMINDER: {msg}",
        "no_ai": "No AI set up. Type 'help' and see AI SETUP.",
        "ai_err": "AI error: {e}\n(Using Ollama? Is 'ollama serve' running in Termux?)",
        "thinking": "Thinking...",
        "time": "It is {t}.",
        "cleared": "Chat history cleared.",
        "calc_err": "Invalid expression.",
        "send": "Send", "hint": "Type a message...", "mic": "Talk",
        "mic_prompt": "Say your question...",
        "mic_err": "Can't start speech recognition. Install/enable the Google app.",
        "searching": "Searching online...",
        "working": "Creating...",
        "file_saved": "File saved: {p}\nOpen it with the My Files app.",
        "img_saved": "Image saved: {p}",
        "tool_err": "Couldn't create it: {e}",
        "no_server": "No PC address yet. Type: server <PC IP>, e.g. server 192.168.1.20",
        "pc_err": "Can't reach the PC ({e}). Is Stable Diffusion/Ollama running and on the same wifi?",
        "drawing": "Drawing on the PC...",
        "locked": "Voice lock on. Voice commands must start with: \"{p}\"",
        "unlocked": "Voice lock off.",
        "voice_ignored": "Ignored: speech didn't start with the passphrase.",
        "stop": "Stop", "photo": "Photo", "file": "File", "notes_btn": "Notes",
        "todos_btn": "Tasks", "help_btn": "Help",
        "img_attached": "Photo attached. Now ask about it (e.g. what is this?).",
        "doc_loading": "Reading the document...",
        "doc_loaded": "Read \"{n}\" ({c} characters). Ask anything about it. Type 'doc clear' to close it.",
        "doc_cleared": "Document closed.",
        "doc_err": "Couldn't read the document: {e}",
        "pick_err": "Couldn't open the file picker.",
        "web_q": "Searching the web: {q}",
        "web_read": "Reading page: {q}",
        "fallback_phone": "(PC not responding – using Ollama on the phone)",
        "fallback_claude": "(PC not responding – using Claude)",
        "stopped": " …(stopped)",
        "budget_hit": "Claude budget for this month used up ({b} USD). Use Ollama, or type: budget <USD>",
        "refused": "(Claude declined to answer this)",
        "usage": "Claude {m}: {c} calls, {i} input tokens, {o} output tokens\nEstimated cost: {usd:.4f} / {b} USD\nAbout {n} questions left.",
    },
}


# ======================================================== logic (không cần Kivy)
class Core:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "tro_ly_ao.json")
        self.d = {"name": "", "lang": "vi", "notes": [], "todos": [], "facts": {},
                  "history": [], "ai": "off", "api_key": "",
                  "ollama_model": "", "ollama_url": DEFAULT_OLLAMA_URL,
                  "voice": True, "web": True, "passphrase": "", "pc": "",
                  "think": False, "vision_model": "gemma3:4b",
                  "pc_model": "", "phone_model": "", "doc_name": "",
                  "claude_model": "claude-haiku-5-5", "effort": "low", "budget": 1.0}
        try:
            with open(self.path, encoding="utf-8") as f:
                self.d.update(json.load(f))
        except (OSError, ValueError):
            pass
        self.doc_path = os.path.join(data_dir, "tai_lieu.txt")
        self.doc_text = ""
        if self.d.get("doc_name"):
            try:
                with open(self.doc_path, encoding="utf-8") as f:
                    self.doc_text = f.read()
            except OSError:
                self.d["doc_name"] = ""
        self.pending_image = None      # ảnh (base64 JPEG) gửi kèm câu hỏi tiếp theo

    def on_pc(self):
        pc = self.d.get("pc")
        return bool(pc) and f"//{pc}:" in self.d.get("ollama_url", "")

    def t(self, k, **kw):
        return T[self.d["lang"]][k].format(**kw)

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    # Trả về (câu trả lời, cần_gọi_AI)
    def handle(self, line):
        d = self.d
        line = line.strip()
        if not d["name"]:
            d["name"] = line or "bạn"
            return self.t("welcome", name=d["name"]), False
        cmd, _, arg = line.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()

        if cmd == "help":
            return self.t("help"), False
        if cmd == "time":
            return self.t("time", t=datetime.now().strftime("%H:%M, %d/%m/%Y")), False
        if cmd == "note" and arg:
            d["notes"].append(f"[{datetime.now():%d/%m %H:%M}] {arg}")
            return self.t("saved"), False
        if cmd == "notes":
            return self._list(d["notes"]), False
        if cmd == "delnote":
            return self._pop(d["notes"], arg), False
        if cmd == "todo" and arg:
            d["todos"].append({"task": arg, "done": False})
            return self.t("saved"), False
        if cmd == "todos":
            return self._list([("[x] " if x["done"] else "[ ] ") + x["task"]
                               for x in d["todos"]]), False
        if cmd == "done":
            try:
                d["todos"][int(arg) - 1]["done"] = True
                return self.t("saved"), False
            except (ValueError, IndexError):
                return self.t("bad_num"), False
        if cmd == "calc":
            try:
                if not arg or not set(arg) <= set("0123456789+-*/().% "):
                    raise ValueError
                return f"{arg} = {eval(arg, {'__builtins__': {}}, {})}", False
            except Exception:
                return self.t("calc_err"), False
        if cmd == "remember" and "=" in arg:
            k, v = (s.strip() for s in arg.split("=", 1))
            d["facts"][k] = v
            return self.t("saved"), False
        if cmd == "profile":
            return "\n".join([f"name: {d['name']}"] +
                             [f"{k}: {v}" for k, v in d["facts"].items()]), False
        if cmd == "forget" and arg:
            d["facts"].pop(arg, None)
            return self.t("deleted"), False
        if cmd == "name" and arg:
            d["name"] = arg
            return self.t("saved"), False
        if cmd == "lang" and arg in ("vi", "en"):
            d["lang"] = arg
            return self.t("saved"), False
        if cmd == "model" and arg:
            arg = arg.replace(" ", "")  # bàn phím Samsung hay tự chèn dấu cách
            d["ollama_model"], d["ai"] = arg, "ollama"
            d["pc_model" if self.on_pc() else "phone_model"] = arg
            return self.t("saved") + f" (Ollama: {arg})", False
        if cmd == "server" and arg:
            ip = arg.replace(" ", "").replace("http://", "").split("/")[0].split(":")[0]
            d["pc"] = ip
            return self.t("saved") + f" (PC: {ip})", False
        if cmd == "ollama" and arg in ("pc", "phone"):
            if arg == "pc" and not d.get("pc"):
                return self.t("no_server"), False
            host = d["pc"] if arg == "pc" else "127.0.0.1"
            d["ollama_url"] = f"http://{host}:11434/api/chat"
            d["ai"] = "ollama"
            d["ollama_model"] = d.get(arg + "_model") or d["ollama_model"]
            return self.t("saved") + f" (Ollama: {host})", False
        if cmd == "ollama" and arg:
            d["ollama_url"] = arg.replace(" ", "")
            return self.t("saved"), False
        if cmd == "key" and arg:
            d["api_key"] = arg.replace(" ", "")
            if not d.get("ollama_model"):          # có Ollama thì Claude chỉ là dự phòng
                d["ai"] = "claude"
            return self.t("saved") + f" (Claude API, AI: {d['ai']})", False
        if cmd == "ai" and arg in ("ollama", "claude", "off"):
            d["ai"] = arg
            return self.t("saved"), False
        if cmd == "lock" and arg:
            d["passphrase"] = arg.lower().strip()
            return self.t("locked", p=d["passphrase"]), False
        if cmd == "unlock":
            d["passphrase"] = ""
            return self.t("unlocked"), False
        if cmd == "claude" and arg in ("haiku", "sonnet", "opus"):
            d["claude_model"] = f"claude-{arg}-5-5"
            return self.t("saved") + f" ({d['claude_model']})", False
        if cmd == "effort" and arg in ("low", "medium", "high"):
            d["effort"] = arg
            return self.t("saved") + f" (effort: {arg})", False
        if cmd == "budget" and arg:
            try:
                d["budget"] = float(arg.replace(",", ".").replace("$", ""))
            except ValueError:
                return self.t("bad_num"), False
            return self.t("saved") + f" (budget: {d['budget']:g} USD/tháng)", False
        if cmd == "usage":
            u = self._usage()
            return self.t("usage", m=u["month"], c=u["calls"], i=u["in"], o=u["out"],
                          usd=u["usd"], b=d.get("budget", 1.0),
                          n=max(0, int((float(d.get("budget", 1.0)) - u["usd"]) / 0.0004))), False
        if cmd == "vision" and arg:
            d["vision_model"] = arg.replace(" ", "")
            return self.t("saved") + f" (vision: {d['vision_model']})", False
        if cmd == "doc" and arg in ("clear", "off"):
            self.doc_text, d["doc_name"] = "", ""
            try:
                os.remove(self.doc_path)
            except OSError:
                pass
            return self.t("doc_cleared"), False
        if cmd in ("voice", "web", "think") and arg in ("on", "off"):
            d[cmd] = arg == "on"
            return self.t("saved") + f" ({cmd}: {arg})", False
        if cmd == "status":
            key = ("..." + d["api_key"][-4:]) if d["api_key"] else "-"
            return (f"AI: {d['ai']}\nOllama model: {d['ollama_model'] or '-'}\n"
                    f"Ollama URL: {d['ollama_url']}\nClaude key: {key}\n"
                    f"PC: {d.get('pc') or '-'}  (PC model: {d.get('pc_model') or '-'}, "
                    f"phone model: {d.get('phone_model') or '-'})\n"
                    f"Vision model: {d.get('vision_model')}\n"
                    f"Think: {'on' if d.get('think') else 'off'}\n"
                    f"Document: {d.get('doc_name') or '-'}\n"
                    f"Claude: {d.get('claude_model')} (effort {d.get('effort')}), "
                    f"tháng này {self._usage()['usd']:.3f}/{float(d.get('budget', 1)):g} USD\n"
                    f"Voice: {'on' if d['voice'] else 'off'}\n"
                    f"Web: {'on' if d['web'] else 'off'}"), False
        if cmd == "clear":
            d["history"] = []
            return self.t("cleared"), False
        if d["ai"] == "off":
            return self.t("no_ai"), False
        return None, True

    def check_voice(self, spoken):
        """Khóa giọng nói: trả về câu lệnh (đã bỏ mật khẩu) hoặc None."""
        pw = self.d.get("passphrase", "")
        if not pw:
            return spoken
        low = spoken.lower().strip()
        if low.startswith(pw):
            return spoken.strip()[len(pw):].lstrip(" ,.:")
        return None

    def _list(self, items):
        return "\n".join(f"{i}. {x}" for i, x in enumerate(items, 1)) or self.t("empty")

    def _pop(self, items, arg):
        try:
            items.pop(int(arg) - 1)
            return self.t("deleted")
        except (ValueError, IndexError):
            return self.t("bad_num")

    # Tìm kiếm online miễn phí (Wikipedia + DuckDuckGo) để đưa cho Ollama
    @staticmethod
    def fetch(url, timeout=20):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Android) TroLyAo/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            return r.read()

    @classmethod
    def _get(cls, url, timeout=12):
        return cls.fetch(url, timeout).decode("utf-8", "replace")

    def web_context(self, query):
        q = urllib.parse.quote(query)
        out = []
        try:
            html = self._get("https://html.duckduckgo.com/html/?q=" + q)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
            for t, sn in list(zip(titles, snippets))[:5]:
                out.append(f"- {_strip(t)}: {_strip(sn)}")
        except Exception:
            pass
        try:
            wl = "vi" if self.d["lang"] == "vi" else "en"
            js = json.loads(self._get(
                f"https://{wl}.wikipedia.org/w/api.php?action=query&list=search"
                f"&srsearch={q}&srlimit=3&format=json"))
            for it in js.get("query", {}).get("search", []):
                out.append(f"- Wikipedia {it['title']}: {_strip(it['snippet'])}")
        except Exception:
            pass
        return "\n".join(out)

    def _system(self, tools=True):
        d = self.d
        facts = "\n".join(f"- {k}: {v}" for k, v in d["facts"].items()) or "(none)"
        lang = "Trả lời bằng tiếng Việt." if d["lang"] == "vi" else "Reply in English."
        web = ("\nYou can use the web_search and fetch_page tools when the question needs "
               "current or factual information you are unsure about (news, prices, weather, "
               "recent events). Do not search for simple chat." if d.get("web") else "")
        return (f"You are a friendly, concise personal assistant on the user's "
                f"Android phone. User's name: {d['name']}. Known facts:\n{facts}\n"
                f"Now: {datetime.now():%Y-%m-%d %H:%M}. Keep answers short. "
                f"Write plain text only: no Markdown, no LaTeX, no code blocks. {lang}"
                + web + (TOOL_HINT if tools else ""))

    # ---------------- công cụ web cho AI (tool calling)
    def fetch_page(self, url):
        html = self._get(url, 15)
        html = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"\s+", " ", _strip(html))
        return text[:5000]

    def _run_tool(self, name, args, on_status):
        try:
            if name == "web_search":
                q = str(args.get("query", ""))
                on_status(self.t("web_q", q=q))
                return self.web_context(q) or "No results."
            if name == "fetch_page":
                u = str(args.get("url", ""))
                on_status(self.t("web_read", q=u[:60]))
                return self.fetch_page(u)
        except Exception as e:
            return f"Error: {e}"
        return "Unknown tool."

    # ---------------- Ollama (streaming + tool calling)
    def _reachable(self, url, timeout=2.5):
        base = url.split("/api/")[0]
        try:
            with urllib.request.urlopen(base + "/api/version", timeout=timeout):
                return True
        except Exception:
            return False

    def _ollama(self, url, model, system, msgs, query, on_token, on_status, stop, image):
        d = self.d
        msgs = [{"role": "system", "content": system}] + [dict(m) for m in msgs]
        if image:
            model = d.get("vision_model") or model
            msgs[-1]["images"] = [image]
        use_tools = bool(d.get("web")) and not image
        tools = [
            {"type": "function", "function": {
                "name": "web_search",
                "description": "Search the internet. Use for current events, news, prices, "
                               "weather, or facts you are not sure about.",
                "parameters": {"type": "object", "required": ["query"], "properties": {
                    "query": {"type": "string", "description": "search keywords"}}}}},
            {"type": "function", "function": {
                "name": "fetch_page",
                "description": "Read the text of a web page found by web_search.",
                "parameters": {"type": "object", "required": ["url"], "properties": {
                    "url": {"type": "string"}}}}}]
        content = ""
        for _round in range(5):
            body = {"model": model, "messages": msgs, "stream": True,
                    "keep_alive": "30m", "options": {"num_ctx": 8192}}
            if model.startswith("qwen3"):
                body["think"] = bool(d.get("think"))
            if use_tools:
                body["tools"] = tools
            req = urllib.request.Request(url, json.dumps(body).encode(),
                                         {"content-type": "application/json"})
            try:
                r = urllib.request.urlopen(req, timeout=900)
            except urllib.error.HTTPError as e:
                err = e.read().decode("utf-8", "replace")
                if use_tools and "tool" in err.lower():
                    # model không hỗ trợ tool calling -> tìm sẵn rồi đưa vào câu hỏi
                    use_tools = False
                    if d.get("web") and query:
                        on_status(self.t("web_q", q=query))
                        ctx = self.web_context(query)
                        if ctx:
                            msgs[-1]["content"] = (f"Kết quả tìm kiếm trên mạng (dùng nếu liên quan):"
                                                   f"\n{ctx}\n\nCâu hỏi: {msgs[-1]['content']}")
                    continue
                if "think" in err.lower() and "think" in body:
                    body.pop("think")      # model không hỗ trợ think -> bỏ tham số
                    r = urllib.request.urlopen(urllib.request.Request(
                        url, json.dumps(body).encode(), {"content-type": "application/json"}),
                        timeout=900)
                else:
                    raise RuntimeError(f"{e.code}: {err[:200]}")
            calls, content = [], ""
            with r:
                for line in r:
                    if stop is not None and stop.is_set():
                        return content + self.t("stopped")
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise RuntimeError(chunk["error"])
                    m = chunk.get("message", {})
                    if m.get("content"):
                        content += m["content"]
                        on_token(content)
                    calls += m.get("tool_calls") or []
                    if chunk.get("done"):
                        break
            if not calls:
                return content
            msgs.append({"role": "assistant", "content": content, "tool_calls": calls})
            for c in calls:
                f = c.get("function", {})
                args = f.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {"query": args}
                msgs.append({"role": "tool", "tool_name": f.get("name", ""),
                             "content": self._run_tool(f.get("name"), args, on_status)})
        return content

    # ---------------- Claude (chế độ tiết kiệm: Haiku, effort thấp, tìm web miễn phí)
    def _usage(self):
        u = self.d.setdefault("usage", {})
        month = datetime.now().strftime("%Y-%m")
        if u.get("month") != month:                  # sang tháng mới -> đếm lại
            u.clear()
            u.update({"month": month, "in": 0, "out": 0, "usd": 0.0, "calls": 0})
        return u

    def over_budget(self):
        return self._usage()["usd"] >= float(self.d.get("budget", 1.0))

    def _add_usage(self, model, usage):
        pin, pout = PRICES.get(model, PRICES["claude-haiku-5-5"])
        tin = (usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) * 1.25
               + usage.get("cache_read_input_tokens", 0) * 0.1)
        tout = usage.get("output_tokens", 0)
        searches = (usage.get("server_tool_use") or {}).get("web_search_requests", 0)
        u = self._usage()
        u["in"] += int(tin)
        u["out"] += tout
        u["calls"] += 1
        u["usd"] += tin * pin / 1e6 + tout * pout / 1e6 + searches * 0.01

    def _claude(self, system, msgs, image, on_status=None):
        d = self.d
        on_status = on_status or (lambda t: None)
        if not d.get("api_key"):
            raise RuntimeError("chưa có Claude API key (gõ: key sk-ant-...)")
        if self.over_budget():
            raise RuntimeError(self.t("budget_hit", b=d.get("budget", 1.0)))
        model = d.get("claude_model", "claude-haiku-5-5")
        msgs = [dict(m) for m in msgs][-CLAUDE_TURNS:]    # chỉ gửi vài lượt gần nhất
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        if image:
            msgs[-1]["content"] = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": image}},
                {"type": "text", "text": msgs[-1]["content"]}]
        body = {"model": model, "max_tokens": 1500, "system": system, "messages": msgs,
                "output_config": {"effort": d.get("effort", "low")}}
        if d.get("web") and not image:
            body["tools"] = CLAUDE_TOOLS                  # tìm web miễn phí do app tự chạy
        reply = ""
        for _ in range(5):
            req = urllib.request.Request(API_URL, json.dumps(body).encode(), {
                "x-api-key": d["api_key"], "anthropic-version": "2023-06-01",
                "content-type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=180, context=_ssl_ctx()) as r:
                    res = json.load(r)
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"Claude {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
            self._add_usage(model, res.get("usage", {}))
            self.save()
            content = res.get("content", [])
            reply += "".join(b.get("text", "") for b in content if b.get("type") == "text")
            stop = res.get("stop_reason")
            if stop == "refusal":
                return reply.strip() or self.t("refused")
            if stop != "tool_use":
                break
            results = []
            for b in content:
                if b.get("type") == "tool_use":
                    results.append({"type": "tool_result", "tool_use_id": b["id"],
                                    "content": self._run_tool(b["name"], b.get("input") or {},
                                                              on_status)[:6000]})
            body["messages"] = body["messages"] + [
                {"role": "assistant", "content": content},   # giữ nguyên mọi khối trả về
                {"role": "user", "content": results}]
        return reply.strip()

    def _call_ai(self, system, msgs, query, on_token=None, on_status=None, stop=None,
                 image=None):
        """Gọi AI; tự chuyển PC -> điện thoại -> Claude khi máy tính không phản hồi."""
        d = self.d
        on_token = on_token or (lambda t: None)
        on_status = on_status or (lambda t: None)
        if d["ai"] == "claude":
            return self._claude(system, msgs, image, on_status)
        url, model, note = d["ollama_url"], d["ollama_model"], ""
        if self.on_pc() and not self._reachable(url):
            if d.get("phone_model") and self._reachable(DEFAULT_OLLAMA_URL, 1.5):
                url, model, note = DEFAULT_OLLAMA_URL, d["phone_model"], self.t("fallback_phone")
            elif d.get("api_key") and not self.over_budget():
                on_status(self.t("fallback_claude"))
                return self.t("fallback_claude") + "\n" + self._claude(system, msgs, image,
                                                                        on_status)
        if note:
            on_status(note)
        out = self._ollama(url, model, system, msgs, query, on_token, on_status, stop, image)
        return (note + "\n" + out) if note else out

    # ---------------- tài liệu (hỏi đáp PDF/Word/TXT/Excel)
    def load_doc(self, path, name):
        ext = os.path.splitext(name.lower())[1]
        if ext == ".pdf":
            from pypdf import PdfReader
            text = "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)
        elif ext == ".docx":
            import zipfile
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            text = unescape(re.sub(r"<[^>]+>", "", xml))
        elif ext in (".xlsx", ".xlsm"):
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            rows = []
            for ws in wb.worksheets:
                rows.append(f"[{ws.title}]")
                for row in ws.iter_rows(values_only=True):
                    if any(c is not None for c in row):
                        rows.append(" | ".join("" if c is None else str(c) for c in row))
            text = "\n".join(rows)
        else:
            with open(path, "rb") as f:
                raw = f.read()
            text = raw.decode("utf-8", "replace")
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            raise ValueError("không tìm thấy chữ (có thể là bản scan)")
        self.doc_text, self.d["doc_name"] = text, name
        with open(self.doc_path, "w", encoding="utf-8") as f:
            f.write(text)
        return len(text)

    def doc_context(self, question, limit=7000):
        text = self.doc_text
        if not text:
            return ""
        if len(text) <= limit:
            return text
        size, step = 1400, 1100
        chunks = [text[i:i + size] for i in range(0, len(text), step)]
        words = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 2}
        scored = sorted(range(len(chunks)), key=lambda i: -sum(
            chunks[i].lower().count(w) for w in words))
        keep = sorted(([0] + scored)[:5])           # luôn kèm phần đầu tài liệu
        return "\n...\n".join(chunks[i] for i in dict.fromkeys(keep))

    # Hội thoại (chạy trong luồng phụ)
    def ask_ai(self, text, on_token=None, on_status=None, stop=None):
        history = (self.d["history"] + [{"role": "user", "content": text}])[-20:]
        msgs = [dict(m) for m in history]
        if self.doc_text:
            msgs[-1]["content"] = (f"Tài liệu \"{self.d['doc_name']}\" (các đoạn liên quan):\n"
                                   f"{self.doc_context(text)}\n\nCâu hỏi: {text}")
        image, self.pending_image = self.pending_image, None
        reply = self._call_ai(self._system(), msgs, text, on_token, on_status, stop,
                              image) or "(không có câu trả lời)"
        if not is_tool_line(reply):
            reply = _plain(reply)
        self.d["history"] = history + [{"role": "assistant", "content": reply}]
        return reply

    # Vẽ tranh bằng Stable Diffusion (AUTOMATIC1111 / Forge, chạy với --api --listen)
    def txt2img(self, prompt):
        import base64
        if not self.d.get("pc"):
            raise RuntimeError(self.t("no_server"))
        body = {"prompt": prompt + ", high quality, detailed",
                "negative_prompt": "lowres, blurry, bad anatomy, deformed, watermark, text",
                "steps": 25, "width": 1024, "height": 1024, "cfg_scale": 6.5,
                "sampler_name": "DPM++ 2M", "batch_size": 1}
        req = urllib.request.Request(f"http://{self.d['pc']}:7860/sdapi/v1/txt2img",
                                     json.dumps(body).encode(),
                                     {"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                res = json.load(r)
        except (OSError, ValueError) as e:
            raise RuntimeError(self.t("pc_err", e=e))
        return base64.b64decode(res["images"][0].split(",", 1)[-1])

    # Viết nội dung một lần (cho PDF/Word/Excel), không lưu lịch sử
    def generate(self, prompt, query):
        return self._call_ai(self._system(tools=False),
                             [{"role": "user", "content": prompt}], query)


# ======================================================== giọng nói / voice (Android)
class Voice:
    """Đọc to (TextToSpeech) và nhận giọng nói (RecognizerIntent) trên Android."""
    REQ = 4321

    def __init__(self):
        self.ok = False
        try:
            from jnius import autoclass
            self.autoclass = autoclass
            self.activity = autoclass("org.kivy.android.PythonActivity").mActivity
            self.TTS = autoclass("android.speech.tts.TextToSpeech")
            self.Locale = autoclass("java.util.Locale")
            self.JString = autoclass("java.lang.String")
            self.tts = self.TTS(self.activity, None)
            self.ok = True
        except Exception:
            pass

    def speak(self, text, lang):
        if not self.ok or not text:
            return
        try:
            loc = self.Locale("vi", "VN") if lang == "vi" else self.Locale("en", "US")
            self.tts.setLanguage(loc)
            self.tts.speak(self.JString(text[:3500]), self.TTS.QUEUE_FLUSH, None, "troly")
        except Exception:
            pass

    def stop(self):
        if self.ok:
            try:
                self.tts.stop()
            except Exception:
                pass

    def listen(self, lang, prompt, on_text):
        """Mở hộp thoại nhận giọng nói; trả về False nếu không mở được."""
        if not self.ok:
            return False
        try:
            from android import activity as android_activity
            Intent = self.autoclass("android.content.Intent")
            RI = self.autoclass("android.speech.RecognizerIntent")

            def on_result(req, res, data):
                if req != self.REQ:
                    return
                android_activity.unbind(on_activity_result=on_result)
                if res == -1 and data is not None:  # RESULT_OK
                    found = data.getStringArrayListExtra(RI.EXTRA_RESULTS)
                    if found is not None and found.size() > 0:
                        on_text(found.get(0))

            android_activity.bind(on_activity_result=on_result)
            intent = Intent(RI.ACTION_RECOGNIZE_SPEECH)
            intent.putExtra(RI.EXTRA_LANGUAGE_MODEL, RI.LANGUAGE_MODEL_FREE_FORM)
            intent.putExtra(RI.EXTRA_LANGUAGE, "vi-VN" if lang == "vi" else "en-US")
            intent.putExtra(RI.EXTRA_PROMPT, prompt)
            self.activity.startActivityForResult(intent, self.REQ)
            return True
        except Exception:
            return False


def pick_file(mime, req_code, on_path, cache_dir):
    """Mở trình chọn file Android; sao chép file được chọn vào cache_dir rồi gọi on_path."""
    from jnius import autoclass, cast
    from android import activity as android_activity
    Intent = autoclass("android.content.Intent")
    act = autoclass("org.kivy.android.PythonActivity").mActivity

    def on_result(req, res, data):
        if req != req_code:
            return
        android_activity.unbind(on_activity_result=on_result)
        if res != -1 or data is None or data.getData() is None:
            return
        uri = data.getData()
        resolver = act.getContentResolver()
        name = "file"
        try:
            cur = resolver.query(uri, None, None, None, None)
            if cur is not None and cur.moveToFirst():
                idx = cur.getColumnIndex("_display_name")
                if idx >= 0:
                    name = cur.getString(idx)
                cur.close()
        except Exception:
            pass
        dest = os.path.join(cache_dir, "pick_" + re.sub(r"[^\w.\-]", "_", name))
        ins = resolver.openInputStream(uri)
        outs = autoclass("java.io.FileOutputStream")(dest)
        autoclass("android.os.FileUtils").copy(ins, outs)
        ins.close()
        outs.close()
        on_path(dest, name)

    android_activity.bind(on_activity_result=on_result)
    intent = Intent(Intent.ACTION_GET_CONTENT)
    intent.setType(mime)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    act.startActivityForResult(intent, req_code)


# ======================================================== giao diện / UI (Kivy)
def run_app():
    from kivy.app import App
    from kivy.clock import Clock
    from kivy.core.window import Window
    from kivy.metrics import dp
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.textinput import TextInput
    from kivy.uix.image import Image as KImage

    Window.clearcolor = (0.96, 0.96, 0.97, 1)
    Window.softinput_mode = "below_target"

    class Bubble(Label):
        def __init__(self, text, mine, **kw):
            super().__init__(text=text, markup=False, size_hint_y=None,
                             halign="right" if mine else "left", valign="top",
                             padding=(dp(12), dp(8)), font_size="15sp",
                             color=(1, 1, 1, 1) if mine else (0.1, 0.1, 0.12, 1), **kw)
            from kivy.graphics import Color, RoundedRectangle
            with self.canvas.before:
                Color(*((0.18, 0.42, 0.85, 1) if mine else (1, 1, 1, 1)))
                self._bg = RoundedRectangle(radius=[dp(12)])
            self.bind(width=self._wrap, texture_size=self._resize,
                      pos=self._draw, size=self._draw)

        def _wrap(self, *_):
            self.text_size = (self.width, None)

        def _resize(self, *_):
            self.height = self.texture_size[1]

        def _draw(self, *_):
            self._bg.pos, self._bg.size = self.pos, self.size

    class AssistantApp(App):
        title = "Trợ lý ảo"

        def build(self):
            self.core = Core(self.user_data_dir)
            self.voice = Voice()
            root = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))

            header = Label(text="Trợ lý ảo", size_hint_y=None, height=dp(44),
                           font_size="20sp", bold=True, color=(0.1, 0.1, 0.12, 1))
            root.add_widget(header)

            self.scroll = ScrollView(do_scroll_x=False)
            self.chat = BoxLayout(orientation="vertical", size_hint_y=None,
                                  spacing=dp(8), padding=(0, dp(4)))
            self.chat.bind(minimum_height=self.chat.setter("height"))
            self.scroll.add_widget(self.chat)
            root.add_widget(self.scroll)

            quick = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(4))
            for key, action in (("photo", self.pick_photo), ("file", self.pick_doc),
                                ("notes_btn", lambda: self.send("notes")),
                                ("todos_btn", lambda: self.send("todos")),
                                ("help_btn", lambda: self.send("help"))):
                b = Button(text=self.core.t(key), font_size="14sp", background_normal="",
                           background_color=(0.85, 0.88, 0.95, 1),
                           color=(0.1, 0.1, 0.12, 1))
                b.bind(on_release=lambda _b, a=action: a())
                quick.add_widget(b)
            root.add_widget(quick)

            bar = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
            self.inp = TextInput(hint_text=self.core.t("hint"), multiline=False,
                                 font_size="16sp", padding=(dp(10), dp(14)))
            self.inp.bind(on_text_validate=lambda *_: self.send())
            self.btn = Button(text=self.core.t("send"), size_hint_x=None,
                              width=dp(80), background_normal="",
                              background_color=(0.18, 0.42, 0.85, 1))
            self.btn.bind(on_release=lambda *_: self.on_btn())
            self.stop_ev = None
            self.mic = Button(text=self.core.t("mic"), size_hint_x=None,
                              width=dp(64), background_normal="",
                              background_color=(0.10, 0.62, 0.40, 1))
            self.mic.bind(on_release=lambda *_: self.listen())
            bar.add_widget(self.mic)
            bar.add_widget(self.inp)
            bar.add_widget(self.btn)
            root.add_widget(bar)

            for m in self.core.d.get("history", [])[-10:]:   # hiện lại đoạn chat gần nhất
                if isinstance(m.get("content"), str) and not is_tool_line(m["content"]):
                    self.add(m["content"], m["role"] == "user", speak=False)
            if self.core.d["name"]:
                self.add(self.core.t("welcome", name=self.core.d["name"]), False, speak=False)
            else:
                self.add(self.core.t("ask_name"), False)
            return root

        def add(self, text, mine, speak=True):
            self.chat.add_widget(Bubble(text, mine))
            if not mine and speak and self.core.d.get("voice") \
                    and text != self.core.t("help"):
                self.voice.speak(text, self.core.d["lang"])
            Clock.schedule_once(lambda *_: setattr(self.scroll, "scroll_y", 0), 0.05)

        def send(self, text=None):
            text = (text if text is not None else self.inp.text).strip()
            if not text:
                return
            self.inp.text = ""
            self.voice.stop()
            self.add(text, True)
            cmd, _, arg = text.partition(" ")
            if cmd.lower() == "remind" and self.core.d["name"]:
                self.remind(arg)
                return
            if cmd.lower() in TOOL_CMDS and self.core.d["name"]:
                self.run_tool(cmd.lower(), arg.strip())
                return
            reply, need_ai = self.core.handle(text)
            self.core.save()
            self.inp.hint_text, self.btn.text = self.core.t("hint"), self.core.t("send")
            self.mic.text = self.core.t("mic")
            if reply:
                self.add(reply, False)
            if need_ai:
                self._thinking = Bubble(self.core.t("thinking"), False)
                self.chat.add_widget(self._thinking)
                self.inp.disabled = self.mic.disabled = True
                self.stop_ev = threading.Event()
                self.btn.text = self.core.t("stop")
                self._pending_text = None
                threading.Thread(target=self._ai, args=(text, self.stop_ev),
                                 daemon=True).start()

        def on_btn(self):
            if self.stop_ev is not None:       # đang trả lời -> nút là "Dừng"
                self.stop_ev.set()
            else:
                self.send()

        def _show_live(self, text):
            """Cập nhật bong bóng trả lời khi chữ đang chạy (gọi từ luồng phụ)."""
            first = self._pending_text is None
            self._pending_text = text
            if first:
                Clock.schedule_once(self._flush_live, 0.08)

        def _flush_live(self, *_):
            if self._pending_text is not None and self.stop_ev is not None:
                self._thinking.text = self._pending_text
                self.scroll.scroll_y = 0
            self._pending_text = None

        def _ai(self, text, stop_ev):
            try:
                reply = self.core.ask_ai(text, on_token=self._show_live,
                                         on_status=self._show_live, stop=stop_ev)
                self.core.save()
            except Exception as e:  # mạng, Ollama chưa chạy, key sai...
                reply = self.core.t("ai_err", e=e)
            Clock.schedule_once(lambda *_: self._ai_done(reply))

        def _busy(self, key):
            self._thinking = Bubble(self.core.t(key), False)
            self.chat.add_widget(self._thinking)
            self.btn.disabled = self.inp.disabled = self.mic.disabled = True

        def _ai_done(self, reply):
            self.stop_ev = None
            self.btn.text = self.core.t("send")
            self.chat.remove_widget(self._thinking)  # bỏ bong bóng tạm
            self.btn.disabled = self.inp.disabled = self.mic.disabled = False
            if is_tool_line(reply):           # AI chọn lệnh vẽ / xuất file
                line = reply.strip().split("\n")[0].strip("` ")
                cmd, _, arg = line.partition(" ")
                self.run_tool(cmd.lower(), arg.strip())
                return
            self.last_answer = reply
            self.add(reply, False)

        # ---------------- vẽ / xuất file
        def out_dir(self):
            if getattr(self, "_out", None):
                return self._out
            for d in ("/storage/emulated/0/Download/TroLyAo",
                      os.path.join(self.user_data_dir, "exports")):
                try:
                    os.makedirs(d, exist_ok=True)
                    test = os.path.join(d, ".test")
                    open(test, "w").close()
                    os.remove(test)
                    self._out = d
                    return d
                except OSError:
                    continue
            self._out = self.user_data_dir
            return self._out

        def add_image(self, path):
            img = KImage(source=path, size_hint_y=None, height=dp(260),
                         fit_mode="contain", nocache=True)
            self.chat.add_widget(img)
            Clock.schedule_once(lambda *_: setattr(self.scroll, "scroll_y", 0), 0.05)

        def run_tool(self, cmd, arg):
            self._busy("drawing" if cmd == "image" else "working")
            threading.Thread(target=self._tool_thread, args=(cmd, arg), daemon=True).start()

        def _tool_thread(self, cmd, arg):
            try:
                text, image, file = self._tool(cmd, arg)
            except Exception as e:
                text, image, file = self.core.t("tool_err", e=e), None, None
            Clock.schedule_once(lambda *_: self._tool_done(text, image, file))

        def _tool_done(self, text, image, file):
            self.chat.remove_widget(self._thinking)
            self.btn.disabled = self.inp.disabled = self.mic.disabled = False
            if image:
                self.add_image(image)
            if text:
                self.add(text, False)

        def _tool(self, cmd, arg):
            import tools
            out, core = self.out_dir(), self.core
            if cmd == "plot":
                exprs, a, b = tools.parse_plot(arg)
                path = tools.plot_functions(exprs, a, b, out)
                fs = [tools.compile_expr(e) for e in exprs]
                rows = [["x"] + ["y = " + e for e in exprs]]
                for i in range(21):
                    x = a + (b - a) * i / 20
                    row = [round(x, 4)]
                    for f in fs:
                        try:
                            row.append(round(float(f(x)), 6))
                        except Exception:
                            row.append("")
                    rows.append(row)
                self.last_image, self.last_rows = path, rows
                return "y = " + "; y = ".join(exprs) + f"  (x từ {a:g} đến {b:g})", path, None
            if cmd in ("bar", "pie"):
                title, labels, values = tools.parse_data(arg)
                maker = tools.bar_chart if cmd == "bar" else tools.pie_chart
                path = maker(title, labels, values, out)
                self.last_image = path
                self.last_rows = [["Mục", "Giá trị"]] + [[l, v] for l, v in zip(labels, values)]
                return title or None, path, None
            if cmd in ("flow", "cycle"):
                title, steps = tools.parse_flow(arg)
                path = tools.flow_diagram(title, steps, out, cycle=cmd == "cycle")
                self.last_image = path
                self.last_rows = [["Bước", "Nội dung"]] + [[i + 1, st] for i, st in enumerate(steps)]
                return None, path, None
            if cmd == "image":
                prompt = arg or "a beautiful landscape"
                if not prompt.isascii() and core.d["ai"] != "off":
                    try:
                        prompt = core.generate(
                            "Translate this picture request into one short English prompt for "
                            "Stable Diffusion (only the prompt, no quotes): " + prompt,
                            "").strip().strip('"') or prompt
                    except Exception:
                        pass
                data = core.txt2img(prompt)
                path = os.path.join(out, f"tranh_{datetime.now():%Y%m%d_%H%M%S}.png")
                with open(path, "wb") as fh:
                    fh.write(data)
                self.last_image = path
                return core.t("img_saved", p=_nice(path)), path, None
            if cmd == "chem":
                path, info = tools.chem_image(arg, out, core.fetch)
                self.last_image = path
                return info or arg, path, None
            # ---- xuất file
            topic = arg or "Tài liệu"
            images = [self.last_image] if getattr(self, "last_image", None) else []
            has_ai = core.d["ai"] != "off"
            if cmd in ("pdf", "word"):
                if has_ai and arg:
                    content = core.generate(
                        f"Viết nội dung cho một tài liệu dạng infographic về: {topic}. "
                        "Gồm 3 đến 5 mục. Mỗi mục có một dòng tiêu đề ngắn kết thúc bằng "
                        "dấu ':' và vài gạch đầu dòng ngắn bắt đầu bằng '- '. "
                        "Chỉ văn bản thuần, không Markdown.", topic)
                    content = _plain(content)
                else:
                    content = getattr(self, "last_answer", "") or topic
                fn = tools.export_pdf if cmd == "pdf" else tools.export_docx
                path = fn(out, topic, content, images)
                return core.t("file_saved", p=_nice(path)), None, path
            if cmd == "excel":
                rows = []
                if has_ai and arg:
                    table = core.generate(
                        f"Tạo bảng dữ liệu về: {topic}. Trả lời CHỈ bằng các dòng dạng "
                        "'cột 1 | cột 2 | cột 3', dòng đầu là tên cột, tối đa 30 dòng, "
                        "không giải thích.", topic)
                    rows = tools.parse_table(table)
                if not rows:
                    rows = getattr(self, "last_rows", None) or [["Nội dung"], [topic]]
                path = tools.export_xlsx(out, topic, rows, images[0] if images else None)
                return core.t("file_saved", p=_nice(path)), None, path
            raise ValueError(cmd)

        # ---------------- ảnh & tài liệu
        def pick_photo(self):
            try:
                pick_file("image/*", 5001, lambda p, n: Clock.schedule_once(
                    lambda *_: self._photo_picked(p)), self.user_data_dir)
            except Exception:
                self.add(self.core.t("pick_err"), False, speak=False)

        def _photo_picked(self, path):
            import base64
            import io
            from PIL import Image as PImage
            try:
                im = PImage.open(path).convert("RGB")
                im.thumbnail((1024, 1024))
                small = os.path.join(self.user_data_dir, "anh_gui.jpg")
                im.save(small, "JPEG", quality=85)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=85)
                self.core.pending_image = base64.b64encode(buf.getvalue()).decode()
                self.add_image(small)
                self.add(self.core.t("img_attached"), False)
            except Exception as e:
                self.add(self.core.t("doc_err", e=e), False, speak=False)

        def pick_doc(self):
            try:
                pick_file("*/*", 5002, lambda p, n: Clock.schedule_once(
                    lambda *_: self._doc_picked(p, n)), self.user_data_dir)
            except Exception:
                self.add(self.core.t("pick_err"), False, speak=False)

        def _doc_picked(self, path, name):
            self._busy("doc_loading")

            def work():
                try:
                    n = self.core.load_doc(path, name)
                    self.core.save()
                    msg = self.core.t("doc_loaded", n=name, c=n)
                except Exception as e:
                    msg = self.core.t("doc_err", e=e)
                Clock.schedule_once(lambda *_: self._tool_done(msg, None, None))
            threading.Thread(target=work, daemon=True).start()

        def listen(self):
            self.voice.stop()
            ok = self.voice.listen(
                self.core.d["lang"], self.core.t("mic_prompt"),
                lambda txt: Clock.schedule_once(lambda *_: self._heard(txt)))
            if not ok:
                self.add(self.core.t("mic_err"), False, speak=False)

        def _heard(self, txt):
            cmd = self.core.check_voice(txt)
            if cmd is None:
                self.add(txt, True)
                self.add(self.core.t("voice_ignored"), False)
            elif cmd:
                self.send(cmd)

        def remind(self, arg):
            mins, _, msg = arg.partition(" ")
            try:
                m = float(mins)
            except ValueError:
                self.add(self.core.t("bad_num"), False)
                return
            when = (datetime.now() + timedelta(minutes=m)).strftime("%H:%M")
            Clock.schedule_once(
                lambda *_: self.add(self.core.t("remind_fire", msg=msg or "..."), False),
                m * 60)
            self.add(self.core.t("remind_set", t=when), False)

        def on_pause(self):
            self.core.save()
            return True

        def on_stop(self):
            self.voice.stop()

    AssistantApp().run()


if __name__ == "__main__":
    run_app()
