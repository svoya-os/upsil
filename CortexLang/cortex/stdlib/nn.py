class Linear:
    def __init__(self, in_features, out_features):
        self.in_features = in_features
        self.out_features = out_features
        
    def __call__(self, x):
        return f"[Linear({self.in_features}->{self.out_features}) * {x}]"

class MultiHeadAttention:
    def __init__(self, heads):
        self.heads = heads
        
    def __call__(self, x):
        return f"[Attention(heads={self.heads}) on {x}]"
