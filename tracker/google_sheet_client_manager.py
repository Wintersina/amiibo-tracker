import json
import os
from functools import cached_property
import tempfile  # Import tempfile module
import gspread
from django.conf import settings
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.cloud import secretmanager
import google.auth

from constants import OauthConstants


class GoogleSheetClientManager:

    def __init__(
        self,
        sheet_name="AmiiboCollection",
        work_sheet_amiibo_manager="AmiiboCollection",
        work_sheet_config_manager="AmiiboCollectionConfigManager",
        creds_json=None,
    ):
        self.sheet_name = sheet_name
        self.work_sheet_amiibo_manager = work_sheet_amiibo_manager
        self.work_sheet_config_manager = work_sheet_config_manager
        self.creds_json = creds_json
        # self._client_secrets_data = None # We will now store the path to a temporary file
        self._client_secrets_temp_filepath = None

    def _get_client_secrets_file_path(self):
        """
        Fetches client_secret.json content (from Secret Manager or local file),
        writes it to a temporary file, and returns the path to that file.
        """
        if self._client_secrets_temp_filepath and os.path.exists(
            self._client_secrets_temp_filepath
        ):
            return self._client_secrets_temp_filepath

        client_secrets_content = None

        # Try local client_secret.json first for local development
        client_secrets_path_local = os.path.join(
            settings.BASE_DIR, "client_secret.json"
        )
        if not settings.GCP_PROJECT_ID and os.path.exists(client_secrets_path_local):
            print(
                "Running locally without GCP_PROJECT_ID. Falling back to local client_secret.json."
            )
            with open(client_secrets_path_local, "r") as f:
                client_secrets_content = f.read()
        else:
            # If not local or GCP_PROJECT_ID is set, try Secret Manager
            if not settings.GCP_PROJECT_ID:
                raise ValueError(
                    "GCP_PROJECT_ID is not set in Django settings. Cannot retrieve client secrets from Secret Manager."
                )

            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{settings.GCP_PROJECT_ID}/secrets/{settings.CLIENT_SECRET_SECRET_NAME}/versions/latest"

            try:
                response = client.access_secret_version(request={"name": name})
                client_secrets_content = response.payload.data.decode("UTF-8")
            except Exception as e:
                raise RuntimeError(
                    f"Failed to load client secrets from Secret Manager. Error: {e}. "
                    f"Ensure GCP_PROJECT_ID is set, service account has Secret Accessor role, "
                    f"and secret '{settings.CLIENT_SECRET_SECRET_NAME}' exists."
                )

        if not client_secrets_content:
            raise RuntimeError("Client secrets could not be loaded from any source.")

        # Write the content to a temporary file
        # Using NamedTemporaryFile ensures it's cleaned up automatically when closed
        # or when the program exits.
        temp_file = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json")
        temp_file.write(client_secrets_content)
        temp_file.close()  # Close the file so Flow.from_client_secrets_file can read it

        self._client_secrets_temp_filepath = temp_file.name
        return self._client_secrets_temp_filepath

    def __del__(self):
        """Cleanup: Delete the temporary client secrets file when the object is garbage collected."""
        if self._client_secrets_temp_filepath and os.path.exists(
            self._client_secrets_temp_filepath
        ):
            try:
                os.remove(self._client_secrets_temp_filepath)
                # print(f"Cleaned up temporary client secrets file: {self._client_secrets_temp_filepath}")
            except OSError as e:
                print(
                    f"Error cleaning up temporary file {self._client_secrets_temp_filepath}: {e}"
                )

    def get_creds(self, creds_json) -> Credentials:
        if not creds_json:
            return None
        creds = Credentials.from_authorized_user_info(creds_json, OauthConstants.SCOPES)
        return creds

    def get_flow(self) -> Flow:
        # Pass the path to the temporary file to Flow.from_client_secrets_file()
        client_secrets_filepath = self._get_client_secrets_file_path()
        flow = Flow.from_client_secrets_file(
            client_secrets_filepath,  # Pass the file path
            scopes=OauthConstants.SCOPES,
            redirect_uri=OauthConstants.REDIRECT_URI,
        )
        return flow

    @cached_property
    def client(self):
        if self.creds_json:
            oauth_creds = self.get_creds(self.creds_json)
            if not oauth_creds:
                raise ValueError(
                    "User credentials are invalid or missing for Google Sheet access."
                )
            return gspread.authorize(oauth_creds)
        else:
            print(
                "No user credentials (creds_json) provided. Attempting to use Application Default Credentials (ADC)."
            )
            try:
                credentials, project = google.auth.default(scopes=OauthConstants.SCOPES)
                return gspread.authorize(credentials)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to obtain Google Cloud Application Default Credentials. Error: {e}. "
                    "Ensure your environment is correctly set up for ADC (e.g., service account roles)."
                )

    @cached_property
    def spreadsheet(self):
        try:
            return self.client.open(self.sheet_name)
        except gspread.exceptions.SpreadsheetNotFound:
            print(
                f"Spreadsheet '{self.sheet_name}' not found. Creating a new spreadsheet."
            )
            spreadsheet = self.client.create(self.sheet_name)

            print(
                f"Creating worksheet '{self.work_sheet_amiibo_manager}' within the new spreadsheet."
            )
            self.work_sheet_amiibo_manager_object = spreadsheet.add_worksheet(
                title=self.work_sheet_amiibo_manager, rows=500, cols=3
            )
            self.work_sheet_config_manager_object = spreadsheet.add_worksheet(
                title=self.work_sheet_config_manager, rows=500, cols=3
            )

            self.work_sheet_amiibo_manager_object.append_row(
                ["Amiibo ID", "Amiibo Name", "Collected Status"]
            )
            self.work_sheet_config_manager_object.append_row(["DarkMode"])
            self.work_sheet_config_manager_object.append_row(["0"])

            print(f"Successfully initialized with spreadsheet '{spreadsheet.title}'")
            return spreadsheet

    def get_or_create_worksheet_by_name(self, worksheet_name):
        try:
            sheet = self.spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = self.spreadsheet.add_worksheet(
                title=worksheet_name, rows=500, cols=3
            )
            if worksheet_name == "AmiiboCollection":
                sheet.append_row(["Amiibo ID", "Amiibo Name", "Collected Status"])
            if worksheet_name == "AmiiboCollectionConfigManager":
                sheet.append_row(["DarkMode"])
                sheet.append_row(["0"])
        return sheet
