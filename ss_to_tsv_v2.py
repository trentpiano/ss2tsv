import cv2
import re
from PIL import Image, ImageTk
import imagehash
import os
import datetime
import pyperclip
import shutil
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
import json

CONFIG_PATH = "config.json"

DEFAULT_CONFIG = {
    "growth_input_enabled": False,
    "growth_input_order": "oldest_first",
    "growth_input_mode": "dialog"
}

def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(
                DEFAULT_CONFIG,
                f,
                ensure_ascii=False,
                indent=4
            )
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_CONFIG.copy()

    order = config.get(
        "growth_input_order",
        DEFAULT_CONFIG["growth_input_order"]
    )

    if order not in ("newest_first", "oldest_first"):
        order = DEFAULT_CONFIG["growth_input_order"]

    return {
        **DEFAULT_CONFIG,
        **config,
        "growth_input_order": order
    }

def imread_unicode(path):
    img = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(img, cv2.IMREAD_COLOR)
    return img

def imwrite_unicode(path, img):
    ext = os.path.splitext(path)[1]
    result, encoded = cv2.imencode(ext, img)
    if result:
        encoded.tofile(path)

def initialize_lists():
    global SP_LIST, DATE

    for folder in ["archive_results", "input_results", "seito", "sensei"]:
        os.makedirs(folder, exist_ok=True)

    with open("sp.txt", "r", encoding="utf-8") as f:
        SP_LIST = [line.strip() for line in f]

    DATE = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')

    adwlTemplates = {"templates_adwl/templateAL.png":("攻撃", "False"), 
                    "templates_adwl/templateAW.png":("攻撃", "True"),
                    "templates_adwl/templateDL.png":("防衛", "False"),
                    "templates_adwl/templateDW.png":("防衛", "True")}

    adwl_hash_db = {}
    for templ in adwlTemplates:
        img = imread_unicode(templ)
        img = preprocess_icon(img)
        h = get_hash(img)
        adwl_hash_db[templ] = h

    sensei_db = {}
    for f in os.listdir("sensei"):
        if f.lower().endswith((".png",".jpg",".jpeg")):
            img = Image.open(f"sensei/{f}").convert("L").resize((128,32))
            sensei_db[f[:-4]] = imagehash.phash(img)

    seito_db = {}
    for f in os.listdir("seito"):
        if not f.lower().endswith((".png",".jpg",".jpeg")):
            continue
        img = Image.open(f"seito/{f}").convert("L").resize((64,64))
        seito_db[f[:-4]] = imagehash.phash(img)

    return adwlTemplates, adwl_hash_db, sensei_db, seito_db

def create_DnD_tk():
    def on_drop(event):
        files = root.tk.splitlist(event.data)
        for f in files:
            if os.path.isfile(f):
                shutil.move(f,"input_results")
        root.destroy()

    root = TkinterDnD.Tk()
    root.title("画像をドラッグ＆ドロップしてください")
    root.geometry("400x200")
    label = tk.Label(root, text="ここに画像をドロップ", width=40, height=10)
    label.pack(padx=20, pady=20)
    label.drop_target_register(DND_FILES)
    label.dnd_bind("<<Drop>>", on_drop)
    root.mainloop()

def create_progress_window(max_value):
    root = tk.Tk()
    root.withdraw()
    win = tk.Toplevel()
    win.title("処理中…")
    win.geometry("300x80+100+100")

    label = tk.Label(win, text="画像を処理しています…")
    label.pack(pady=5)

    bar = ttk.Progressbar(win, length=250, mode="determinate", maximum=max_value)
    bar.pack(pady=5)

    return win, bar

# ダイアログ切り出し
def cropDialog(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        aspect = w / h
        if 2.2 < aspect < 2.4:  
            dialog = img[y:y+h, x:x+w]
            return dialog, w, h
    return None, None, None

# adwl判定
def adwl_hash_detect(dialog, w, h, adwl_hash_db):
    cropADWL = dialog[int(h*0.15):int(h*0.3), int(w*0.02):int(w*0.18)]
    cropADWL = preprocess_icon(cropADWL)
    ha = get_hash(cropADWL)
    best = None
    best_diff = 999
    for name, th in adwl_hash_db.items():
        diff = ha - th  
        if diff < best_diff:
            best_diff = diff
            best = name
    return best, best_diff

def get_sensei_noOCR(dialog, w, h, sensei_db):
    cropSenseiR = dialog[int(h*0.15):int(h*0.19), int(w*0.83):int(w)]

    name, diff = detect_sensei(cropSenseiR, sensei_db)
    print(f"先生: {name}, 差分: {diff}")
    if diff > 4:
        name, sensei_db = save_unknown_sensei(cropSenseiR, sensei_db)
    
    return name

def detect_sensei(crop_img, sensei_db):
    gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    resized = cv2.resize(binary, (256, 64), interpolation=cv2.INTER_AREA)

    pil_img = Image.fromarray(resized)
    h = imagehash.phash(pil_img)

    best = None
    best_diff = 999
    for name, chash in sensei_db.items():
        diff = h - chash
        if diff < best_diff:
            best_diff = diff
            best = name
    # print(f"先生候補: {best}, 差分: {best_diff}")

    return best, best_diff

def save_unknown_sensei(img, sensei_db):
    name = register_sensei_tk(img)
    if not name:
        return "不明", sensei_db

    sensei_db = add_sensei_to_db(name, img, sensei_db)
    return name, sensei_db

def add_sensei_to_db(name, img, sensei_db):
    os.makedirs("sensei", exist_ok=True)
    path = f"sensei/{name}.png"

    # 前処理：グレースケール + 二値化
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    # サイズを統一（例：256×64）
    resized = cv2.resize(binary, (256, 64), interpolation=cv2.INTER_AREA)

    # 保存
    imwrite_unicode(path, resized)

    # ハッシュ作成
    pil = Image.fromarray(resized)
    h = imagehash.phash(pil)
    sensei_db[name] = h

    print(f"先生DB更新: {name}")
    return sensei_db

def register_sensei_tk(img):
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb).resize((256, 32))
    win = tk.Toplevel()
    win.title("先生名登録")
    win.geometry("300x200+100+300")
    win.resizable(False, False)

    tk_img = ImageTk.PhotoImage(pil_img)
    img_label = ttk.Label(win, image=tk_img)
    img_label.pack(pady=10)

    name_var = tk.StringVar()
    entry = ttk.Entry(win, textvariable=name_var, font=("",14))
    entry.pack(pady=5)
    entry.focus()

    result = {"name": None}

    def on_ok(event=None):
        text = name_var.get().strip()
        if text:
            result["name"] = text
            win.destroy()

    def on_cancel(event=None):
        win.destroy()

    ttk.Button(win, text="登録", command=on_ok).pack(pady=5)
    ttk.Button(win, text="キャンセル", command=on_cancel).pack()
    entry.bind("<Return>", on_ok)
    win.wait_window() 
    return result["name"]

# 生徒画像取得
def get_seito(dialog, w, h, seito_db):
    seito = []
    positionList = {"l1":0.07, "l2":0.1313, "l3":0.1926, "l4":0.2539, "l5":0.3152, "l6":0.3765,
                    "r1":0.588, "r2":0.6493, "r3":0.7106, "r4":0.7719, "r5":0.8332, "r6":0.8945}
    for pos in positionList:
        leftEdge = positionList[pos]
        cropS = dialog[int(h*0.826):int(h*0.911), int(w*leftEdge):int((w*leftEdge)+(w*0.033))]
        name, diff = detect_seito(cropS, seito_db)
        if diff > 10:  
            name, seito_db = save_unknown(cropS, seito_db)
        if name:
            name = re.sub(r"[0-9]", "", name)
        seito.append(name)
        # print(pos, name, diff)
    seito = sortseito(seito)
    return seito, seito_db

# アイコン判別関数
def detect_seito(crop_img, seito_db):
    pil_img = Image.fromarray(crop_img)
    pil_img = pil_img.resize((64,64))
    h = imagehash.phash(pil_img)
    best = None
    best_diff = 999

    for name, chash in seito_db.items():
        diff = h - chash
        if diff < best_diff:
            best_diff = diff
            best = name

    return best, best_diff

def save_unknown(img, seito_db):
    name = register_seito_tk(img)
    if not name:
        return "空き"

    seito_db = add_seito_to_db(name, img, seito_db)
    return name, seito_db

def register_seito_tk(img):
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb).resize((128, 128))
    
    win = tk.Toplevel()
    win.title("生徒登録")
    win.geometry("300x250+100+300")
    win.resizable(False, False)

    tk_img = ImageTk.PhotoImage(pil_img)
    img_label = ttk.Label(win, image=tk_img)
    img_label.pack(pady=10)

    name_var = tk.StringVar()
    entry = ttk.Entry(win, textvariable=name_var, font=("",14))
    entry.pack(pady=5)
    entry.focus()

    result = {"name": None}

    def on_ok(event=None):
        text = name_var.get().strip()
        if text:
            result["name"] = text
            win.destroy()

    def on_cancel(event=None):
        win.destroy()

    ttk.Button(win, text="登録", command=on_ok).pack(pady=5)
    ttk.Button(win, text="キャンセル", command=on_cancel).pack()
    entry.bind("<Return>", on_ok)
    win.wait_window()
    return result["name"]

def add_seito_to_db(name, img, seito_db):
    os.makedirs("seito", exist_ok=True)
    path = f"seito/{name}.png"

    resized = cv2.resize(img, (64, 64), interpolation=cv2.INTER_AREA)
    imwrite_unicode(path, resized)

    pil = Image.fromarray(resized)
    h = imagehash.phash(pil)
    seito_db[name] = h

    print(f"キャラDB更新: {name}")
    return seito_db

def sortseito(seito):
    if seito.count("空き") != 0:   
        spaceL = seito[0:6].count("空き")
        spaceR = seito[6:12].count("空き")
        new_seito = [s for s in seito if s != "空き"]
        spL = len(set(seito[0:6]) & set(SP_LIST))
        spR = len(set(seito[6:12])& set(SP_LIST))
        stL = 6 - spaceL - spL
        stR = 6 - spaceR - spR
        for i in range(12):
            if (stL<=i<4) or (spL+4<=i<6) or (stR+6<=i<10) or (spR+10<=i<12):
                new_seito.insert(i, "空き")
        return new_seito
    return seito

# 2値化
def preprocess_icon(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    return binary

# ハッシュ作成
def get_hash(img):
    pil = Image.fromarray(img)
    pil = pil.resize((64,64))
    return imagehash.phash(pil)

# 育成状況入力ダイアログ
def input_growth_statuses(count, filenames,mode="dialog"):
    if mode == "clipboard":
        text = pyperclip.paste()
        statuses = text.splitlines()

        # 末尾の空行だけを無視
        while statuses and statuses[-1] == "":
            statuses.pop()

        if len(statuses) > count:
            messagebox.showerror(
                "入力エラー",
                f"必要な行数: {count}行\n"
                f"実際のデータ行数: {len(statuses)}行"
            )
            return None

        # 足りない分は空欄で補完
        statuses.extend([""] * (count - len(statuses)))

        return statuses

    # ここから下は既存のダイアログ処理
    win = tk.Toplevel()
    win.title("育成状況の入力")
    win.geometry("550x500")
    win.grab_set()

    tk.Label(
        win,
        text=(
            f"育成状況を入力してください（全{count}件）\n"
            "画像の順番に合わせて、1行につき1件入力してください。"
        ),
        justify="left"
    ).pack(anchor="w", padx=10, pady=10)

    # 画像と入力順の対応を表示
    file_text = "\n".join(
        f"{i + 1}. {name}"
        for i, name in enumerate(filenames)
    )

    tk.Label(
        win,
        text=file_text,
        justify="left",
        anchor="w"
    ).pack(anchor="w", padx=10)

    text_box = tk.Text(win, height=12, width=60)
    text_box.pack(fill="both", expand=True, padx=10, pady=10)

    result = {"statuses": None}

    def on_ok():
        statuses = text_box.get("1.0", "end-1c").splitlines()

        # 最後の改行による空行は許容する
        if len(statuses) == count - 1 and text_box.get("end-2c", "end-1c") == "\n":
            statuses.append("")

        if len(statuses) != count:
            messagebox.showerror(
                "入力エラー",
                f"{count}件の育成状況を入力してください。"
            )
            return

        result["statuses"] = statuses
        win.destroy()

    def on_cancel():
        result["statuses"] = None
        win.destroy()

    buttons = tk.Frame(win)
    buttons.pack(pady=10)

    tk.Button(
        buttons, text="確定", command=on_ok
    ).pack(side="left", padx=5)

    tk.Button(
        buttons, text="キャンセル", command=on_cancel
    ).pack(side="left", padx=5)

    win.protocol("WM_DELETE_WINDOW", on_cancel)
    text_box.focus_set()
    win.wait_window()

    return result["statuses"]

def format_growth_status(seito, growth):
    # 育成状況を記録するキャラのインデックス
    indices = [6, 10, 11]

    # 例: "412"   → ["4", "1", "2"]
    #     "41!3"  → ["4", "1", "!3"]
    ranks = re.findall(r"![1-5]|[1-4]", growth)

    # 入力全体が正しい形式か検証
    if "".join(ranks) != growth or len(ranks) != len(indices):
        raise ValueError(
            f"育成状況の形式が不正です: {growth}"
        )

    result = []

    for index, rank in zip(indices, ranks):
        name = seito[index]

        if rank.startswith("!"):
            result.append(
                f"{name}：星{rank[1:]}"
            )
        else:
            result.append(f"{name}：固有{rank}")

    return "、".join(result)

def main():
    config = load_config()

    adwlTemplates, adwl_hash_db, sensei_db, seito_db = initialize_lists()
    create_DnD_tk()

    files = os.listdir("input_results")
    total = len(files)

    progress_win, progress_bar = create_progress_window(total)
    progress_bar["value"] = 0
    progress_win.update()

    outputLines = []
    outputFiles = []
    attackLines = []
    attackFiles = []

    for i, result in enumerate(files, start=1):
        result_path = os.path.join("input_results", result)
        inputImage = imread_unicode(result_path)
        if inputImage is None:
            print("読み込み失敗:", result_path)
            continue

        dialog, w, h = cropDialog(inputImage)
        if dialog is None:
            print("ダイアログ検出失敗:", result)
            continue

        templ, diff = adwl_hash_detect(dialog, w, h, adwl_hash_db)
        if diff <= 8:
            AorD, WorL = adwlTemplates[templ]

        senseiR = get_sensei_noOCR(dialog, w, h, sensei_db)
        seito, seito_db = get_seito(dialog, w, h, seito_db)

        outputLine = [DATE, AorD, senseiR, WorL, *seito]
        outputLines.append("\t".join(outputLine))
        outputFiles.append(result)
        # 攻撃の行だけを育成状況の入力対象にする
        if AorD == "攻撃":
            attackLines.append("\t".join(outputLine))
            attackFiles.append(result)

        shutil.move(result_path, "archive_results")

        # プログレスバー更新
        progress_bar["value"] = i
        progress_win.update()

    # 全部終わったら閉じる
    progress_win.destroy()

    # 育成状況機能が有効な場合
    if config.get("growth_input_enabled", True):

        # 攻撃の行のインデックスを取得
        attack_indices = [
            i for i, line in enumerate(outputLines)
            if line.split("\t", 2)[1] == "攻撃"
        ]

        # 設定に応じて入力順を決定
        input_indices = attack_indices.copy()

        if config["growth_input_order"] == "oldest_first":
            input_indices.reverse()

        input_files = [outputFiles[i] for i in input_indices]

        # 攻撃が存在する場合のみ入力
        if input_indices:
            statuses = input_growth_statuses(
                len(input_indices),
                input_files,
                mode=config.get("growth_input_mode", "dialog")
            )

            if statuses is None:
                return
        else:
            statuses = []

        status_by_index = dict(zip(input_indices, statuses))
        finalLines = []

        for i, line in enumerate(outputLines):
            if i in status_by_index:
                status = status_by_index[i].strip()

                if status:
                    columns = line.split("\t")
                    seito = columns[4:16]
                    status = format_growth_status(seito, status)

                finalLines.append(line + "\t" + status)
            else:
                finalLines.append(line)

    # 育成状況機能が無効な場合
    else:
        finalLines = outputLines.copy()

    # どちらの場合も最後にまとめてコピー
    pyperclip.copy("\n".join(finalLines))
    print("解析結果をコピーしました。")

main()