"""
使用 Captum 进行模型可解释性
===================================
"""

######################################################################
# Captum 可以帮助您了解数据特征如何影响模型的预测或神经元激活,从而揭示模型的工作原理。
#
# 使用 Captum,您可以统一地应用广泛的最先进的特征归因算法,如 ``Guided GradCam`` 和 ``Integrated Gradients``。
#
# 在本教程中,您将学习如何使用 Captum:
#
# - 将图像分类器的预测归因于相应的图像特征。
# - 可视化归因结果。
#

######################################################################
# 开始之前
# ----------------
#

######################################################################
# 确保在您的活跃 Python 环境中安装了 Captum。Captum 可以在 GitHub 上获取,也可以作为 ``pip`` 包或 ``conda`` 包获取。
# 有关详细说明,请查阅安装指南 https://captum.ai/
#

######################################################################
# 对于模型,我们使用 PyTorch 中的内置图像分类器。Captum 可以揭示样本图像的哪些部分支持了模型做出的某些预测。
#

from io import BytesIO
import requests
import torchvision
from PIL import Image
from torchvision import models, transforms

model = torchvision.models.resnet18(
    weights=models.ResNet18_Weights.IMAGENET1K_V1
).eval()

response = requests.get(
    "https://image.freepik.com/free-photo/two-beautiful-puppies-cat-dog_58409-6024.jpg"
)
img = Image.open(BytesIO(response.content))

center_crop = transforms.Compose(
    [
        transforms.Resize(256),
        transforms.CenterCrop(224),
    ]
)

normalize = transforms.Compose(
    [
        transforms.ToTensor(),  # 将图像转换为值在 0 到 1 之间的张量
        transforms.Normalize(  # 归一化以遵循 0 均值的 ImageNet 像素 RGB 分布
            mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
        ),
    ]
)
input_img = normalize(center_crop(img)).unsqueeze(0)

######################################################################
# 计算归因
# ---------------------
#

######################################################################
# 在模型的前 3 个预测中,类别 208 和 283 分别对应于狗和猫。
#
# 让我们使用 Captum 的 ``Occlusion`` 算法将这些预测归因于输入的相应部分。
#

from captum.attr import Occlusion

occlusion = Occlusion(model)

strides = (3, 9, 9)  # 步长越小,归因越细粒度,但速度越慢
target = (208,)  # ImageNet 中的拉布拉多索引
sliding_window_shapes = (3, 45, 45)  # 选择足以改变对象外观的大小
baselines = 0  # 用于遮挡图像的值。0 对应灰色

attribution_dog = occlusion.attribute(
    input_img,
    strides=strides,
    target=target,
    sliding_window_shapes=sliding_window_shapes,
    baselines=baselines,
)


target = (283,)  # ImageNet 中的波斯猫索引
attribution_cat = occlusion.attribute(
    input_img,
    strides=strides,
    target=target,
    sliding_window_shapes=sliding_window_shapes,
    baselines=0,
)

######################################################################
# 除了 ``Occlusion`` 之外,Captum 还提供了许多算法,如 ``Integrated Gradients``、``Deconvolution``、
# ``GuidedBackprop``、``Guided GradCam``、``DeepLift`` 和 ``GradientShap``。所有这些算法都是 ``Attribution`` 的子类,
# 在初始化时需要将您的模型作为可调用的 ``forward_func``传入,并具有 ``attribute(...)`` 方法,该方法以统一的格式返回归因结果。
#
# 让我们可视化计算出的图像归因结果。
#

######################################################################
# 可视化结果
# -----------------------
#

######################################################################
# Captum 的 ``visualization`` 实用程序提供了开箱即用的方法,用于可视化图像和文本输入的归因结果。
#

import numpy as np
from captum.attr import visualization as viz

# 将计算出的归因张量转换为类似图像的 numpy 数组
attribution_dog = np.transpose(
    attribution_dog.squeeze().cpu().detach().numpy(), (1, 2, 0)
)

vis_types = ["heat_map", "original_image"]
vis_signs = ["all", "all"]  # "positive"、"negative" 或 "all" 以显示两者
# 正归因表示该区域的存在会增加预测分数
# 负归因表示该区域的缺失会增加预测分数

_ = viz.visualize_image_attr_multiple(
    attribution_dog,
    np.array(center_crop(img)),
    vis_types,
    vis_signs,
    ["attribution for dog", "image"],
    show_colorbar=True,
)


attribution_cat = np.transpose(
    attribution_cat.squeeze().cpu().detach().numpy(), (1, 2, 0)
)

_ = viz.visualize_image_attr_multiple(
    attribution_cat,
    np.array(center_crop(img)),
    ["heat_map", "original_image"],
    ["all", "all"],  # 正/负归因或全部
    ["attribution for cat", "image"],
    show_colorbar=True,
)

######################################################################
# 如果您的数据是文本,``visualization.visualize_text()`` 提供了一个专用视图,用于探索输入文本的归因。
# 更多信息请访问 http://captum.ai/tutorials/IMDB_TorchText_Interpret
#

######################################################################
# 最后注意
# -----------
#

######################################################################
# Captum 可以处理 PyTorch 中包括视觉、文本等各种模态的大多数模型类型。使用 Captum 您可以:
# * 将特定输出归因于模型输入,如上所示。
# * 将特定输出归因于隐藏层神经元(参见 Captum API 参考)。
# * 将隐藏层神经元响应归因于模型输入(参见 Captum API 参考)。
#
# 有关支持方法的完整 API 和教程列表,请查阅我们的网站 http://captum.ai
#
# Gilbert Tanner 的另一篇有用文章:
# https://gilberttanner.com/blog/interpreting-pytorch-models-with-captum
#
