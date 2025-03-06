import streamlit as st
import pandas as pd
import tempfile
import gspread
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.http import MediaIoBaseDownload
import hashlib
import re
import cv2
import numpy as np
import io

# パスワードのハッシュ
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# googleの設定
google_config = {
    "apiKey": st.secrets["google"]["apiKey"],
    "projectId": st.secrets["google"]["projectId"],
    "client_email": st.secrets["google"]["client_email"],
    "private_key": st.secrets["google"]["private_key"],
    "folder_id": st.secrets["google"]["folder_id"],
}

# secrets.tomlからGoogle認証情報を取得
google_creds = st.secrets["google"]

# JSON構造に変換
creds_dict = {
    "type": google_creds["type"],
    "projectId": google_creds["projectId"],
    "private_key_id": google_creds["private_key_id"],
    "private_key": google_creds["private_key"].replace("\\n", "\n"),  # 改行コードの修正
    "client_email": google_creds["client_email"],
    "client_id": google_creds["client_id"],
    "auth_uri": google_creds["auth_uri"],
    "token_uri": google_creds["token_uri"],
    "auth_provider_x509_cert_url": google_creds["auth_provider_x509_cert_url"],
    "client_x509_cert_url": google_creds["client_x509_cert_url"],
}

# Google Sheets APIに接続するための認証設定
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

# gspreadに認証情報を渡す
client = gspread.authorize(creds)

# スプレッドシートにアクセス
spreadsheet = client.open("SalonUsers")  # スプレッドシート名

def authenticate_google_drive():
    creds_dict = st.secrets["google"]
    
    # Google Drive APIサービスのインスタンスを作成
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    service = build('drive', 'v3', credentials=credentials)
    return service

# 顔認証
# Google Drive から画像をダウンロード
def download_image_from_drive(file_id):
    service = authenticate_google_drive()
    request = service.files().get_media(fileId=file_id)
    file = io.BytesIO()
    downloader = MediaIoBaseDownload(file, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    file.seek(0)
    return file   

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
    
    spreadsheet = client.open("SalonUsers")  # スプレッドシート名
    SHEET_ID = spreadsheet.id # スプレッドシートのIDを取得
    sheet = spreadsheet.worksheet("sheet1")  # シート名 "Users" を指定
    # RANGE = "Users!A2:B"  # A列にメールアドレス、B列に画像のDrive File ID

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    # スプレッドシートの全データを取得
    values = sheet.get_all_values()

    # ユーザーの顔画像IDを探す
    for row in values:
        if row[0] == user_email:  # メールアドレスが一致する場合
            return row[1]  # 画像ファイルIDを返す

    return None  # 該当するデータがない場合は None を返す


# スプレッドシートからユーザーのメールアドレスを取得
def get_user_email_from_image_id(image_id):
    sheet = client.open("SalonUsers").sheet1
    data = sheet.get_all_values()
    for row in data[1:]:  # ヘッダー行をスキップ
        if row[1] == image_id:  # 画像IDが一致する場合
            return row[0]  # メールアドレスを返す
    return None  # 該当するデータがない場合は None を返す
  
def upload_to_drive(file):
    try:
        service = authenticate_google_drive()
        # folder_id = st.secrets["google_drive"]["folder_id"]
        folder_id = "1ykcojVR7RbWBOkTM7DHfxt9_asN2NCSY"
        file_metadata = {
            'name': file.name,
            'parents': [folder_id]
        }
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(file.read())
            temp_file_path = temp_file.name

        media = MediaFileUpload(temp_file_path, mimetype='application/octet-stream')  # 画像のMIMEタイプを確認
        uploaded_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        file_url = f"https://drive.google.com/file/d/{uploaded_file.get('id')}/view?usp=sharing"
        return file_url
    except Exception as e:
        st.error(f"❌ 画像のアップロードに失敗しました: {e}")
        return None
    
def convert_to_katakana(text):
    """ ひらがなをカタカナに変換 """
    hira_to_kata = str.maketrans(
        "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをん",
        "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲン"
    )
    return text.translate(hira_to_kata)


def load_treatments_with_furigana():
    """施術履歴に顧客情報のフリガナを追加"""
    sheet_treatments = client.open("SalonDatabase").worksheet("Treatments")
    data_treatments = sheet_treatments.get_all_records()
    df_treatments = pd.DataFrame(data_treatments)

    # 顧客情報の取得（顧客名とフリガナの対応を取得）
    sheet_customers = client.open("SalonDatabase").worksheet("Customers")
    data_customers = sheet_customers.get_all_records()
    df_customers = pd.DataFrame(data_customers)

    # 「顧客名」→「フリガナ」の辞書を作成
    customer_furigana_map = dict(zip(df_customers["顧客名"], df_customers["フリガナ"]))

    # 施術履歴に「フリガナ」列を追加（該当する顧客名があれば追加、なければ空白）
    df_treatments["フリガナ"] = df_treatments["顧客名"].map(customer_furigana_map).fillna("")

    return df_treatments

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
    sheet = client.open("SalonUsers").sheet1
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


def load_customers():
    sheet = client.open("SalonDatabase").worksheet("Customers")
    data = sheet.get_all_records()
    # return pd.DataFrame(data)
    df = pd.DataFrame(data)

    # 電話番号を文字列型に変換
    if "電話番号" in df.columns:
        df["電話番号"] = df["電話番号"].astype(str)

    return df

def load_treatments():
    sheet = client.open("SalonDatabase").worksheet("Treatments")
    data = sheet.get_all_records()
    return pd.DataFrame(data)

def save_customer(customer_data):
    sheet = client.open("SalonDatabase").worksheet("Customers")
    sheet.append_row(customer_data)

def delete_customer(name):
    sheet = client.open("SalonDatabase").worksheet("Customers")
    data = sheet.get_all_values()
    for i, row in enumerate(data):
        if row and row[0] == name:
            sheet.delete_rows(i + 1)
            break

def save_treatment(treatment_data):
    sheet = client.open("SalonDatabase").worksheet("Treatments")
    sheet.append_row(treatment_data)

def delete_treatment(name):
    sheet = client.open("SalonDatabase").worksheet("Treatments")
    data = sheet.get_all_values()
    for i, row in enumerate(data):
        if row and row[0] == name:
            sheet.delete_rows(i + 1)
            break

def update_treatment(row_index, updated_data):
    sheet = client.open("SalonDatabase").worksheet("Treatments")
    for col_index, value in enumerate(updated_data, start=1):
        sheet.update_cell(row_index + 1, col_index, value)

def update_customer(old_name, updated_data):
    sheet = client.open("SalonDatabase").worksheet("Customers")
    data = sheet.get_all_values()

    for i, row in enumerate(data):
        if row and row[0] == old_name:  # 顧客名が一致する行を探す
            for col_index, value in enumerate(updated_data, start=1):
                sheet.update_cell(i + 1, col_index, value)  # セルを更新
            break

def main():
    st.set_page_config(page_title="美容院カルテ管理", layout="wide")
    st.title("💇‍♀️ 美容院カルテ")

    # ✅ セッションステートに reload_data フラグを追加（初期値は False）
    if "reload_data" not in st.session_state:
        st.session_state["reload_data"] = False
    
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
        
    
    if not st.session_state.authenticated:
        st.sidebar.header(" ログイン")
        login_method = st.sidebar.radio("ログイン方法を選択してください", ("ユーザー名とパスワード", "カメラ認証"))

        if login_method == "ユーザー名とパスワード":
            email = st.sidebar.text_input(" ユーザー名")
            password = st.sidebar.text_input(" パスワード", type="password")
            if st.sidebar.button("ログイン", use_container_width=True):
                if authenticate_email_password(email, password):
                    st.session_state.authenticated = True
                    st.sidebar.success("✅ ログイン成功！")
                    st.rerun()
                else:
                    st.sidebar.error("❌ ログイン失敗")
        else:
            uploaded_image = st.sidebar.camera_input("カメラで撮影")
            if st.sidebar.button("ログイン", use_container_width=True):
                email = authenticate_face(uploaded_image)
                if email:
                    st.session_state.authenticated = True
                    st.session_state.user_email = email  # ユーザーのEmailをセッションに保存
                    st.sidebar.success(f"✅ ログイン成功！")  # Emailを表示
                    st.rerun()
                else:
                    st.sidebar.error("❌ ログイン失敗")
        return


    
    menu = ["👤 顧客情報", "✂️ 施術履歴", "🚪 ログアウト"]
    choice = st.sidebar.radio("メニュー", menu)
    
    if choice == "👤 顧客情報":
        st.subheader("📋 顧客情報一覧")

        @st.cache_data(ttl=60)  # 60秒間キャッシュ
        def load_customers_cached():
            return load_customers()

        df = load_customers_cached()

        search_query = st.text_input("🔍 検索（顧客名 または フリガナ）")
        if search_query:
            df = df[df["顧客名"].str.contains(search_query, na=False, case=False) |
                    df["フリガナ"].str.contains(search_query, na=False, case=False)]
        st.dataframe(df, use_container_width=True)
        
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
                    # st.rerun()
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
                    update_customer(selected_name, [new_name, new_furigana, new_phone, new_address, new_note])
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
                    # st.rerun()

      
    elif choice == "✂️ 施術履歴":
        st.subheader("📜 施術履歴一覧")

        @st.cache_data(ttl=60)  # API呼び出しを減らす
        def load_treatments_cached():
            # return load_treatments()
            return load_treatments_with_furigana()
        
        df_treatments = load_treatments_cached()
        df_customers = load_customers()

        # 日付カラムを適切なデータ型に変換
        if "施術日" in df_treatments.columns:
            df_treatments["施術日"] = pd.to_datetime(df_treatments["施術日"], errors="coerce").dt.strftime("%Y-%m-%d")

        # 🔍 検索機能（AND検索 & 日付検索対応）
        search_query = st.text_input("🔍 検索（スペース区切りでAND検索、日付も可）")

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
                        file_url = upload_to_drive(photo)
                        st.success("✅ アップロード完了！")
                    except Exception as e:
                        st.error(f"❌ 画像のアップロードに失敗しました: {e}")
                
                if customer_name and treatment:
                    save_treatment([customer_name, treatment, str(date), file_url, note])
                    st.success(f"✅ {customer_name} の施術履歴を追加しました")
                    st.session_state["customer_updated"] = True  # 更新フラグをセット
                    # st.rerun()

        with st.expander("✏️ 施術履歴の編集"):
            # 編集用の選択肢を作成（顧客名 | 施術内容 | 施術日）
            df_treatments["編集候補"] = df_treatments.apply(
                lambda row: f"{row['顧客名']} | {row['施術内容']} | {row['日付']}", axis=1
            )

            # 施術履歴を選択
            edit_option = st.selectbox("✏️ 編集する施術履歴を選択", df_treatments["編集候補"].tolist())

            if edit_option:
                # 選択されたデータを取得
                selected_row = df_treatments[df_treatments["編集候補"] == edit_option].iloc[0]

                # 入力フォーム
                new_treatment = st.text_input("施術内容", selected_row["施術内容"])
                new_date = st.date_input("日付", pd.to_datetime(selected_row["日付"], errors="coerce"))
                new_memo = st.text_area("施術メモ", selected_row["施術メモ"])

                if st.button("💾 保存"):
                    # データを更新
                    update_treatment(selected_row["顧客名"], new_treatment, new_date, new_memo)
                    st.success("✅ 施術履歴を更新しました！")
                    st.session_state["customer_updated"] = True  # 更新フラグをセット
                    

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
                # st.rerun()

        
    elif choice == "🚪 ログアウト":
        st.session_state.authenticated = False
        st.sidebar.success("🔓 ログアウトしました")
        st.rerun()

if __name__ == "__main__":
    main()
