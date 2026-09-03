import torch
import torch.nn as nn
import torch.nn.functional as F
from numba import cuda

import upsil.stdlib.ui as ui
import upsil.stdlib.llm as llm
def main():
    window = ui.Window("UpsiL NeuroChat 1.0", 600, 700)
    ai = llm.Model("upsil-gpt-mini")
    def on_message(msg):
        reply = ai.generate(msg)
        window.add_message("🤖 AI: " + reply)

    window.on_submit(on_message)
    window.show()

main()
