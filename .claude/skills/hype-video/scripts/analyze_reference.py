#!/usr/bin/env python3
"""参考動画を実測して、編集の仕様を割り出す。

映像は再生できないので、代わりに数値とコマ画像に落として読む。
    - カットの切り替わり位置と長さの分布  → カットの速さの設計
    - 音声のBPMと、カットがビートに乗っている割合 → 音ハメしているかどうか
    - 黒レベル・白レベル・彩度・色かぶり     → 色調補正の数値
    - 上下左右の黒帯                       → レターボックスの比率
    - カットごとの代表コマを並べた画像       → 構図・テロップ・被写体を目で見る

使い方:
    python analyze_reference.py 参考.mp4 -o 出力先ディレクトリ

出力:
    analysis.json  機械可読なまとめ
    cuts.txt       カット位置(秒)
    sheet_NN.png   コンタクトシート（これをReadツールで実際に見ること）
    標準出力       日本語のまとめ
"""

import argparse
import json
import os
import subprocess
import sys

MISSING = []
try:
    import numpy as np
except ImportError:
    MISSING.append("numpy")
try:
    import av
except ImportError:
    MISSING.append("av")
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    MISSING.append("pillow")

if MISSING:
    sys.exit(
        "必要なライブラリがありません: " + ", ".join(MISSING) + "\n"
        "次を実行してください:\n"
        "  pip install av librosa imageio-ffmpeg numpy pillow"
    )

# librosa は音声解析にだけ使う。無ければ映像の解析だけ続ける。
try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False


def find_ffmpeg():
    """音声の取り出しに使う ffmpeg を探す。

    Playwright 同梱の ffmpeg は機能を削った版で mp4 を読めないので使わない。
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    from shutil import which
    return which("ffmpeg")


def find_font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------- 映像を1回なめる

def scan_video(path, color_every=10):
    """1回のデコードで、コマ間の変化量と色の統計をまとめて取る。"""
    container = av.open(path)
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"

    diffs, times = [], []
    blacks, whites, means, sats, rgbs = [], [], [], [], []
    rows_acc = cols_acc = None
    prev = None
    n = 0

    for i, frame in enumerate(container.decode(video=0)):
        t = float(frame.pts * stream.time_base) if frame.pts is not None else i / 25.0

        # 変化量：64x36 のグレーに落として差分を取る（速いうえに微ブレに強い）
        small = frame.reformat(width=64, height=36, format="gray").to_ndarray()
        small = small.astype(np.float32) / 255.0
        if prev is not None:
            diffs.append(float(np.abs(small - prev).mean()))
            times.append(t)
        prev = small

        # 色の統計：重いので間引く
        if i % color_every == 0:
            a = frame.to_ndarray(format="rgb24").astype(np.float32) / 255.0
            lum = a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722
            mx, mn = a.max(2), a.min(2)
            sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
            blacks.append(float(np.percentile(lum, 1)))
            whites.append(float(np.percentile(lum, 99)))
            means.append(float(lum.mean()))
            sats.append(float(sat.mean()))
            rgbs.append(a.reshape(-1, 3).mean(0))
            rows_acc = lum.mean(1) if rows_acc is None else rows_acc + lum.mean(1)
            cols_acc = lum.mean(0) if cols_acc is None else cols_acc + lum.mean(0)
            n += 1

    width, height = stream.codec_context.width, stream.codec_context.height
    fps = float(stream.average_rate) if stream.average_rate else 25.0
    duration = float(stream.duration * stream.time_base) if stream.duration else (times[-1] if times else 0.0)
    container.close()

    return dict(
        width=width, height=height, fps=fps, duration=duration,
        diffs=np.array(diffs), times=np.array(times),
        black=float(np.mean(blacks)), white=float(np.mean(whites)),
        mean=float(np.mean(means)), sat=float(np.mean(sats)),
        rgb=np.array(rgbs).mean(0),
        rows=rows_acc / max(n, 1), cols=cols_acc / max(n, 1),
        color_frames=n,
    )


def detect_cuts(diffs, times, sensitivity=1.0, min_gap=0.15):
    """コマ間の変化量が突出したところをカットとみなす。

    固定のしきい値だと、暗い動画や手ブレの多い動画で総崩れになる。
    中央値と MAD（中央絶対偏差）から動的にしきい値を決めると素材を選ばない。
    """
    if len(diffs) == 0:
        return np.array([])
    med = float(np.median(diffs))
    mad = float(np.median(np.abs(diffs - med))) or 1e-6
    thr = med + (6.0 / sensitivity) * mad
    thr = max(thr, 0.04)

    idx = np.where(diffs > thr)[0]
    cuts = []
    for i in idx:
        t = float(times[i])
        # ワイプやフラッシュは数コマにまたがるので、近いものは1つに畳む
        if not cuts or t - cuts[-1] > min_gap:
            cuts.append(t)
    return np.array(cuts), thr


# ---------------------------------------------------------------- 音声

def analyze_audio(path, out_dir):
    if not HAS_LIBROSA:
        return None
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    wav = os.path.join(out_dir, "_audio.wav")
    r = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", path,
         "-vn", "-ac", "1", "-ar", "22050", "-f", "wav", wav],
        capture_output=True,
    )
    if r.returncode != 0 or not os.path.exists(wav):
        return None
    try:
        y, sr = librosa.load(wav, sr=22050)
        onset = librosa.onset.onset_strength(y=y, sr=sr)
        tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, units="time")
        bpm = float(np.atleast_1d(tempo)[0])
        beat_int = float(np.median(np.diff(beats))) if len(beats) > 1 else 0.0

        rms = librosa.feature.rms(y=y)[0]
        t_rms = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
        quiet = rms < rms.mean() * 0.35
        segs, start = [], None
        for i, q in enumerate(quiet):
            if q and start is None:
                start = float(t_rms[i])
            if not q and start is not None:
                if t_rms[i] - start > 0.4:
                    segs.append((round(start, 2), round(float(t_rms[i]), 2)))
                start = None
        if start is not None and t_rms[-1] - start > 0.4:
            segs.append((round(start, 2), round(float(t_rms[-1]), 2)))

        return dict(bpm=bpm, beat_interval=beat_int,
                    first_beat=float(beats[0]) if len(beats) else 0.0,
                    beats=beats, quiet=segs)
    finally:
        if os.path.exists(wav):
            os.remove(wav)


def beat_alignment(cuts, audio, fps):
    """カットがビートのグリッドにどれだけ乗っているかを、偶然の期待値と比べる。

    「乗っている割合」だけ見ても意味がない。細かいグリッドほど偶然当たるので、
    偶然の期待値を必ず併記して、それを大きく超えたときだけ音ハメと判断する。
    """
    if not audio or audio["beat_interval"] <= 0 or len(cuts) == 0:
        return []
    tol = 1.0 / fps  # ±1フレーム
    out = []
    for name, div in (("1拍", 1.0), ("半拍", 0.5), ("1/4拍", 0.25)):
        step = audio["beat_interval"] * div
        grid = np.arange(audio["first_beat"] - 8 * step, float(cuts.max()) + step, step)
        err = np.array([float(np.min(np.abs(grid - c))) for c in cuts])
        hit = float((err < tol).mean())
        chance = min(2 * tol / step, 1.0)
        out.append(dict(grid=name, step=round(step, 3),
                        hit=round(hit * 100, 1), chance=round(chance * 100, 1),
                        verdict="音ハメあり" if hit > chance * 1.6 else "偶然の範囲"))
    return out


# ---------------------------------------------------------------- コンタクトシート

def contact_sheets(path, cuts, out_dir, per_sheet=16, cols=4, tile_w=470, offset=0.15):
    """各カットの代表コマを並べた画像を作る。これを実際に見ないと構図は分からない。"""
    times = sorted(set([0.3] + [round(float(c) + offset, 3) for c in cuts]))
    container = av.open(path)
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"

    grabbed, i = [], 0
    for frame in container.decode(video=0):
        t = float(frame.pts * stream.time_base) if frame.pts is not None else 0.0
        while i < len(times) and t >= times[i]:
            grabbed.append((times[i], frame.to_ndarray(format="rgb24")))
            i += 1
        if i >= len(times):
            break
    container.close()
    if not grabbed:
        return []

    font = find_font(20)
    h, w, _ = grabbed[0][1].shape
    tile_h = int(tile_w * h / w)
    label_h = 26
    made = []
    for s in range((len(grabbed) + per_sheet - 1) // per_sheet):
        chunk = grabbed[s * per_sheet:(s + 1) * per_sheet]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * tile_w, rows * (tile_h + label_h)), (18, 18, 20))
        draw = ImageDraw.Draw(sheet)
        for k, (t, arr) in enumerate(chunk):
            x, y = (k % cols) * tile_w, (k // cols) * (tile_h + label_h)
            sheet.paste(Image.fromarray(arr).resize((tile_w, tile_h), Image.LANCZOS), (x, y))
            draw.text((x + 6, y + tile_h + 3), f"{t:6.2f}s", font=font, fill=(120, 230, 150))
        out = os.path.join(out_dir, f"sheet_{s + 1:02d}.png")
        sheet.save(out)
        made.append(out)
    return made


# ---------------------------------------------------------------- まとめて出力

def main():
    ap = argparse.ArgumentParser(description="参考動画から編集の仕様を実測する")
    ap.add_argument("video")
    ap.add_argument("-o", "--out", default="reference_analysis")
    ap.add_argument("--sensitivity", type=float, default=1.0,
                    help="カット検出の感度。増やすと細かく拾う（既定1.0）")
    ap.add_argument("--no-sheets", action="store_true", help="コンタクトシートを作らない")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    v = scan_video(args.video)
    cuts, thr = detect_cuts(v["diffs"], v["times"], args.sensitivity)
    audio = analyze_audio(args.video, args.out)
    align = beat_alignment(cuts, audio, v["fps"])

    np.savetxt(os.path.join(args.out, "cuts.txt"), cuts, fmt="%.3f")

    lens = np.diff(cuts) if len(cuts) > 1 else np.array([0.0])
    aspect = v["width"] / v["height"]

    # 黒帯：上下左右それぞれ、ほぼ真っ黒な行/列が何px続くか
    def bar(arr):
        c = 0
        for x in arr:
            if x < 0.02:
                c += 1
            else:
                break
        return c
    bars = dict(top=bar(v["rows"]), bottom=bar(v["rows"][::-1]),
                left=bar(v["cols"]), right=bar(v["cols"][::-1]))

    r, g, b = v["rgb"]
    report = dict(
        file=os.path.abspath(args.video),
        width=v["width"], height=v["height"], fps=round(v["fps"], 3),
        duration=round(v["duration"], 2), aspect=round(aspect, 3),
        cut_count=int(len(cuts)),
        cut_per_sec=round(len(cuts) / v["duration"], 3) if v["duration"] else 0,
        cut_len=dict(
            min=round(float(lens.min()), 2), p25=round(float(np.percentile(lens, 25)), 2),
            median=round(float(np.median(lens)), 2), p75=round(float(np.percentile(lens, 75)), 2),
            max=round(float(lens.max()), 2)),
        color=dict(
            black_255=round(v["black"] * 255, 1), white_255=round(v["white"] * 255, 1),
            mean_255=round(v["mean"] * 255, 1), saturation_pct=round(v["sat"] * 100, 1),
            rgb_255=[round(float(r) * 255, 1), round(float(g) * 255, 1), round(float(b) * 255, 1)],
            warm_cool=round(float(r - b) * 255, 1)),
        letterbox=bars,
        audio=(dict(bpm=round(audio["bpm"], 1),
                    beat_sec=round(audio["beat_interval"], 3),
                    beat_frames_60fps=round(audio["beat_interval"] * 60, 1),
                    first_beat=round(audio["first_beat"], 2),
                    quiet_sections=audio["quiet"]) if audio else None),
        beat_alignment=align,
        cut_detect_threshold=round(thr, 4),
    )

    sheets = [] if args.no_sheets else contact_sheets(args.video, cuts, args.out)
    report["sheets"] = sheets

    with open(os.path.join(args.out, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------ 人が読むまとめ
    p = print
    p(f"===== {os.path.basename(args.video)} =====")
    p(f"{v['width']}x{v['height']} / {v['fps']:.2f}fps / {v['duration']:.2f}秒 / 画面比 {aspect:.3f}:1")
    p("")
    p("■ カット")
    p(f"  {len(cuts)}カット（平均 {v['duration'] / max(len(cuts), 1):.2f}秒に1回）")
    cl = report["cut_len"]
    p(f"  長さ: 最短{cl['min']}s / 25%点{cl['p25']}s / 中央{cl['median']}s / 75%点{cl['p75']}s / 最長{cl['max']}s")
    if len(lens) > 1:
        edges = [0, .2, .35, .5, .75, 1.0, 1.5, 2.0, 3.0, 99]
        hist, _ = np.histogram(lens, bins=edges)
        for i, c in enumerate(hist):
            if c:
                p(f"    {edges[i]:>4.2f}〜{edges[i+1]:<5.2f}秒 : {'#' * int(c)} ({c})")
    p("")
    if audio:
        p("■ 音楽")
        p(f"  BPM {audio['bpm']:.1f}（1拍 {audio['beat_interval']:.3f}秒 = 60fpsで {audio['beat_interval']*60:.1f}フレーム）")
        p(f"  最初のビート {audio['first_beat']:.2f}秒")
        p(f"  音が落ちる区間: {', '.join(f'{a}〜{b}s' for a, b in audio['quiet']) or 'なし'}")
        p("  カットがビートに乗っているか（±1フレーム判定）:")
        for a in align:
            p(f"    {a['grid']:>5}グリッド({a['step']}秒): 実測{a['hit']:5.1f}%  偶然なら{a['chance']:5.1f}%  → {a['verdict']}")
    else:
        p("■ 音楽: librosa か ffmpeg が無いため解析なし（pip install librosa imageio-ffmpeg）")
    p("")
    p("■ 色")
    c = report["color"]
    p(f"  黒レベル(下位1%) {c['black_255']:5.1f}/255   ← 0付近なら黒を潰している。15〜25ならフィルム調に持ち上げている")
    p(f"  白レベル(上位1%) {c['white_255']:5.1f}/255   ← 255未満なら白を抑えている")
    p(f"  平均の明るさ     {c['mean_255']:5.1f}/255")
    p(f"  平均の彩度       {c['saturation_pct']:5.1f}%")
    p(f"  色かぶり R-B = {c['warm_cool']:+.1f} → {'暖色寄り' if c['warm_cool'] > 2 else '寒色寄り' if c['warm_cool'] < -2 else 'ほぼ中立'}")
    p("")
    p("■ レターボックス（黒帯）")
    if any(bars.values()):
        p(f"  上{bars['top']}px 下{bars['bottom']}px 左{bars['left']}px 右{bars['right']}px")
        inner = v["height"] - bars["top"] - bars["bottom"]
        p(f"  帯の内側の比率 = {v['width'] / max(inner, 1):.3f}:1")
    else:
        p(f"  帯なし。素材自体が {aspect:.3f}:1 の横長")
        if abs(aspect - 16 / 9) > 0.02:
            need = (1080 - 1920 / aspect) / 2
            p(f"  1920x1080で同じ比率にするなら、上下に約{need:.0f}pxずつ黒帯を入れる")
    p("")
    if sheets:
        p("■ コンタクトシート（必ず画像を開いて中身を見ること）")
        for s in sheets:
            p(f"  {s}")
    p(f"\n{os.path.join(args.out, 'analysis.json')} に全項目を保存しました。")


if __name__ == "__main__":
    main()
