import tkinter as tk
from tkinter import scrolledtext

class Window:
    def __init__(self, title, width, height):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry(f"{width}x{height}")
        self.root.configure(bg="#1E1E1E") 
        
        self.chat_history = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, bg="#252526", fg="#D4D4D4", 
            font=("Segoe UI", 12), borderwidth=0
        )
        self.chat_history.pack(padx=20, pady=20, fill=tk.BOTH, expand=True)
        
        self.input_frame = tk.Frame(self.root, bg="#1E1E1E")
        self.input_frame.pack(padx=20, pady=(0, 20), fill=tk.X)
        
        self.entry = tk.Entry(
            self.input_frame, font=("Segoe UI", 12), bg="#3C3C3C", 
            fg="#D4D4D4", insertbackground="white", borderwidth=0
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=12, ipadx=10)
        
        self.send_btn = tk.Button(
            self.input_frame, text="Send to UpsiL", bg="#0E639C", 
            fg="white", font=("Segoe UI", 11, "bold"), borderwidth=0, 
            command=self._on_send, cursor="hand2"
        )
        self.send_btn.pack(side=tk.RIGHT, padx=(10, 0), ipadx=20, ipady=8)
        
        self.on_message_callback = None
        self.entry.bind("<Return>", lambda e: self._on_send())
        self.add_message("⚡ UpsiL Engine Initialized. NeuroChat Ready.")

    def add_message(self, text):
        self.chat_history.insert(tk.END, text + "\n\n")
        self.chat_history.see(tk.END)

    def on_submit(self, callback):
        self.on_message_callback = callback

    def _on_send(self):
        msg = self.entry.get()
        if msg.strip() and self.on_message_callback:
            self.entry.delete(0, tk.END)
            self.add_message(f"👤 Вы: {msg}")
            
            # Show a loading indicator
            self.chat_history.insert(tk.END, "🤖 UpsiL: Думаю...\n\n", "loading")
            self.chat_history.see(tk.END)
            
            self.root.after(100, lambda: self._process_msg(msg))
            
    def _process_msg(self, msg):
        self.chat_history.delete("end-3l", "end-1c") # Remove thinking
        self.on_message_callback(msg)

    def show(self):
        self.root.mainloop()
