"""Blob Storage にドキュメントをアップロードするスクリプト"""

import os
import glob
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

load_dotenv()

STORAGE_ACCOUNT = os.environ["AZURE_STORAGE_ACCOUNT_NAME"]
CONTAINER_NAME = os.environ.get("AZURE_STORAGE_CONTAINER", "documents")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

credential = DefaultAzureCredential()
blob_service = BlobServiceClient(
    account_url=f"https://{STORAGE_ACCOUNT}.blob.core.windows.net",
    credential=credential,
)

container_client = blob_service.get_container_client(CONTAINER_NAME)
if not container_client.exists():
    container_client.create_container()
    print(f"📁 コンテナ '{CONTAINER_NAME}' を作成しました")

files = glob.glob(os.path.join(DATA_DIR, "*"))
for filepath in files:
    blob_name = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        container_client.upload_blob(name=blob_name, data=f, overwrite=True)
    print(f"⬆️  {blob_name}")

print(f"\n✅ {len(files)} ファイルをアップロードしました")
