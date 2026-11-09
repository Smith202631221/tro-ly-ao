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
import urllib.request
from datetime import datetime, timedelta

API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-5-5"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

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
        "send": "Gửi", "hint": "Nhập tin nhắn...",
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
        "send": "Send", "hint": "Type a message...",
    },
}


# ======================================================== logic (không cần Kivy)
class Core:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "tro_ly_ao.json")
        self.d = {"name": "", "lang": "vi", "notes": [], "todos": [], "facts": {},
                  "history": [], "ai": "off", "api_key": "",
                  "ollama_model": "", "ollama_url": DEFAULT_OLLAMA_URL}
        try:
            with open(self.path, encoding="utf-8") as f:
                self.d.update(json.load(f))
        except (OSError, ValueError):
            pass

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
            d["ollama_model"], d["ai"] = arg, "ollama"
            return self.t("saved") + f" (Ollama: {arg})", False
        if cmd == "ollama" and arg:
            d["ollama_url"] = arg
            return self.t("saved"), False
        if cmd == "key" and arg:
            d["api_key"], d["ai"] = arg, "claude"
            return self.t("saved") + " (Claude API)", False
        if cmd == "ai" and arg in ("ollama", "claude", "off"):
            d["ai"] = arg
            return self.t("saved"), False
        if cmd == "status":
            key = ("..." + d["api_key"][-4:]) if d["api_key"] else "-"
            return (f"AI: {d['ai']}\nOllama model: {d['ollama_model'] or '-'}\n"
                    f"Ollama URL: {d['ollama_url']}\nClaude key: {key}"), False
        if cmd == "clear":
            d["history"] = []
            return self.t("cleared"), False
        if d["ai"] == "off":
            return self.t("no_ai"), False
        return None, True

    def _list(self, items):
        return "\n".join(f"{i}. {x}" for i, x in enumerate(items, 1)) or self.t("empty")

    def _pop(self, items, arg):
        try:
            items.pop(int(arg) - 1)
            return self.t("deleted")
        except (ValueError, IndexError):
            return self.t("bad_num")

    # Gọi AI (chạy trong luồng phụ)
    def ask_ai(self, text):
        d = self.d
        facts = "\n".join(f"- {k}: {v}" for k, v in d["facts"].items()) or "(none)"
        lang = "Trả lời bằng tiếng Việt." if d["lang"] == "vi" else "Reply in English."
        system = (f"You are a friendly, concise personal assistant on the user's "
                  f"Android phone. User's name: {d['name']}. Known facts:\n{facts}\n"
                  f"Now: {datetime.now():%Y-%m-%d %H:%M}. Keep answers short. {lang}")
        history = (d["history"] + [{"role": "user", "content": text}])[-20:]

        if d["ai"] == "ollama":
            body = {"model": d["ollama_model"], "stream": False,
                    "messages": [{"role": "system", "content": system}] + history}
            req = urllib.request.Request(d["ollama_url"], json.dumps(body).encode(),
                                         {"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                reply = json.load(r).get("message", {}).get("content", "")
        else:
            body = {"model": CLAUDE_MODEL, "max_tokens": 1024,
                    "system": system, "messages": history}
            req = urllib.request.Request(API_URL, json.dumps(body).encode(), {
                "x-api-key": d["api_key"], "anthropic-version": "2023-06-01",
                "content-type": "application/json"})
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=90, context=ctx) as r:
                res = json.load(r)
            reply = "".join(b.get("text", "") for b in res.get("content", []))

        d["history"] = history + [{"role": "assistant", "content": reply}]
        return reply


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
            for label, cmd in (("Giờ", "time"), ("Ghi chú", "notes"),
                               ("Việc", "todos"), ("Lệnh", "help")):
                b = Button(text=label, font_size="14sp", background_normal="",
                           background_color=(0.85, 0.88, 0.95, 1),
                           color=(0.1, 0.1, 0.12, 1))
                b.bind(on_release=lambda _b, c=cmd: self.send(c))
                quick.add_widget(b)
            root.add_widget(quick)

            bar = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6))
            self.inp = TextInput(hint_text=self.core.t("hint"), multiline=False,
                                 font_size="16sp", padding=(dp(10), dp(14)))
            self.inp.bind(on_text_validate=lambda *_: self.send())
            self.btn = Button(text=self.core.t("send"), size_hint_x=None,
                              width=dp(80), background_normal="",
                              background_color=(0.18, 0.42, 0.85, 1))
            self.btn.bind(on_release=lambda *_: self.send())
            bar.add_widget(self.inp)
            bar.add_widget(self.btn)
            root.add_widget(bar)

            if self.core.d["name"]:
                self.add(self.core.t("welcome", name=self.core.d["name"]), False)
            else:
                self.add(self.core.t("ask_name"), False)
            return root

        def add(self, text, mine):
            self.chat.add_widget(Bubble(text, mine))
            Clock.schedule_once(lambda *_: setattr(self.scroll, "scroll_y", 0), 0.05)

        def send(self, text=None):
            text = (text if text is not None else self.inp.text).strip()
            if not text:
                return
            self.inp.text = ""
            self.add(text, True)
            cmd, _, arg = text.partition(" ")
            if cmd.lower() == "remind" and self.core.d["name"]:
                self.remind(arg)
                return
            reply, need_ai = self.core.handle(text)
            self.core.save()
            self.inp.hint_text, self.btn.text = self.core.t("hint"), self.core.t("send")
            if reply:
                self.add(reply, False)
            if need_ai:
                self.add(self.core.t("thinking"), False)
                self.btn.disabled = True
                threading.Thread(target=self._ai, args=(text,), daemon=True).start()

        def _ai(self, text):
            try:
                reply = self.core.ask_ai(text)
                self.core.save()
            except Exception as e:  # mạng, Ollama chưa chạy, key sai...
                reply = self.core.t("ai_err", e=e)
            Clock.schedule_once(lambda *_: self._ai_done(reply))

        def _ai_done(self, reply):
            self.chat.remove_widget(self.chat.children[0])  # bỏ "Đang suy nghĩ..."
            self.add(reply, False)
            self.btn.disabled = False

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

    AssistantApp().run()


if __name__ == "__main__":
    run_app()
