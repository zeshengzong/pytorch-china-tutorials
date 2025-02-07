"""
通过区域编译减少 torch.compile 冷启动编译时间
============================================================================

**作者:** `Animesh Jain <https://github.com/anijain2305>`_

随着深度学习模型变得越来越大，这些模型的编译时间也会增加。这种延长的编译时间可能会增加
推理服务的启动时间或大规模训练中的资源浪费。本教程展示了一个通过选择编译模型的重复区域
而不是整个模型来减少冷启动编译时间的示例。

先决条件
----------------

* Pytorch 2.5 或更高版本

设置
-----
在开始之前，需要先安装 `torch`。



.. code-block:: sh

   pip install torch

.. note::
   此功能从 2.5 版本开始可用。如果您使用的是 2.4 版本，可以启用配置标志 
   ``torch._dynamo.config.inline_inbuilt_nn_modules=True`` 以防止区域编译期间的重新编译。
   在 2.5 版本中，此标志默认启用。
"""

from time import perf_counter

######################################################################
# 步骤
# -----
#
# 在本教程中，我们将遵循以下步骤：
#
# 1. 导入所有必要的库。
# 2. 定义并初始化一个具有重复区域的神经网络。
# 3. 理解完整模型和区域编译之间的区别。
# 4. 测量完整模型和区域编译的编译时间。
#
# 首先，让我们导入加载数据所需的库：

import torch
import torch.nn as nn


##########################################################
# 接下来，让我们定义并初始化一个具有重复区域的神经网络。
#
# 通常，神经网络由重复的层组成。例如，一个大型语言模型由许多 Transformer 块组成。在本教程中，
# 我们将使用 ``nn.Module`` 类创建一个 ``Layer`` 作为重复区域的代理。
# 然后，我们将创建一个由 64 个 ``Layer`` 类实例组成的 ``Model``。
#
class Layer(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.linear1 = torch.nn.Linear(10, 10)
        self.relu1 = torch.nn.ReLU()
        self.linear2 = torch.nn.Linear(10, 10)
        self.relu2 = torch.nn.ReLU()

    def forward(self, x):
        a = self.linear1(x)
        a = self.relu1(a)
        a = torch.sigmoid(a)
        b = self.linear2(a)
        b = self.relu2(b)
        return b


class Model(torch.nn.Module):
    def __init__(self, apply_regional_compilation):
        super().__init__()
        self.linear = torch.nn.Linear(10, 10)
        # 仅对重复的层应用编译。
        if apply_regional_compilation:
            self.layers = torch.nn.ModuleList(
                [torch.compile(Layer()) for _ in range(64)]
            )
        else:
            self.layers = torch.nn.ModuleList([Layer() for _ in range(64)])

    def forward(self, x):
        # 在区域编译中，self.linear 不在 `torch.compile` 的范围内。
        x = self.linear(x)
        for layer in self.layers:
            x = layer(x)
        return x


####################################################
# 接下来，让我们回顾一下完整模型和区域编译之间的区别。
#
# 在完整模型编译中，整个模型作为一个整体进行编译。这是大多数用户使用 ``torch.compile`` 的常见方法。
# 在这个示例中，我们将 ``torch.compile`` 应用于 ``Model`` 对象。这将有效地内联 64 层，生成一个
# 大的图进行编译。您可以通过运行此教程并设置 ``TORCH_LOGS=graph_code`` 来查看完整的图。
#

model = Model(apply_regional_compilation=False).cuda()
full_compiled_model = torch.compile(model)


###################################################
# 另一方面，区域编译对模型的某个区域进行编译。
# 通过战略性地选择编译模型的重复区域，我们可以编译一个小得多的图，然后将编译后的图用于所有区域。
# 在这个示例中，``torch.compile`` 仅应用于 ``layers``，而不是整个模型。
#

regional_compiled_model = Model(apply_regional_compilation=True).cuda()

#####################################################
# 将编译应用于重复区域而不是整个模型，可以大大节省编译时间。在这里，我们将只编译一个层实例，
# 然后在 ``Model`` 对象中重复使用 64 次。
#
# 请注意，对于重复区域，模型的某些部分可能不会被编译。例如，``Model`` 中的 ``self.linear`` 
# 不在区域编译的范围内。
#
# 还要注意，性能提升和编译时间之间存在权衡。完整模型编译涉及更大的图，并且理论上提供了更多的优化空间。
# 然而，出于实际目的，并且根据模型的不同，我们观察到完整模型和区域编译之间的速度提升差异很小的情况很多。
#

###################################################
# 接下来，让我们测量完整模型和区域编译的编译时间。
#
# ``torch.compile`` 是一个 JIT 编译器，这意味着它在第一次调用时进行编译。在下面的代码中，
# 我们测量第一次调用所花费的总时间。虽然这种方法不精确，但它提供了一个很好的估计，因为大部分时间都花在编译上。


def measure_latency(fn, input):
    # 重置编译器缓存以确保不同运行之间没有重用
    torch.compiler.reset()
    with torch._inductor.utils.fresh_inductor_cache():
        start = perf_counter()
        fn(input)
        torch.cuda.synchronize()
        end = perf_counter()
        return end - start


input = torch.randn(10, 10, device="cuda")
full_model_compilation_latency = measure_latency(full_compiled_model, input)
print(f"Full model compilation time = {full_model_compilation_latency:.2f} seconds")

regional_compilation_latency = measure_latency(regional_compiled_model, input)
print(f"Regional compilation time = {regional_compilation_latency:.2f} seconds")

assert regional_compilation_latency < full_model_compilation_latency

############################################################################
# 结论
# -----------
#
# 本教程展示了如何在模型具有重复区域时控制冷启动编译时间。这种方法需要用户修改以将 `torch.compile` 应用于
# 重复区域，而不是更常用的全模型编译。我们正在不断努力减少冷启动编译时间。