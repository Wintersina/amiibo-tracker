

# windows:
Get-ExecutionPolicy -List
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

gcloud auth activate-service-account --key-file=credentials.json
gcloud config set project amiibo-tracker-458804
gcloud builds submit --tag us-central1-docker.pkg.dev/amiibo-tracker-458804/amiibo-tracker/amiibo-tracker
gcloud run deploy amiibo-tracker --image us-central1-docker.pkg.dev/amiibo-tracker-458804/amiibo-tracker/amiibo-tracker --platform managed --region us-central1 --allow-unauthenticated
gcloud run services update amiibo-tracker --region us-central1 --set-env-vars GCP_PROJECT_ID=amiibo-tracker-45880