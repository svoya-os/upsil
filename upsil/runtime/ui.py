# SPDX-License-Identifier: Apache-2.0
"""ui: a small chat window (tkinter).

    import ui
    import llm
    val window = ui.Window("Chat", 600, 700)
    llm m = llm.Model()
    fun on_message(text) { window.add_message("AI: " + ([m] => text)) }
    window.on_submit(on_message)
    window.show()

The handler runs in a background thread, so the window stays responsive
while a model thinks; ``add_message`` may be called from any thread.
Needs tkinter (``sudo apt install python3-tk``) and a graphical session.
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Optional, Tuple

from ..errors import UpsilError
from ..i18n import tr

__all__ = ["Window"]

_BG, _PANEL, _FG, _INPUT, _ACCENT = "#1e1e1e", "#252526", "#d4d4d4", "#3c3c3c", "#0e639c"


def _tk() -> Tuple[Any, Any]:
    try:
        import tkinter
        from tkinter import scrolledtext
    except ImportError:
        raise UpsilError("tkinter is not installed: sudo apt install python3-tk",
                         "tkinter не установлен: sudo apt install python3-tk") from None
    return tkinter, scrolledtext


class Window:
    def __init__(self, title: str = "UpsiL", width: int = 600, height: int = 700, *, echo: bool = True):
        tk, scrolledtext = _tk()
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise UpsilError(f"No graphical display: ui needs a desktop session ({exc})",
                             f"Нет графического дисплея: ui работает только в графическом сеансе ({exc})") from None
        self.echo = echo
        self._callback: Optional[Callable[[str], Any]] = None
        self._busy = False
        self._queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self._closed = False
        self.root.title(str(title))
        self.root.geometry(f"{int(width)}x{int(height)}")
        self.root.configure(bg=_BG)
        self.history = scrolledtext.ScrolledText(self.root, wrap="word", bg=_PANEL, fg=_FG, borderwidth=0,
                                                 padx=12, pady=12, state="disabled")
        self.history.pack(padx=16, pady=16, fill="both", expand=True)
        bar = tk.Frame(self.root, bg=_BG)
        bar.pack(padx=16, pady=(0, 16), fill="x")
        self.entry = tk.Entry(bar, bg=_INPUT, fg=_FG, insertbackground=_FG, borderwidth=0)
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, ipadx=8)
        self.button = tk.Button(bar, text=tr("Send", "Отправить"), bg=_ACCENT, fg="white", borderwidth=0,
                                command=self._on_send)
        self.button.pack(side="right", padx=(8, 0), ipadx=12, ipady=6)
        self.entry.bind("<Return>", self._on_send)
        self.entry.focus_set()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(50, self._poll)

    # ------------------------------------------------------------------ API
    def add_message(self, text: Any) -> None:
        """Append a message to the conversation (safe from any thread)."""
        from .prelude import show
        self._queue.put(("add", show(text)))
        if threading.current_thread() is threading.main_thread():
            self._drain()

    def on_submit(self, callback: Callable[[str], Any]) -> None:
        """Call ``callback(text)`` when the user sends a message."""
        self._callback = callback

    def show(self) -> None:
        """Open the window and wait until it is closed."""
        self.root.mainloop()

    def close(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            self._queue.put(("close", None))
            return
        if not self._closed:
            self._closed = True
            self.root.destroy()

    # ------------------------------------------------------------------ internals
    def _insert(self, text: str) -> None:
        self.history.configure(state="normal")
        self.history.insert("end", text + "\n\n")
        self.history.configure(state="disabled")
        self.history.see("end")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.button.configure(state="disabled" if busy else "normal",
                              text=tr("Thinking…", "Думаю…") if busy else tr("Send", "Отправить"))

    def _drain(self) -> None:
        while True:
            try:
                kind, value = self._queue.get_nowait()
            except queue.Empty:
                return
            if kind == "add":
                self._insert(value)
            elif kind == "busy":
                self._set_busy(value)
            elif kind == "close":
                self.close()
                return

    def _poll(self) -> None:
        if self._closed:
            return
        self._drain()
        self.root.after(50, self._poll)

    def _on_send(self, event: Any = None) -> str:
        text = self.entry.get().strip()
        if not text or self._busy:
            return "break"
        self.entry.delete(0, "end")
        if self.echo:
            self._insert(tr("You: ", "Вы: ") + text)
        if self._callback is not None:
            self._set_busy(True)
            threading.Thread(target=self._run, args=(text,), daemon=True).start()
        return "break"

    def _run(self, text: str) -> None:
        try:
            self._callback(text)
        except Exception as exc:  # shown in the window instead of killing the thread silently
            self._queue.put(("add", tr("error: ", "ошибка: ") + str(exc)))
        finally:
            self._queue.put(("busy", False))
