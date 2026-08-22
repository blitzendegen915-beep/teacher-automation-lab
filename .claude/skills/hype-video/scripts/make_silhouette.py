#!/usr/bin/env python3
"""実写動画から、人物を黒単色・背景をグリーンバックにしたシルエット素材を作る。

ペルソナ5風の演出で、シルエットからシーンチェンジで実写に戻す用途を想定している。
単純なクロマキーや輝度キーでは芝・空・白線を拾ってノイズだらけになるので、
人物セグメンテーションのモデルで抜く。

方針:
  1. deeplab_v3 で全画面をざっくり見て、人物がどこにいるかを掴む
  2. 人物ごとに切り出し、selfie_multiclass に入れ直す
     （256x256 の入力を1人ぶんに使うので、実質的に解像度が上がる）
  3. 得られたマスクから箱を取り直して、もう一度切り出して精度を上げる
  4. 小片・横スジ・穴を落として、輪郭をなめらかにする
  5. 前後フレームで平均を取り、チラつきを消す

「人として読めること」と「ノイズっぽくないこと」の両立が目的なので、
人らしくない形（極端に横長・小さすぎる）は積極的に捨てる。
"""

import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

try:
    import av
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    sys.exit("pip install av ai-edge-litert scipy pillow numpy を実行してください")


def ffmpeg_bin():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        from shutil import which
        return which("ffmpeg")


# ---------------------------------------------------------------- モデル

class DeepLab:
    """Pascal VOC 21クラス。person は 15。全画面から人物の場所を掴むのに使う。"""

    SIZE = 257
    PERSON = 15

    def __init__(self, path):
        self.it = Interpreter(model_path=path)
        self.it.allocate_tensors()
        self.i = self.it.get_input_details()[0]
        self.o = self.it.get_output_details()[0]

    def prob(self, rgb):
        x = np.asarray(Image.fromarray(rgb).resize((self.SIZE, self.SIZE), Image.BILINEAR),
                       dtype=np.float32) / 127.5 - 1.0
        self.it.set_tensor(self.i['index'], x[None])
        self.it.invoke()
        lg = self.it.get_tensor(self.o['index'])[0]
        e = np.exp(lg - lg.max(-1, keepdims=True))
        return (e / e.sum(-1, keepdims=True))[..., self.PERSON]


class Selfie:
    """人物用の6クラス分割。背景以外をまとめて「人」として扱う。

    1人ぶんを切り出して入れると、256x256 の入力がその人だけに使われるので
    全画面で回すより細部（腕・脚の隙間）がはっきり出る。
    """

    SIZE = 256

    def __init__(self, path):
        self.it = Interpreter(model_path=path)
        self.it.allocate_tensors()
        self.i = self.it.get_input_details()[0]
        self.o = self.it.get_output_details()[0]

    def prob(self, rgb):
        x = np.asarray(Image.fromarray(rgb).resize((self.SIZE, self.SIZE), Image.BILINEAR),
                       dtype=np.float32) / 255.0
        self.it.set_tensor(self.i['index'], x[None])
        self.it.invoke()
        p = self.it.get_tensor(self.o['index'])[0]
        e = np.exp(p - p.max(-1, keepdims=True))
        p = e / e.sum(-1, keepdims=True)
        return 1.0 - p[..., 0]


def upscale(m, w, h):
    return np.asarray(Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8))
                      .resize((w, h), Image.BILINEAR), dtype=np.float32) / 255.0


# ---------------------------------------------------------------- 形の判定

def boxes_from(mask, min_area, merge=0):
    """マスクから人物ごとの外接矩形を取り出す。

    merge を指定すると、その半径だけマスクを膨らませてから連結成分を取る。
    1人の人物が「頭」「胴」「脚」に分裂して検出されることがよくあるので、
    切り出す前にこれで1つの箱にまとめる。分裂したまま別々に切り出すと、
    モデルが体の一部しか見られず、シルエットがバラバラになる。
    """
    if merge > 0:
        # 原寸で膨らませると 1920x1080 に対して大きな構造要素を掛けることになり、
        # ここだけで1フレーム2秒以上かかる。縮小してから膨らませれば結果はほぼ同じで
        # 桁違いに速い。箱を決めるだけの用途なので、この精度で十分。
        sc = 4
        small = ndimage.binary_dilation(mask[::sc, ::sc], disk(max(1, round(merge / sc))))
        lab_s, n = ndimage.label(small)
        lab = np.repeat(np.repeat(lab_s, sc, 0), sc, 1)[:mask.shape[0], :mask.shape[1]]
    else:
        lab, n = ndimage.label(mask)
    out = []
    if n == 0:
        return out
    objs = ndimage.find_objects(lab)
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        ys, xs = sl
        # 面積は膨らませる前のマスクで数える
        area = int(mask[sl][lab[sl] == i].sum())
        if area < min_area:
            continue
        out.append((xs.start, ys.start, xs.stop, ys.stop, area))
    return out


def looks_human(w, h, area, cfg):
    """人らしい形かどうか。横スジや小片を弾くための判定。

    人は「縦長〜だいたい正方形」に収まる。極端に横長のものは
    白線・フェンス・影を拾った誤検出なので落とす。
    """
    if area < cfg.min_area:
        return False
    if h < cfg.min_height:
        return False
    if w > h * cfg.max_aspect:
        return False
    # 外接矩形に対して中身がスカスカすぎるものも誤検出であることが多い
    if area < w * h * cfg.min_fill:
        return False
    return True


def disk(r):
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r


def clean(prob, cfg):
    """確率マップを、人らしい形だけの締まったマスクに落とす。"""
    m = prob > cfg.threshold

    # 穴を埋める（ユニフォームの明るい部分などが抜けるのを防ぐ）
    m = ndimage.binary_fill_holes(m)

    # 人らしくない連結成分を捨てる
    lab, n = ndimage.label(m)
    if n:
        keep = np.zeros(n + 1, bool)
        objs = ndimage.find_objects(lab)
        for i, sl in enumerate(objs, start=1):
            if sl is None:
                continue
            ys, xs = sl
            area = int((lab[sl] == i).sum())
            if looks_human(xs.stop - xs.start, ys.stop - ys.start, area, cfg):
                keep[i] = True
        m = keep[lab]

    # 輪郭をなめらかにする。ぼかしてから閾値を取り直すと、
    # ギザギザだけが取れて形は保たれる
    if cfg.smooth > 0:
        f = ndimage.gaussian_filter(m.astype(np.float32), cfg.smooth)
        m = f > 0.5

    # 細かい出っ張り・欠けを整える
    if cfg.morph > 0:
        st = disk(cfg.morph)
        m = ndimage.binary_closing(m, st)
        m = ndimage.binary_opening(m, st)
        m = ndimage.binary_fill_holes(m)

    return m


# ---------------------------------------------------------------- 1フレーム

def segment_frame(frame, dl, sf, cfg):
    H, W, _ = frame.shape

    # 1) 全画面でざっくり
    coarse = upscale(dl.prob(frame), W, H) > 0.4

    # 2) 人物ごとに切り出して高解像度化。2周して精度を上げる
    prob = np.zeros((H, W), np.float32)
    src_boxes = boxes_from(coarse, cfg.min_area // 4, merge=cfg.merge)

    for _round in range(cfg.rounds):
        if not src_boxes:
            break
        acc = np.zeros((H, W), np.float32)
        for (x0, y0, x1, y1, _a) in src_boxes:
            bw, bh = x1 - x0, y1 - y0
            padx = int(bw * cfg.pad) + 16
            pady = int(bh * cfg.pad) + 16
            X0, Y0 = max(0, x0 - padx), max(0, y0 - pady)
            X1, Y1 = min(W, x1 + padx), min(H, y1 + pady)
            if X1 - X0 < 8 or Y1 - Y0 < 8:
                continue
            pm = upscale(sf.prob(frame[Y0:Y1, X0:X1]), X1 - X0, Y1 - Y0)
            acc[Y0:Y1, X0:X1] = np.maximum(acc[Y0:Y1, X0:X1], pm)
        prob = acc
        # 次の周は、いま得たマスクから箱を取り直す（より締まった箱になる）
        src_boxes = boxes_from(prob > cfg.threshold, cfg.min_area // 2, merge=cfg.merge)

    return prob


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser(description="人物を黒、背景をグリーンバックにしたシルエット素材を作る")
    ap.add_argument("src")
    ap.add_argument("-o", "--out", default="silhouette.mp4")
    ap.add_argument("--models", default="models")
    ap.add_argument("--green", default="0,255,0", help="背景色 R,G,B")
    ap.add_argument("--fg", default="0,0,0", help="人物の色 R,G,B")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--min-area", type=int, default=1200, help="これ未満の面積は捨てる")
    ap.add_argument("--min-height", type=int, default=48, help="これ未満の高さは捨てる")
    ap.add_argument("--max-aspect", type=float, default=2.2, help="横幅が高さのこの倍を超えたら捨てる")
    ap.add_argument("--min-fill", type=float, default=0.12, help="外接矩形に対する充填率の下限")
    ap.add_argument("--smooth", type=float, default=2.0, help="輪郭をなめらかにする強さ")
    ap.add_argument("--morph", type=int, default=3, help="出っ張り・欠けを整える半径")
    ap.add_argument("--pad", type=float, default=0.08, help="切り出しの余白の割合")
    ap.add_argument("--rounds", type=int, default=2, help="切り出し→再切り出しの回数")
    ap.add_argument("--merge", type=int, default=22,
                    help="この半径だけ膨らませて箱をまとめる。頭・胴・脚の分裂を防ぐ")
    ap.add_argument("--temporal", type=int, default=2, help="前後何フレームで平均するか（0で無効）")
    ap.add_argument("--feather", type=float, default=0.7, help="最終的なエッジの柔らかさ(px)")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=0.0, help="0で最後まで")
    ap.add_argument("--crf", type=int, default=12)
    ap.add_argument("--preview", default="", help="指定すると、その秒数のPNGだけ出して終わる（カンマ区切り）")
    cfg = ap.parse_args()

    green = np.array([int(v) for v in cfg.green.split(",")], np.uint8)
    fg = np.array([int(v) for v in cfg.fg.split(",")], np.uint8)

    dl = DeepLab(os.path.join(cfg.models, "deeplab_v3.tflite"))
    sf = Selfie(os.path.join(cfg.models, "selfie_multiclass_256x256.tflite"))

    container = av.open(cfg.src)
    st = container.streams.video[0]
    st.thread_type = "AUTO"
    fps = float(st.average_rate)
    W, H = st.codec_context.width, st.codec_context.height

    # プレビュー: 指定秒だけ処理して PNG を出す
    if cfg.preview:
        times = sorted(float(t) for t in cfg.preview.split(","))
        got, i = [], 0
        for f in container.decode(video=0):
            t = float(f.pts * st.time_base)
            while i < len(times) and t >= times[i]:
                got.append((times[i], f.to_ndarray(format="rgb24")))
                i += 1
            if i >= len(times):
                break
        container.close()
        os.makedirs(os.path.dirname(cfg.out) or ".", exist_ok=True)
        for t, frame in got:
            prob = segment_frame(frame, dl, sf, cfg)
            m = clean(prob, cfg)
            a = m.astype(np.float32)
            if cfg.feather > 0:
                a = ndimage.gaussian_filter(a, cfg.feather)
            out = (green[None, None, :] * (1 - a[..., None]) + fg[None, None, :] * a[..., None])
            Image.fromarray(out.astype(np.uint8)).save(f"{cfg.out}_{t:05.2f}.png")
            print(f"  preview {t:.2f}s -> {cfg.out}_{t:05.2f}.png  人物面積={m.mean()*100:.2f}%")
        return

    FF = ffmpeg_bin()
    proc = subprocess.Popen(
        [FF, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{fps}",
         "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "slow", "-crf", str(cfg.crf),
         "-pix_fmt", "yuv420p", cfg.out],
        stdin=subprocess.PIPE)

    t_end = cfg.start + cfg.duration if cfg.duration > 0 else 1e9
    buf = []                      # 時間方向の平均用
    n_out = 0

    def flush(prob):
        nonlocal n_out
        m = clean(prob, cfg)
        a = m.astype(np.float32)
        if cfg.feather > 0:
            a = ndimage.gaussian_filter(a, cfg.feather)
        out = (green[None, None, :] * (1 - a[..., None]) + fg[None, None, :] * a[..., None])
        proc.stdin.write(out.astype(np.uint8).tobytes())
        n_out += 1
        if n_out % 30 == 0:
            print(f"  {n_out} frames")

    for f in container.decode(video=0):
        t = float(f.pts * st.time_base)
        if t < cfg.start:
            continue
        if t > t_end:
            break
        frame = f.to_ndarray(format="rgb24")
        prob = segment_frame(frame, dl, sf, cfg)

        if cfg.temporal <= 0:
            flush(prob)
            continue
        buf.append(prob)
        k = cfg.temporal * 2 + 1
        if len(buf) > k:
            buf.pop(0)
        if len(buf) == k:
            flush(np.mean(buf, axis=0))

    # 時間平均の端を埋める
    if cfg.temporal > 0 and buf:
        while len(buf) > 1:
            buf.pop(0)
            flush(np.mean(buf, axis=0))

    container.close()
    proc.stdin.close()
    proc.wait()
    print(f"\n完成: {cfg.out}  ({n_out} フレーム)")


if __name__ == "__main__":
    main()
