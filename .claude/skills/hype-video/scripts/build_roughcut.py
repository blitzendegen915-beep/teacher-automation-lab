#!/usr/bin/env python3
"""素材フォルダと楽曲から、ハイプ動画のラフカットを自動で組んで書き出す。

手作業でやると数時間かかる「素材を全部見て、使えるところを拾って、
曲の構造に合わせて並べる」までを自動化する。仕上げは AviUtl で詰める前提の
たたき台だが、そのまま見られる程度には仕上げる。

やること:
  1. 素材を1本ずつ解析し、0.5秒ごとに「動きの量・明るさ・ブレの少なさ」を測る
  2. 各クリップから使えそうな見せ場を抜き出して点数をつける
  3. 楽曲の構造（プランJSON）に合わせて、区間ごとに見せ場を割り当てる
  4. 区間ごとにイージングつきの寄り・スロー・色味を掛けて書き出す
  5. つないで、テロップを載せて、曲を乗せる

使い方:
  pip install av numpy pillow imageio-ffmpeg
  python build_roughcut.py --footage 素材フォルダ --music Prime.mp3 \\
      --plan prime_plan.json --out roughcut.mp4

  # チーム名とキャッチコピーを入れる
  python build_roughcut.py ... --title "○○高校ラグビー部" --tagline "ここに一言。"

素材の区間分け:
  素材フォルダに `01_歩き/` `02_準備/` `03_プレー/` `04_衝突/` のように
  数字ではじまるサブフォルダを作ると、その名前で区間に割り当てる（確実）。
  サブフォルダが無ければ、動きの量から自動で振り分ける。
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys

try:
    import numpy as np
    import av
except ImportError:
    sys.exit("pip install av numpy imageio-ffmpeg pillow を実行してください")


def ffmpeg_bin():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        from shutil import which
        exe = which("ffmpeg")
        if not exe:
            sys.exit("ffmpeg が見つかりません。pip install imageio-ffmpeg を実行してください")
        return exe


FF = None
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".MP4", ".MOV")


def find_font():
    for p in ("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
              "C:/Windows/Fonts/meiryob.ttc", "C:/Windows/Fonts/YuGothB.ttc",
              "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"):
        if os.path.exists(p):
            return p
    return None


# ------------------------------------------------------------------ 素材の解析

def analyze_clip(path, win=0.5, max_seconds=None):
    """0.5秒ごとに 動き・明るさ・シャープさ を測って、見せ場の候補を返す。

    低解像度に落として1回デコードするだけなので、素材が多くても現実的な時間で終わる。
    """
    try:
        container = av.open(path)
    except Exception as e:
        return None
    if not container.streams.video:
        container.close()
        return None
    st = container.streams.video[0]
    st.thread_type = "AUTO"
    fps = float(st.average_rate) if st.average_rate else 30.0

    prev = None
    times, motion, bright, sharp = [], [], [], []
    try:
        for i, frame in enumerate(container.decode(video=0)):
            t = float(frame.pts * st.time_base) if frame.pts is not None else i / fps
            if max_seconds and t > max_seconds:
                break
            if i % max(1, int(round(fps * win))) != 0:
                continue
            g = frame.reformat(width=96, height=54, format="gray").to_ndarray().astype(np.float32) / 255.0
            times.append(t)
            bright.append(float(g.mean()))
            # 隣接画素の差 = 輪郭の量。ブレていると小さくなる
            sharp.append(float(np.abs(np.diff(g, axis=1)).mean() + np.abs(np.diff(g, axis=0)).mean()))
            motion.append(0.0 if prev is None else float(np.abs(g - prev).mean()))
            prev = g
    except Exception:
        pass
    dur = float(st.duration * st.time_base) if st.duration else (times[-1] if times else 0.0)
    w, h = st.codec_context.width, st.codec_context.height
    container.close()

    if len(times) < 3:
        return None
    return dict(path=path, fps=fps, duration=dur, width=w, height=h,
                times=np.array(times), motion=np.array(motion),
                bright=np.array(bright), sharp=np.array(sharp))


def score_windows(a, seg=1.2):
    """クリップの中から、使える区間を点数つきで抜き出す。

    点数 = 動き × 輪郭の量。明るすぎ・暗すぎは減点する。
    ブレて輪郭が消えたところを弾くのが目的で、これをやらないと
    振り回しただけのカットばかり拾ってしまう。
    """
    out = []
    n = len(a["times"])
    step = max(1, int(seg / 0.5))
    for i in range(0, n - step, max(1, step // 2)):
        j = min(i + step, n - 1)
        mot = float(a["motion"][i:j].mean())
        shp = float(a["sharp"][i:j].mean())
        brt = float(a["bright"][i:j].mean())
        if brt < 0.06 or brt > 0.94:      # 真っ暗・真っ白は使えない
            continue
        exposure = 1.0 - abs(brt - 0.45) * 1.1
        s = (mot ** 0.6) * (shp ** 0.8) * max(exposure, 0.15)
        out.append(dict(path=a["path"], start=float(a["times"][i]),
                        end=float(a["times"][j]), motion=mot, sharp=shp,
                        bright=brt, score=s))
    return out


# ------------------------------------------------------------------ 区間の割当

SECTION_ALIASES = {
    "歩き": ["歩", "walk", "intro", "導入"],
    "準備": ["準備", "prep", "会議", "装具", "meeting"],
    "溜め": ["溜", "break", "間", "表情"],
    "プレー": ["プレー", "play", "practice", "練習", "ボール"],
    "衝突": ["衝突", "scrum", "スクラム", "impact"],
    "締め": ["締", "end", "outro", "ラスト"],
}


def folder_section(path, footage_root):
    rel = os.path.relpath(path, footage_root)
    parts = rel.split(os.sep)
    if len(parts) < 2:
        return None
    folder = re.sub(r"^[0-9]+[_\-\s]*", "", parts[0]).strip().lower()
    for name, keys in SECTION_ALIASES.items():
        if any(k.lower() in folder for k in keys):
            return name
    return None


def assign(cands, sections, footage_root, seed=7):
    """区間ごとに候補を割り当てる。

    フォルダ分けがあればそれを最優先する。無ければ動きの量で振り分ける。
    映像の中身までは判別できないので、確実にやりたいならフォルダ分けを勧める。
    """
    rng = random.Random(seed)
    by_section = {s["name"]: [] for s in sections}
    foldered = False
    for c in cands:
        sec = folder_section(c["path"], footage_root)
        if sec and sec in by_section:
            by_section[sec].append(c)
            foldered = True

    if not foldered:
        mot = np.array([c["motion"] for c in cands])
        hi, lo = np.percentile(mot, 65), np.percentile(mot, 35)
        for c in cands:
            if c["motion"] >= hi:
                by_section.setdefault("プレー", []).append(c)
            elif c["motion"] <= lo:
                for n in ("歩き", "準備", "溜め", "締め"):
                    if n in by_section:
                        by_section[n].append(c)
            else:
                for n in ("準備", "プレー"):
                    if n in by_section:
                        by_section[n].append(c)
        # 衝突は動きが一番大きいものから
        if "衝突" in by_section:
            by_section["衝突"] = sorted(cands, key=lambda c: -c["motion"])[:12]

    for k in by_section:
        by_section[k].sort(key=lambda c: -c["score"])
        rng.shuffle(by_section[k][:0])   # 上位はそのまま、順序は点数順
    return by_section, foldered


def build_edl(plan, by_section):
    """プランの区間を、実際のカット列に展開する。"""
    edl = []
    used = set()

    def take(pool, want_len):
        for c in pool:
            key = (c["path"], round(c["start"], 1))
            if key in used:
                continue
            if c["end"] - c["start"] < want_len * 0.9:
                continue
            used.add(key)
            return c
        for c in pool:                      # 足りなければ使い回す
            if c["end"] - c["start"] >= want_len * 0.9:
                return c
        return pool[0] if pool else None

    for sec in plan["sections"]:
        pool = by_section.get(sec["name"]) or []
        if not pool:
            continue
        t = sec["start"]
        lo, hi = sec["cut"]
        bursts = list(sec.get("bursts", []))
        while t < sec["end"] - 0.05:
            burst = None
            for b in bursts:
                if b[0] <= t < b[0] + b[1] * b[2]:
                    burst = b
                    break
            if burst:
                dur = burst[1]
            else:
                dur = lo + (hi - lo) * ((len(edl) * 0.618) % 1.0)   # 単調にならないよう散らす
            dur = min(dur, sec["end"] - t)
            if dur < 0.1:
                break
            src_len = dur * sec.get("speed", 1.0)
            c = take(pool, src_len)
            if c is None:
                break
            edl.append(dict(section=sec["name"], t=t, dur=dur,
                            src=c["path"], src_start=c["start"], src_len=src_len,
                            speed=sec.get("speed", 1.0), zoom=sec.get("zoom", 0),
                            curve=sec.get("curve", 0), shake=sec.get("shake", False),
                            black=sec.get("black", False)))
            t += dur
    return edl


# ------------------------------------------------------------------ 書き出し

def ease_expr(curve, dur):
    """crop に渡す、時間 t の進み具合の式。curve>0 でイーズアウト。"""
    p = f"min(t/{dur:.3f},1)"
    if curve > 0:
        a = 1 + abs(curve) / 100 * 3
        return f"(1-pow(1-{p},{a:.2f}))"
    if curve < 0:
        a = 1 + abs(curve) / 100 * 3
        return f"pow({p},{a:.2f})"
    return p


def measure_source(files, ffmpeg_probe_frames=50):
    """素材そのものの明るさを測る。

    色味は「一律にこの数値を掛ける」ではうまくいかない。真昼の順光と夕方では
    出発点がまるで違うので、同じ処理をすると片方が破綻する。
    素材の黒・中間・白がどこにあるかを先に測って、目標値へ寄せる曲線を作る。
    """
    import random
    rng = random.Random(3)
    picks = files if len(files) <= 12 else rng.sample(files, 12)
    lows, mids, highs = [], [], []
    per = max(1, ffmpeg_probe_frames // max(len(picks), 1))
    for f in picks:
        try:
            c = av.open(f)
        except Exception:
            continue
        st = c.streams.video[0]
        st.thread_type = "AUTO"
        n = 0
        try:
            for i, frame in enumerate(c.decode(video=0)):
                if i % 25:
                    continue
                a = frame.reformat(width=320, height=180, format="rgb24").to_ndarray().astype(np.float32) / 255
                lum = a[..., 0] * .2126 + a[..., 1] * .7152 + a[..., 2] * .0722
                lows.append(float(np.percentile(lum, 1)))
                mids.append(float(np.percentile(lum, 50)))
                highs.append(float(np.percentile(lum, 99)))
                n += 1
                if n >= per:
                    break
        except Exception:
            pass
        c.close()
    if not mids:
        return dict(black=0.02, mid=0.45, white=0.98)
    return dict(black=float(np.mean(lows)), mid=float(np.mean(mids)), white=float(np.mean(highs)))


def grade_chain(g, src, bar):
    """素材の実測値を、目標の黒・中間・白へ寄せる曲線を組み立てる。"""
    tb, tw = g["black_lift"], g["white_cap"]
    tm = g.get("mid_target", 0.34)
    sb, sm, sw = src["black"], src["mid"], src["white"]

    # 単調になるよう最低限の間隔を確保する（真っ白／真っ黒な素材で壊れないように）
    sb = min(sb, sm - 0.05)
    sw = max(sw, sm + 0.05)
    pts = [(0.0, tb), (sb, tb + 0.01), (sm, tm), (sw, tw), (1.0, tw)]
    pts = sorted({round(x, 4): y for x, y in pts}.items())
    curves = " ".join(f"{x:.3f}/{y:.3f}" for x, y in pts)

    chain = [
        f"curves=all='{curves}'",
        f"eq=saturation={g['saturation']}:contrast={g['contrast']}",
        f"colorbalance=rs={g['warm']}:bs={-g['warm']}",
    ]
    if g.get("grain"):
        chain.append(f"noise=alls={int(g['grain'])}:allf=t")
    if bar > 0:
        chain.append(f"drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill")
        chain.append(f"drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill")
    return ",".join(chain)


def calibrate_saturation(sample, plan, src, work):
    """1秒だけ試し焼きして、彩度が目標に乗る係数を求める。

    S字の階調カーブはハイライトを伸ばすので、副作用で彩度が上がる。
    上がり方は素材によって違うため、決め打ちの数値では合わない。
    実際に1秒書き出して測り、必要な係数を割り出すのが確実で速い。
    """
    g = dict(plan["grade"])
    target = g.get("sat_target")
    if not target:
        return g.get("saturation", 1.0)
    probe = os.path.join(work, "_satprobe.mp4")
    g2 = dict(g); g2["saturation"] = 1.0; g2["grain"] = 0
    chain = grade_chain(g2, src, 0)
    r = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", sample, "-an",
                        "-vf", f"scale=960:540,{chain}", "-t", "1.5",
                        "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", probe],
                       capture_output=True)
    if r.returncode != 0 or not os.path.exists(probe):
        return g.get("saturation", 1.0)
    try:
        c = av.open(probe)
        vals = []
        for i, f in enumerate(c.decode(video=0)):
            if i % 5:
                continue
            a = f.to_ndarray(format="rgb24").astype(np.float32) / 255
            mx, mn = a.max(2), a.min(2)
            vals.append(float(np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0).mean()))
        c.close()
    except Exception:
        return g.get("saturation", 1.0)
    finally:
        if os.path.exists(probe):
            os.remove(probe)
    if not vals:
        return g.get("saturation", 1.0)
    cur = float(np.mean(vals))
    mul = target / max(cur, 1e-3)
    mul = max(0.35, min(mul, 1.3))     # 効かせすぎて色が飛ぶのを防ぐ
    print(f"彩度の調整: 素材 {cur*100:.0f}% → 目標 {target*100:.0f}% なので係数 {mul:.2f}")
    return round(mul, 3)


def render_cut(cut, idx, plan, work, src_stats):
    w, h, fps = plan["width"], plan["height"], plan["fps"]
    out = os.path.join(work, f"cut_{idx:04d}.mp4")
    dur, speed = cut["dur"], cut["speed"]

    vf = [f"scale={w}:{h}:force_original_aspect_ratio=increase",
          f"crop={w}:{h}"]
    if speed != 1.0:
        vf.append(f"setpts=PTS/{speed}")
    if cut["zoom"]:
        e = ease_expr(cut["curve"], dur)
        z = f"(1+{cut['zoom'] / 100:.4f}*{e})"
        vf.append(f"crop=w='iw/{z}':h='ih/{z}':x='(iw-ow)/2':y='(ih-oh)/2'")
        vf.append(f"scale={w}:{h}")
    if cut["shake"]:
        # 先頭で強く、すぐ収まる揺れ
        d = f"exp(-t*7)"
        vf.append(f"crop=w=iw-40:h=ih-40:x='20+18*{d}*sin(t*46)':y='20+18*{d}*sin(t*61)'")
        vf.append(f"scale={w}:{h}")
    vf.append(grade_chain(plan["grade"], src_stats, plan.get("letterbox", 0)))
    vf.append(f"fps={fps}")

    cmd = [FF, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{cut['src_start']:.3f}", "-t", f"{cut['src_len'] + 0.4:.3f}",
           "-i", cut["src"], "-an",
           "-vf", ",".join(vf), "-t", f"{dur:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 2000:
        return None, (r.stderr or b"").decode("utf-8", "ignore")[-400:]
    return out, None


def draw_telop_png(path, text, label, size, font_path):
    """テロップを透過PNGに描く。

    ffmpeg の drawtext は freetype 付きビルドでないと使えず、環境によっては入っていない
    （pip の imageio-ffmpeg 同梱ビルドがまさにそれ）。PIL で画像にして overlay で重ねれば、
    どのビルドでも同じ結果になる。字間や2行組の制御もこちらのほうがやりやすい。
    """
    from PIL import Image, ImageDraw, ImageFont
    pad = 60
    font = ImageFont.truetype(font_path, size)
    small = ImageFont.truetype(font_path, max(int(size * 0.32), 14))

    d0 = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tb = d0.textbbox((0, 0), text, font=font)
    tw, th = tb[2], tb[3]
    lab, lw, lh = "", 0, 0
    if label:
        # ラベルは字間を広げて小さく置く（参考動画の型）
        lab = "\u3000".join(list(label)) if len(label) <= 4 else label
        lb = d0.textbbox((0, 0), lab, font=small)
        lw, lh = lb[2], lb[3] + int(size * 0.22)

    W, H = max(tw, lw) + pad * 2, th + lh + pad * 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if label:
        d.text((pad + 2, pad + 3), lab, font=small, fill=(0, 0, 0, 120))
        d.text((pad, pad), lab, font=small, fill=(255, 253, 248, 235))
    # 影を薄く落として、明るい映像に重なっても読めるようにする
    d.text((pad + 3, pad + lh + 4), text, font=font, fill=(0, 0, 0, 130))
    d.text((pad, pad + lh), text, font=font, fill=(255, 253, 248, 255))
    img.save(path)
    return W, H


def telop_overlays(plan, font, title, tagline, work):
    """テロップを overlay 用の指定に変換する。"""
    out = []
    if not font:
        return out
    for i, tp in enumerate(plan.get("telops", [])):
        text = tp.get("text") or ""
        if tp.get("drift") and not text:
            # キャッチコピー枠と締め枠は引数で埋める
            text = tagline if tp["start"] < 65 else title
        if not text:
            continue
        png = os.path.join(work, f"telop_{i}.png")
        pw, ph = draw_telop_png(png, text, tp.get("label", ""), tp["size"], font)
        st, dur = tp["start"], tp["dur"]
        if tp.get("drift"):
            x = "(main_w-overlay_w)/2"
            y = f"{tp['y'] - tp['drift'] // 2 - ph // 2}+{tp['drift']}*(t-{st})/{dur}"
        else:
            x = "160"                       # ラベル付きは左揃え
            y = str(tp["y"] - ph // 2)
        out.append(dict(png=png, start=st, dur=dur, x=x, y=y))
    return out



def main():
    global FF
    ap = argparse.ArgumentParser(description="素材と楽曲からラフカットを自動生成する")
    ap.add_argument("--footage", required=True, help="素材フォルダ（サブフォルダも探す）")
    ap.add_argument("--music", required=True)
    ap.add_argument("--plan", default=os.path.join(os.path.dirname(__file__), "prime_plan.json"))
    ap.add_argument("--out", default="roughcut.mp4")
    ap.add_argument("--work", default="_roughcut_work")
    ap.add_argument("--title", default="", help="締めに出すチーム名")
    ap.add_argument("--tagline", default="", help="キャッチコピー")
    ap.add_argument("--cache", default="", help="解析結果のキャッシュJSON（2回目以降が速い）")
    ap.add_argument("--max-clip-seconds", type=float, default=90.0,
                    help="1本あたり解析する秒数の上限。長回し素材があるときに効く")
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()

    FF = ffmpeg_bin()
    plan = json.load(open(args.plan, encoding="utf-8"))
    os.makedirs(args.work, exist_ok=True)

    files = []
    for root, _, names in os.walk(args.footage):
        for n in sorted(names):
            if n.endswith(VIDEO_EXT):
                files.append(os.path.join(root, n))
    if not files:
        sys.exit(f"{args.footage} に動画が見つかりません")
    print(f"素材 {len(files)} 本を解析します…")

    cache = {}
    if args.cache and os.path.exists(args.cache):
        cache = json.load(open(args.cache, encoding="utf-8"))

    cands = []
    for i, f in enumerate(files, 1):
        key = os.path.abspath(f)
        if key in cache:
            cands.extend(cache[key])
            print(f"  [{i}/{len(files)}] {os.path.basename(f)} (キャッシュ)")
            continue
        a = analyze_clip(f, max_seconds=args.max_clip_seconds)
        if a is None:
            print(f"  [{i}/{len(files)}] {os.path.basename(f)} 読めません。飛ばします")
            continue
        w = score_windows(a)
        cache[key] = w
        cands.extend(w)
        print(f"  [{i}/{len(files)}] {os.path.basename(f)}  {a['duration']:.1f}秒 "
              f"{a['width']}x{a['height']} {a['fps']:.0f}fps  見せ場{len(w)}か所")
    if args.cache:
        json.dump(cache, open(args.cache, "w", encoding="utf-8"))

    if not cands:
        sys.exit("使える区間が見つかりませんでした")

    by_section, foldered = assign(cands, plan["sections"], args.footage)
    print(f"\n区間の割り当て: {'フォルダ名から' if foldered else '動きの量から自動'}")
    for s in plan["sections"]:
        print(f"  {s['name']:<5} 候補 {len(by_section.get(s['name']) or [])} か所")

    src_stats = measure_source(files)
    print(f"\n素材の実測: 黒 {src_stats['black']*255:.0f} / 中間 {src_stats['mid']*255:.0f} / 白 {src_stats['white']*255:.0f} (255中)")
    g = plan["grade"]
    print(f"目標:       黒 {g['black_lift']*255:.0f} / 中間 {g.get('mid_target',0.34)*255:.0f} / 白 {g['white_cap']*255:.0f}")

    plan["grade"]["saturation"] = calibrate_saturation(files[0], plan, src_stats, args.work)

    edl = build_edl(plan, by_section)
    print(f"\nカット {len(edl)} 個を書き出します…")

    parts = []
    for i, cut in enumerate(edl):
        p, err = render_cut(cut, i, plan, args.work, src_stats)
        if p is None:
            print(f"  [{i+1}/{len(edl)}] 失敗: {os.path.basename(cut['src'])} {err}")
            continue
        parts.append(p)
        if (i + 1) % 10 == 0 or i + 1 == len(edl):
            print(f"  [{i+1}/{len(edl)}]")

    if not parts:
        sys.exit("書き出せたカットがありません")

    lst = os.path.join(args.work, "concat.txt")
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")

    joined = os.path.join(args.work, "joined.mp4")
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", joined], check=True)

    font = find_font()
    if not font:
        print("※ 日本語フォントが見つからないのでテロップは省きます")
    tel = telop_overlays(plan, font, args.title, args.tagline, args.work)

    cmd = [FF, "-hide_banner", "-loglevel", "error", "-y", "-i", joined, "-i", args.music]
    for t in tel:
        cmd += ["-loop", "1", "-t", f"{t['dur']:.3f}", "-i", t["png"]]

    if tel:
        # テロップPNGを1枚ずつ、出入りをフェードさせながら本編に重ねる
        fc, base = [], "0:v"
        for i, t in enumerate(tel):
            idx = 2 + i
            fo = max(t["dur"] - 0.35, 0.01)
            fc.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.35:alpha=1,"
                      f"fade=t=out:st={fo:.3f}:d=0.35:alpha=1,setpts=PTS+{t['start']}/TB[tl{i}]")
            nxt = f"v{i}"
            fc.append(f"[{base}][tl{i}]overlay=x={t['x']}:y={t['y']}:"
                      f"enable='between(t,{t['start']},{t['start'] + t['dur']})'[{nxt}]")
            base = nxt
        cmd += ["-filter_complex", ";".join(fc), "-map", f"[{base}]"]
    else:
        cmd += ["-map", "0:v"]

    cmd += ["-map", "1:a", "-shortest",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", args.out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print("テロップ付きの書き出しに失敗しました:")
        print((r.stderr or b"").decode("utf-8", "ignore")[-800:])
        print("テロップ無しで書き出し直します…")
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", joined, "-i", args.music, "-map", "0:v", "-map", "1:a",
                        "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", args.out],
                       check=True)

    if not args.keep_work:
        for p in parts:
            os.remove(p)
        for p in (lst, joined):
            if os.path.exists(p):
                os.remove(p)

    print(f"\n完成: {args.out}")
    print("AviUtl で詰めるためのカット表は、同じフォルダの edl.json に出しています。")
    json.dump(edl, open(os.path.splitext(args.out)[0] + "_edl.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
