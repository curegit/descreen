import sys
import torch
from io import BytesIO
from .image import load_image, save_image, magick_wide_png, magick_srgb_png

import numpy as np

# from .training import model

from .networks.models import DescreenModel
from .networks.models import pull


def main():
    # dest_group = parser.add_mutually_exclusive_group()
    # dest_group.add_argument("-m", "--model", metavar="NAME" action="store_true", help="send output to standard output")
    # dest_group.add_argument("-d", "--ddbin", metavar="FILE", type=nonempty, default=".", help="save output images in DIR directory")
    # dest_group.add_argument("-x", "--onnx", metavar="FILE", type=nonempty, default=".", help="save output images in DIR directory")
    device = "cpu"
    model = DescreenModel.deserialize(sys.argv[1])
    model.to(device)
    model.eval()
    print(model)

    # img = read_uint16_image(sys.argv[3])

    with open(sys.argv[2], "rb") as fp:
        img = load_image(magick_wide_png(fp.read(), relative=True), assert16=True)

    padded, patches, crop = model.patch(img, 512)
    dest = np.ones_like(padded, dtype=np.float32)
    for (j, i), (k, l) in patches:
        print(k)

        x = padded[:, j, i].astype(np.float32)
        t = torch.from_numpy(x).reshape((1, *x.shape)).to(device)
        z = model(t)
        y = z.detach().cpu().numpy()[0]
        print(y.shape)
        dest[:, k, l] = y
    result = dest[:, crop[0], crop[1]]

    buf = BytesIO()
    save_image(result, buf, prefer16=True)
    r = magick_srgb_png(buf.getvalue(), relative=True, prefer48=False)
    with open(sys.argv[3], "wb") as fp:
        fp.write(r)
    # save_wide_gamut_uint16_array_as_srgb(res, sys.argv[4])