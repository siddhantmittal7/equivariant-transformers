"""
Network architectures for classification and pose prediction in transformer modules.
"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from .coordinates import identity_grid

import matplotlib.pyplot as plt

class TransformerCNN(nn.Module):
    def __init__(self, net, transformer=None, coords=identity_grid, downsample=1):
        """
        """
        super().__init__()
        self.transformer = transformer
        self.net = net
        self.coords = coords
        self.downsample = downsample
    
    def forward(self, x):
        grid_size = (x.shape[-2]//self.downsample, x.shape[-1]//self.downsample)
        grid = self.coords(grid_size, device=x.device)
        grid = grid.unsqueeze(0).expand(x.shape[0], -1, -1, -1)
        if self.transformer is not None:
            tf_out = self.transformer(x, grid_size=grid_size)
            transform = tf_out['transform']
            if type(transform) is list:
                transform = transform[-1]
            grid = transform(grid)
        
        out = F.grid_sample(x, grid)
        out = self.net(out)
        return out
    
    
class SiameseNetwork(nn.Module):
    def __init__(self, net, normalize=True, bias=True):
        super().__init__()
        self.net = net
        self.normalize = normalize
        self.bias = nn.Parameter(torch.tensor(0.)) if bias else None
        
    def forward(self, x1, x2):
        n = x1.shape[0]
        z = self.net(torch.cat([x1, x2]))
        if self.normalize:
            z = z.div(torch.norm(z, dim=-1, keepdim=True))
        logits = torch.bmm(z[:n].unsqueeze(1), z[n:].unsqueeze(2)).view(-1)
        if self.bias is not None:
            logits = logits + self.bias
        return logits
    
    
# =================================================================================
# Helper functions that allow for cyclic (i.e., wrap-around) padding along an axis.
# We use cyclic padding when applying the CNN over coordinate systems that are
# periodic in at least one dimension (e.g., polar and log-polar coordinates).
# =================================================================================
    
def _pad1d(x, pad, mode):
    """1D padding.
    
    Args:
        x (torch.Tensor): input tensor
        pad (int): pad amount
        mode (str): 'constant', 'reflect', 'replicate', or 'cyclic'
    
    Output:
        Padded tensor
    """
    out = x
    if mode == 'cyclic':
        out = _cyclic_pad(out, pad=pad, axis=2)
    elif mode is not None:
        out = F.pad(out, (pad, pad), mode)
    return out


def _pad2d(x, pad, mode):
    """2D padding.
    
    Args:
        x (torch.Tensor): input tensor
        pad (int or (int, int)): pad amount
        mode (str or (str, str)): 'constant', 'reflect', 'replicate', or 'cyclic'
    
    Output:
        Padded tensor
    """
    if type(pad) is int:
        pad = (pad, pad)
    if type(mode) is str:
        mode = (mode, mode)
        
    wmode, hmode = mode
    wpad, hpad = pad
    out = x

    if wmode == 'cyclic':
        out = _cyclic_pad(out, pad=wpad, axis=3)
    elif wmode is not None:
        out = F.pad(out, (wpad, wpad, 0, 0), wmode)

    if hmode == 'cyclic':
        out = _cyclic_pad(out, pad=hpad, axis=2)
    elif hmode is not None:
        out = F.pad(out, (0, 0, hpad, hpad), hmode)

    return out


def _cyclic_pad(x, pad, axis):
    """Cyclic padding.
    
    Args:
        x (torch.Tensor): input tensor
        pad (int or (int, int)): pad amount
        axis (int): axis along which to pad
    
    Output:
        Padded tensor
    """
    if type(pad) is int:
        pad = (pad, pad)
    if pad[0] == 0 and pad[1] == 0:
        return x
    if pad[1] > 0:
        left = x.narrow(axis, 0, pad[1])
    if pad[0] > 0:
        right = x.narrow(axis, x.shape[axis] - pad[0], pad[0])
    if pad[0] == 0:
        return torch.cat([x, left], axis)
    if pad[1] == 0:
        return torch.cat([right, x], axis)
    return torch.cat([right, x, left], axis)
    

# =================================================================================
# ResNet architectures
# Adapted from //github.com/pytorch/vision/blob/master/torchvision/models/resnet.py
# =================================================================================
    
class BasicCNN(nn.Module):
    def __init__(self, 
                 input_channels=1,
                 output_size=10, nf=20,
                 p_dropout=0., 
                 pad_mode=(None, None), 
                 strides=(1, 1, 1),
                 pool=(True, True, False)):
        super().__init__()
        self.input_channels = input_channels
        self.output_size = output_size
        self.nf = nf
        self.p_dropout = p_dropout    
        self.pad_mode = pad_mode
        self.strides = strides  
        self.pool = pool
        
        self.conv1 = nn.Conv2d(input_channels, nf, 3, stride=strides[0], bias=False)
        self.bn1 = nn.BatchNorm2d(nf)
        self.conv2 = nn.Conv2d(nf, nf, 3, stride=strides[1], bias=False)
        self.bn2 = nn.BatchNorm2d(nf)
        self.conv3 = nn.Conv2d(nf, nf, 3, stride=strides[2], bias=False)
        self.bn3 = nn.BatchNorm2d(nf)
        self.conv4 = nn.Conv2d(nf, nf, 3, stride=1, bias=False)
        self.bn4 = nn.BatchNorm2d(nf)
        self.conv5 = nn.Conv2d(nf, nf, 3, stride=1, bias=False)
        self.bn5 = nn.BatchNorm2d(nf)
        self.conv6 = nn.Conv2d(nf, nf, 3, stride=1, bias=False)
        self.bn6 = nn.BatchNorm2d(nf)
        self.conv7 = nn.Conv2d(nf, output_size, 3, stride=1)
    
    def forward(self, x):               
        out = _pad2d(x, 1, self.pad_mode)
        out = F.relu(self.bn1(self.conv1(out)), True)
        if self.pool[0]:
            out = F.avg_pool2d(out, 2, stride=2)

        out = _pad2d(out, 1, self.pad_mode)
        out = F.relu(self.bn2(self.conv2(out)), True)
        if self.pool[1]:
            out = F.avg_pool2d(out, 2, stride=2)
       
        out = _pad2d(out, 1, self.pad_mode)
        out = F.relu(self.bn3(self.conv3(out)), True)     
        if self.pool[2]:
            out = F.avg_pool2d(out, 2, stride=2)
        out = F.dropout(out, self.p_dropout, self.training)
        
        out = _pad2d(out, 1, self.pad_mode)
        out = F.relu(self.bn4(self.conv4(out)), True) 
        
        out = _pad2d(out, 1, self.pad_mode)
        out = F.relu(self.bn5(self.conv5(out)), True) 
       
        out = _pad2d(out, 1, self.pad_mode)
        out = F.relu(self.bn6(self.conv6(out)), True)
        out = F.dropout(out, self.p_dropout, self.training)
        
        out = _pad2d(out, 1, self.pad_mode)
        out = self.conv7(out)
        out, _ = out.view(out.shape[0], self.output_size, -1).max(-1)
        return out
    
    
# =================================================================================
# ResNet architectures
# Adapted from //github.com/pytorch/vision/blob/master/torchvision/models/resnet.py
# =================================================================================
    
def conv3x3(in_planes, out_planes, stride=1):
    """3x3 convolution with padding"""
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                     padding=0, bias=False)


class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, inplanes, planes, stride=1, downsample=None, 
                 p_dropout=0., nonlin=F.relu, pad_fn=F.pad):
        super().__init__()
        self.nonlin = nonlin
        self.pad_fn = pad_fn
        self.p_dropout = p_dropout
        self.conv1 = conv3x3(inplanes, planes, stride)
        self.bn1 = nn.BatchNorm2d(planes)
        self.conv2 = conv3x3(planes, planes)
        self.bn2 = nn.BatchNorm2d(planes)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x
        out = self.pad_fn(x, 1)
        out = self.conv1(out)
        out = self.bn1(out)
        out = self.nonlin(out)
        out = F.dropout(out, self.p_dropout, training=self.training)
        out = self.pad_fn(out, 1)
        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.nonlin(out)
        return out
   
    
class ResNet(nn.Module):
    def __init__(self, block, layers, 
                 output_size=10,
                 output_bias=True,
                 nf=32, 
                 in_channels=3, 
                 in_kernel_size=5,
                 in_stride=1,
                 in_padding=0,
                 nonlin=F.relu,
                 p_dropout=0., 
                 pad_mode=('constant', 'constant')):
        self.inplanes = nf
        super().__init__()
        self.output_size = output_size
        self.output_bias = output_bias
        self.pad_mode = pad_mode
        self.conv1 = nn.Conv2d(
            in_channels, nf, kernel_size=in_kernel_size, 
            stride=in_stride, padding=in_padding, bias=False)
        self.bn1 = nn.BatchNorm2d(nf)
        self.nonlin = nonlin
        self.p_dropout = p_dropout
        
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=0)
        self.layer1 = self._make_layer(block, nf, layers[0])
        self.layer2 = self._make_layer(block, 2*nf, layers[1], stride=2)
        self.layer3 = self._make_layer(block, 4*nf, layers[2], stride=2)
        self.layer4 = self._make_layer(block, 8*nf, layers[3], stride=2)
        self.fc = nn.Linear(8 * nf * block.expansion, output_size, bias=self.output_bias)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

    def _make_layer(self, block, planes, blocks, stride=1):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * block.expansion),
            )

        layers = []
        layers.append(block(self.inplanes, planes, stride, downsample, 
                            nonlin=self.nonlin, 
                            p_dropout=self.p_dropout, 
                            pad_fn=lambda x, pad: _pad2d(x, pad, self.pad_mode)))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes, 
                                nonlin=self.nonlin,
                                p_dropout=self.p_dropout, 
                                pad_fn=lambda x, pad: _pad2d(x, pad, self.pad_mode)))

        return nn.Sequential(*layers)

    def forward(self, x):
        x = _pad2d(x, 2, self.pad_mode)
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.nonlin(x)
        x = _pad2d(x, 1, self.pad_mode)
        x = self.maxpool(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)
        x = x.view(x.shape[0], x.shape[1], -1).mean(-1)
        x = F.dropout(x, self.p_dropout, training=self.training)
        x = self.fc(x)
        return x

    
def resnet10(**kwargs):
    model = ResNet(BasicBlock, [1, 1, 1, 1], **kwargs)
    return model
    

def resnet18(**kwargs):
    model = ResNet(BasicBlock, [2, 2, 2, 2], **kwargs)
    return model


def resnet34(**kwargs):
    model = ResNet(BasicBlock, [3, 4, 6, 3], **kwargs)
    return model
    
    
# =========================================================
# Pose prediction modules
# =========================================================
    
def _centroid(heatmap, step, periodic=False):
    rnge = torch.arange(heatmap.shape[1], dtype=torch.float, device=heatmap.device).mul_(step)
    rnge.add_(-rnge[-1]/2)  # center at 0
        
    if periodic:
        thetas = rnge.mul_(np.pi)
        xs = torch.cos(thetas)
        ys = torch.sin(thetas)
        x_c = heatmap.mv(xs)
        y_c = heatmap.mv(ys)
        return torch.atan2(y_c, x_c).div(np.pi)
    else:        
        return heatmap.mv(rnge)

    
class EquivariantPosePredictor(nn.Module):
    def __init__(self, in_channels, nf,
                 kernel_size=5,
                 strides=(2, 2),
                 periodic_u=False, periodic_v=False,
                 return_u=True, return_v=True,
                 nonlin=lambda x: F.leaky_relu(x, 0.1, True),
                 **kwargs):
        """
        """
        super().__init__()
        self.in_channels = in_channels
        self.nf = nf
        self.strides = strides
        self.kernel_size = kernel_size
        self.nonlin = nonlin              
        
        if not return_u and not return_v:
            raise ValueError('At least one of return_u and return_v must be true.')
        self.return_u = return_u
        self.return_v = return_v
    
        self.periodic_u = periodic_u
        self.periodic_v = periodic_v
        wmode = 'cyclic' if periodic_u else 'constant'
        hmode = 'cyclic' if periodic_v else 'constant'
        self.pad_mode = wmode, hmode
        
        k = kernel_size
        self.conv1 = nn.Conv2d(in_channels, nf, k, stride=strides[0], bias=False)
        self.bn1 = nn.BatchNorm2d(nf)
        self.conv2 = nn.Conv2d(nf, nf, k, stride=strides[1], bias=False)
        self.bn2 = nn.BatchNorm2d(nf)
        self.conv_u = nn.Conv1d(nf, 1, k, stride=1, bias=False)
        self.conv_v = nn.Conv1d(nf, 1, k, stride=1, bias=False)
        self.bias_u = nn.Parameter(torch.tensor(0.))
        self.bias_v = nn.Parameter(torch.tensor(0.))
    
    @staticmethod
    def _forward(x, module, deltas):
        vstride, ustride = module.stride
        vdelta, udelta = deltas
        return module(x), (vdelta*vstride, udelta*ustride)
    
    def forward(self, x):
        vdelta, udelta = 2./(x.shape[2]-1), 2./(x.shape[3]-1)
        
        out = _pad2d(x, (self.conv1.kernel_size[0]//2, self.conv1.kernel_size[1]//2), self.pad_mode)
        out, (vdelta, udelta) = self._forward(out, self.conv1, (vdelta, udelta))
        out = self.nonlin(self.bn1(out))
        
        out = _pad2d(out, (self.conv2.kernel_size[0]//2, self.conv2.kernel_size[1]//2), self.pad_mode)
        out, (vdelta, udelta) = self._forward(out, self.conv2, (vdelta, udelta))
        phi = self.nonlin(self.bn2(out))
        
        if self.return_u:
            out_u, _ = phi.max(2)
            out_u = _pad1d(out_u, self.conv_u.kernel_size[0]//2, self.pad_mode[0])
            out_u = self.conv_u(out_u).squeeze(1)
            heatmap_u = F.softmax(out_u, -1)
            u = _centroid(heatmap_u, udelta, self.periodic_u) + torch.tanh(self.bias_u)
            if not self.return_v:
                return u, heatmap_u
            
        if self.return_v:
            out_v, _ = phi.max(3)
            out_v = _pad1d(out_v, self.conv_v.kernel_size[0]//2, self.pad_mode[1])
            out_v = self.conv_v(out_v).squeeze(1)          
            heatmap_v = F.softmax(out_v, -1)
            v = _centroid(heatmap_v, vdelta, self.periodic_v) + torch.tanh(self.bias_v)
            if not self.return_u:
                return v, heatmap_v
        
        return (u, v), (heatmap_u, heatmap_v)

    
class DirectPosePredictor(nn.Module):
    def __init__(self, in_channels, nf,
                 kernel_size=5,
                 strides=(2, 2),
                 periodic_u=False, periodic_v=False,
                 nonlin=lambda x: F.leaky_relu(x, 0.1, True),
                 num_outputs=1, f_output=torch.tanh,
                 **kwargs):
        """
        """
        super().__init__()
        self.in_channels = in_channels
        self.nf = nf
        self.strides = strides
        self.nonlin = nonlin  
        self.f_output = f_output
        self.kernel_size = kernel_size
        self.num_outputs = num_outputs

        self.periodic_u = periodic_u
        self.periodic_v = periodic_v
        wmode = 'cyclic' if periodic_u else 'constant'
        hmode = 'cyclic' if periodic_v else 'constant'
        self.pad_mode = wmode, hmode
        
        k = kernel_size
        self.conv1 = nn.Conv2d(in_channels, nf, k, stride=strides[0], bias=False)
        self.bn1 = nn.BatchNorm2d(nf)
        self.conv2 = nn.Conv2d(nf, nf, k, stride=strides[1], bias=False)
        self.bn2 = nn.BatchNorm2d(nf)
        self.fc = nn.Linear(nf*k*k, self.num_outputs, bias=True)
    
    def forward(self, x):        
        out = _pad2d(x, (self.conv1.kernel_size[0]//2, self.conv1.kernel_size[1]//2), self.pad_mode)
        out = self.conv1(out)
        out = self.nonlin(self.bn1(out))
        
        out = _pad2d(out, (self.conv2.kernel_size[0]//2, self.conv2.kernel_size[1]//2), self.pad_mode)
        out = self.conv2(out)
        phi = self.nonlin(self.bn2(out))
        
        k = self.kernel_size
        out = F.adaptive_max_pool2d(out, k).view(out.shape[0], self.nf*k*k)
        out = self.f_output(self.fc(out))
        if self.num_outputs == 1:
            return out[:, 0], None  # no heatmap
        return tuple([out[:, i] for i in range(self.num_outputs)]), tuple([None for i in range(self.num_outputs)])
    