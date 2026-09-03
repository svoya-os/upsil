import torch
import torch.nn.functional as F

def forward(x, W):
    result = x @ W
    return result

def main():
    x = torch.randn(32, 768)
    W = torch.randn(768, 768)
    out = forward(x, W)
    print(out.shape)

main()
