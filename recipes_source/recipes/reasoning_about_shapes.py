"""
在PyTorch中推理形状
=================================

在使用PyTorch编写模型时,通常会遇到某一层的参数取决于前一层输出的形状的情况。例如,
``nn.Linear``层的``in_features``必须与输入的``size(-1)``相匹配。对于某些层,形状计算涉及复杂的等式,例如卷积运算。

一种解决方法是使用随机输入进行前向传播,但这在内存和计算方面是浪费的。

相反,我们可以使用``meta``设备来确定层的输出形状,而无需实际化任何数据。
"""

import timeit

import torch

t = torch.rand(2, 3, 10, 10, device="meta")
conv = torch.nn.Conv2d(3, 5, 2, device="meta")
start = timeit.default_timer()
out = conv(t)
end = timeit.default_timer()

print(out)
print(f"所需时间: {end-start}")


##########################################################################
# 观察到,由于没有实际化数据,即使传入任意大的输入,用于形状计算的时间也不会显著改变。

t_large = torch.rand(2**10, 3, 2**16, 2**16, device="meta")
start = timeit.default_timer()
out = conv(t_large)
end = timeit.default_timer()

print(out)
print(f"所需时间: {end-start}")


######################################################
# 考虑以下任意网络:

import torch.nn as nn
import torch.nn.functional as F


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 6, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(6, 16, 5)
        self.fc1 = nn.Linear(16 * 5 * 5, 120)
        self.fc2 = nn.Linear(120, 84)
        self.fc3 = nn.Linear(84, 10)

    def forward(self, x):
        x = self.pool(F.relu(self.conv1(x)))
        x = self.pool(F.relu(self.conv2(x)))
        x = torch.flatten(x, 1)  # 展平除批次维度外的所有维度
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)
        return x


###############################################################################
# 我们可以通过为每一层注册一个前向钩子来打印输出的形状,从而查看整个网络中间层的形状。


def fw_hook(module, input, output):
    print(f"{module}的输出形状为{output.shape}。")


# 在此torch.device上下文管理器中创建的任何张量都将在meta设备上。
with torch.device("meta"):
    net = Net()
    inp = torch.randn((1024, 3, 32, 32))

for name, layer in net.named_modules():
    layer.register_forward_hook(fw_hook)

out = net(inp)
