import io
import os
import numpy as np
import torch
from hashlib import blake2s
from pathlib import Path
from functools import cache
from itertools import permutations
from collections.abc import Iterator
from numpy import ndarray
from torch import Tensor
from torch.utils.data import Dataset, DataLoader
from descreen.image import load_image, save_image
from descreen.image.halftone import convert as halftonecv
from descreen.image.magick import magick_png, magick_wide_png
from descreen.utilities import once, flatmap
from descreen.utilities.array import unpad
from descreen.utilities.filesys import resolve_path, glob_recursively


class HalftonePairDataset(Dataset[tuple[ndarray, ndarray]]):

    extensions = ["png", "jpg", "jpeg", "jpe", "jp2", "bmp", "dib", "tif", "tiff", "webp", "avif"]

    min_pitch, max_pitch = 2.14, 5.24

    cmyk_angles: list[tuple[int, ...]] = sum([
        list(permutations((15, 45, 90, 75))),
        list(permutations((15, 75, 30, 45))),
        list(permutations((105, 75, 90, 15))),
        list(permutations((165, 45, 90, 105))),
    ], [])

    def __init__(
        self,
        dirpath: str | Path,
        cmyk_profile: str | Path | None,
        patch_size: int,
        reduced_padding: int,
        *,
        augment: bool = False,
        extend=1,
        debug: bool = False,
        debug_dir: str | Path = Path("."),
        save_dir: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.dirpath = resolve_path(dirpath, strict=True)
        self.debug_dir = resolve_path(debug_dir, strict=True)
        self.cmyk_profile = None if cmyk_profile is None else resolve_path(cmyk_profile, strict=True)
        self.reduced_padding = reduced_padding
        self.patch_size = patch_size
        self.debug = debug
        self.augment = augment
        self.save_dir = save_dir
        self.files = flatmap(glob_recursively(dirpath, ext) for ext in self.extensions)
        if len(self.files) < 1:
            print("f")
            raise RuntimeError()
        while len(self.files) < extend:
            print("epoch differ")
            self.files = self.files + self.files

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> tuple[ndarray, ndarray]:
        img = self.load_image_cached(idx)
        assert img.ndim == 3
        assert img.shape[2] == 3
        height, width = img.shape[:2]
        safe_margin = 7
        crop_size = self.patch_size + safe_margin * 2
        assert height >= crop_size
        assert width >= crop_size

        # Random crop
        # left = random.randrange(width - crop_size)
        left = int(torch.randint(width - crop_size, size=(1,)).item())
        # top = random.randrange(height - crop_size
        top = int(torch.randint(height - crop_size, size=(1,)).item())
        right = left + crop_size
        bottom = top + crop_size
        patch = img[top:bottom, left:right, :]

        # Augment (Pre)
        if self.augment:
            ops = [
                lambda x: x,
                lambda x: np.rot90(x, 1, (0, 1)),
                lambda x: np.rot90(x, 2, (0, 1)),
                lambda x: np.rot90(x, 3, (0, 1)),
                lambda x: np.flip(x, 0),
                lambda x: np.flip(x, 1),
                lambda x: np.flip(np.rot90(x, 1, (0, 1)), 0),
                lambda x: np.flip(np.rot90(x, 1, (0, 1)), 1),
            ]
            # patch = random.choice(ops)(patch)
            patch = ops[int(torch.randint(len(ops), size=(1,)).item())](patch)

        # Halftone
        buffer = io.BytesIO()
        save_image(patch, buffer, transposed=False, prefer16=False, compress=False)
        patch_bytes = buffer.getvalue()
        # pitch = random.uniform(self.min_pitch, self.max_pitch)  # ピッチバリエーション
        max_p = (self.max_pitch - self.min_pitch) * min(1.0, (max(width, height) / 5000)) + self.min_pitch
        pitch = float(torch.rand(size=(1,)).item()) * (max_p - self.min_pitch) + self.min_pitch
        theta = float(torch.rand(size=(1,)).item()) * 90
        angles = tuple(a + theta for a in self.cmyk_angles[int(torch.randint(len(self.cmyk_angles), size=(1,)).item())])  # 角度バリエーション
        # angles = tuple(a + theta for a in random.choice(self.cmyk_angles))  # 角度バリエーション
        color_cmds = ["-m", "CMYK", "-o", "CMYK", "-c", "rel", "-T"]
        if self.cmyk_profile is not None:
            color_cmds += ["-C", str(self.cmyk_profile)]
        resampler = "lanczos2"  # random.choice(["linear", "lanczos2"])
        patch_cmyk = halftonecv(patch_bytes, color_cmds + ["-K"])
        halftone_patch_cmyk = halftonecv(patch_cmyk, color_cmds + ["-F", resampler, "-p", f"{pitch:.12f}", "-a", *(f"{a:.12f}" for a in angles)])

        # To RGB
        wide_x = magick_wide_png(halftone_patch_cmyk, relative=True)
        wide_y = magick_wide_png(patch_cmyk, relative=True)

        # Augment (Post)
        # if self.augment:
        #    if random.random() < 0.8:
        #        sigma = random.random() * 0.3 + 0.01
        #        wide_x = magick_png(wide_x, ["-gaussian-blur", f"1x{sigma:.4f}"], png48=True)

        # Debug
        # if self.debug:
        #    self.save_example_pair(idx, wide_x, wide_y)

        # To array
        x = load_image(wide_x, orient=False, assert16=True)
        y = load_image(wide_y, orient=False, assert16=True)
        x = unpad(x, safe_margin)
        y = unpad(y, safe_margin + self.reduced_padding)

        if self.save_dir is not None:
            name = blake2s(wide_x).hexdigest()
            p = resolve_path(self.save_dir, strict=True) / name[:2]
            try:
                os.mkdir(p)
            except FileExistsError:
                pass
            save_image(x, p / f"{name}.x.png", transposed=True, prefer16=True, compress=True)
            save_image(y, p / f"{name}.y.png", transposed=True, prefer16=True, compress=True)

        assert x.shape[1] == x.shape[2] == self.patch_size
        assert y.shape[1] == y.shape[2]
        return x, y

    # @cache
    def load_image_cached(self, idx: int) -> ndarray:
        path = self.files[idx]
        return load_image(path, transpose=False, normalize=False)

    # @once
    def save_example_pair(self, idx: int, x_png: bytes, y_png: bytes) -> None:
        with open(self.debug_dir / f"example-{idx}-x.png", "wb") as fp:
            fp.write(x_png)
        with open(self.debug_dir / f"example-{idx}-y.png", "wb") as fp:
            fp.write(y_png)

    def as_tensor(self):
        return HalftonePairTensorDataset(self)


class CachedHalftonePairDataset(Dataset[tuple[ndarray, ndarray]]):

    def __init__(
        self,
        dirpath: str | Path,
        patch_size: int,
        reduced_padding: int,
    ) -> None:
        super().__init__()
        self.dirpath = resolve_path(dirpath, strict=True)
        # self.debug_dir = resolve_path(debug_dir, strict=True)
        # self.cmyk_profile = None if cmyk_profile is None else resolve_path(cmyk_profile, strict=True)
        self.reduced_padding = reduced_padding
        self.patch_size = patch_size
        # self.debug = debug
        # self.augment = augment
        # self.save_dir = save_dir
        self.files = list(
            zip(
                sorted(glob_recursively(dirpath, "x.png"), key=lambda a: a.stem),
                sorted(glob_recursively(dirpath, "y.png"), key=lambda a: a.stem),
            )
        )
        if len(self.files) < 1:
            print("f")
            raise RuntimeError()
        # while len(self.files) < extend:
        #    print("epoch differ")
        #    self.files = self.files + self.files

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> tuple[ndarray, ndarray]:
        # img = self.load_image_cached(idx)
        # assert img.ndim == 3
        # assert img.shape[2] == 3
        # height, width = img.shape[:2]
        # safe_margin = 7
        # crop_size = self.patch_size + safe_margin * 2
        # assert height >= crop_size
        # assert width >= crop_size

        # Random crop
        # left = random.randrange(width - crop_size)
        # left = int(torch.randint(width - crop_size, size=(1,)).item())
        # top = random.randrange(height - crop_size
        # top = int(torch.randint(height - crop_size, size=(1,)).item())
        # right = left + crop_size
        # bottom = top + crop_size
        # patch = img[top:bottom, left:right, :]

        # To array
        x_p, y_p = self.files[idx]
        x = load_image(x_p, orient=False, assert16=True)
        y = load_image(y_p, orient=False, assert16=True)

        # i_s = (x.shape[2] - self.patch_size) // 2
        # assert (x.shape[2] - self.patch_size) % 2 == 0 and x.shape[2] - self.patch_size >= 0
        # x = x[:, i_s:-i_s, i_s:-i_s]
        # py = x.shape[2] - self.reduced_padding * 2
        # i_y = (y.shape[2] - py) // 2
        # y = y[:, i_y:-i_y, i_y:-i_y]

        return x, y

    def as_tensor(self):
        return HalftonePairTensorDataset(self)


class HalftonePairTensorDataset(Dataset[tuple[Tensor, Tensor]]):
    def __init__(self, base_dataset: HalftonePairDataset) -> None:
        super().__init__()
        self.base = base_dataset

    def __len__(self) -> int:
        return len(self.base)

    def __getitem__(self, idx: int) -> tuple[Tensor, Tensor]:
        x, y = self.base[idx]
        xt = torch.from_numpy(x)
        yt = torch.from_numpy(y)
        return xt, yt


def enumerate_loader[T: tuple[Tensor, ...]](data_loader: DataLoader[T], *, device=None) -> Iterator[tuple[tuple[int, int, int], T]]:
    epoch = 0
    iters = 0
    samples = 0
    while True:
        for batch in data_loader:
            counts = epoch, iters, samples
            n = len(batch[0])
            yield counts, (batch if device is None else tuple(x.to(device, non_blocking=True) for x in batch))
            samples += n
            iters += 1
        epoch += 1
