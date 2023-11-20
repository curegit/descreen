import os
import os.path
import pathlib
import glob
import random
import torch
from torch.utils.data import Dataset
from numpy import array, uint16, float32
from numpy.lib.format import open_memmap

import cv2
import numpy as np

def read_image(src):
    x = cv2.imread(src, cv2.IMREAD_COLOR | cv2.IMREAD_ANYDEPTH)
    x = x[:, :, [2, 1, 0]].transpose(2, 0, 1)
    if x.dtype != np.uint16:
        raise RuntimeError()
    return x

class CustomImageArrayDataset(Dataset):
    def __init__(self, npy_dir, input_patch_size):
        super().__init__()
        self.patch_size = input_patch_size
        self.img_dir = pathlib.Path(npy_dir).resolve()
        pattern = os.path.join(glob.escape(str(self.img_dir)), "**", "*" + os.extsep + "npy")
        self.files = glob.glob(pattern, recursive=True)

    def __len__(self):
        return len(self.files)

    def __getitem__(self, idx):
        path = self.files[idx]
        i_array = read_image(path)
        _, height, width = i_array.shape
        j = random.randrange(height - self.patch_size)
        i = random.randrange(width - self.patch_size)
        arr = array(mem_array[:, :, j:j + self.patch_size, i:i + self.patch_size])
        x, y = arr
        return x, y


class CustomImageTensorDataset(Dataset):
    def __init__(self, array_dataset, reduced_padding, device):
        super().__init__()
        self.base_dataset = array_dataset
        self.unpad = reduced_padding
        self.device = device

    def __len__(self):
        return len(self.base_dataset)

    def __getitem__(self, idx):
        x, y = self.base_dataset[idx]
        X = torch.from_numpy((x / (2 ** 16 - 1)).astype(float32))
        Y = torch.from_numpy((y / (2 ** 16 - 1)).astype(float32))
        Y = Y[:, self.unpad:-self.unpad, self.unpad:-self.unpad]
        X = X.to(self.device)
        Y = Y.to(self.device)
        return X, Y
