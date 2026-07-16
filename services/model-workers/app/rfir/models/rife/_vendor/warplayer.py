import threading

import torch

# Local modifications vs upstream (see NOTICE.md): the grid cache is guarded by
# a lock so concurrent inference calls can't race on first population, and grids
# are built on the input tensor's own device instead of a fixed CUDA/CPU one.
backwarp_tenGrid = {}
_grid_lock = threading.Lock()


def warp(tenInput, tenFlow):
    dev = tenFlow.device  # build the grid on the same device as the input tensors
    k = (str(dev), str(tenFlow.size()))
    if k not in backwarp_tenGrid:
        with _grid_lock:
            if k not in backwarp_tenGrid:  # double-checked: another thread may have filled it
                tenHorizontal = torch.linspace(-1.0, 1.0, tenFlow.shape[3], device=dev).view(
                    1, 1, 1, tenFlow.shape[3]).expand(tenFlow.shape[0], -1, tenFlow.shape[2], -1)
                tenVertical = torch.linspace(-1.0, 1.0, tenFlow.shape[2], device=dev).view(
                    1, 1, tenFlow.shape[2], 1).expand(tenFlow.shape[0], -1, -1, tenFlow.shape[3])
                backwarp_tenGrid[k] = torch.cat(
                    [tenHorizontal, tenVertical], 1).to(dev)

    tenFlow = torch.cat([tenFlow[:, 0:1, :, :] / ((tenInput.shape[3] - 1.0) / 2.0),
                         tenFlow[:, 1:2, :, :] / ((tenInput.shape[2] - 1.0) / 2.0)], 1)

    g = (backwarp_tenGrid[k] + tenFlow).permute(0, 2, 3, 1)
    return torch.nn.functional.grid_sample(input=tenInput, grid=g, mode='bilinear', padding_mode='border', align_corners=True)
