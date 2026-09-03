import torch
import torch.nn as nn
import torch.nn.functional as F

import cortex.stdlib.nn
class Transformer(nn.Module):
    def __init__(self):
        super().__init__()
        self.attention = nn.Linear(768, 768)
        self.ffn = nn.Linear(768, 3072)
def forward(self, x):
        context = attention(x)
        return ffn(context)

def train_step(epoch):
    if epoch == 0:
        print("Starting training...")
    else:
        print("Epoch " + str(epoch))


def main():
    print("=== Cortex Turing Complete Demo ===")
    config = {"lr": 0.001, "batch_size": 32}
    dataset = ["text1", "text2", "text3"]
    print("Config loaded: " + str(config))
    my_net = Transformer()
    print("Model initialized: " + str(my_net))
    for i in range(0, 3):
        train_step(i)

    is_ready = True
    if is_ready:
        print("Training complete!")


main()
