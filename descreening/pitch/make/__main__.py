import sys
import random
import itertools
from tempfile import NamedTemporaryFile
from PIL import Image
from descreening.pitch import patch_size, n_samples
from descreening.image import halftone_rgb_image_to_wide_gamut_uint16_array
from descreening.utilities import mkdirs, save_array, build_filepath, relaxed_glob_recursively, eprint
from descreening.config import pitch_range, cmyk_angles, srgb_icc


# ピッチ推定器作成用データセット生成プログラム
if __name__ == "__main__":
    try:
        cmyk_icc = sys.argv[1]
        img_dir = sys.argv[2]
        dest_dir = sys.argv[3]
    except Exception:
        prog = "python3 -m descreening.pitch.make"
        eprint(f"Usage: {prog} CMYK_ICC SRC_DIR DEST_DIR")
        sys.exit(1)
    # 画像データセットを循環リスト化
    extensions = ["png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp"]
    files = sum([relaxed_glob_recursively(img_dir, e) for e in extensions], [])
    sources = itertools.cycle(files)
    # 保存先ディレクトリを作成
    mkdirs(dest_dir)
    # n_samples 個のデータを生成する
    for i in range(n_samples):
        src = next(sources)
        # ピッチと角度をランダムに選択
        min_pitch, max_pitch = pitch_range
        pitch = random.uniform(min_pitch, max_pitch)
        angles = random.choice(cmyk_angles)
        # PNG 用一時ファイルを作成
        with NamedTemporaryFile(dir="./tmp", mode="w+", suffix=".png", delete=False) as tmp_png:
            # ハーフトーン化の処理高速化のため必要な部分のみ切り取り（ハーフトーン化処理のときに端の情報が欲しいので大きめに切り出す）
            p_size = patch_size + 20
            img = Image.open(src)
            if img.mode != "RGB":
                img = img.convert("RGB")
            if img.width < p_size or img.height < p_size:
                raise RuntimeError()
            i = random.randrange(img.width - p_size)
            j = random.randrange(img.height - p_size)
            cropped = img.crop((i, j, i + p_size, j + p_size))
            # ICC プロファイルがなければ、sRGB として保存
            if cropped.info.get("icc_profile") is None:
                with open(srgb_icc, "rb") as fp:
                    icc_bytes = fp.read()
                cropped.info["icc_profile"] = icc_bytes
            cropped.save(tmp_png.name)
            # ハーフトーン化
            array = halftone_rgb_image_to_wide_gamut_uint16_array(tmp_png.name, cmyk_icc, pitch, angles, perceptual=True)
            # 真ん中で切り出し
            j = (array.shape[1] - patch_size) // 2
            i = (array.shape[2] - patch_size) // 2
            cropped_array = array[:, j:j + patch_size, i:i + patch_size]
            # 正解ピッチをファイル名として保存
            save_array(build_filepath(dest_dir, f"{pitch:.14f}", "npy"), cropped_array)
