# SPDX-License-Identifier: Apache-2.0
import importlib.util
import unittest

from fake_modules import fake_torch, modules
from support import UpsilTestCase, lang, run_upl

from upsil.compiler import compile_source
from upsil.errors import UpsilError

HAS_TORCH = importlib.util.find_spec("torch") is not None

NET = """import nn

model Net {
    val hidden: int
    val l1 = nn.Linear(3, hidden)
    val l2 = nn.Linear(hidden, 1)
    var calls = 0

    graph forward(x) {
        calls += 1
        return l2(nn.relu(l1(x)))
    }
}

val net = Net(2)
print(net([1, -2, 4]), net.calls, net.hidden)
"""


class ModelCodegenTest(UpsilTestCase):
    def test_generated_python(self):
        text = compile_source(NET, "net.upl").python_source()
        self.assertIn("from upsil.runtime import nn as _upsil_nn", text)
        self.assertIn("class Net(_upsil_nn.Module):", text)
        self.assertIn("def __init__(self, hidden: int):\n        super().__init__()\n        self.hidden = hidden\n"
                      "        self.l1 = nn.Linear(3, self.hidden)", text)
        self.assertIn("def forward(self, x):\n        self.calls += 1\n        return self.l2(nn.relu(self.l1(x)))", text)

    def test_runs_as_a_module_subclass(self):
        with modules(**fake_torch()):
            self.assertEqual(run_upl(NET), "[6] 1 2\n")

    def test_nn_looks_in_torch_nn_then_functional_then_torch(self):
        with modules(**fake_torch()):
            self.assertEqual(run_upl("import nn\nimport nn.functional as F\n"
                                     "print(nn.relu([-1, 2]), F.relu([3, -3]), nn.tensor([1, 2]), nn.available())"),
                             "[0, 2] [3, 0] [1, 2] true\n")
            import torch
            from upsil.runtime import nn
            self.assertIs(nn.torch, torch)

    def test_missing_torch_is_a_clear_error(self):
        with modules(torch=None):
            with lang("en"), self.assertRaises(UpsilError) as cm:
                run_upl(NET)
            self.assertIn("PyTorch is not installed", str(cm.exception))
            self.assertIn("uv tool install 'upsil[nn]'", str(cm.exception))
            with lang("ru"):
                self.assertIn("PyTorch не установлен", str(cm.exception))
            self.assertEqual(run_upl("import nn\nprint(nn.available())"), "false\n")

    def test_missing_torch_error_points_at_the_model_line(self):
        import traceback
        with modules(torch=None):
            program = compile_source(NET, "net.upl")
            try:
                exec(program.code, {"__name__": "__main__"})
            except UpsilError as exc:
                frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == "net.upl"]
            else:
                self.fail("no error")
        self.assertEqual((frames[-1].lineno, frames[-1].line), (3, "model Net {"))


@unittest.skipUnless(HAS_TORCH, "PyTorch is not installed")
class RealTorchTest(UpsilTestCase):
    def test_training_reduces_the_loss(self):
        src = """import nn
nn.manual_seed(0)
model Line {
    val lin = nn.Linear(1, 1)
    graph forward(x) { return lin(x) }
}
val net = Line()
val opt = nn.optim.SGD(net.parameters(), lr = 0.1)
val xs = nn.tensor([[0.0], [1.0], [2.0], [3.0]])
val ys = xs * 2.0 + 1.0
var first = 0.0
var last = 0.0
for (step in 0..200) {
    opt.zero_grad()
    val loss = nn.mse_loss(net(xs), ys)
    loss.backward()
    opt.step()
    if step == 0 { first = loss.item() }
    last = loss.item()
}
print(last < first / 100)
"""
        self.assertEqual(run_upl(src), "true\n")


if __name__ == "__main__":
    unittest.main()
