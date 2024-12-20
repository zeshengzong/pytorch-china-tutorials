# -*- coding: utf-8 -*-
"""
自动混合精度
*************************
**作者**: `Michael Carilli <https://github.com/mcarilli>`_

`torch.cuda.amp <https://pytorch.org/docs/stable/amp.html>`_ 提供了混合精度的便利方法,
其中一些操作使用 ``torch.float32`` (``float``) 数据类型,而另一些操作使用 ``torch.float16`` (``half``)。
一些操作,如线性层和卷积,在 ``float16`` 或 ``bfloat16`` 下运行速度更快。
而其他操作,如归约操作,通常需要 ``float32`` 的动态范围。混合精度试图将每个操作与其合适的数据类型相匹配,
从而减少网络的运行时间和内存占用。

通常,"自动混合精度训练"同时使用 `torch.autocast <https://pytorch.org/docs/stable/amp.html#torch.autocast>`_ 和
`torch.cuda.amp.GradScaler <https://pytorch.org/docs/stable/amp.html#torch.cuda.amp.GradScaler>`_。

本教程测量了一个简单网络在默认精度下的性能,然后通过添加 ``autocast`` 和 ``GradScaler`` 以混合精度运行相同的网络,提高性能。

您可以下载并运行本教程作为独立的 Python 脚本。唯一的要求是 PyTorch 1.6 或更高版本,以及支持 CUDA 的 GPU。

混合精度主要受益于支持张量核心的架构(Volta、Turing、Ampere)。在这些架构上,本教程应显示显著的(2-3倍)加速。
在较早的架构(Kepler、Maxwell、Pascal)上,您可能会观察到适度的加速。
运行 ``nvidia-smi`` 可以显示您的 GPU 架构。
"""

import torch, time, gc

# 计时工具
start_time = None

def start_timer():
    global start_time
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.reset_max_memory_allocated()
    torch.cuda.synchronize()
    start_time = time.time()

def end_timer_and_print(local_msg):
    torch.cuda.synchronize()
    end_time = time.time()
    print("\n" + local_msg)
    print("Total execution time = {:.3f} sec".format(end_time - start_time))
    print("Max memory used by tensors = {} bytes".format(torch.cuda.max_memory_allocated()))

##########################################################
# 一个简单的网络
# ----------------
# 以下线性层和 ReLU 的序列应该在混合精度下显示加速。

def make_model(in_size, out_size, num_layers):
    layers = []
    for _ in range(num_layers - 1):
        layers.append(torch.nn.Linear(in_size, in_size))
        layers.append(torch.nn.ReLU())
    layers.append(torch.nn.Linear(in_size, out_size))
    return torch.nn.Sequential(*tuple(layers)).cuda()

##########################################################
# ``batch_size``、``in_size``、``out_size`` 和 ``num_layers`` 被选择为足够大的值,以饱和 GPU 工作负载。
# 通常,当 GPU 饱和时,混合精度提供的加速最大。
# 小型网络可能受 CPU 限制,在这种情况下,混合精度不会提高性能。
# 这些大小还被选择为线性层的参与维度是 8 的倍数,以允许在支持张量核心的 GPU 上使用张量核心(见下面的 :ref:`故障排除<troubleshooting>`)。
#
# 练习:改变参与大小,观察混合精度加速的变化。

batch_size = 512 # 尝试,例如 128、256、513。
in_size = 4096
out_size = 4096
num_layers = 3
num_batches = 50
epochs = 3

device = 'cuda' if torch.cuda.is_available() else 'cpu'
torch.set_default_device(device)

# 以默认精度创建数据。
# 下面的默认精度和混合精度试验使用相同的数据。
# 启用混合精度时,您不需要手动更改输入的 ``dtype``。
data = [torch.randn(batch_size, in_size) for _ in range(num_batches)]
targets = [torch.randn(batch_size, out_size) for _ in range(num_batches)]

loss_fn = torch.nn.MSELoss().cuda()

##########################################################
# 默认精度
# -----------------
# 不使用 ``torch.cuda.amp`` 时,以下简单网络以默认精度( ``torch.float32`` )执行所有操作:

net = make_model(in_size, out_size, num_layers)
opt = torch.optim.SGD(net.parameters(), lr=0.001)

start_timer()
for epoch in range(epochs):
    for input, target in zip(data, targets):
        output = net(input)
        loss = loss_fn(output, target)
        loss.backward()
        opt.step()
        opt.zero_grad() # set_to_none=True 这里可以适度提高性能
end_timer_and_print("Default precision:")

##########################################################
# 添加 ``torch.autocast``
# -------------------------
# `torch.autocast <https://pytorch.org/docs/stable/amp.html#autocasting>`_ 的实例
# 作为上下文管理器,允许脚本的某些区域以混合精度运行。
#
# 在这些区域中,CUDA 操作以 ``autocast`` 选择的 ``dtype`` 运行,
# 以提高性能,同时保持精度。
# 有关 ``autocast`` 为每个操作选择的精度以及在什么情况下选择的详细信息,请参阅
# `Autocast 操作参考 <https://pytorch.org/docs/stable/amp.html#autocast-op-reference>`_。

for epoch in range(0): # 0 个 epoch,此部分仅用于说明
    for input, target in zip(data, targets):
        # 在 ``autocast`` 下运行前向传递。
        with torch.autocast(device_type=device, dtype=torch.float16):
            output = net(input)
            # 输出是 float16,因为线性层 ``autocast`` 到 float16。
            assert output.dtype is torch.float16

            loss = loss_fn(output, target)
            # 损失是 float32,因为 ``mse_loss`` 层 ``autocast`` 到 float32。
            assert loss.dtype is torch.float32

        # 在 backward() 之前退出 ``autocast``。
        # 不建议在 ``autocast`` 下进行反向传播。
        # 反向操作以 ``autocast`` 为相应前向操作选择的相同 ``dtype`` 运行。
        loss.backward()
        opt.step()
        opt.zero_grad() # set_to_none=True 这里可以适度提高性能

##########################################################
# 添加 ``GradScaler``
# ---------------------
# `梯度缩放 <https://pytorch.org/docs/stable/amp.html#gradient-scaling>`_
# 有助于防止梯度幅度较小时在混合精度训练中被冲刷为零
# ("下溢")。
#
# `torch.cuda.amp.GradScaler <https://pytorch.org/docs/stable/amp.html#torch.cuda.amp.GradScaler>`_
# 方便地执行梯度缩放的步骤。

# 在收敛运行开始时使用默认参数构造一个 ``scaler``。
# 如果您的网络在默认 ``GradScaler`` 参数下无法收敛,请提交一个 issue。
# 整个收敛运行应该使用相同的 ``GradScaler`` 实例。
# 如果您在同一个脚本中执行多个收敛运行,每个运行应该使用一个专用的新 ``GradScaler`` 实例。``GradScaler`` 实例是轻量级的。
scaler = torch.cuda.amp.GradScaler()

for epoch in range(0): # 0 个 epoch,此部分仅用于说明
    for input, target in zip(data, targets):
        with torch.autocast(device_type=device, dtype=torch.float16):
            output = net(input)
            loss = loss_fn(output, target)

        # 缩放损失。在缩放后的损失上调用 ``backward()`` 以创建缩放后的梯度。
        scaler.scale(loss).backward()

        # ``scaler.step()`` 首先将优化器分配的参数的梯度反缩放。
        # 如果这些梯度不包含 ``inf`` 或 ``NaN``s,则调用 optimizer.step(),
        # 否则跳过 optimizer.step()。
        scaler.step(opt)

        # 更新下一次迭代的缩放比例。
        scaler.update()

        opt.zero_grad() # set_to_none=True 这里可以适度提高性能

##########################################################
# 全部集成: 自动混合精度
# ------------------------------------------
# (以下还演示了 ``enabled`` 参数,这是 ``autocast`` 和 ``GradScaler`` 的一个可选便利参数。
# 如果为 False, ``autocast`` 和 ``GradScaler`` 的调用将成为无操作。
# 这允许在默认精度和混合精度之间切换,而无需使用 if/else 语句。)

use_amp = True

net = make_model(in_size, out_size, num_layers)
opt = torch.optim.SGD(net.parameters(), lr=0.001)
scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

start_timer()
for epoch in range(epochs):
    for input, target in zip(data, targets):
        with torch.autocast(device_type=device, dtype=torch.float16, enabled=use_amp):
            output = net(input)
            loss = loss_fn(output, target)
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
        opt.zero_grad() # set_to_none=True 这里可以适度提高性能
end_timer_and_print("混合精度:")

##########################################################
# 检查/修改梯度(例如,梯度裁剪)
# --------------------------------------------------------
# ``scaler.scale(loss).backward()`` 产生的所有梯度都是缩放过的。
# 如果您希望在 ``backward()`` 和 ``scaler.step(optimizer)`` 之间检查或修改
# 参数的 ``.grad`` 属性,您应该首先使用 
# `scaler.unscale_(optimizer) <https://pytorch.org/docs/stable/amp.html#torch.cuda.amp.GradScaler.unscale_>`_ 对它们进行反缩放。

# 0个epoch,这一部分仅用于说明
for epoch in range(0):  
    for input, target in zip(data, targets):
        # 在 ``autocast`` 下运行前向传播。
        with torch.autocast(device_type=device, dtype=torch.float16):
            output = net(input)
            # output 是 float16 因为线性层会 ``autocast`` 到 float16。
            assert output.dtype is torch.float16

            loss = loss_fn(output, target)
            # loss 是 float32 因为 ``mse_loss`` 层会 ``autocast`` 到 float32。
            assert loss.dtype is torch.float32

        # 在 backward() 之前退出 ``autocast``。
        # 不推荐在 ``autocast`` 下进行反向传播。
        # 反向传播的 ops 在与对应前向传播相同的 ``dtype`` 下运行。
        loss.backward()
        opt.step()
        opt.zero_grad() # set_to_none=True 这里可以略微提高性能

##########################################################
# 保存/恢复
# ----------------
# 要以位级精度保存/恢复启用了 Amp 的运行,请使用
# `scaler.state_dict <https://pytorch.org/docs/stable/amp.html#torch.cuda.amp.GradScaler.state_dict>`_ 和
# `scaler.load_state_dict <https://pytorch.org/docs/stable/amp.html#torch.cuda.amp.GradScaler.load_state_dict>`_。
#
# 保存时,将 ``scaler`` 的状态字典与通常的模型和优化器状态字典一起保存。
# 可以在迭代开始时,任何前向传播之前,或在迭代结束时,在 ``scaler.update()`` 之后执行此操作。

checkpoint = {"model": net.state_dict(),
              "optimizer": opt.state_dict(),
              "scaler": scaler.state_dict()}
# 按需写入检查点,例如:
# torch.save(checkpoint, "filename")

##########################################################
# 恢复时,将 ``scaler`` 的状态字典与模型和优化器状态字典一起加载。
# 按需读取检查点,例如:
#
# .. code-block::
#
#    dev = torch.cuda.current_device()
#    checkpoint = torch.load("filename",
#                            map_location = lambda storage, loc: storage.cuda(dev))
#
net.load_state_dict(checkpoint["model"])
opt.load_state_dict(checkpoint["optimizer"])
scaler.load_state_dict(checkpoint["scaler"])

##########################################################
# 如果检查点是从一个没有使用 Amp 的运行中创建的,而您想恢复训练时使用 Amp,
# 像往常一样从检查点加载模型和优化器状态。检查点不会包含已保存的 ``scaler`` 状态,因此
# 使用一个新的 ``GradScaler`` 实例。
#
# 如果检查点是从一个使用了 Amp 的运行中创建的,而您想恢复训练时不使用 ``Amp``,
# 像往常一样从检查点加载模型和优化器状态,并忽略已保存的 ``scaler`` 状态。

##########################################################
# 推理/评估
# --------------------
# ``autocast`` 可以单独用于包装推理或评估的前向传播。不需要 ``GradScaler``。

##########################################################
# .. _advanced-topics:
#
# 高级主题
# ---------------
# 请参阅 `自动混合精度示例 <https://pytorch.org/docs/stable/notes/amp_examples.html>`_ 以了解高级用例,包括:
#
# * 梯度累积
# * 梯度惩罚/双向反向传播
# * 包含多个模型、优化器或损失的网络
# * 多 GPU (``torch.nn.DataParallel`` 或 ``torch.nn.parallel.DistributedDataParallel``)
# * 自定义自动梯度函数 (``torch.autograd.Function`` 的子类)
#
# 如果在同一个脚本中执行多个收敛运行,每个运行都应该使用一个专用的新 ``GradScaler`` 实例。``GradScaler`` 实例是轻量级的。
#
# 如果您正在使用调度程序注册自定义 C++ op,请参阅
# `调度程序教程 <https://pytorch.org/tutorials/advanced/dispatcher.html#autocast>`_ 中的 `autocast 部分`。

##########################################################
# .. _troubleshooting:
#
# 故障排除
# ---------------
# 使用 Amp 的加速效果微乎其微
# ~~~~~~~~~~~~~~~~~~~~~~~~~
# 1. 您的网络可能无法充分利用 GPU 的计算能力,因此受到 CPU 的限制。Amp 对 GPU 性能的影响将无关紧要。
#
#    * 一个粗略的经验法则是,尽可能增加批量和/或网络大小,直到不会发生内存不足错误。
#    * 尽量避免过多的 CPU-GPU 同步 (``.item()`` 调用或从 CUDA 张量打印值)。
#    * 尽量避免大量小型 CUDA 操作的序列 (如果可能,请将这些操作合并为几个大型 CUDA 操作)。
# 2. 您的网络可能是 GPU 计算密集型的 (大量 ``matmuls``/卷积),但您的 GPU 没有张量核心。
#    在这种情况下,预期加速效果会降低。
# 3. ``matmul`` 的维度不适合张量核心。请确保参与计算的 ``matmuls`` 的大小是 8 的倍数。
#    (对于带有 encoders/decoders 的 NLP 模型,这可能是一个微妙的问题。此外,早期版本的卷积也有类似的尺寸限制,以便使用张量核心,
#    但对于 CuDNN 7.3 及更高版本,不存在此类限制。请参阅 `这里 <https://github.com/NVIDIA/apex/issues/221#issuecomment-478084841>`_ 以获取指导。)
#
# 损失是 inf/NaN
# ~~~~~~~~~~~~~~~
# 首先,检查您的网络是否符合 :ref:`高级用例<advanced-topics>`。
# 另请参阅 `优先使用 binary_cross_entropy_with_logits 而不是 binary_cross_entropy <https://pytorch.org/docs/stable/amp.html#prefer-binary-cross-entropy-with-logits-over-binary-cross-entropy>`_。
#
# 如果您确信您的 Amp 用法是正确的,您可能需要提交一个 issue,但在这样做之前,收集以下信息会很有帮助:
#
# 1. 通过将 ``enabled=False`` 传递给它们的构造函数,分别禁用 ``autocast`` 或 ``GradScaler``,并查看 ``infs``/``NaNs`` 是否仍然存在。
# 2. 如果您怀疑网络的某一部分 (例如,一个复杂的损失函数) 溢出,请在 ``float32`` 中运行该前向区域,
#    并查看 ``infs``/``NaN``s 是否仍然存在。
#    `autocast 文档字符串 <https://pytorch.org/docs/stable/amp.html#torch.autocast>`_ 的最后一个代码片段
#    展示了如何强制子区域在 ``float32`` 中运行 (通过在本地禁用 ``autocast`` 并将子区域的输入转换为 ``float32``)。
#
# 类型不匹配错误 (可能表现为 ``CUDNN_STATUS_BAD_PARAM``)
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# ``Autocast`` 试图涵盖所有可从中受益或需要转换的 ops。
# `获得明确覆盖的 ops <https://pytorch.org/docs/stable/amp.html#autocast-op-reference>`_
# 是根据数值属性选择的,但也基于经验。
# 如果您在启用了 ``autocast`` 的前向区域或随后的反向传播中看到类型不匹配错误,
# 那可能是 ``autocast`` 漏掉了一个 op。
#
# 请提交一个包含错误回溯的 issue。在运行您的脚本之前 ``export TORCH_SHOW_CPP_STACKTRACES=1`` 以提供有关哪个后端 op 失败的详细信息。
