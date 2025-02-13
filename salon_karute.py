import streamlit as st
import pandas as pd
import tempfile
import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client.service_account import ServiceAccountCredentials
import hashlib

# パスワードのハッシュ
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Falebaseの設定
firebase_config = {
    "apiKey": st.secrets["firebase"]["apiKey"],
    "authDomain": st.secrets["firebase"]["authDomain"],
    "databaseURL": st.secrets["firebase"]["databaseURL"],
    "projectId": st.secrets["firebase"]["projectId"],
    "storageBucket": st.secrets["firebase"]["storageBucket"],
    "messagingSenderId": st.secrets["firebase"]["messagingSenderId"],
    "appId": st.secrets["firebase"]["appId"],
}

# googleの設定
google_config = {
    "apiKey": st.secrets["google"]["apiKey"],
    "projectId": st.secrets["google"]["projectId"],
    "client_email": st.secrets["google"]["client_email"],
    "private_key": st.secrets["google"]["private_key"],
    "folder_id": st.secrets["google"]["folder_id"],
}

def authenticate_google_drive():
    creds_dict = st.secrets["google"]
    
    creds = Credentials.from_authorized_user_info(
        {
            
            "refresh_token": creds_dict.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": creds_dict["client_id"],
            "client_secret": creds_dict["client_secret"],
        },
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )

    # Google Drive APIサービスのインスタンスを作成
    service = build("drive", "v3", credentials=creds)
    return service
  
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

def load_users():
    sheet = client.open("SalonUsers").sheet1
    data = sheet.get_all_records()
    return pd.DataFrame(data)

def authenticate(email, password):
    users = load_users()
    hashed_input = hash_password(password)
    if any((users['Email'] == email) & (users['Password'] == hashed_input)):
        return True
    return False

def load_customers():
    sheet = client.open("SalonDatabase").worksheet("Customers")
    data = sheet.get_all_records()
    return pd.DataFrame(data)

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

def main():
    st.set_page_config(page_title="美容院カルテ管理", layout="wide")
    st.title("💇‍♀️ 美容院カルテ")
    
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        st.sidebar.header("🔑 ログイン")
        email = st.sidebar.text_input("📧 ユーザー名")
        password = st.sidebar.text_input("🔒 パスワード", type="password")
        if st.sidebar.button("ログイン", use_container_width=True):
            if authenticate(email, password):
                st.session_state.authenticated = True
                st.sidebar.success("✅ ログイン成功！")
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

        search_query = st.text_input("🔍 検索（顧客名でフィルター）")
        if search_query:
            df = df[df['顧客名'].str.contains(search_query, na=False, case=False)]
        st.dataframe(df, use_container_width=True)
        
        with st.expander("➕ 顧客情報の追加"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("👤 顧客名")
                phone = st.text_input("📞 電話番号")
            with col2:
                address = st.text_input("🏠 住所")
                note = st.text_area("📝 メモ")
            if st.button("追加", use_container_width=True):
                if name:
                    save_customer([name, str(phone), address, note])
                    st.success(f"✅ {name} を追加しました")
                    st.session_state["customer_updated"] = True  # 更新フラグをセット
                    # st.rerun()
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
            return load_treatments()

        df_treatments = load_treatments_cached()
        df_customers = load_customers()

        # 日付カラムを適切なデータ型に変換
        if "施術日" in df_treatments.columns:
            df_treatments["施術日"] = pd.to_datetime(df_treatments["施術日"], errors="coerce").dt.strftime("%Y-%m-%d")

        # 🔍 検索機能（AND検索 & 日付検索対応）
        search_query = st.text_input("🔍 検索（スペース区切りでAND検索、日付も可）")

        if search_query:
            search_columns = ["顧客名", "施術内容", "施術メモ", "日付"]  # 🔥 日付も検索対象に追加
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
