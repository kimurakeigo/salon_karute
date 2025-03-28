import streamlit as st
import pandas as pd
import tempfile
import gspread
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.http import MediaIoBaseDownload
import hashlib
import re
import cv2
import numpy as np
import io
from googleapiclient import errors  # Google API のエラー処理用
import json  # 設定ファイル読み込み用
import time  # ローディングインジケーター用

def responsive_layout():
    # デバイスの画面幅を検出
    device_width = st.experimental_get_query_params().get("width", ["1200"])[0]
    is_mobile = int(device_width) < 768
    
    if is_mobile:
        # モバイル向けレイアウト
        st.markdown("""
        <style>
        .block-container {padding-top: 1rem; padding-bottom: 1rem;}
        </style>
        """, unsafe_allow_html=True)
    
    return is_mobile


# 設定ファイルの読み込み
def load_config():
    """secrets.toml から設定を読み込む."""
    try:
        config = st.secrets  # Streamlit の secrets を使用
        return config
    except Exception as e:
        st.error(f"設定の読み込みに失敗しました: {e}")
        return None

# 設定を読み込む
config = load_config()

# 設定ファイルが存在しない場合、プログラムを終了
if config is None:
    st.stop()

# Google API の認証情報
GOOGLE_CREDENTIALS = config.get("google", None)
GOOGLE_SHEET_NAME = config.get("google_sheet_name", "SalonUsers")
GOOGLE_DATABASE_SHEET_NAME = config.get("google_database_sheet_name", "SalonDatabase")
GOOGLE_CUSTOMERS_SHEET_NAME = config.get("google_customers_sheet_name", "Customers")
GOOGLE_TREATMENTS_SHEET_NAME = config.get("google_treatments_sheet_name", "Treatments")
GOOGLE_DRIVE_FOLDER_ID = config.get("google_drive_folder_id", "1ykcojVR7RbWBOkTM7DHfxt9_asN2NCSY")

if GOOGLE_CREDENTIALS is None:
    st.error("Google API 認証情報が設定されていません。")
    st.stop()

if GOOGLE_DRIVE_FOLDER_ID is None:
    st.error("Google Drive フォルダ ID が設定されていません。")
    st.stop()

# JSON構造に変換
creds_dict = GOOGLE_CREDENTIALS
# Google Sheets APIに接続するための認証設定
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scope)

# gspreadに認証情報を渡す
client = gspread.authorize(creds)

# スプレッドシートにアクセス
spreadsheet = client.open(GOOGLE_SHEET_NAME)  # スプレッドシート名

# パスワードのハッシュ
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Google Drive API サービスを構築
def authenticate_google_drive():
    credentials = service_account.Credentials.from_service_account_info(creds_dict, scopes=scope)
    service = build('drive', 'v3', credentials=credentials)
    return service

# Google Drive API: ファイル名とリンクを効率的に取得 (フィールドマスクを使用)
def get_file_name_and_link(file_id):
    """Google Drive API を使用してファイル名と公開リンクを取得 (フィールドマスクを使用)."""
    try:
        service = authenticate_google_drive()
        # ファイル名 (name) とwebViewLink(共有可能なURL)のみを要求
        results = service.files().get(fileId=file_id, fields="name,webViewLink").execute()  # フィールドマスクを使用
        file_name = results.get('name')
        file_link = results.get('webViewLink')
        return file_name, file_link
    except errors.HttpError as error:
        print(f"An error occurred: {error}")
        return None, None

# 顔認証
# Google Drive から画像をダウンロード
def download_image_from_drive(file_id):
    """Google Drive から画像をダウンロード (フィールドマスクを使用)."""
    try:
        service = authenticate_google_drive()
        request = service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        file.seek(0)
        return file
    except errors.HttpError as error:
        print(f"An error occurred: {error}")
        return None

# 顔認識（OpenCV）を使って認証
def face_recognition(uploaded_image, registered_image):
    # 画像を OpenCV 形式に変換
    img1 = cv2.imdecode(np.frombuffer(uploaded_image.read(), np.uint8), cv2.IMREAD_COLOR)
    img2 = cv2.imdecode(np.frombuffer(registered_image.read(), np.uint8), cv2.IMREAD_COLOR)

    # グレースケール変換
    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

    # ORB (Oriented FAST and Rotated BRIEF) を使った特徴点検出
    orb = cv2.ORB_create()
    kp1, des1 = orb.detectAndCompute(gray1, None)
    kp2, des2 = orb.detectAndCompute(gray2, None)

    # 特徴点のマッチング
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)

    # 類似度（マッチング数）を計算
    similarity = len(matches)

    return similarity

 # スプレッドシートからユーザーの登録画像IDを取得
def get_registered_image_id(user_email):
    # Google Sheets APIの認証（事前にシートをGoogle Drive APIと連携）

    spreadsheet = client.open(GOOGLE_SHEET_NAME)  # スプレッドシート名
    SHEET_ID = spreadsheet.id # スプレッドシートのIDを取得
    sheet = spreadsheet.worksheet("sheet1")  # シート名 "Users" を指定
    # RANGE = "Users!A2:B"  # A列にメールアドレス、B列に画像のDrive File ID

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = service_account.Credentials.from_service_account_info(creds_dict, scopes=scope)
    # スプレッドシートの全データを取得
    values = sheet.get_all_values()

    # ユーザーの顔画像IDを探す
    for row in values:
        if row[0] == user_email:  # メールアドレスが一致する場合
            return row[1]  # 画像ファイルIDを返す

    return None  # 該当するデータがない場合は None を返す


# スプレッドシートからユーザーのメールアドレスを取得
def get_user_email_from_image_id(image_id):
    sheet = client.open(GOOGLE_SHEET_NAME).sheet1
    data = sheet.get_all_values()
    for row in data[1:]:  # ヘッダー行をスキップ
        if row[1] == image_id:  # 画像IDが一致する場合
            return row[0]  # メールアドレスを返す
    return None  # 該当するデータがない場合は None を返す

def upload_to_drive(file):
    try:
        service = authenticate_google_drive()
        # folder_id = st.secrets["google_drive"]["folder_id"]
        folder_id = GOOGLE_DRIVE_FOLDER_ID
        file_metadata = {
            'name': file.name,
            'parents': [folder_id]
        }
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(file.read())
            temp_file_path = temp_file.name

        media = MediaFileUpload(temp_file_path, mimetype='application/octet-stream')  # 画像のMIMEタイプを確認
        uploaded_file = service.files().create(body=file_metadata, media_body=media, fields='id,webViewLink').execute() # フィールドマスクを追加
        file_url = f"https://drive.google.com/file/d/{uploaded_file.get('id')}/view?usp=sharing"
        return file_url
    except Exception as e:
        st.error(f"❌ 画像のアップロードに失敗しました: {e}")
        return None

def convert_to_katakana(text):
    """ ひらがなをカタカナに変換 """
    hira_to_kata = str.maketrans(
        "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢつづてでとどなにぬねのはばぱ히비피ふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをん",
        "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂツヅテデトドナニヌネノハバ파히비피フブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲン"
    )
    return text.translate(hira_to_kata)

@st.cache_data(ttl=60)  # 60秒間キャッシュ
def load_treatments_with_furigana():
    """施術履歴に顧客情報のフリガナを追加"""
    try:
        with st.spinner("施術履歴を読み込み中..."): # ローディングインジケーター
            sheet_treatments = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_TREATMENTS_SHEET_NAME)
            data_treatments = sheet_treatments.get_all_records()
            df_treatments = pd.DataFrame(data_treatments)

            # 顧客情報の取得（顧客名とフリガナの対応を取得）
            sheet_customers = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_CUSTOMERS_SHEET_NAME)
            data_customers = sheet_customers.get_all_records()
            df_customers = pd.DataFrame(data_customers)

            # 「顧客名」→「フリガナ」の辞書を作成
            customer_furigana_map = dict(zip(df_customers["顧客名"], df_customers["フリガナ"]))

            # 施術履歴に「フリガナ」列を追加（該当する顧客名があれば追加、なければ空白）
            df_treatments["フリガナ"] = df_treatments["顧客名"].map(customer_furigana_map).fillna("")

            return df_treatments
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"シート '{GOOGLE_TREATMENTS_SHEET_NAME}' または '{GOOGLE_CUSTOMERS_SHEET_NAME}' が見つかりません。")
        return pd.DataFrame()  # 空の DataFrame を返す
    except Exception as e:
        st.error(f"施術履歴の読み込みに失敗しました: {e}")
        return pd.DataFrame()

# 電話番号を正規表現に
def format_phone_number(phone_number):
    # 携帯電話等11桁の電話番号の場合（例: 09012345678）
    if len(phone_number) == 11:
        pattern = r"(\d{3})(\d{4})(\d{4})"
        formatted_phone = re.sub(pattern, r"\1-\2-\3", phone_number)
    # 市外局番込み10桁の電話番号の場合（例: 0123456789）
    elif len(phone_number) == 10:
        pattern = r"(\d{4})(\d{2})(\d{4})"
        formatted_phone = re.sub(pattern, r"\1-\2-\3", phone_number)
    # 市外局番なし6桁の電話番号の場合（例: 123456）
    elif len(phone_number) == 6:
        pattern = r"(\d{2})(\d{4})"
        formatted_phone = re.sub(pattern, r"\1-\2", phone_number)
    else:
        # それ以外の長さの場合はそのまま返す（エラーチェックなど追加可能）
        formatted_phone = phone_number

    return formatted_phone

def load_users():
    sheet = client.open(GOOGLE_SHEET_NAME).sheet1
    data = sheet.get_all_records()
    return pd.DataFrame(data)

def authenticate_email_password(email, password):
    users = load_users()
    hashed_input = hash_password(password)
    if any((users['Email'] == email) & (users['Password'] == hashed_input)):
        return True
    return False

def authenticate_face(uploaded_image):
    try:
        users = load_users()
        if users is None:
            st.error("ユーザーデータの読み込みに失敗しました。")
            return None

        for index, row in users.iterrows():
            registered_image_id = row["FaceID"]
            if registered_image_id:
                registered_image = download_image_from_drive(registered_image_id)
                if registered_image is None:
                    st.error(f"登録画像 ({registered_image_id}) のダウンロードに失敗しました。")
                    continue  # 次のユーザーへ

                similarity = face_recognition(uploaded_image, registered_image)
                if similarity is None:
                    st.error("顔認識処理でエラーが発生しました。")
                    continue # 次のユーザーへ

                if similarity > 1:
                    return row["Email"]  # 認証成功時にEmailを返す
        return None  # 認証失敗時にNoneを返す

    except Exception as e:
        st.error(f"予期せぬエラーが発生しました: {e}")
        st.error(f"Clearphotoを押して再度顔を認証してみてください")
        return None

@st.cache_data(ttl=60)  # API呼び出しを減らす
def load_customers():
    try:
        with st.spinner("顧客情報を読み込み中..."):  # ローディングインジケーター
            sheet = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_CUSTOMERS_SHEET_NAME)
            data = sheet.get_all_records()
            df = pd.DataFrame(data)

            # 電話番号を文字列型に変換
            if "電話番号" in df.columns:
                df["電話番号"] = df["電話番号"].astype(str)

            return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"シート '{GOOGLE_CUSTOMERS_SHEET_NAME}' が見つかりません。")
        return pd.DataFrame()  # 空の DataFrame を返す
    except Exception as e:
        st.error(f"顧客情報の読み込みに失敗しました: {e}")
        return pd.DataFrame()

def load_treatments():
    sheet = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_TREATMENTS_SHEET_NAME)
    data = sheet.get_all_records()
    return pd.DataFrame(data)

def save_customer(customer_data):
    try:
        with st.spinner("顧客情報を保存中..."): # ローディングインジケーター
            sheet = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_CUSTOMERS_SHEET_NAME)
            sheet.append_row(customer_data)
            st.success(f"✅ 顧客情報を保存しました")
            return True
    except gspread.exceptions.APIError as e:
        st.error(f"顧客情報の保存に失敗しました: {e}")
        return False
    
def delete_customer(name):
    try:
        with st.spinner("顧客情報を削除中..."): # ローディングインジケーター
            sheet = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_CUSTOMERS_SHEET_NAME)
            data = sheet.get_all_values()
            for i, row in enumerate(data):
                if row and row[0] == name:
                    sheet.delete_rows(i + 1)
                break
            st.success(f"✅ 顧客情報 '{name}' を削除しました。")
    except gspread.exceptions.APIError as e:
        st.error(f"顧客情報の削除に失敗しました: {e}")

def save_treatment(treatment_data):
    try:
        with st.spinner("施術履歴を保存中..."): # ローディングインジケーター
            sheet = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_TREATMENTS_SHEET_NAME)
            sheet.append_row(treatment_data)
            st.success(f"✅ 施術履歴を保存しました。")
    except gspread.exceptions.APIError as e:
        st.error(f"施術履歴の保存に失敗しました: {e}")

def delete_treatment(name):
    try:
        with st.spinner("施術履歴を削除中..."): # ローディングインジケーター
            sheet = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_TREATMENTS_SHEET_NAME)
            data = sheet.get_all_values()
            for i, row in enumerate(data):
                if row and row[0] == name:
                    sheet.delete_rows(i + 1)
                    break
            st.success(f"✅ 施術履歴 '{name}' を削除しました。")
    except gspread.exceptions.APIError as e:
        st.error(f"施術履歴の削除に失敗しました: {e}")

# def update_treatment(row_index, updated_data):
#     sheet = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_TREATMENTS_SHEET_NAME)
#     for col_index, value in enumerate(updated_data, start=1):
#         sheet.update_cell(row_index + 1, col_index, value)

def update_treatment(df_index, updates):
    """指定された行の特定のセルを更新する (gspread.update_cellsを使用)。

    Args:
        df_index (int): 更新する行の DataFrame インデックス (0-based)。
        updates (dict): 更新内容の辞書 {列名: 新しい値}。
    """
    try:
        with st.spinner("施術履歴を更新中..."):
            sheet = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_TREATMENTS_SHEET_NAME)
            headers = sheet.row_values(1) # ヘッダー行を取得して列名と列番号をマッピング
            col_map = {header: i + 1 for i, header in enumerate(headers)} # 列名 -> 列番号 (1-based)

            cells_to_update = []
            # DataFrame index (0-based) を Google Sheets の行番号 (1-based) に変換 (ヘッダー分 +1, 0-basedを1-basedに+1 => +2)
            google_sheets_row_index = df_index + 2

            for col_name, value in updates.items():
                if col_name in col_map:
                    col_index = col_map[col_name]
                    # gspread の update_cells 用に Cell オブジェクトを作成
                    # 値は文字列に変換しておくのが無難 (日付なども)
                    cells_to_update.append(gspread.Cell(google_sheets_row_index, col_index, str(value)))
                else:
                    # シートに存在しない列名を指定した場合の警告
                    st.warning(f"列名 '{col_name}' がシート '{GOOGLE_TREATMENTS_SHEET_NAME}' に見つかりません。スキップします。")

            if cells_to_update:
                # 複数のセルを一度に更新 (API呼び出し回数を削減)
                sheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
                st.success("✅ 施術履歴を更新しました！")
                # キャッシュクリア
                load_treatments_with_furigana.clear()
                st.session_state["customer_updated"] = True # 更新フラグ
                return True # 成功を示す値を返す
            else:
                st.info("更新対象のデータがありませんでした。")
                return False
    except gspread.exceptions.APIError as e:
        st.error(f"施術履歴の更新に失敗しました (APIエラー): {e}")
        return False
    except Exception as e:
        st.error(f"施術履歴の更新中に予期せぬエラーが発生しました: {e}")
        return False


def update_customer(old_name, updated_data):
  try:
    with st.spinner("顧客情報を更新中..."): # ローディングインジケーター
        sheet = client.open(GOOGLE_DATABASE_SHEET_NAME).worksheet(GOOGLE_CUSTOMERS_SHEET_NAME)
        data = sheet.get_all_values()

        for i, row in enumerate(data):
            if row and row[0] == old_name:  # 顧客名が一致する行を探す
                for col_index, value in enumerate(updated_data, start=1):
                    sheet.update_cell(i + 1, col_index, value)  # セルを更新
                break
  except gspread.exceptions.APIError as e:
        st.error(f"顧客情報の更新に失敗しました: {e}")

# Google Sheets API: 複数のセルをまとめて更新 (バッチリクエスト)
def update_cells_batch(spreadsheet_id, sheet_name, updates):
    """Google Sheets API を使用して複数のセルをまとめて更新 (バッチリクエスト).

    Args:
        spreadsheet_id (str): スプレッドシートのID
        sheet_name (str): シート名
        updates (list of dict): 更新内容のリスト。各辞書はセル範囲と新しい値を含む。
            例: [{'range': 'A1:A2', 'values': [[1], [2]]}, {'range': 'B1', 'values': [['test']]}]
    """
    try:
        service = build('sheets', 'v4', credentials=creds)  # sheets API v4 を使用

        body = {'value_input_option': 'USER_ENTERED',  # 'USER_ENTERED'は数式を評価, 'RAW'はそのまま
                'data': updates}  # dataに更新内容のリストを設定

        request = service.spreadsheets().values().batchUpdate(spreadsheetId=spreadsheet_id, body=body)
        response = request.execute()
        print(f"更新結果: {response}")
        return response
    except errors.HttpError as error:
        print(f"An error occurred: {error}")
        return None

def customer_details_view(customer_name):
    """顧客詳細ビューを表示する関数"""
    df_customers = load_customers()
    df_treatments = load_treatments_with_furigana()
    
    # 選択された顧客の情報を取得
    customer_info = df_customers[df_customers["顧客名"] == customer_name].iloc[0]
    
    # 顧客の施術履歴を取得
    customer_treatments = df_treatments[df_treatments["顧客名"] == customer_name]
    
    # カラムレイアウト
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader(f"👤 {customer_name}")
        st.caption(f"フリガナ: {customer_info['フリガナ']}")
        
        # 基本情報テーブル
        info_data = {
            "項目": ["電話番号", "住所", "最終来店日","メモ"],
            "内容": [
                customer_info["電話番号"],
                customer_info["住所"],
                customer_treatments["日付"].max() if "日付" in customer_treatments.columns and not customer_treatments.empty else "なし",
                customer_info["メモ"] if not pd.isna(customer_info["メモ"]) else "なし"
                              
            ]
        }
        st.table(pd.DataFrame(info_data))
            
    with col2:
        st.subheader("✂️ 施術履歴")
        if customer_treatments.empty:
            st.info("施術履歴がありません")
        else:
            # 施術履歴をタイムライン表示
            for _, treatment in customer_treatments.sort_values("日付", ascending=False).iterrows():
                with st.expander(f"{treatment['日付']} - {treatment['施術内容']}"):
                    # 写真がある場合は表示
                    if not pd.isna(treatment["写真"]) and treatment["写真"]:
                        try:
                            st.markdown(f"[![施術写真]({treatment['写真']})]({treatment['写真']})")
                        except:
                            st.warning("写真を表示できません")
                    
                    # 施術メモ
                    st.markdown("#### 施術メモ")
                    st.write(treatment["施術メモ"] if not pd.isna(treatment["施術メモ"]) else "なし")
                    
                    # アクション
                    # col1, col2 = st.columns(2)
                    # with col1:
                    #     if st.button("✏️ 編集", key=f"edit_{treatment['日付']}_{treatment['施術内容']}"):
                    #         st.session_state["edit_treatment"] = (treatment["日付"], treatment["施術内容"])
                    #         st.rerun()
                    # with col2:
                    #     if st.button("🗑️ 削除", key=f"delete_{treatment['日付']}_{treatment['施術内容']}"):
                    #         if st.session_state.get("confirm_delete") == (treatment["日付"], treatment["施術内容"]):
                    #             # 削除処理
                    #             delete_treatment(customer_name, treatment["日付"], treatment["施術内容"])
                    #             st.session_state.pop("confirm_delete", None)
                    #             st.rerun()
                    #         else:
                    #             st.session_state["confirm_delete"] = (treatment["日付"], treatment["施術内容"])
                    #             st.warning("もう一度クリックすると削除されます")    

def main():
    st.set_page_config(page_title="美容院カルテ管理", layout="wide")

    # CSSの追加
    st.markdown("""
    <style>
    .main {padding: 1rem 1rem;}
    .stTabs [data-baseweb="tab-list"] {gap: 10px;}
    .stTabs [data-baseweb="tab"] {
        padding: 10px 20px;
        border-radius: 8px 8px 0px 0px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #f0f2f6;
        border-bottom: 2px solid #4e8cff;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("💇‍♀️ 美容院カルテ")

    # ✅ セッションステートに reload_data フラグを追加（初期値は False）
    if "reload_data" not in st.session_state:
        st.session_state["reload_data"] = False

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

        # 更新フラグが立っていれば、キャッシュをクリア
    if "customer_updated" in st.session_state and st.session_state["customer_updated"]:
        # キャッシュをクリア
        load_customers.clear()
        load_treatments_with_furigana.clear()
        # フラグをリセット
        st.session_state["customer_updated"] = False

    if not st.session_state.authenticated:
        st.subheader(" ログインフォーム")
        login_method = st.radio("ログイン方法を選択してください", ("ユーザー名とパスワード", "カメラ認証"))

        if login_method == "ユーザー名とパスワード":
            email = st.text_input(" ユーザー名")
            password = st.text_input(" パスワード", type="password")
            if st.button("ログイン", use_container_width=True):
                if authenticate_email_password(email, password):
                    st.session_state.authenticated = True
                    st.success("✅ ログイン成功！")
                    st.rerun()
                else:
                    st.error("❌ ログイン失敗")
        else:
            uploaded_image = st.camera_input("カメラで撮影")
            if st.button("ログイン", use_container_width=True):
                email = authenticate_face(uploaded_image)
                if email:
                    st.session_state.authenticated = True
                    st.session_state.user_email = email  # ユーザーのEmailをセッションに保存
                    st.success(f"✅ ログイン成功！")  # Emailを表示
                    st.rerun()
                else:
                    st.error("❌ ログイン失敗")
        return        

    tab1, tab2, tab3, tab4 = st.tabs(["👤 顧客情報", "✂️ 施術履歴","👫個人履歴","🚪 ログアウト"])
    with tab1:
        st.subheader("📋 顧客情報一覧")
        df = load_customers()
        if df.empty:
          st.warning("顧客情報がありません。")
        else:
            search_query = st.text_input("🔍 検索（顧客名 または フリガナ）", key="customer_search")
            if search_query:
                df = df[df["顧客名"].str.contains(search_query, na=False, case=False) |
                        df["フリガナ"].str.contains(search_query, na=False, case=False)]
            st.dataframe(df, use_container_width=True,hide_index=True)

        with st.expander("➕ 顧客情報の追加"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("👤 顧客名")
                furigana = st.text_input("🔤 フリガナ (カタカナのみ)", key="furigana_input")
                # ひらがなをカタカナに自動変換
                furigana = convert_to_katakana(furigana)

                # カタカナ以外の文字が含まれていないかチェック
                if not re.fullmatch(r"[ァ-ヶー]+", furigana) and furigana:
                    st.warning("⚠ フリガナはカタカナのみで入力してください")
                    furigana = ""  # 不正な入力をクリア

                # st.text(f"変換後: {furigana}")

                phone = st.text_input("📞 電話番号")
                phone = format_phone_number(phone)  # 電話番号のフォーマット
                st.text(f"変換後: {phone}")
            with col2:
                address = st.text_input("🏠 住所")
                note = st.text_area("📝 メモ")
            if st.button("追加", use_container_width=True):
                if name:
                    save_customer([name, furigana, str(phone), address, note])
                    st.success(f"✅ {name} ({furigana}) を追加しました")
                    st.session_state["customer_updated"] = True  # 更新フラグをセット
                    st.rerun()
        with st.expander("✏️ 顧客情報の編集"):
            df_customers = load_customers()

            if not df_customers.empty:
                selected_name = st.selectbox("編集する顧客を選択", df_customers["顧客名"].tolist())

                # 選択した顧客の情報を取得
                selected_customer = df_customers[df_customers["顧客名"] == selected_name].iloc[0]

                # フォームの初期値（key を追加）
                new_name = st.text_input("👤 顧客名", selected_customer["顧客名"], key="edit_name")
                new_furigana = st.text_input("🔤 フリガナ", selected_customer["フリガナ"], key="edit_furigana")
                new_phone = st.text_input("📞 電話番号", str(selected_customer["電話番号"]), key="edit_phone")  # str に変換
                new_address = st.text_input("🏠 住所", selected_customer["住所"], key="edit_address")
                new_note = st.text_area("📝 メモ", selected_customer["メモ"], key="edit_note")

                if st.button("更新"):
                  # バッチアップデートの準備
                  spreadsheet_id = client.open(GOOGLE_DATABASE_SHEET_NAME).id
                  sheet_name = GOOGLE_CUSTOMERS_SHEET_NAME
                  updates = []

                  row_index = df_customers[df_customers["顧客名"] == selected_name].index[0] + 2 # 1始まりなので+2
                  updates.append({'range': f'{sheet_name}!A{row_index}', 'values': [[new_name]]})  # 顧客名
                  updates.append({'range': f'{sheet_name}!B{row_index}', 'values': [[new_furigana]]})  # フリガナ
                  updates.append({'range': f'{sheet_name}!C{row_index}', 'values': [[new_phone]]})  # 電話番号
                  updates.append({'range': f'{sheet_name}!D{row_index}', 'values': [[new_address]]})  # 住所
                  updates.append({'range': f'{sheet_name}!E{row_index}', 'values': [[new_note]]})   # メモ
                  update_cells_batch(spreadsheet_id, sheet_name, updates)
                  st.success(f"✅ {selected_name} ({new_furigana}) の情報を更新しました")
                  st.session_state["customer_updated"] = True
                  st.rerun()

        # 顧客情報の削除
        with st.expander("❌ 顧客情報の削除"):
            delete_name = st.selectbox("削除する顧客を選択", df['顧客名'] if not df.empty else [])
            if st.button("削除", use_container_width=True):
                if delete_name:
                    delete_customer(delete_name)
                    st.success(f"✅ {delete_name} を削除しました")
                    st.session_state["customer_updated"] = True  # 更新フラグをセット
                    st.rerun()
    with tab2:
        st.subheader("📜 施術履歴一覧")

        df_treatments = load_treatments_with_furigana()
        if df_treatments.empty:
            st.warning("施術履歴がありません。")
        else:
            df_customers = load_customers()

            # 日付カラムを適切なデータ型に変換
            if "施術日" in df_treatments.columns:
                df_treatments["施術日"] = pd.to_datetime(df_treatments["施術日"], errors="coerce").dt.strftime("%Y-%m-%d")

            # 🔍 検索機能（AND検索 & 日付検索対応）
            search_query = st.text_input("🔍 検索（スペース区切りでAND検索、日付も可）",key="treatment_search")

            if search_query:
                search_columns = ["顧客名","フリガナ", "施術内容", "施術メモ", "日付"]  # 🔥 日付も検索対象に追加
                df_treatments = df_treatments.dropna(subset=search_columns)  # NaNを除去

                # スペース区切りでキーワードをリスト化
                keywords = search_query.split()

                # すべてのキーワードを含む行のみ抽出（AND検索）
                for keyword in keywords:
                    df_treatments = df_treatments[
                        df_treatments[search_columns].apply(lambda row: row.astype(str).str.contains(keyword, case=False, na=False).any(), axis=1)
                    ]

            # DataFrame のカラム名を変更（写真 → 画像URL）
            df_treatments.rename(columns={"写真": "画像URL"}, inplace=True)

            # StreamlitのDataFrame表示でリンクを設定
            st.dataframe(
                df_treatments,
                column_config={
                    "画像URL": st.column_config.LinkColumn("📸 施術写真"),
                },
                use_container_width=True
            )

        with st.expander("➕ 施術履歴の追加"):
            customer_names = df_customers["顧客名"].tolist()
            customer_name = st.selectbox("👤 顧客名", customer_names)
            treatment = st.text_input("✂️ 施術内容")
            date = st.date_input("📅 施術日")
            note = st.text_area("📝 施術メモ")
            photo = st.file_uploader("🖼️ 写真アップロード（Google Drive）", type=["jpg", "jpeg", "png"])

            if st.button("施術履歴を追加"):
                file_url = None
                if photo:
                    st.image(photo, caption="アップロード画像", width=200)
                    try:
                        with st.spinner("画像をアップロード中..."):  # ローディングインジケーター
                            file_url = upload_to_drive(photo)
                            st.success("✅ アップロード完了！")
                    except Exception as e:
                        st.error(f"❌ 画像のアップロードに失敗しました: {e}")

                if customer_name and treatment:
                    save_treatment([customer_name, treatment, str(date), file_url, note])
                    st.success(f"✅ {customer_name} の施術履歴を追加しました")
                    st.session_state["customer_updated"] = True  # 更新フラグをセット
                    st.rerun()

        # with st.expander("✏️ 施術履歴の編集"):
        #     # 編集用の選択肢を作成（顧客名 | 施術内容 | 施術日）
        #     df_treatments["編集候補"] = df_treatments.apply(
        #         lambda row: f"{row['顧客名']} | {row['施術内容']} | {row['日付']}", axis=1
        #     )

        #     # 施術履歴を選択
        #     edit_option = st.selectbox("✏️ 編集する施術履歴を選択", df_treatments["編集候補"].tolist())

        #     if edit_option:
        #         # 選択されたデータを取得
        #         selected_row = df_treatments[df_treatments["編集候補"] == edit_option].iloc[0]

        #         # 入力フォーム
        #         new_treatment = st.text_input("施術内容", selected_row["施術内容"])
        #         new_date = st.date_input("日付", pd.to_datetime(selected_row["日付"], errors="coerce"))
        #         new_memo = st.text_area("施術メモ", selected_row["施術メモ"])

        #         if st.button("💾 保存"):
        #             # データを更新
        #             update_treatment(selected_row["顧客名"], new_treatment, new_date, new_memo)
        #             st.success("✅ 施術履歴を更新しました！")
        #             st.session_state["customer_updated"] = True  # 更新フラグをセット

        with st.expander("✏️ 施術履歴の編集"):
            df_treatments = load_treatments_with_furigana() # 最新のデータを読み込む

            if not df_treatments.empty:
                # 日付列を文字列に整形（選択肢表示用、エラー処理追加）
                if "日付" in df_treatments.columns:
                    try:
                        df_treatments["日付_str"] = pd.to_datetime(df_treatments["日付"], errors='coerce').dt.strftime('%Y-%m-%d')
                        # NaT (不正な日付) を空文字に置換
                        df_treatments["日付_str"] = df_treatments["日付_str"].fillna("")
                    except Exception as e:
                        st.warning(f"日付のフォーマット中にエラー: {e}")
                        df_treatments["日付_str"] = "" # エラー時は空文字
                else:
                    df_treatments["日付_str"] = "" # 日付列がない場合

                # 編集用の選択肢を作成（顧客名 | 施術内容 | 日付）
                # 欠損値があるとエラーになるため、fillna('') で空文字に置換
                df_treatments["編集候補"] = df_treatments.apply(
                    lambda row: f"{row.get('顧客名','')} | {row.get('施術内容','')} | {row.get('日付_str','')}", axis=1
                )

                # 施術履歴を選択 (keyを追加して状態保持)
                edit_option = st.selectbox(
                    "✏️ 編集する施術履歴を選択",
                    df_treatments["編集候補"].tolist(),
                    key="edit_treatment_select" # Selectbox用のキー
                )

                if edit_option:
                    try:
                        # 選択されたデータを取得 (候補文字列からDataFrameの行を特定)
                        # iloc[0] を使うために、該当行が必ず1つ存在すると仮定。エラー処理を追加するとより安全。
                        selected_row_df = df_treatments[df_treatments["編集候補"] == edit_option]

                        if not selected_row_df.empty:
                            selected_row = selected_row_df.iloc[0]
                            # DataFrame のインデックス (0-based) を取得
                            df_index = selected_row.name

                            # --- 入力フォーム ---
                            # 各入力ウィジェットに一意なキーを設定 (df_indexを使用)
                            new_treatment = st.text_input(
                                "✂️ 施術内容",
                                selected_row.get("施術内容", ""), # .getで欠損値対応
                                key=f"edit_treat_{df_index}"
                            )

                            # 日付入力: st.date_input は datetime.date オブジェクトを扱う
                            current_date_obj = None
                            if pd.notna(selected_row.get("日付")):
                                try:
                                    current_date_obj = pd.to_datetime(selected_row["日付"]).date()
                                except ValueError:
                                    st.warning("既存の日付データが不正な形式です。")
                            new_date = st.date_input(
                                "📅 日付",
                                current_date_obj, # dateオブジェクトまたはNone
                                key=f"edit_date_{df_index}"
                            )

                            new_memo = st.text_area(
                                "📝 施術メモ",
                                selected_row.get("施術メモ", ""), # .getで欠損値対応
                                key=f"edit_memo_{df_index}"
                            )
                            # --- 入力フォームここまで ---

                            # 保存ボタン (一意なキーを設定)
                            if st.button("💾 保存", key=f"save_edit_{df_index}"):
                                # 更新データの辞書を作成 (キーはシートのヘッダー名と一致させる)
                                updates = {
                                    "施術内容": new_treatment,
                                    "日付": str(new_date) if new_date else "", # シートには文字列 YYYY-MM-DD で保存
                                    "施術メモ": new_memo
                                    # 注意: 顧客名や写真URLを更新する場合はここに追加
                                }
                                # 修正した update_treatment を呼び出し (DataFrameのインデックスを渡す)
                                if update_treatment(df_index, updates):
                                     # 更新成功したら画面を再読み込みして変更を反映
                                     st.rerun()
                        else:
                            st.error("選択された編集候補に一致するデータが見つかりませんでした。")

                    except KeyError as e:
                         st.error(f"編集中に必要なデータが見つかりません (KeyError: {e})。データを確認してください。")
                    except Exception as e:
                         st.error(f"施術履歴の編集中に予期せぬエラーが発生しました: {e}")

            else:
                st.info("編集可能な施術履歴がありません。")
                    

        with st.expander("🗑️ 施術履歴の削除"):
            # 削除用の選択肢を作成（顧客名 | 施術内容 | 施術日）
            df_treatments["削除候補"] = df_treatments.apply(
                lambda row: f"{row['顧客名']} | {row['施術内容']} | {row['日付']}", axis=1
            )

            # 施術履歴を選択肢に表示
            delete_option = st.selectbox("👤 削除する施術履歴を選択", df_treatments["削除候補"].tolist())

            # 削除処理
            if st.button("❌ 削除"):
                # 選択されたデータを元に、元の `顧客名` を取得
                delete_name = delete_option.split(" | ")[0]  # 顧客名を取得
                delete_treatment(delete_name)  # 削除関数を実行

                st.success(f"🗑️ {delete_option} の施術履歴を削除しました")
                st.session_state["customer_updated"] = True  # 更新フラグをセット
                st.rerun() 
    with tab4:
            st.subheader("🚪ログアウト")
            if st.button("ログアウト"):
            # セッションステートをリセット
                st.text("ログアウトするにはログアウトボタンを押してください")
                st.session_state.authenticated = None
                st.success("ログアウトしました")
                st.rerun()
    with tab3:
        st.subheader("個人履歴")
        # 検索ワードの入力
        search_query = st.text_input("顧客名またはフリガナを入力してください", key="test_customer_search")

        # 検索結果のリストをセッションステートで管理
        if "filtered_customers" not in st.session_state:
            st.session_state.filtered_customers = []

        # 選択した顧客をセッションステートで管理
        if "selected_customer" not in st.session_state:
            st.session_state.selected_customer = None

        # 顧客情報を検索
        if st.button("顧客情報を表示", key="show_customer_info"):
            if search_query:
                df_customers = load_customers()
                filtered_customers = df_customers[
                    df_customers["顧客名"].str.contains(search_query, na=False, case=False) |
                    df_customers["フリガナ"].str.contains(search_query, na=False, case=False)
                ]
                
                if not filtered_customers.empty:
                    st.session_state.filtered_customers = filtered_customers["顧客名"].tolist()
                else:
                    st.error("該当する顧客が見つかりませんでした。")
                    st.session_state.filtered_customers = []
            else:
                st.warning("顧客名またはフリガナを入力してください。")

        # 検索結果がある場合のみ表示
        if st.session_state.filtered_customers:
            selected_customer = st.selectbox("該当する顧客を選択してください", st.session_state.filtered_customers)

            # 選択した顧客を保持
            if st.button("選択した顧客の情報を表示"):
                st.session_state.selected_customer = selected_customer

        # 選択した顧客の情報を表示
        if st.session_state.selected_customer:
            customer_details_view(st.session_state.selected_customer)
                    
if __name__ == "__main__":
    main()